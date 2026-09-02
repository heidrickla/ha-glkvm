"""The config flow: setup and its failures, the duplicate guard, reconfigure, reauth."""

from dataclasses import replace

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.glkvm.api import (
    GlkvmAuthError,
    GlkvmConnectionError,
    GlkvmResponseError,
)
from custom_components.glkvm.const import DOMAIN

from .conftest import ENTRY_DATA, HOST, SERIAL


async def test_user_step_creates_the_entry_keyed_on_the_serial(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == HOST
    assert result["result"].unique_id == SERIAL
    # GL.iNet's hostname, not kvmd's localhost.localdomain.
    assert result["title"] == "GL-RM10-Example"


async def test_title_falls_back_to_the_address(hass, fake_client):
    fake_client.hostname = None
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == HOST


async def test_the_first_form_is_shown_with_no_input(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (GlkvmAuthError("no"), "invalid_auth"),
        (GlkvmConnectionError("down"), "cannot_connect"),
        (GlkvmResponseError(500, "Error", "weird"), "unknown"),
    ],
)
async def test_each_failure_maps_to_its_message(hass, fake_client, raised, expected):
    fake_client.fail = raised
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_the_same_unit_at_a_new_address_updates_the_existing_entry(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**ENTRY_DATA, CONF_HOST: "192.0.2.16"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # Same serial, so the entry followed the unit rather than duplicating it.
    assert config_entry.data[CONF_HOST] == "192.0.2.16"
    # The update schedules a reload; let it finish inside the test.
    await hass.async_block_till_done()


async def test_reconfigure_updates_the_credentials(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
        data={**ENTRY_DATA, CONF_PASSWORD: "newer"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PASSWORD] == "newer"
    # Reconfigure schedules a reload; a reload still running when the test
    # ends leaves the camera component's token timer behind at teardown.
    await hass.async_block_till_done()


async def test_reconfigure_refuses_a_different_unit(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    fake_client.system = replace(fake_client.system, serial="FFFFFFFFFFFFFFFF")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
        data={**ENTRY_DATA, CONF_HOST: "192.0.2.99"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "another_device"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reauth_replaces_only_the_credentials(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "reauthed"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "reauthed"
    assert config_entry.data[CONF_HOST] == HOST
    # Reauth schedules a reload; see test_reconfigure_updates_the_credentials.
    await hass.async_block_till_done()


async def test_reauth_with_a_still_wrong_password_stays_on_the_form(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    fake_client.fail = GlkvmAuthError("still no")
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"}
    )
    assert done["type"] is FlowResultType.FORM
    assert done["errors"] == {"base": "invalid_auth"}
