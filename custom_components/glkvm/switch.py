"""Switches: host power, virtual media, the mouse jiggler, GPIO outputs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SECTION_ATX, SECTION_GPIO, SECTION_HID, SECTION_MSD
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity
from .models import GpioChannel

# Commands go to one embedded device that serialises its own ATX and USB
# gadget operations; sending them one at a time avoids "busy" refusals.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        GlkvmHostPowerSwitch(coordinator),
        GlkvmVirtualMediaSwitch(coordinator),
        GlkvmJigglerSwitch(coordinator),
    ]
    if coordinator.data.gpio is not None:
        entities.extend(
            GlkvmGpioSwitch(coordinator, channel)
            for channel in coordinator.data.gpio.outputs
            if channel.switch
        )
    async_add_entities(entities)


class GlkvmHostPowerSwitch(GlkvmEntity, SwitchEntity):
    """The attached host's power, through the ATX board.

    On means GL.iNet's ATX board reads the host as powered. Turning on presses
    the power button; turning off presses it once, which asks the OS to shut
    down (ACPI) rather than cutting power. The hard variants are the buttons
    and the `power` action. Unavailable while no ATX board is attached.
    """

    _attr_translation_key = "host_power"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "host_power", section=SECTION_ATX)

    @property
    def available(self) -> bool:
        return super().available and self.data.atx is not None and self.data.atx.enabled

    @property
    def is_on(self) -> bool | None:
        return self.data.atx.power_on if self.data.atx else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.atx_power("on"))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.atx_power("off"))


class GlkvmVirtualMediaSwitch(GlkvmEntity, SwitchEntity):
    """Whether the selected image is plugged into the host as a USB drive."""

    _attr_translation_key = "virtual_media"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "virtual_media", section=SECTION_MSD)

    @property
    def available(self) -> bool:
        return super().available and self.data.msd is not None and self.data.msd.online

    @property
    def is_on(self) -> bool | None:
        return self.data.msd.connected if self.data.msd else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        msd = self.data.msd
        if msd is None:
            return {}
        return {"image": msd.image, "cdrom": msd.cdrom, "read_write": msd.rw}

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.data.msd is None or self.data.msd.image is None:
            # kvmd would answer with an opaque error; say what is missing. The
            # user's request is what is wrong, so it is a validation error.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_image_selected"
            )
        await self._run(self.coordinator.client.msd_set_connected(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.msd_set_connected(False))


class GlkvmJigglerSwitch(GlkvmEntity, SwitchEntity):
    """kvmd's mouse jiggler: nudges the host's pointer so it never sleeps.

    On is `jiggler.active`, the running state; `jiggler.enabled` is the
    unit's configuration and only decides whether the switch is available.
    The first version read `enabled` and showed on while nothing jiggled -
    caught by turning it off on the real unit and watching nothing change.
    """

    _attr_translation_key = "mouse_jiggler"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        super().__init__(coordinator, "mouse_jiggler", section=SECTION_HID)

    @property
    def available(self) -> bool:
        hid = self.data.hid
        return (
            super().available
            and hid is not None
            and hid.enabled
            and hid.jiggler_enabled is not False
        )

    @property
    def is_on(self) -> bool | None:
        return self.data.hid.jiggler_active if self.data.hid else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.hid_set_jiggler(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.hid_set_jiggler(False))


class GlkvmGpioSwitch(GlkvmEntity, SwitchEntity):
    """A user-GPIO output configured as a switch: a relay, a smart plug."""

    _attr_translation_key = "gpio_output"

    def __init__(self, coordinator: GlkvmCoordinator, channel: GpioChannel) -> None:
        super().__init__(
            coordinator, f"gpio_out_{channel.channel}", section=SECTION_GPIO
        )
        self._channel = channel.channel
        self._attr_translation_placeholders = {"channel": channel.channel}

    def _current(self) -> GpioChannel | None:
        if self.data.gpio is None:
            return None
        return next(
            (ch for ch in self.data.gpio.outputs if ch.channel == self._channel), None
        )

    @property
    def available(self) -> bool:
        current = self._current()
        return super().available and current is not None and current.online is not False

    @property
    def is_on(self) -> bool | None:
        current = self._current()
        return current.state if current else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.gpio_switch(self._channel, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.client.gpio_switch(self._channel, False))
