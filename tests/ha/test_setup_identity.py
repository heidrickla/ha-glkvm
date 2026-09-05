"""What setup reads about the unit, and what it does with a gap in it.

The identity reads (/api/info, GL.iNet's firmware, hostname and network
endpoints) decorate the device page and feed discovery. None of them is
allowed to stop an entry that has authenticated, and the MAC among them has
to be kept current, because it is the key a zeroconf announcement is matched
against.
"""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_MAC
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glkvm.api import GlkvmResponseError
from custom_components.glkvm.const import DOMAIN
from custom_components.glkvm.models import NetworkConfig

from .conftest import ENTRY_DATA, SERIAL, UNIT_MAC, setup_entry


async def test_the_identity_read_failing_does_not_stop_the_entry(
    hass, fake_client, config_entry
):
    # /api/info is decoration on the device page. A unit that answers its
    # state reads but not that one still works.
    fake_client.read_fail["system"] = GlkvmResponseError(500, "Error", "boom")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("switch.kvm_host_power").state == "on"
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None and device.serial_number is None


async def test_the_software_version_falls_back_to_kvmds_own(
    hass, fake_client, config_entry
):
    # Firmware without GL.iNet's /api/upgrade/version: the device page shows
    # the kvmd version rather than nothing.
    fake_client.firmware = None
    await setup_entry(hass, config_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None
    assert device.sw_version == "kvmd 4.82"
    assert device.model == "Rockchip RV1126B-P EVB V14 Board"


async def test_an_entry_with_no_unique_id_falls_back_to_its_entry_id(hass, fake_client):
    # A unit that reported no serial when it was added is keyed on its
    # address, and one added before that fallback existed has no unique id at
    # all. The device and its entities still need a stable key.
    entry = MockConfigEntry(domain=DOMAIN, title="KVM", data=dict(ENTRY_DATA))
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None


# ------------------------------------------------------------- the unit MAC


async def test_setup_stores_the_units_mac_for_discovery_to_match_on(
    hass, fake_client, config_entry
):
    assert CONF_MAC not in config_entry.data
    await setup_entry(hass, config_entry)
    assert config_entry.data[CONF_MAC] == UNIT_MAC


async def test_setup_refreshes_a_mac_that_has_changed(hass, fake_client, config_entry):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_MAC: "02:00:00:00:00:ff"}
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.data[CONF_MAC] == UNIT_MAC


async def test_a_unit_that_will_not_say_its_mac_still_sets_up(
    hass, fake_client, config_entry
):
    fake_client.read_fail["network"] = GlkvmResponseError(500, "Error", "boom")
    await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert CONF_MAC not in config_entry.data


async def test_a_firmware_without_the_network_endpoint_stores_no_mac(
    hass, fake_client, config_entry
):
    fake_client.network = None
    await setup_entry(hass, config_entry)
    assert CONF_MAC not in config_entry.data


async def test_a_network_config_without_a_mac_stores_nothing(
    hass, fake_client, config_entry
):
    fake_client.network = NetworkConfig(ip="192.0.2.15")
    await setup_entry(hass, config_entry)
    assert CONF_MAC not in config_entry.data
