"""Selects: which image the virtual drive presents, and the mouse mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity

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


class GlkvmImageSelect(GlkvmEntity, SelectEntity):
    """The stored image the virtual drive will present to the host.

    Options are whatever is on the unit's media partition right now, minus
    the directory Windows leaves behind. The drive has to be detached to
    change image; kvmd refuses otherwise, and so does this entity, in words.
    """

    _attr_translation_key = "virtual_media_image"

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "virtual_media_image")

    @property
    def available(self) -> bool:
        return super().available and self.data.msd is not None and self.data.msd.online

    @property
    def options(self) -> list[str]:
        if self.data.msd is None:
            return []
        return [img.name for img in self.data.msd.images if img.complete]

    @property
    def current_option(self) -> str | None:
        return self.data.msd.image if self.data.msd else None

    async def async_select_option(self, option: str) -> None:
        if self.data.msd is not None and self.data.msd.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="media_connected"
            )
        await self._run(self.coordinator.client.msd_select_image(option))


class GlkvmMouseOutputSelect(GlkvmEntity, SelectEntity):
    """How the mouse is presented to the host: absolute, relative, hybrid, touch."""

    _attr_translation_key = "mouse_output"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "mouse_output")

    @property
    def available(self) -> bool:
        return super().available and self.data.hid is not None and self.data.hid.enabled

    @property
    def options(self) -> list[str]:
        return list(self.data.hid.mouse_outputs) if self.data.hid else []

    @property
    def current_option(self) -> str | None:
        return self.data.hid.mouse_output if self.data.hid else None

    async def async_select_option(self, option: str) -> None:
        await self._run(self.coordinator.client.hid_set_mouse_output(option))
