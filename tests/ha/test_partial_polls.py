"""A poll where some endpoints answer and some do not.

The unit reads its seven sections from seven endpoints, and GL.iNet's kvmd
fails them one at a time: a 500 from /api/msd while /api/atx is fine, a
socket timeout on one read. What must not happen is an entity going on
showing the value from the last good poll as though the unit had confirmed
it. These tests drive one section at a time and check the entities that read
it, and only those, go unavailable.
"""

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.glkvm.api import GlkvmConnectionError, GlkvmResponseError
from custom_components.glkvm.const import SECTIONS
from custom_components.glkvm.models import KvmData

from .conftest import setup_entry

# One entity per section, chosen because it reads that section and nothing
# else. The GPIO entities come from the recorded unit's own channels.
BY_SECTION = {
    "atx": "switch.kvm_host_power",
    "msd": "select.kvm_virtual_media_image",
    "streamer": "binary_sensor.kvm_video_signal",
    "hid": "binary_sensor.kvm_keyboard_connected",
    "gpio": "switch.kvm_relay",
    "health": "sensor.kvm_cpu_temperature",
    "wol": "button.kvm_wake_lab_server",
}


async def _poll(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.mark.parametrize("section", sorted(BY_SECTION))
@pytest.mark.parametrize(
    "failure",
    [GlkvmConnectionError("timed out"), GlkvmResponseError(500, "Error", "boom")],
    ids=["unreachable", "http_500"],
)
async def test_one_failed_section_only_takes_its_own_entities(
    hass, fake_client, config_entry, section, failure
):
    await setup_entry(hass, config_entry)
    live = hass.states.get(BY_SECTION[section]).state
    assert live != "unavailable"

    fake_client.read_fail[section] = failure
    await _poll(hass, config_entry)
    # The poll succeeded - six sections answered - so the coordinator is not
    # in failure and the other entities are untouched.
    assert config_entry.runtime_data.last_update_success is True
    assert hass.states.get(BY_SECTION[section]).state == "unavailable"
    for other, entity_id in BY_SECTION.items():
        if other != section:
            assert hass.states.get(entity_id).state != "unavailable", other

    # The endpoint comes back and so does the entity, with a real value.
    fake_client.read_fail.clear()
    await _poll(hass, config_entry)
    assert hass.states.get(BY_SECTION[section]).state == live


async def test_six_failed_sections_still_leave_the_seventh_live(
    hass, fake_client, config_entry
):
    await setup_entry(hass, config_entry)
    for section in SECTIONS:
        if section != "atx":
            fake_client.read_fail[section] = GlkvmConnectionError("down")
    await _poll(hass, config_entry)
    assert config_entry.runtime_data.last_update_success is True
    assert hass.states.get("switch.kvm_host_power").state == "on"
    assert hass.states.get("binary_sensor.kvm_video_signal").state == "unavailable"


async def test_a_section_that_fails_before_it_has_ever_answered(
    hass, fake_client, config_entry
):
    # Nothing to keep from a previous poll, so the entities have no value at
    # all. They must be unavailable rather than unknown, and nothing may raise.
    fake_client.read_fail["msd"] = GlkvmConnectionError("timed out")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("select.kvm_virtual_media_image").state == "unavailable"
    assert hass.states.get("switch.kvm_virtual_media_attached").state == "unavailable"
    assert hass.states.get("sensor.kvm_media_storage_free").state == "unavailable"
    assert hass.states.get("switch.kvm_host_power").state == "on"


async def test_every_entity_survives_a_poll_that_carried_nothing(
    hass, fake_client, config_entry
):
    """No section answered but enough of them were reachable to count.

    Every read raised something that is not a connection error, so the poll
    itself succeeded with an empty result. Each entity is asked for its state
    with all seven sections missing; none may raise, and all must be
    unavailable.
    """
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.data = KvmData(failed=SECTIONS)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    for entity_id in (
        "switch.kvm_host_power",
        "switch.kvm_virtual_media_attached",
        "switch.kvm_mouse_jiggler",
        "switch.kvm_relay",
        "button.kvm_power_button",
        "button.kvm_reset_keyboard_and_mouse",
        "button.kvm_demo_button",
        "binary_sensor.kvm_video_signal",
        "binary_sensor.kvm_keyboard_connected",
        "binary_sensor.kvm_door",
        "sensor.kvm_capture_resolution",
        "sensor.kvm_media_storage_free",
        "sensor.kvm_cpu_temperature",
        "select.kvm_virtual_media_image",
        "select.kvm_mouse_mode",
        "camera.kvm_screen",
    ):
        state = hass.states.get(entity_id)
        assert state is not None and state.state == "unavailable", entity_id
