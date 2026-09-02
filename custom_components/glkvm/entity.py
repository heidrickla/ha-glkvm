"""Shared entity base bound to the one KVM, and the shared error mapping."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import NoReturn

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GlkvmAuthError, GlkvmError
from .const import DOMAIN
from .coordinator import GlkvmCoordinator
from .models import KvmData


def raise_from_error(err: GlkvmError) -> NoReturn:
    """Turn a client error into the translated Home Assistant error.

    Used by every entity command and every action, so a refused credential
    and a failed command read the same everywhere.
    """
    if isinstance(err, GlkvmAuthError):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"error": str(err)},
    ) from err


class GlkvmEntity(CoordinatorEntity[GlkvmCoordinator]):
    """Base entity for the KVM."""

    _attr_has_entity_name = True
    # Declared so the attribute is typed even where Home Assistant is absent
    # and CoordinatorEntity resolves to Any.
    coordinator: GlkvmCoordinator

    def __init__(self, coordinator: GlkvmCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_id}_{key}"
        self._attr_device_info = coordinator.device_info

    @property
    def data(self) -> KvmData:
        data: KvmData = self.coordinator.data
        return data

    async def _run(self, command: Awaitable[None]) -> None:
        """Send one command, translate its failure, then re-read the state.

        The refresh is what makes a switch settle on the state the unit
        actually reached rather than the one that was asked for.
        """
        try:
            await command
        except GlkvmError as err:
            raise_from_error(err)
        await self.coordinator.async_request_refresh()
