"""Buttons: the ATX front panel, HID reset, GPIO pulses, and Wake-on-LAN."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import GlkvmClient
from .const import DOMAIN
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity
from .models import GpioChannel, KvmData, WolTarget

# See switch.py: one command at a time to the unit.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class GlkvmButtonDescription(ButtonEntityDescription):
    """A button plus the command it sends."""

    press_fn: Callable[[GlkvmClient], Awaitable[None]]
    available_fn: Callable[[KvmData], bool] = lambda _data: True


def _atx_present(data: KvmData) -> bool:
    return data.atx is not None and data.atx.enabled


def _hid_present(data: KvmData) -> bool:
    return data.hid is not None and data.hid.enabled


BUTTONS: tuple[GlkvmButtonDescription, ...] = (
    GlkvmButtonDescription(
        key="power_button",
        translation_key="power_button",
        press_fn=lambda c: c.atx_click("power"),
        available_fn=_atx_present,
    ),
    GlkvmButtonDescription(
        key="power_long",
        translation_key="power_long",
        press_fn=lambda c: c.atx_click("power_long"),
        available_fn=_atx_present,
    ),
    GlkvmButtonDescription(
        key="reset",
        translation_key="reset",
        device_class=ButtonDeviceClass.RESTART,
        press_fn=lambda c: c.atx_click("reset"),
        available_fn=_atx_present,
    ),
    GlkvmButtonDescription(
        key="hid_reset",
        translation_key="hid_reset",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c: c.hid_reset(),
        available_fn=_hid_present,
    ),
)


def _wake_key(mac: str) -> str:
    return f"wake_{mac.replace(':', '')}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [
        GlkvmButton(coordinator, description) for description in BUTTONS
    ]
    if coordinator.data.gpio is not None:
        entities.extend(
            GlkvmGpioPulseButton(coordinator, channel)
            for channel in coordinator.data.gpio.outputs
            if not channel.switch
        )
    async_add_entities(entities)

    # Wake-on-LAN targets are edited in the unit's web UI at any time, so
    # they are the one dynamic set: new targets appear as buttons on the next
    # poll and removed ones are taken out of the registry.
    registry = er.async_get(hass)
    known: set[str] = set()

    @callback
    def _sync_wol_targets() -> None:
        current = {t.mac: t for t in coordinator.data.wol} if coordinator.data else {}
        added = [current[mac] for mac in current if mac not in known]
        if added:
            async_add_entities(GlkvmWakeButton(coordinator, t) for t in added)
            known.update(t.mac for t in added)
        for mac in [mac for mac in known if mac not in current]:
            entity_id = registry.async_get_entity_id(
                Platform.BUTTON, DOMAIN, f"{coordinator.unique_id}_{_wake_key(mac)}"
            )
            if entity_id:
                registry.async_remove(entity_id)
            known.discard(mac)

    _sync_wol_targets()
    entry.async_on_unload(coordinator.async_add_listener(_sync_wol_targets))


class GlkvmButton(GlkvmEntity, ButtonEntity):
    """A fixed button sending one command."""

    entity_description: GlkvmButtonDescription

    def __init__(
        self, coordinator: GlkvmCoordinator, description: GlkvmButtonDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.data)

    async def async_press(self) -> None:
        await self._run(self.entity_description.press_fn(self.coordinator.client))


class GlkvmGpioPulseButton(GlkvmEntity, ButtonEntity):
    """A user-GPIO output configured as a pulse: a momentary relay."""

    _attr_translation_key = "gpio_pulse"

    def __init__(self, coordinator: GlkvmCoordinator, channel: GpioChannel) -> None:
        super().__init__(coordinator, f"gpio_out_{channel.channel}")
        self._channel = channel.channel
        self._attr_translation_placeholders = {"channel": channel.channel}

    @property
    def available(self) -> bool:
        if not super().available or self.data.gpio is None:
            return False
        current = next(
            (ch for ch in self.data.gpio.outputs if ch.channel == self._channel), None
        )
        return current is not None and current.online is not False

    async def async_press(self) -> None:
        await self._run(self.coordinator.client.gpio_pulse(self._channel))


class GlkvmWakeButton(GlkvmEntity, ButtonEntity):
    """Sends a Wake-on-LAN packet from the KVM to one stored target."""

    _attr_translation_key = "wake"

    def __init__(self, coordinator: GlkvmCoordinator, target: WolTarget) -> None:
        super().__init__(coordinator, _wake_key(target.mac))
        self._mac = target.mac
        self._attr_translation_placeholders = {"target": target.name}

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        target = next((t for t in self.data.wol if t.mac == self._mac), None)
        return {"mac": self._mac, "ip": target.ip if target else None}

    async def async_press(self) -> None:
        await self._run(self.coordinator.client.wol_wake(self._mac))
