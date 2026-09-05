"""The config flow: setup and its failures, discovery, reconfigure, reauth.

Every step that can show an error is also driven past it: the unit comes
back, the same flow is resubmitted, and it ends where it should.
"""

from dataclasses import replace
from ipaddress import ip_address

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.glkvm.api import (
    GlkvmAuthError,
    GlkvmConnectionError,
    GlkvmResponseError,
)
from custom_components.glkvm.config_flow import mac_from_txt, normalise_mac
from custom_components.glkvm.const import DOMAIN

from .conftest import ENTRY_DATA, HOST, SERIAL, UNIT_MAC, UNIT_MAC_TXT


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
    # The unit's own MAC is stored beside the serial: it is what a zeroconf
    # announcement can be matched against, and the serial is not in one.
    assert result["data"][CONF_MAC] == UNIT_MAC


async def test_a_unit_that_will_not_say_its_mac_is_still_added(hass, fake_client):
    # A firmware without the endpoint, or one that errors on it, only costs
    # the entry its discovery key.
    fake_client.network = None
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_MAC not in result["data"]


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


# ----------------------------------------------------------------- zeroconf


def _announcement(host: str = "192.0.2.30", mac: str = UNIT_MAC_TXT, **properties):
    """What the unit puts on the wire, as Home Assistant hands it to the flow.

    Measured from a GL-RM10 on the LAN: `_glinet._tcp.local.` on 443, TXT
    `mn`, `v`, `devid` and `mac`, the MAC base64-encoded, instance name
    GL-RM10-<last three hex of the MAC>.
    """
    txt = {"mn": "rm10", "v": "1.10.0", "devid": "abcdef", "mac": mac, **properties}
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=443,
        hostname="GL-RM10-215.local.",
        type="_glinet._tcp.local.",
        name="GL-RM10-215._glinet._tcp.local.",
        properties={key: value for key, value in txt.items() if value is not None},
    )


async def _discover(hass, info=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info or _announcement()
    )


def test_the_txt_mac_is_base64_of_the_twelve_hex_digits():
    assert mac_from_txt(UNIT_MAC_TXT) == UNIT_MAC
    # Not base64, base64 of the wrong length, and not a string at all.
    assert mac_from_txt("not base64!") is None
    assert mac_from_txt("YWJj") is None
    assert mac_from_txt(None) is None
    assert mac_from_txt("") is None
    # Whatever separated the digits, and whatever case they came in.
    assert normalise_mac("94-83-C4-00-02-15") == UNIT_MAC
    assert normalise_mac("9483c4000215") == UNIT_MAC
    assert normalise_mac("94:83:c4:00:02:1") is None
    assert normalise_mac("zz:83:c4:00:02:15") is None
    assert normalise_mac(None) is None


async def test_a_discovered_unit_asks_for_its_login_and_is_added(hass, fake_client):
    result = await _discover(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {"host": "192.0.2.30"}
    _password_is_not_echoed(result)

    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    # The address and port came from the announcement; the serial, which the
    # announcement cannot carry, came from the unit once it was authenticated.
    assert done["result"].unique_id == SERIAL
    assert done["data"][CONF_HOST] == "192.0.2.30"
    assert done["data"][CONF_PORT] == 443
    assert done["data"][CONF_MAC] == UNIT_MAC


async def test_a_discovered_unit_that_refuses_the_login_recovers(hass, fake_client):
    result = await _discover(hass)
    fake_client.fail = GlkvmAuthError("no")
    shown = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"}
    )
    assert shown["type"] is FlowResultType.FORM
    assert shown["errors"] == {"base": "invalid_auth"}
    _password_is_not_echoed(shown)

    fake_client.fail = None
    done = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "right"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"][CONF_PASSWORD] == "right"


async def test_an_announcement_with_no_readable_mac_is_dropped(hass, fake_client):
    result = await _discover(hass, _announcement(mac=None))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_mac"


async def test_a_known_unit_that_moved_is_followed_to_its_new_address(
    hass, fake_client, config_entry
):
    # discovery-update-info: the entry keeps its identity and its history and
    # is polled at the address the unit is answering on now.
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_MAC: UNIT_MAC}
    )
    result = await _discover(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.0.2.30"
    await hass.async_block_till_done()


async def test_a_known_unit_at_the_address_it_already_has_changes_nothing(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_MAC: UNIT_MAC.upper()}
    )
    result = await _discover(hass, _announcement(host=HOST))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == HOST


async def test_an_entry_added_before_the_mac_was_stored_is_still_recognised(
    hass, fake_client, config_entry
):
    # No stored MAC to match on, so the unit looks new until the confirm step
    # reads its serial; that is what stops a second entry for the same KVM.
    config_entry.add_to_hass(hass)
    result = await _discover(hass)
    assert result["type"] is FlowResultType.FORM
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.0.2.30"
    assert config_entry.data[CONF_MAC] == UNIT_MAC
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


async def test_reauth_refuses_a_different_unit_at_the_same_address(
    hass, fake_client, config_entry
):
    # A KVM swapped in at the stored address will accept its own login. Taking
    # it would hand this entry's device, entities and history to another unit.
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    fake_client.system = replace(fake_client.system, serial="FFFFFFFFFFFFFFFF")
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "other"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "another_device"
    assert config_entry.data[CONF_PASSWORD] == ENTRY_DATA[CONF_PASSWORD]


async def test_reauth_survives_a_unit_that_will_not_say_its_mac(
    hass, fake_client, config_entry
):
    config_entry.add_to_hass(hass)
    fake_client.read_fail["network"] = GlkvmResponseError(500, "Error", "boom")
    result = await config_entry.start_reauth_flow(hass)
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "reauthed"}
    )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "reauthed"
    assert CONF_MAC not in config_entry.data
    await hass.async_block_till_done()
