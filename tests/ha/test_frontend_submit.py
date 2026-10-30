"""Each form with an Advanced section, submitted the way the dialog sends it.

The data comes from the schema the frontend receives, through a port of its
initial-data code (frontend_form.py); Advanced is never opened.
"""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType

from custom_components.glkvm.api import GlkvmConnectionError
from custom_components.glkvm.const import CONF_ADVANCED, DOMAIN

from .conftest import ENTRY_DATA, HOST, SERIAL
from .frontend_form import frontend_submission
from .test_config_flow import _discover


async def test_the_first_screen_submits_with_advanced_collapsed(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        frontend_submission(result, {CONF_HOST: HOST, CONF_PASSWORD: "secret"}),
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["result"].unique_id == SERIAL
    for key, value in ENTRY_DATA.items():
        assert done["data"][key] == value


async def test_the_first_screen_shown_again_after_an_error_submits(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    fake_client.fail = GlkvmConnectionError("down")
    shown = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        frontend_submission(result, {CONF_HOST: HOST, CONF_PASSWORD: "secret"}),
    )
    assert shown["errors"] == {"base": "cannot_connect"}

    # The address comes back filled in; only the password is typed again.
    fake_client.fail = None
    done = await hass.config_entries.flow.async_configure(
        shown["flow_id"], frontend_submission(shown, {CONF_PASSWORD: "secret"})
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_a_discovered_unit_submits_with_advanced_collapsed(hass, fake_client):
    result = await _discover(hass)
    assert result["step_id"] == "zeroconf_confirm"
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], frontend_submission(result, {CONF_PASSWORD: "secret"})
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["result"].unique_id == SERIAL


async def test_what_was_typed_in_advanced_comes_back_after_an_error(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    fake_client.fail = GlkvmConnectionError("down")
    sent = frontend_submission(result, {CONF_HOST: HOST, CONF_PASSWORD: "secret"})
    sent[CONF_ADVANCED][CONF_PORT] = 8443
    shown = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert shown["errors"] == {"base": "cannot_connect"}

    # The section reopens holding the typed port, and Submit sends it back.
    again = frontend_submission(shown, {CONF_PASSWORD: "secret"})
    assert again[CONF_ADVANCED][CONF_PORT] == 8443
