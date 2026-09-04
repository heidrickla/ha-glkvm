"""The config flow: setup and its failures, the duplicate guard, reconfigure, reauth.

Every step that can show an error is also driven past it: the unit comes
back, the same flow is resubmitted, and it ends where it should.
"""

from dataclasses import replace

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.glkvm.api import (
    GlkvmAuthError,
    GlkvmConnectionError,
    GlkvmResponseError,
)
from custom_components.glkvm.const import DOMAIN

from .conftest import ENTRY_DATA, HOST, SERIAL


def _field(schema, name):
    for key in schema.schema:
        if key == name:
            return key
    pytest.fail(f"no {name} field on the form")


def _password_is_not_echoed(result) -> None:
    """The password field carries neither a default nor a suggested value."""
    key = _field(result["data_schema"], CONF_PASSWORD)
    assert key.default is vol.UNDEFINED
    assert (key.description or {}).get("suggested_value") in (None, "")


# --------------------------------------------------------------------- user


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


async def test_a_unit_without_a_serial_is_keyed_on_its_address(hass, fake_client):
    fake_client.system = replace(fake_client.system, serial=None)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == HOST


async def test_the_first_form_is_shown_with_no_input(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    _password_is_not_echoed(result)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (GlkvmAuthError("no"), "invalid_auth"),
        (GlkvmConnectionError("down"), "cannot_connect"),
        (GlkvmResponseError(500, "Error", "weird"), "unknown"),
    ],
)
async def test_each_failure_maps_to_its_message_and_the_flow_recovers(
    hass, fake_client, raised, expected
):
    fake_client.fail = raised
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    # What was typed comes back for correction, except the password.
    assert (
        _field(result["data_schema"], CONF_HOST).description["suggested_value"] == HOST
    )
    _password_is_not_echoed(result)

    # The unit answers on the retry: the same flow finishes.
    fake_client.fail = None
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(ENTRY_DATA)
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["result"].unique_id == SERIAL
    assert done["data"][CONF_PASSWORD] == ENTRY_DATA[CONF_PASSWORD]


async def test_the_same_unit_at_a_new_address_updates_the_existing_entry(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            **ENTRY_DATA,
            CONF_HOST: "192.0.2.16",
            CONF_PORT: 8443,
            CONF_PASSWORD: "rotated",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # Same serial, so the entry followed the unit rather than duplicating it,
    # and took the new port and password with it.
    assert config_entry.data[CONF_HOST] == "192.0.2.16"
    assert config_entry.data[CONF_PORT] == 8443
    assert config_entry.data[CONF_PASSWORD] == "rotated"
    # The update schedules a reload; let it finish inside the test.
    await hass.async_block_till_done()


# -------------------------------------------------------------- reconfigure


async def _start_reconfigure(hass, config_entry, data=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
        data=data,
    )


async def test_reconfigure_updates_the_credentials(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    result = await _start_reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_PASSWORD: "newer"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PASSWORD] == "newer"
    # Reconfigure schedules a reload; a reload still running when the test
    # ends leaves the camera component's token timer behind at teardown.
    await hass.async_block_till_done()


async def test_reconfigure_form_does_not_carry_the_stored_password(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    result = await _start_reconfigure(hass, config_entry)
    assert result["type"] is FlowResultType.FORM
    assert _field(result["data_schema"], CONF_HOST).description["suggested_value"] == (
        HOST
    )
    _password_is_not_echoed(result)


async def test_reconfigure_with_a_blank_password_keeps_the_stored_one(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    result = await _start_reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_HOST: "192.0.2.16", CONF_PASSWORD: ""}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "192.0.2.16"
    assert config_entry.data[CONF_PASSWORD] == ENTRY_DATA[CONF_PASSWORD]
    await hass.async_block_till_done()


async def test_reconfigure_refuses_a_different_unit(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    fake_client.system = replace(fake_client.system, serial="FFFFFFFFFFFFFFFF")
    result = await _start_reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_HOST: "192.0.2.99"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "another_device"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_shows_the_error_then_recovers(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    fake_client.fail = GlkvmConnectionError("wrong address")
    result = await _start_reconfigure(
        hass, config_entry, {**ENTRY_DATA, CONF_HOST: "192.0.2.99"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    # The typed address is offered back for correction; the password is not.
    assert _field(result["data_schema"], CONF_HOST).description["suggested_value"] == (
        "192.0.2.99"
    )
    _password_is_not_echoed(result)
    assert config_entry.data[CONF_HOST] == HOST

    fake_client.fail = None
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, CONF_HOST: "192.0.2.16"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "192.0.2.16"
    await hass.async_block_till_done()


# ------------------------------------------------------------------- reauth


async def test_reauth_replaces_only_the_credentials(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    _password_is_not_echoed(result)
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "reauthed"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "reauthed"
    assert config_entry.data[CONF_HOST] == HOST
    # Reauth schedules a reload; see test_reconfigure_updates_the_credentials.
    await hass.async_block_till_done()


async def test_reauth_with_a_still_wrong_password_stays_on_the_form_then_recovers(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    fake_client.fail = GlkvmAuthError("still no")
    shown = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"}
    )
    assert shown["type"] is FlowResultType.FORM
    assert shown["step_id"] == "reauth_confirm"
    assert shown["errors"] == {"base": "invalid_auth"}
    _password_is_not_echoed(shown)
    assert config_entry.data[CONF_PASSWORD] == ENTRY_DATA[CONF_PASSWORD]

    fake_client.fail = None
    done = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "right"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "right"
    await hass.async_block_till_done()
