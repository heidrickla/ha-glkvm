"""The GL-RM4PE's port switch: its entities, the action, and its poll section.

The recorded GL-RM10 has no switch, so FakeClient defaults to none and every
other test file sees the entity set it always did. Here the fake is given
the shape a GL-RM4PE answers /api/switch with, and port names as GL's web UI
stores them (invented names, not a household's).
"""

from dataclasses import replace

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.glkvm.api import GlkvmConnectionError, GlkvmResponseError
from custom_components.glkvm.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PORT,
    DOMAIN,
    SERVICE_SET_ACTIVE_PORT,
    SERVICE_TYPE_TEXT,
)
from custom_components.glkvm.diagnostics import async_get_config_entry_diagnostics

from .conftest import RM4PE_SWITCH, SERIAL, setup_entry

NAMES = ("Workstation", None, "Build box", "Media player")
LABELS = ["Workstation", "Port 2", "Build box", "Media player"]

SELECT = "select.kvm_active_port"
SENSOR = "sensor.kvm_active_port"
PORT_VIDEO = [f"binary_sensor.kvm_port_{n}_video" for n in range(1, 5)]


@pytest.fixture
def rm4pe(fake_client):
    fake_client.switch = RM4PE_SWITCH
    fake_client.port_names = NAMES
    return fake_client


async def _poll(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def _set_port(hass, entry, port) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_ACTIVE_PORT,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_PORT: port},
        blocking=True,
    )


# ------------------------------------------------------------- no switch


async def test_a_unit_without_a_switch_gets_no_switch_entities(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    registry = er.async_get(hass)
    for entity_id in (SELECT, SENSOR, *PORT_VIDEO):
        assert hass.states.get(entity_id) is None, entity_id
        assert registry.async_get(entity_id) is None, entity_id
    # Absence is not a failure: nothing is unavailable, and the switch is not
    # among the failed sections.
    assert "switch" not in config_entry.runtime_data.data.failed
    assert config_entry.runtime_data.data.switch is None
    # The port names are only asked for where there is a switch.
    assert "port_names" not in fake_client.reads
    assert hass.states.get("switch.kvm_host_power").state == "on"


async def test_the_action_refuses_a_unit_without_a_switch(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError, match="has no port switch"):
        await _set_port(hass, config_entry, 1)
    assert fake_client.calls == []


# ------------------------------------------------------------- entities


async def test_the_switch_entities_and_their_ids(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get(SELECT).unique_id == f"{SERIAL}_active_port"
    assert registry.async_get(SENSOR).unique_id == f"{SERIAL}_active_port"
    for n, entity_id in enumerate(PORT_VIDEO, start=1):
        assert registry.async_get(entity_id).unique_id == f"{SERIAL}_port_{n}_video"

    select = hass.states.get(SELECT)
    assert select.attributes["options"] == LABELS
    assert select.state == "Workstation"
    assert select.attributes["friendly_name"] == "KVM Active port"
    # 1-based, as printed on the unit; kvmd reported active_port 0.
    assert hass.states.get(SENSOR).state == "1"
    # video.links was [true, false, true, true].
    assert [hass.states.get(e).state for e in PORT_VIDEO] == ["on", "off", "on", "on"]
    port_2 = hass.states.get(PORT_VIDEO[1])
    assert port_2.attributes["device_class"] == "plug"
    assert port_2.attributes["friendly_name"] == "KVM Port 2 video"


async def test_without_names_the_ports_are_numbered(hass, rm4pe, config_entry):
    rm4pe.port_names = None
    await setup_entry(hass, config_entry)
    select = hass.states.get(SELECT)
    assert select.attributes["options"] == ["Port 1", "Port 2", "Port 3", "Port 4"]
    assert select.state == "Port 1"


async def test_selecting_a_port_switches_and_re_reads(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    rm4pe.reads.clear()
    rm4pe.switch = replace(RM4PE_SWITCH, active_port=2, active_id="1.3")
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Build box"},
        blocking=True,
    )
    await hass.async_block_till_done()
    # 0-based on the wire.
    assert rm4pe.calls == [("switch_set_active", (2,), {})]
    assert "switch" in rm4pe.reads
    assert hass.states.get(SELECT).state == "Build box"
    assert hass.states.get(SENSOR).state == "3"


async def test_no_active_port_reads_unknown(hass, rm4pe, config_entry):
    rm4pe.switch = replace(RM4PE_SWITCH, active_port=None)
    await setup_entry(hass, config_entry)
    assert hass.states.get(SELECT).state == "unknown"
    assert hass.states.get(SENSOR).state == "unknown"


async def test_an_active_port_beyond_the_listed_ports_reads_unknown(
    hass, rm4pe, config_entry
):
    rm4pe.switch = replace(RM4PE_SWITCH, active_port=7)
    await setup_entry(hass, config_entry)
    assert hass.states.get(SELECT).state == "unknown"


async def test_a_name_gone_by_the_time_it_is_picked_is_refused(
    hass, rm4pe, config_entry
):
    await setup_entry(hass, config_entry)
    entity = hass.data["entity_components"]["select"].get_entity(SELECT)
    with pytest.raises(ServiceValidationError):
        await entity.async_select_option("Renamed meanwhile")
    assert rm4pe.calls == []


async def test_a_failed_switch_is_a_translated_error(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    rm4pe.fail = GlkvmResponseError(500, "Error", "boom")
    with pytest.raises(HomeAssistantError, match="did not carry out"):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": SELECT, "option": "Port 2"},
            blocking=True,
        )


# --------------------------------------------------------------- action


async def test_the_action_takes_the_printed_port_number(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    await _set_port(hass, config_entry, 4)
    await _set_port(hass, config_entry, "1")
    assert rm4pe.calls == [
        ("switch_set_active", (3,), {}),
        ("switch_set_active", (0,), {}),
    ]


async def test_the_action_refuses_a_port_the_unit_does_not_have(
    hass, rm4pe, config_entry
):
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError, match="It has 4"):
        await _set_port(hass, config_entry, 5)
    with pytest.raises(vol.Invalid):
        await _set_port(hass, config_entry, 0)
    with pytest.raises(vol.Invalid):
        await _set_port(hass, config_entry, "two")
    assert rm4pe.calls == []


async def test_the_action_reports_a_failed_switch(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    rm4pe.fail = GlkvmConnectionError("timed out")
    with pytest.raises(HomeAssistantError):
        await _set_port(hass, config_entry, 2)


async def test_typing_still_goes_to_the_unit_on_a_switch(hass, rm4pe, config_entry):
    # kvmd's HID gadget follows the switch, so type_text needs no port.
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_TYPE_TEXT,
        {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, "text": "hi"},
        blocking=True,
    )
    assert rm4pe.calls == [("hid_type_text", ("hi",), {"slow": False})]


# ------------------------------------------------------------- polling


async def test_a_failed_switch_read_takes_only_the_switch_entities(
    hass, rm4pe, config_entry
):
    await setup_entry(hass, config_entry)
    rm4pe.read_fail["switch"] = GlkvmConnectionError("timed out")
    await _poll(hass, config_entry)
    assert config_entry.runtime_data.last_update_success is True
    for entity_id in (SELECT, SENSOR, *PORT_VIDEO):
        assert hass.states.get(entity_id).state == "unavailable", entity_id
    assert hass.states.get("switch.kvm_host_power").state == "on"

    rm4pe.read_fail.clear()
    await _poll(hass, config_entry)
    assert hass.states.get(SELECT).state == "Workstation"
    assert hass.states.get(PORT_VIDEO[0]).state == "on"


async def test_unreadable_port_names_are_not_a_failure(hass, rm4pe, config_entry):
    await setup_entry(hass, config_entry)
    rm4pe.read_fail["port_names"] = GlkvmResponseError(502, "BadRequestError", "x")
    await _poll(hass, config_entry)
    data = config_entry.runtime_data.data
    assert data.failed == ()
    # The names the last read had are kept.
    assert hass.states.get(SELECT).attributes["options"] == LABELS


async def test_port_names_unreadable_from_the_start_fall_back_to_numbers(
    hass, rm4pe, config_entry
):
    rm4pe.read_fail["port_names"] = GlkvmConnectionError("timed out")
    await setup_entry(hass, config_entry)
    assert hass.states.get(SELECT).attributes["options"] == [
        "Port 1",
        "Port 2",
        "Port 3",
        "Port 4",
    ]
    assert config_entry.runtime_data.last_update_success is True


async def test_names_changed_on_the_unit_show_at_the_next_poll(
    hass, rm4pe, config_entry
):
    await setup_entry(hass, config_entry)
    rm4pe.port_names = ("Laptop", "Laptop", None, None)
    await _poll(hass, config_entry)
    assert hass.states.get(SELECT).attributes["options"] == [
        "Laptop (1)",
        "Laptop (2)",
        "Port 3",
        "Port 4",
    ]
    assert hass.states.get(SELECT).state == "Laptop (1)"
    # Entity names and ids follow the printed number, not the name.
    assert hass.states.get(PORT_VIDEO[0]) is not None


async def test_a_switch_that_answers_late_still_gets_its_entities(
    hass, rm4pe, config_entry
):
    rm4pe.read_fail["switch"] = GlkvmResponseError(500, "Error", "boom")
    await setup_entry(hass, config_entry)
    assert hass.states.get(SELECT) is None

    rm4pe.read_fail.clear()
    await _poll(hass, config_entry)
    assert hass.states.get(SELECT).state == "Workstation"
    assert hass.states.get(SENSOR).state == "1"
    assert hass.states.get(PORT_VIDEO[3]).state == "on"
    # A later poll does not add them twice.
    await _poll(hass, config_entry)
    registry = er.async_get(hass)
    ours = [
        e
        for e in er.async_entries_for_config_entry(registry, config_entry.entry_id)
        if "port" in e.unique_id
    ]
    assert len(ours) == 6


async def test_a_switch_that_disappears_makes_its_entities_unavailable(
    hass, rm4pe, config_entry
):
    await setup_entry(hass, config_entry)
    rm4pe.switch = None
    await _poll(hass, config_entry)
    assert config_entry.runtime_data.last_update_success is True
    for entity_id in (SELECT, SENSOR, *PORT_VIDEO):
        assert hass.states.get(entity_id).state == "unavailable", entity_id


async def test_an_unreachable_unit_with_a_switch_is_unreachable(
    hass, rm4pe, config_entry
):
    await setup_entry(hass, config_entry)
    for section in ("atx", "msd", "streamer", "hid", "gpio", "health", "wol"):
        rm4pe.read_fail[section] = GlkvmConnectionError("down")
    # The switch answered, so the unit is there: a partial poll.
    await _poll(hass, config_entry)
    assert config_entry.runtime_data.last_update_success is True
    assert hass.states.get(SELECT).state == "Workstation"

    rm4pe.read_fail["switch"] = GlkvmConnectionError("down")
    await _poll(hass, config_entry)
    assert config_entry.runtime_data.last_update_success is False


async def test_diagnostics_redact_the_port_names(hass, rm4pe, config_entry):
    rm4pe.switch = replace(
        RM4PE_SWITCH,
        ports=tuple(replace(p, name="kvmd name") for p in RM4PE_SWITCH.ports),
    )
    await setup_entry(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    switch = diag["data"]["switch"]
    assert switch["ui_names"] == "**REDACTED**"
    assert switch["ports"][0]["name"] == "**REDACTED**"
    assert "Workstation" not in repr(diag)
    assert "kvmd name" not in repr(diag)
    # Everything else about the switch stays in clear.
    assert switch["active_port"] == 0
    assert switch["video_links"] == [True, False, True, True]
    assert switch["ports"][0]["id"] == "1.1"
