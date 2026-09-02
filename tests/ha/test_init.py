"""Setup, unload, the two failure modes, and the repair issues."""

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.helpers import issue_registry as ir

from custom_components.glkvm.api import GlkvmAuthError, GlkvmConnectionError
from custom_components.glkvm.const import (
    DOMAIN,
    ISSUE_MSD_OFFLINE,
    ISSUE_STREAMER_STOPPED,
    SERVICE_POWER,
    SERVICE_SEND_KEYS,
    SERVICE_TYPE_TEXT,
    SERVICE_WAKE,
)
from custom_components.glkvm.models import MsdState, StreamerState
from tests.pure import result

from .conftest import setup_entry


async def _poll(hass, entry, times: int = 1) -> None:
    """Run the coordinator's poll, as the 30 s timer would.

    Driven directly rather than through the loop's timers, so what is tested
    is the poll and not the harness's clock.
    """
    for _ in range(times):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _reauth_in_progress(hass) -> bool:
    return any(
        flow["context"].get("source") == SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_setup_loads_and_creates_the_entities(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    for entity_id in (
        "switch.kvm_host_power",
        "switch.kvm_virtual_media_attached",
        "switch.kvm_mouse_jiggler",
        "switch.kvm_relay",
        "button.kvm_power_button",
        "button.kvm_hold_power_button",
        "button.kvm_reset",
        "button.kvm_reset_keyboard_and_mouse",
        "button.kvm_demo_button",
        "button.kvm_wake_lab_server",
        "binary_sensor.kvm_video_signal",
        "binary_sensor.kvm_keyboard_connected",
        "binary_sensor.kvm_mouse_connected",
        "binary_sensor.kvm_door",
        "sensor.kvm_capture_resolution",
        "sensor.kvm_capture_frame_rate",
        "sensor.kvm_cpu_temperature",
        "sensor.kvm_media_storage_free",
        "select.kvm_virtual_media_image",
        "select.kvm_mouse_mode",
        "camera.kvm_screen",
    ):
        assert hass.states.get(entity_id) is not None, entity_id


async def test_the_device_carries_the_units_identity(hass, fake_client, config_entry):
    from homeassistant.helpers import device_registry as dr

    await setup_entry(hass, config_entry)
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, "0123456789ABCDEF")}
    )
    assert device is not None
    assert device.manufacturer == "GL.iNet"
    assert device.model == "RM10"
    assert device.sw_version == "V1.10.0 beta2"
    assert device.serial_number == "0123456789ABCDEF"
    assert device.configuration_url == "https://192.0.2.15"


async def test_health_sensors_are_not_created_where_the_firmware_has_none(
    hass, fake_client, config_entry
):
    fake_client.health = None
    await setup_entry(hass, config_entry)
    assert hass.states.get("sensor.kvm_cpu_temperature") is None
    assert hass.states.get("sensor.kvm_capture_resolution") is not None


async def test_unload_removes_the_entities_but_not_the_actions(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    for service in (SERVICE_TYPE_TEXT, SERVICE_SEND_KEYS, SERVICE_WAKE, SERVICE_POWER):
        assert hass.services.has_service(DOMAIN, service)


async def test_an_unreachable_unit_retries(hass, fake_client, config_entry):
    fake_client.fail = GlkvmConnectionError("down")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not _reauth_in_progress(hass)


async def test_refused_credentials_start_reauth(hass, fake_client, config_entry):
    fake_client.fail = GlkvmAuthError("nope")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert _reauth_in_progress(hass)


async def test_a_401_on_a_later_poll_starts_reauth(hass, fake_client, config_entry):
    await setup_entry(hass, config_entry)
    fake_client.fail = GlkvmAuthError("password changed")
    await _poll(hass, config_entry)
    assert _reauth_in_progress(hass)
    assert hass.states.get("switch.kvm_host_power").state == "unavailable"


async def test_losing_the_unit_marks_entities_unavailable_then_recovers(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    fake_client.fail = GlkvmConnectionError("cable out")
    await _poll(hass, config_entry)
    assert hass.states.get("binary_sensor.kvm_video_signal").state == "unavailable"
    fake_client.fail = None
    await _poll(hass, config_entry)
    assert hass.states.get("binary_sensor.kvm_video_signal").state == "on"


async def test_msd_offline_raises_a_repair_issue_and_clears_it(
    hass, fake_client, config_entry
):
    fake_client.msd = MsdState.from_result(result("msd_offline.json"))
    await setup_entry(hass, config_entry)
    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_MSD_OFFLINE}_{config_entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None
    assert hass.states.get("switch.kvm_virtual_media_attached").state == "unavailable"

    fake_client.msd = MsdState.from_result(result("msd_with_image.json"))
    await _poll(hass, config_entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    assert hass.states.get("switch.kvm_virtual_media_attached").state == "off"


async def test_a_stopped_streamer_raises_an_issue_only_after_three_polls(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_STREAMER_STOPPED}_{config_entry.entry_id}"

    fake_client.streamer = StreamerState.from_result(result("streamer_stopped.json"))
    await _poll(hass, config_entry, times=2)
    # Two polls: could be GL.iNet's UI in adaptive mode. No issue yet...
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    # ...but the camera and capture sensors already say so.
    assert hass.states.get("camera.kvm_screen").state == "unavailable"
    assert hass.states.get("sensor.kvm_capture_resolution").state == "unavailable"

    await _poll(hass, config_entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    fake_client.streamer = StreamerState.from_result(result("streamer.json"))
    await _poll(hass, config_entry)
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    assert hass.states.get("sensor.kvm_capture_resolution").state == "2560x1440"


async def test_unload_clears_the_issues(hass, fake_client, config_entry):
    fake_client.msd = MsdState.from_result(result("msd_offline.json"))
    await setup_entry(hass, config_entry)
    issue_id = f"{ISSUE_MSD_OFFLINE}_{config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
