"""The GL.iNet KVM integration."""

from __future__ import annotations

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import GlkvmClient
from .const import DEFAULT_PORT, DEFAULT_VERIFY_SSL
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions once, at component setup.

    Registered here rather than per entry so an automation calling one while
    the entry is unloaded gets a translated refusal instead of looking like a
    typo in the action name.
    """
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GlkvmConfigEntry) -> bool:
    """Set up one KVM from its config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    # The shared session is the right one: authentication is per-request
    # headers, so there is no cookie jar to keep apart from other integrations.
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = GlkvmClient(
        session,
        entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        username=entry.data.get(CONF_USERNAME) or None,
        password=entry.data.get(CONF_PASSWORD) or None,
        verify_ssl=verify_ssl,
    )
    coordinator = GlkvmCoordinator(hass, entry, client)
    # Raises ConfigEntryNotReady while the unit is unreachable and
    # ConfigEntryAuthFailed when it refuses the credentials.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GlkvmConfigEntry) -> bool:
    """Unload a config entry. The actions stay registered - see async_setup."""
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.clear_issues()
    return unloaded
