"""Selects: the virtual drive's image, the mouse mode, and the active port."""

from __future__ import annotations

from typing import override

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SECTION_HID, SECTION_MSD, SECTION_SWITCH
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity, add_switch_entities

# See switch.py: one command at a time to the unit.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [GlkvmImageSelect(coordinator)]
    hid = coordinator.data.hid
    if hid is not None and hid.mouse_outputs:
        entities.append(GlkvmMouseOutputSelect(coordinator))
    async_add_entities(entities)
    add_switch_entities(
        entry, async_add_entities, lambda _switch: [GlkvmActivePortSelect(coordinator)]
    )


class GlkvmImageSelect(GlkvmEntity, SelectEntity):
    """The stored image the virtual drive will present to the host.

    Options are whatever is on the unit's media partition right now, minus
    the directory Windows leaves behind. The drive has to be detached to
    change image; kvmd refuses otherwise, and so does this entity, in words.
    """

    _attr_translation_key = "virtual_media_image"

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "virtual_media_image", section=SECTION_MSD)

    @property
    @override
    def available(self) -> bool:
        return super().available and self.data.msd is not None and self.data.msd.online

    @property
    @override
    def options(self) -> list[str]:
        if self.data.msd is None:
            return []
        return [img.name for img in self.data.msd.images if img.complete]

    @property
    @override
    def current_option(self) -> str | None:
        return self.data.msd.image if self.data.msd else None

    @override
    async def async_select_option(self, option: str) -> None:
        # The user asked for something the unit's state forbids: a validation
        # error, not a failure of the unit.
        if self.data.msd is not None and self.data.msd.connected:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="media_connected"
            )
        await self._run(self.coordinator.client.msd_select_image(option))


class GlkvmMouseOutputSelect(GlkvmEntity, SelectEntity):
    """How the mouse is presented to the host: absolute, relative, hybrid, touch."""

    _attr_translation_key = "mouse_output"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "mouse_output", section=SECTION_HID)

    @property
    @override
    def available(self) -> bool:
        return super().available and self.data.hid is not None and self.data.hid.enabled

    @property
    @override
    def options(self) -> list[str]:
        return list(self.data.hid.mouse_outputs) if self.data.hid else []

    @property
    @override
    def current_option(self) -> str | None:
        return self.data.hid.mouse_output if self.data.hid else None

    @override
    async def async_select_option(self, option: str) -> None:
        await self._run(self.coordinator.client.hid_set_mouse_output(option))


class GlkvmActivePortSelect(GlkvmEntity, SelectEntity):
    """Which of the GL-RM4PE's ports the KVM is showing and typing into.

    Options are the port names set in GL.iNet's web UI, falling back to kvmd's
    own port names and then to "Port 1" to "Port 4" (see SwitchState.labels).
    Selecting one switches the KVM; the unit answers once it has switched,
    about 2.5 s later.
    """

    _attr_translation_key = "active_port"

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "active_port", section=SECTION_SWITCH)

    @property
    @override
    def available(self) -> bool:
        return super().available and self.data.switch is not None

    @property
    @override
    def options(self) -> list[str]:
        return list(self.data.switch.labels) if self.data.switch else []

    @property
    @override
    def current_option(self) -> str | None:
        switch = self.data.switch
        if switch is None or switch.active_port is None:
            return None
        labels = switch.labels
        if switch.active_port >= len(labels):
            return None
        return labels[switch.active_port]

    @override
    async def async_select_option(self, option: str) -> None:
        labels = self.options
        if option not in labels:
            # The names changed on the unit between the options being shown
            # and one being picked.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_port",
                translation_placeholders={"port": option, "count": str(len(labels))},
            )
        async with self.coordinator.port_lock:
            await self._run(
                self.coordinator.client.switch_set_active(labels.index(option))
            )
