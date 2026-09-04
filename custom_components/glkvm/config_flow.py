"""Config flow for GL.iNet KVM: setup, reconfigure and reauth."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GlkvmAuthError,
    GlkvmClient,
    GlkvmConnectionError,
    GlkvmError,
)
from .const import DEFAULT_PORT, DEFAULT_VERIFY_SSL, DOMAIN, NAME


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


async def _identify(hass: HomeAssistant, data: Mapping[str, Any]) -> tuple[str, str]:
    """Check the credentials against the real unit, then read its identity.

    Returns (unique id, title). The serial is the unique id, so a unit that
    moves to a new address is recognised rather than added twice. Raises the
    client's errors on failure.
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
    return unique_id, title


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


def _without_password(data: Mapping[str, Any]) -> dict[str, Any]:
    """What may go back to the browser as suggested values: never the secret."""
    return {k: v for k, v in data.items() if k != CONF_PASSWORD}


class GlkvmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, reconfigure and reauth for one KVM."""

    VERSION = 1

    async def _async_try(
        self, data: Mapping[str, Any]
    ) -> tuple[dict[str, str], str | None, str | None]:
        """Validate against the unit. Returns (errors, unique id, title)."""
        try:
            unique_id, title = await _identify(self.hass, data)
        except GlkvmAuthError:
            return {"base": "invalid_auth"}, None, None
        except GlkvmConnectionError:
            return {"base": "cannot_connect"}, None, None
        except GlkvmError:
            return {"base": "unknown"}, None, None
        return {}, unique_id, title

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, unique_id, title = await self._async_try(user_input)
            if not errors and unique_id is not None:
                await self.async_set_unique_id(unique_id)
                # Re-adding a known unit refreshes everything it was reached
                # with, not only the address: a moved unit may also have a
                # new port or a new password.
                self._abort_if_unique_id_configured(updates=dict(user_input))
                return self.async_create_entry(title=title or NAME, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, _without_password(user_input or {})
            ),
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
            errors, unique_id, _title = await self._async_try(data)
            if not errors and unique_id is not None:
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
            errors, _unique_id, _title = await self._async_try(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                _REAUTH_SCHEMA, {CONF_USERNAME: entry.data.get(CONF_USERNAME, "")}
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )
