"""Binary sensors: video signal, the HID gadget, GPIO inputs, and port video."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SECTION_GPIO, SECTION_HID, SECTION_STREAMER, SECTION_SWITCH
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity, add_switch_entities
from .models import GpioChannel, KvmData

# Read from values already in the coordinator; nothing to serialise.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GlkvmBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor plus how to read it out of one poll.

    `section` is the poll section it reads; a poll in which that section
    failed makes the sensor unavailable rather than stale.
    """

    value_fn: Callable[[KvmData], bool | None]
    available_fn: Callable[[KvmData], bool] = lambda _data: True
    section: str | None = None


SENSORS: tuple[GlkvmBinarySensorDescription, ...] = (
    # GL.iNet's hdmi.signal is the honest "the host is putting out video";
    # kvmd's own source.online is stale across a re-plug.
    GlkvmBinarySensorDescription(
        key="video_signal",
        translation_key="video_signal",
        section=SECTION_STREAMER,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: d.streamer.signal if d.streamer else None,
        available_fn=lambda d: d.streamer is not None and d.streamer.running,
    ),
    GlkvmBinarySensorDescription(
        key="keyboard_online",
        translation_key="keyboard_online",
        section=SECTION_HID,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.hid.keyboard_online if d.hid else None,
        available_fn=lambda d: d.hid is not None and d.hid.enabled,
    ),
    GlkvmBinarySensorDescription(
        key="mouse_online",
        translation_key="mouse_online",
        section=SECTION_HID,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.hid.mouse_online if d.hid else None,
        available_fn=lambda d: d.hid is not None and d.hid.enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        GlkvmBinarySensor(coordinator, description) for description in SENSORS
    ]
    # GPIO channels come from the unit's own configuration and only change
    # with a kvmd restart, so the set present at setup is the set.
    if coordinator.data.gpio is not None:
        entities.extend(
            GlkvmGpioInput(coordinator, channel)
            for channel in coordinator.data.gpio.inputs
        )
    async_add_entities(entities)
    add_switch_entities(
        entry,
        async_add_entities,
        lambda switch: [
            GlkvmPortVideoSensor(coordinator, index)
            for index in range(switch.port_count)
        ],
    )


class GlkvmBinarySensor(GlkvmEntity, BinarySensorEntity):
    """One boolean read from the poll."""

    entity_description: GlkvmBinarySensorDescription

    def __init__(
        self,
        coordinator: GlkvmCoordinator,
        description: GlkvmBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key, section=description.section)
        self.entity_description = description

    @property
    @override
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.data)

    @property
    @override
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.data)


class GlkvmGpioInput(GlkvmEntity, BinarySensorEntity):
    """A user-GPIO input channel, named by the channel the unit's config gave it."""

    _attr_translation_key = "gpio_input"

    def __init__(self, coordinator: GlkvmCoordinator, channel: GpioChannel) -> None:
        super().__init__(
            coordinator, f"gpio_in_{channel.channel}", section=SECTION_GPIO
        )
        self._channel = channel.channel
        self._attr_translation_placeholders = {"channel": channel.channel}

    def _current(self) -> GpioChannel | None:
        if self.data.gpio is None:
            return None
        return next(
            (ch for ch in self.data.gpio.inputs if ch.channel == self._channel), None
        )

    @property
    @override
    def available(self) -> bool:
        current = self._current()
        return super().available and current is not None and current.online is not False

    @property
    @override
    def is_on(self) -> bool | None:
        current = self._current()
        return current.state if current else None


class GlkvmPortVideoSensor(GlkvmEntity, BinarySensorEntity):
    """Whether a source is plugged in and powered on one GL-RM4PE port's HDMI.

    Named and keyed by the port number printed on the unit (1 to 4), never by
    the port's name, which the user can change at any time.
    """

    _attr_translation_key = "port_video"
    _attr_device_class = BinarySensorDeviceClass.PLUG

    def __init__(self, coordinator: GlkvmCoordinator, index: int) -> None:
        super().__init__(coordinator, f"port_{index + 1}_video", section=SECTION_SWITCH)
        self._index = index
        self._attr_translation_placeholders = {"port": str(index + 1)}

    @property
    @override
    def available(self) -> bool:
        switch = self.data.switch
        return (
            super().available
            and switch is not None
            and switch.video_link(self._index) is not None
        )

    @property
    @override
    def is_on(self) -> bool | None:
        switch = self.data.switch
        return switch.video_link(self._index) if switch else None
