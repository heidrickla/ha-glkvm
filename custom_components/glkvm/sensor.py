"""Sensors: the capture pipeline, the media store, and the KVM's own health."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity
from .models import Health, KvmData

# Read from values already in the coordinator; nothing to serialise.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GlkvmSensorDescription(SensorEntityDescription):
    """A sensor plus how to pull its value out of one poll.

    `exists_fn` decides whether the entity is created at all: the health
    section is absent on firmware 1.8.1, and creating six sensors that can
    only ever read unknown is worse than creating none. It is asked again on
    every refresh, so a section that was merely unreadable on the first poll
    still gets its sensors when it answers.
    """

    value_fn: Callable[[KvmData], StateType]
    available_fn: Callable[[KvmData], bool] = lambda _data: True
    exists_fn: Callable[[KvmData], bool] = lambda _data: True


def _health(fn: Callable[[Health], StateType]) -> Callable[[KvmData], StateType]:
    return lambda d: fn(d.health) if d.health is not None else None


def _has_health(data: KvmData) -> bool:
    return data.health is not None


def _streamer_running(data: KvmData) -> bool:
    return data.streamer is not None and data.streamer.running


SENSORS: tuple[GlkvmSensorDescription, ...] = (
    # --- the capture pipeline
    GlkvmSensorDescription(
        key="capture_resolution",
        translation_key="capture_resolution",
        value_fn=lambda d: d.streamer.resolution if d.streamer else None,
        available_fn=_streamer_running,
    ),
    GlkvmSensorDescription(
        key="capture_fps",
        translation_key="capture_fps",
        native_unit_of_measurement="fps",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.streamer.captured_fps if d.streamer else None,
        available_fn=_streamer_running,
    ),
    GlkvmSensorDescription(
        key="stream_clients",
        translation_key="stream_clients",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.streamer.clients if d.streamer else None,
        available_fn=_streamer_running,
    ),
    GlkvmSensorDescription(
        key="h264_bitrate",
        translation_key="h264_bitrate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BITS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=lambda d: d.streamer.h264_bitrate_bps if d.streamer else None,
        available_fn=_streamer_running,
    ),
    # --- the media store
    GlkvmSensorDescription(
        key="media_storage_free",
        translation_key="media_storage_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: d.msd.storage_free if d.msd else None,
        available_fn=lambda d: d.msd is not None and d.msd.online,
    ),
    # --- the KVM's own health (firmware 1.10.0 and later)
    GlkvmSensorDescription(
        key="cpu_temperature",
        translation_key="cpu_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=_health(lambda h: h.cpu_temp),
        exists_fn=_has_health,
    ),
    GlkvmSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=_health(lambda h: h.cpu_percent),
        exists_fn=_has_health,
    ),
    GlkvmSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=_health(lambda h: h.mem_percent),
        exists_fn=_has_health,
    ),
    # Disabled by default from here down: useful when chasing a problem on
    # the unit, noise on a dashboard the rest of the time.
    GlkvmSensorDescription(
        key="memory_available",
        translation_key="memory_available",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=_health(lambda h: h.mem_available),
        exists_fn=_has_health,
    ),
    GlkvmSensorDescription(
        key="network_rx_rate",
        translation_key="network_rx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=_health(lambda h: h.rx_rate),
        exists_fn=_has_health,
    ),
    GlkvmSensorDescription(
        key="network_tx_rate",
        translation_key="network_tx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=1,
        value_fn=_health(lambda h: h.tx_rate),
        exists_fn=_has_health,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_existing() -> None:
        new = [
            description
            for description in SENSORS
            if description.key not in added and description.exists_fn(coordinator.data)
        ]
        if new:
            async_add_entities(GlkvmSensor(coordinator, d) for d in new)
            added.update(d.key for d in new)

    _add_existing()
    entry.async_on_unload(coordinator.async_add_listener(_add_existing))


class GlkvmSensor(GlkvmEntity, SensorEntity):
    """One value read from the poll."""

    entity_description: GlkvmSensorDescription

    def __init__(
        self,
        coordinator: GlkvmCoordinator,
        description: GlkvmSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.data)

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.data)
