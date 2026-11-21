"""The integration's actions, registered once at component setup.

Each takes a `config_entry_id` because a household can have several units;
the entity platforms cover the one-click cases and these cover the ones that
need parameters: typing text, sending a key combination, waking a machine on
the unit's LAN, the full set of ATX power actions, and switching the
GL-RM4PE's active port.

Typing and key presses go to whichever port is active on a GL-RM4PE; the
keyboard gadget follows the switch. So does ATX power: each port has its own
rear USB-A socket for an ATX board, and only the active port's socket is
powered. `power` with a `port` switches there first, waits for that port's
board to appear, and only then presses anything. kvmd's own per-port
endpoints (/api/switch/atx/power and /api/switch/atx/click) answer but do
nothing on GL's firmware, so they are not used.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from . import const
from .api import GlkvmError
from .const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_KEYS,
    ATTR_MAC,
    ATTR_PORT,
    ATTR_SLOW,
    ATTR_TEXT,
    ATTR_WAIT,
    DOMAIN,
    POWER_ACTIONS,
    SERVICE_POWER,
    SERVICE_SEND_KEYS,
    SERVICE_SET_ACTIVE_PORT,
    SERVICE_TYPE_TEXT,
    SERVICE_WAKE,
)
from .coordinator import GlkvmCoordinator
from .entity import raise_from_error
from .models import AtxState, SwitchState

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
# 1-based, as the ports are printed on the unit; the upper bound is the
# unit's own port count, checked when the call runs.
_PORT = vol.All(vol.Coerce(int), vol.Range(min=1))
POWER_SCHEMA = _schema(
    {
        vol.Required(ATTR_ACTION): vol.In(POWER_ACTIONS),
        vol.Optional(ATTR_WAIT, default=True): cv.boolean,
        vol.Optional(ATTR_PORT): _PORT,
    }
)
SET_ACTIVE_PORT_SCHEMA = _schema({vol.Required(ATTR_PORT): _PORT})


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


def _switch(
    hass: HomeAssistant, call: ServiceCall, coordinator: GlkvmCoordinator, port: int
) -> SwitchState:
    """The unit's port switch, refusing a unit without one or a port it lacks."""
    switch = coordinator.data.switch
    if switch is None:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_switch",
            translation_placeholders={"name": entry.title if entry else ""},
        )
    if port > switch.port_count:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_port",
            translation_placeholders={
                "port": str(port),
                "count": str(switch.port_count),
            },
        )
    return switch


async def _wait_for_atx(coordinator: GlkvmCoordinator) -> AtxState | None:
    """The ATX state once a board is present, or None if none appears in time.

    Read fresh from the unit, never from the last poll: straight after a
    switch the poll still describes the previous port's board.
    """
    try:
        async with asyncio.timeout(const.ATX_PORT_TIMEOUT):
            while True:
                atx = await coordinator.client.get_atx()
                if atx.enabled:
                    return atx
                await asyncio.sleep(const.ATX_PORT_POLL_INTERVAL)
    except TimeoutError:
        return None


async def _power_on_port(
    coordinator: GlkvmCoordinator, port: int, action: str, wait: bool
) -> None:
    """Switch to a 1-based port, wait for its ATX board, then run the action.

    The KVM is left on that port: switching back would cut the board's USB
    power, possibly in the middle of a press. Raises GlkvmError from the
    client, and a translated error when no board answers or the port has
    moved by the time the board does.
    """
    index = port - 1
    client = coordinator.client
    async with coordinator.port_lock:
        current = await client.get_switch()
        if current is None or current.active_port != index:
            await client.switch_set_active(index)
        if await _wait_for_atx(coordinator) is None:
            # What the unit did, not what the call asked for: the call was
            # valid and the KVM has switched, so this is no validation error.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_atx_on_port",
                translation_placeholders={"port": str(port)},
            )
        # Last check before pressing anything: the button must reach the
        # host on the port that was asked for, not whichever is active now.
        current = await client.get_switch()
        if current is None or current.active_port != index:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="port_moved",
                translation_placeholders={"port": str(port)},
            )
        await client.atx_power(action, wait=wait)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the five actions, independent of any entry."""

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
        port: int | None = call.data.get(ATTR_PORT)
        if port is not None:
            _switch(hass, call, coordinator, port)
            try:
                await _power_on_port(
                    coordinator, port, call.data[ATTR_ACTION], call.data[ATTR_WAIT]
                )
            except GlkvmError as err:
                raise_from_error(err)
            await coordinator.async_request_refresh()
            return
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

    async def _set_active_port(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        port: int = call.data[ATTR_PORT]
        _switch(hass, call, coordinator, port)
        try:
            async with coordinator.port_lock:
                await coordinator.client.switch_set_active(port - 1)
        except GlkvmError as err:
            raise_from_error(err)
        await coordinator.async_request_refresh()

    # Each action types into, powers, wakes or switches another machine, so only an
    # administrator may call it; a call with no user (automation, script)
    # passes.
    async_register_admin_service(
        hass, DOMAIN, SERVICE_TYPE_TEXT, _type_text, schema=TYPE_TEXT_SCHEMA
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_SEND_KEYS, _send_keys, schema=SEND_KEYS_SCHEMA
    )
    async_register_admin_service(hass, DOMAIN, SERVICE_WAKE, _wake, schema=WAKE_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, SERVICE_POWER, _power, schema=POWER_SCHEMA
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SET_ACTIVE_PORT,
        _set_active_port,
        schema=SET_ACTIVE_PORT_SCHEMA,
    )
