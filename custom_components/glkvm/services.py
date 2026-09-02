"""The integration's actions, registered once at component setup.

Each takes a `config_entry_id` because a household can have several units;
the entity platforms cover the one-click cases and these cover the ones that
need parameters: typing text, sending a key combination, waking a machine on
the unit's LAN, and the full set of ATX power actions.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import GlkvmError
from .const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_KEYS,
    ATTR_MAC,
    ATTR_SLOW,
    ATTR_TEXT,
    ATTR_WAIT,
    DOMAIN,
    POWER_ACTIONS,
    SERVICE_POWER,
    SERVICE_SEND_KEYS,
    SERVICE_TYPE_TEXT,
    SERVICE_WAKE,
)
from .coordinator import GlkvmCoordinator
from .entity import raise_from_error

_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def _schema(fields: dict[vol.Marker, Any]) -> vol.Schema:
    """A service schema: the config entry the call names, plus its own fields."""
    return vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string, **fields})


TYPE_TEXT_SCHEMA = _schema(
    {
        vol.Required(ATTR_TEXT): cv.string,
        vol.Optional(ATTR_SLOW, default=False): cv.boolean,
    }
)
SEND_KEYS_SCHEMA = _schema(
    {vol.Required(ATTR_KEYS): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1))}
)
WAKE_SCHEMA = _schema({vol.Required(ATTR_MAC): cv.string})
POWER_SCHEMA = _schema(
    {
        vol.Required(ATTR_ACTION): vol.In(POWER_ACTIONS),
        vol.Optional(ATTR_WAIT, default=True): cv.boolean,
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> GlkvmCoordinator:
    """The loaded coordinator the call names, or a translated refusal."""
    entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_loaded",
            translation_placeholders={"name": entry.title},
        )
    coordinator: GlkvmCoordinator = entry.runtime_data
    return coordinator


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the four actions, independent of any entry."""

    async def _type_text(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        try:
            await coordinator.client.hid_type_text(
                call.data[ATTR_TEXT], slow=call.data[ATTR_SLOW]
            )
        except GlkvmError as err:
            raise_from_error(err)

    async def _send_keys(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        keys: list[str] = [k.strip() for k in call.data[ATTR_KEYS] if k.strip()]
        if not keys:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_keys"
            )
        try:
            await coordinator.client.hid_send_shortcut(keys)
        except GlkvmError as err:
            raise_from_error(err)

    async def _wake(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        mac: str = call.data[ATTR_MAC].strip()
        if not _MAC.match(mac):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_mac",
                translation_placeholders={"mac": mac},
            )
        try:
            await coordinator.client.wol_wake(mac.replace("-", ":").lower())
        except GlkvmError as err:
            raise_from_error(err)

    async def _power(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        if coordinator.data.atx is None or not coordinator.data.atx.enabled:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_atx"
            )
        try:
            await coordinator.client.atx_power(
                call.data[ATTR_ACTION], wait=call.data[ATTR_WAIT]
            )
        except GlkvmError as err:
            raise_from_error(err)
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_TYPE_TEXT, _type_text, schema=TYPE_TEXT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_KEYS, _send_keys, schema=SEND_KEYS_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_WAKE, _wake, schema=WAKE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_POWER, _power, schema=POWER_SCHEMA)
