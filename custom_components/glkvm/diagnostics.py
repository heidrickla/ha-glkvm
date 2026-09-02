"""Downloadable diagnostics."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import GlkvmConfigEntry

# Credentials, plus everything that identifies the household's hardware or
# the machines on its LAN. Diagnostics files end up in public issue trackers.
REDACT = {CONF_HOST, CONF_USERNAME, CONF_PASSWORD, "serial", "hostname", "mac", "ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GlkvmConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "config": async_redact_data(dict(entry.data), REDACT),
        "system": async_redact_data(
            asdict(coordinator.system) if coordinator.system else {}, REDACT
        ),
        "firmware": asdict(coordinator.firmware) if coordinator.firmware else {},
        "last_update_success": coordinator.last_update_success,
        "data": async_redact_data(
            asdict(coordinator.data) if coordinator.data else {}, REDACT
        ),
    }
