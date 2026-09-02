"""The entities and actions: what they read, and what they send."""

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.glkvm.api import GlkvmAuthError, GlkvmResponseError
from custom_components.glkvm.const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_KEYS,
    ATTR_MAC,
    ATTR_TEXT,
    DOMAIN,
    SERVICE_POWER,
    SERVICE_SEND_KEYS,
    SERVICE_TYPE_TEXT,
    SERVICE_WAKE,
)
from custom_components.glkvm.diagnostics import async_get_config_entry_diagnostics
from custom_components.glkvm.models import AtxState, MsdState
from tests.pure import result

from .conftest import SERIAL, WOL_MAC, setup_entry


async def _poll(hass, entry) -> None:
    """Run the coordinator's poll, as the 30 s timer would."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def _call(hass, domain: str, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, **data}, blocking=True
    )


# ------------------------------------------------------------------- states


async def test_states_read_from_the_recorded_unit(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    assert hass.states.get("switch.kvm_host_power").state == "on"
    assert hass.states.get("binary_sensor.kvm_video_signal").state == "on"
    assert hass.states.get("binary_sensor.kvm_keyboard_connected").state == "on"
    assert hass.states.get("binary_sensor.kvm_door").state == "on"
    assert hass.states.get("sensor.kvm_capture_resolution").state == "2560x1440"
    assert hass.states.get("sensor.kvm_capture_frame_rate").state == "60"
    assert hass.states.get("sensor.kvm_cpu_temperature").state == "47.03"
    assert hass.states.get("switch.kvm_virtual_media_attached").state == "off"
    assert hass.states.get("switch.kvm_mouse_jiggler").state == "on"
    assert hass.states.get("switch.kvm_relay").state == "off"
    select = hass.states.get("select.kvm_virtual_media_image")
    assert select.state == "ubuntu.iso"
    # The incomplete upload is not offered; the Windows directory never is.
    assert select.attributes["options"] == ["rescue.iso", "ubuntu.iso"]
    mouse = hass.states.get("select.kvm_mouse_mode")
    assert mouse.state == "usb"
    assert mouse.attributes["options"] == ["usb", "usb_rel", "usb_hybrid", "usb_touch"]


async def test_media_storage_is_reported_in_bytes_from_the_unit(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    state = hass.states.get("sensor.kvm_media_storage_free")
    # Suggested unit is GB, so the displayed value is converted.
    assert state.attributes["unit_of_measurement"] == "GB"
    assert float(state.state) == pytest.approx(25.9, abs=0.1)


async def test_without_an_atx_board_the_power_entities_are_unavailable(
    hass, fake_client, config_entry
):
    fake_client.atx = AtxState.from_result(result("atx_no_board.json"))
    await setup_entry(hass, config_entry)
    assert hass.states.get("switch.kvm_host_power").state == "unavailable"
    assert hass.states.get("button.kvm_power_button").state == "unavailable"
    assert hass.states.get("button.kvm_reset").state == "unavailable"
    # Everything else is fine.
    assert hass.states.get("binary_sensor.kvm_video_signal").state == "on"


async def test_disabled_by_default_sensors_are_not_added(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    registry = er.async_get(hass)
    entry = registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_network_rx_rate")
    assert entry is not None
    assert registry.async_get(entry).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entry) is None


# ----------------------------------------------------------------- commands


async def test_host_power_switch_sends_the_graceful_pair(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    await _call(hass, "switch", "turn_off", "switch.kvm_host_power")
    await _call(hass, "switch", "turn_on", "switch.kvm_host_power")
    assert fake_client.calls[0] == ("atx_power", ("off",), {"wait": True})
    assert fake_client.calls[1] == ("atx_power", ("on",), {"wait": True})


async def test_the_atx_buttons(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await _call(hass, "button", "press", "button.kvm_power_button")
    await _call(hass, "button", "press", "button.kvm_hold_power_button")
    await _call(hass, "button", "press", "button.kvm_reset")
    assert [c[1][0] for c in fake_client.calls] == ["power", "power_long", "reset"]
    assert {c[0] for c in fake_client.calls} == {"atx_click"}


async def test_virtual_media_attach_and_detach(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await _call(hass, "switch", "turn_on", "switch.kvm_virtual_media_attached")
    await _call(hass, "switch", "turn_off", "switch.kvm_virtual_media_attached")
    assert fake_client.calls == [
        ("msd_set_connected", (True,), {}),
        ("msd_set_connected", (False,), {}),
    ]


async def test_attaching_with_no_image_selected_is_refused_in_words(
    hass, fake_client, config_entry
):
    fake_client.msd = MsdState.from_result(result("msd.json"))
    await setup_entry(hass, config_entry)
    with pytest.raises(HomeAssistantError):
        await _call(hass, "switch", "turn_on", "switch.kvm_virtual_media_attached")
    assert fake_client.calls == []


async def test_selecting_an_image(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await _call(
        hass,
        "select",
        "select_option",
        "select.kvm_virtual_media_image",
        option="rescue.iso",
    )
    assert fake_client.calls == [("msd_select_image", ("rescue.iso",), {"cdrom": True})]


async def test_changing_the_image_while_attached_is_refused(
    hass, fake_client, config_entry
):
    fake_client.msd = MsdState.from_result(result("msd_connected.json"))
    await setup_entry(hass, config_entry)
    assert hass.states.get("switch.kvm_virtual_media_attached").state == "on"
    with pytest.raises(HomeAssistantError):
        await _call(
            hass,
            "select",
            "select_option",
            "select.kvm_virtual_media_image",
            option="ubuntu.iso",
        )
    assert fake_client.calls == []


async def test_jiggler_and_mouse_mode(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await _call(hass, "switch", "turn_off", "switch.kvm_mouse_jiggler")
    await _call(
        hass, "select", "select_option", "select.kvm_mouse_mode", option="usb_rel"
    )
    await _call(hass, "button", "press", "button.kvm_reset_keyboard_and_mouse")
    assert fake_client.calls == [
        ("hid_set_jiggler", (False,), {}),
        ("hid_set_mouse_output", ("usb_rel",), {}),
        ("hid_reset", (), {}),
    ]


async def test_gpio_switch_and_pulse(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await _call(hass, "switch", "turn_on", "switch.kvm_relay")
    await _call(hass, "button", "press", "button.kvm_demo_button")
    assert fake_client.calls == [
        ("gpio_switch", ("relay", True), {"wait": True}),
        ("gpio_pulse", ("demo_button",), {"wait": True}),
    ]


async def test_wake_button_and_its_lifecycle(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    state = hass.states.get("button.kvm_wake_lab_server")
    assert state.attributes["mac"] == WOL_MAC
    await _call(hass, "button", "press", "button.kvm_wake_lab_server")
    assert fake_client.calls == [("wol_wake", (WOL_MAC,), {})]

    # Removed on the unit: removed from the registry on the next poll.
    fake_client.wol = ()
    await _poll(hass, config_entry)
    registry = er.async_get(hass)
    unique_id = f"{SERIAL}_wake_{WOL_MAC.replace(':', '')}"
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is None

    # Added back: a button again.
    fake_client.wol = FakeWol.targets()
    await _poll(hass, config_entry)
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is not None


class FakeWol:
    @staticmethod
    def targets():
        from custom_components.glkvm.models import WolTarget

        return WolTarget.list_from_result(result("wol_list.json"))


async def test_a_failed_command_is_a_translated_error(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    fake_client.fail = GlkvmResponseError(500, "AtxIsBusyError", "busy")
    with pytest.raises(HomeAssistantError):
        await _call(hass, "button", "press", "button.kvm_reset")


async def test_a_refused_command_reads_as_an_auth_error(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    fake_client.fail = GlkvmAuthError("no")
    with pytest.raises(HomeAssistantError, match="rejected the credentials"):
        await _call(hass, "button", "press", "button.kvm_reset")


# ------------------------------------------------------------------- camera


async def test_the_camera_serves_the_snapshot(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    image = await async_get_image(hass, "camera.kvm_screen")
    assert image.content == b"\xff\xd8\xff\xe0jpeg"


async def test_the_camera_survives_a_snapshot_failure(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    fake_client.fail = GlkvmResponseError(500, "Error", "boom")
    with pytest.raises(HomeAssistantError):
        await async_get_image(hass, "camera.kvm_screen")


# ------------------------------------------------------------------ actions


async def test_type_text_action(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_TYPE_TEXT,
        {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_TEXT: "echo hi"},
        blocking=True,
    )
    assert fake_client.calls == [("hid_type_text", ("echo hi",), {"slow": False})]


async def test_send_keys_action(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_KEYS,
        {
            ATTR_CONFIG_ENTRY_ID: config_entry.entry_id,
            ATTR_KEYS: ["ControlLeft", "AltLeft", "Delete"],
        },
        blocking=True,
    )
    assert fake_client.calls == [
        ("hid_send_shortcut", (["ControlLeft", "AltLeft", "Delete"],), {})
    ]


async def test_wake_action_normalises_the_mac(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_WAKE,
        {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_MAC: "AA-BB-CC-DD-EE-FF"},
        blocking=True,
    )
    assert fake_client.calls == [("wol_wake", ("aa:bb:cc:dd:ee:ff",), {})]


async def test_wake_action_refuses_a_non_mac(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_WAKE,
            {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_MAC: "lab-server"},
            blocking=True,
        )
    assert fake_client.calls == []


async def test_power_action(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_POWER,
        {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_ACTION: "reset_hard"},
        blocking=True,
    )
    assert fake_client.calls == [("atx_power", ("reset_hard",), {"wait": True})]


async def test_power_action_without_a_board_is_refused(hass, fake_client, config_entry):
    fake_client.atx = AtxState.from_result(result("atx_no_board.json"))
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_POWER,
            {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_ACTION: "on"},
            blocking=True,
        )
    assert fake_client.calls == []


async def test_actions_refuse_an_unknown_entry(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_TYPE_TEXT,
            {ATTR_CONFIG_ENTRY_ID: "nope", ATTR_TEXT: "x"},
            blocking=True,
        )


async def test_actions_refuse_an_unloaded_entry_in_words(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_TYPE_TEXT,
            {ATTR_CONFIG_ENTRY_ID: config_entry.entry_id, ATTR_TEXT: "x"},
            blocking=True,
        )


# -------------------------------------------------------------- diagnostics


async def test_diagnostics_redact_what_identifies_the_household(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["config"]["host"] == "**REDACTED**"
    assert diag["config"]["password"] == "**REDACTED**"
    assert diag["system"]["serial"] == "**REDACTED**"
    assert diag["data"]["wol"][0]["mac"] == "**REDACTED**"
    assert diag["firmware"]["model"] == "RM10"
    assert diag["data"]["streamer"]["running"] is True
