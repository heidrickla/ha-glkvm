"""Config flow for GL.iNet KVM: setup, zeroconf, reconfigure and reauth."""

from __future__ import annotations

import base64
import logging
import string
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import (
    GlkvmAuthError,
    GlkvmClient,
    GlkvmConnectionError,
    GlkvmError,
)
from .const import DEFAULT_PORT, DEFAULT_VERIFY_SSL, DOMAIN, NAME, ZEROCONF_MAC

_LOGGER = logging.getLogger(__name__)


def normalise_mac(value: Any) -> str | None:
    """Twelve hex digits, however they were separated, as aa:bb:cc:dd:ee:ff."""
    if not isinstance(value, str):
        return None
    digits = value.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(digits) != 12 or not all(c in string.hexdigits for c in digits):
        return None
    digits = digits.lower()
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def mac_from_txt(value: Any) -> str | None:
    """The MAC out of the mDNS TXT records.

    The unit publishes it as base64 of the twelve hex digits, not as the
    digits themselves, so it has to be decoded before it can be matched
    against the MAC the unit's own API reports.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        # binascii.Error and UnicodeDecodeError are both ValueError.
        decoded = base64.b64decode(value, validate=True).decode("ascii")
    except ValueError:
        return None
    return normalise_mac(decoded)


def _client(hass: HomeAssistant, data: Mapping[str, Any]) -> GlkvmClient:
    verify_ssl = bool(data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
    return GlkvmClient(
        async_get_clientsession(hass, verify_ssl=verify_ssl),
        data[CONF_HOST],
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        username=data.get(CONF_USERNAME) or None,
        password=data.get(CONF_PASSWORD) or None,
        verify_ssl=verify_ssl,
    )


async def _identify(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[str, str, str | None]:
    """Check the credentials against the real unit, then read its identity.

    Returns (unique id, title, MAC). The serial is the unique id, so a unit
    that moves to a new address is recognised rather than added twice; the
    MAC is stored beside it because it is the only key a zeroconf
    announcement shares with the unit. Raises the client's errors on failure.
    """
    client = _client(hass, data)
    await client.check_auth()
    system = await client.get_system()
    # A unit that reports no serial is keyed on its address instead, which
    # still keeps one entry per unit as long as the address holds.
    unique_id = system.serial or str(data[CONF_HOST])
    # kvmd's own meta reports localhost.localdomain; GL.iNet's endpoint has
    # the name the user gave the unit.
    hostname = await client.get_hostname()
    title = hostname or system.hostname or str(data[CONF_HOST])
    if title == "localhost.localdomain":
        title = str(data[CONF_HOST])
    mac: str | None = None
    try:
        network = await client.get_network_config()
    except GlkvmError as err:
        # Only discovery uses the MAC. A firmware that has no such endpoint,
        # or errors on it, must not fail a setup that has authenticated.
        _LOGGER.debug("Could not read the network configuration: %s", err)
    else:
        mac = normalise_mac(network.mac) if network else None
    return unique_id, title, mac


_PASSWORD = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)

# The password has no default on purpose. A default is sent to the frontend,
# where the field can reveal it, and it is also applied when the user clears
# the field, so a blanked password would silently resubmit the old one. What
# the user typed is carried across an error as suggested values instead.
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD): _PASSWORD,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)

_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD): _PASSWORD,
    }
)

# A discovered unit brings its own address and port; only the login and the
# certificate check are left to ask for.
_DISCOVERY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD): _PASSWORD,
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


def _without_password(data: Mapping[str, Any]) -> dict[str, Any]:
    """What may go back to the browser as suggested values: never the secret."""
    return {k: v for k, v in data.items() if k != CONF_PASSWORD}


def _with_mac(data: Mapping[str, Any], mac: str | None) -> dict[str, Any]:
    """Entry data with the unit's MAC beside it, where the unit reported one."""
    stored = dict(data)
    if mac:
        stored[CONF_MAC] = mac
    return stored


class GlkvmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, zeroconf discovery, reconfigure and reauth for one KVM."""

    VERSION = 1

    # What a zeroconf announcement told us, carried into the confirm step.
    _discovered: dict[str, Any]

    async def _async_try(
        self, data: Mapping[str, Any]
    ) -> tuple[dict[str, str], str | None, str | None, str | None]:
        """Validate against the unit. Returns (errors, unique id, title, MAC)."""
        try:
            unique_id, title, mac = await _identify(self.hass, data)
        except GlkvmAuthError:
            return {"base": "invalid_auth"}, None, None, None
        except GlkvmConnectionError:
            return {"base": "cannot_connect"}, None, None, None
        except GlkvmError:
            return {"base": "unknown"}, None, None, None
        return {}, unique_id, title, mac

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, unique_id, title, mac = await self._async_try(user_input)
            if not errors and unique_id is not None:
                data = _with_mac(user_input, mac)
                await self.async_set_unique_id(unique_id)
                # Re-adding a known unit refreshes everything it was reached
                # with, not only the address: a moved unit may also have a
                # new port or a new password.
                self._abort_if_unique_id_configured(updates=dict(data))
                return self.async_create_entry(title=title or NAME, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, _without_password(user_input or {})
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A unit announcing itself as _glinet._tcp.local.

        The serial an entry is keyed on is behind authentication, so it is
        not in the announcement; the MAC is, base64-encoded. A MAC that
        matches a configured entry moves that entry to the new address rather
        than offering the same unit a second time.
        """
        mac = mac_from_txt(discovery_info.properties.get(ZEROCONF_MAC))
        if mac is None:
            return self.async_abort(reason="no_mac")
        host = str(discovery_info.host)
        port = discovery_info.port or DEFAULT_PORT

        for entry in self._async_current_entries(include_ignore=False):
            if normalise_mac(entry.data.get(CONF_MAC)) != mac:
                continue
            if entry.data.get(CONF_HOST) != host:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_HOST: host}
                )
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(reason="already_configured")

        # Until the credentials are entered the MAC is all this unit can be
        # keyed on; the serial replaces it once the confirm step has read it.
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered = {CONF_HOST: host, CONF_PORT: port, CONF_MAC: mac}
        name = discovery_info.name.removesuffix(f".{discovery_info.type}") or host
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask a discovered unit's login, then read the serial it is keyed on."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._discovered, **user_input}
            errors, unique_id, title, mac = await self._async_try(data)
            if not errors and unique_id is not None:
                data = _with_mac(data, mac)
                await self.async_set_unique_id(unique_id, raise_on_progress=False)
                # An entry added before the MAC was stored is recognised here,
                # by its serial, and follows the address it was found at.
                self._abort_if_unique_id_configured(updates=dict(data))
                return self.async_create_entry(title=title or NAME, data=data)
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=self.add_suggested_values_to_schema(
                _DISCOVERY_SCHEMA, _without_password(user_input or {})
            ),
            description_placeholders={"host": self._discovered[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address, port or credentials without re-adding the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            # A blank password keeps the stored one. That is safe both ways:
            # a unit with authentication on never accepts an empty password,
            # and a unit with it off accepts anything.
            data = dict(user_input)
            if not data.get(CONF_PASSWORD):
                data[CONF_PASSWORD] = entry.data.get(CONF_PASSWORD, "")
            errors, unique_id, _title, mac = await self._async_try(data)
            if not errors and unique_id is not None:
                data = _with_mac(data, mac)
                await self.async_set_unique_id(unique_id)
                # The address must still answer as the same unit; a different
                # serial means the user pointed this entry at another KVM.
                self._abort_if_unique_id_mismatch(reason="another_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, _without_password(user_input or entry.data)
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                **entry.data,
                CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD, ""),
            }
            errors, unique_id, _title, mac = await self._async_try(data)
            if not errors and unique_id is not None:
                data = _with_mac(data, mac)
                await self.async_set_unique_id(unique_id)
                # New credentials are only the right ones if the address
                # still answers as this entry's unit. Without this a KVM
                # swapped in at the same address would be re-authenticated
                # into the old entry, taking its history with it.
                self._abort_if_unique_id_mismatch(reason="another_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                _REAUTH_SCHEMA, {CONF_USERNAME: entry.data.get(CONF_USERNAME, "")}
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )
