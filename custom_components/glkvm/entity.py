"""Shared entity base bound to the one KVM, and the shared error mapping."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from typing import NoReturn, override

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GlkvmAuthError, GlkvmError
from .const import DOMAIN
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .models import KvmData, SwitchState


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


def add_switch_entities(
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[SwitchState], Iterable[Entity]],
) -> None:
    """Add a platform's port-switch entities once the unit has shown a switch.

    Only a GL-RM4PE has one. Asked again on every refresh, so a switch read
    that failed at startup still gets its entities when it answers, as the
    health sensors do; once added they are not added again.
    """
    coordinator = entry.runtime_data
    added = False

    @callback
    def _add() -> None:
        nonlocal added
        switch = coordinator.data.switch if coordinator.data else None
        if added or switch is None:
            return
        added = True
        async_add_entities(build(switch))

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class GlkvmEntity(CoordinatorEntity[GlkvmCoordinator]):
    """Base entity for the KVM."""

    _attr_has_entity_name = True
    # Declared so the attribute is typed even where Home Assistant is absent
    # and CoordinatorEntity resolves to Any.
    coordinator: GlkvmCoordinator

    def __init__(
        self, coordinator: GlkvmCoordinator, key: str, *, section: str | None = None
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_id}_{key}"
        self._attr_device_info = coordinator.device_info
        # Which of the poll's eight sections this entity reads, if any.
        self._section = section

    @property
    def data(self) -> KvmData:
        data: KvmData = self.coordinator.data
        return data

    @property
    @override
    def available(self) -> bool:
        """False while the section this entity reads is failing.

        A partial poll keeps the failed section's last value so the entity
        set does not churn. Showing that value would be reporting state the
        unit has not confirmed, so the entity goes unavailable instead.
        """
        return super().available and self._section not in self.data.failed

    async def _async_require_admin(self) -> None:
        """Refuse a call made by a user who is not an administrator.

        Every command operates the attached host or reconfigures the unit.
        A call with no user (an automation, a script) passes.
        """
        context = self._context
        user_id = context.user_id if context is not None else None
        if user_id is None:
            return
        user = await self.hass.auth.async_get_user(user_id)
        if user is None or not user.is_admin:
            raise Unauthorized(context=context, entity_id=self.entity_id)

    async def _run(self, command: Awaitable[None]) -> None:
        """Send one command, translate its failure, then re-read the state.

        The refresh is what makes a switch settle on the state the unit
        actually reached rather than the one that was asked for.
        """
        try:
            await self._async_require_admin()
        except Unauthorized:
            # The command was built but never sent; close it so it is not
            # reported as a coroutine that was never awaited.
            if inspect.iscoroutine(command):
                command.close()
            raise
        try:
            await command
        except GlkvmError as err:
            raise_from_error(err)
        await self.coordinator.async_request_refresh()
