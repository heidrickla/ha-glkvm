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

# The Wake-on-LAN list only. WolTarget.name is the label the unit stores for a
# machine on the LAN, in practice that machine's hostname. MsdImage.name and
# MsdState.image are ISO filenames under the same key, and redacting those
# hides what the drive is presenting, so the addition cannot be global.
WOL_REDACT = REDACT | {"name"}


def _plain(value: Any) -> Any:
    """Tuples to lists, recursively.

    asdict() keeps the models' tuples (Wake-on-LAN targets, images, GPIO
    channels) as tuples, and Home Assistant's redactor recurses into lists
    only - a MAC address inside a tuple would go out unredacted.
    """
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GlkvmConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = _plain(asdict(coordinator.data)) if coordinator.data else {}
    if "wol" in data:
        data["wol"] = async_redact_data(data["wol"], WOL_REDACT)
    return {
        "config": async_redact_data(dict(entry.data), REDACT),
        "system": async_redact_data(
            _plain(asdict(coordinator.system)) if coordinator.system else {}, REDACT
        ),
        "firmware": asdict(coordinator.firmware) if coordinator.firmware else {},
        "last_update_success": coordinator.last_update_success,
        "data": async_redact_data(data, REDACT),
    }
