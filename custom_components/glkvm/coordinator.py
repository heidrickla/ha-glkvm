"""Polling coordinator: one round of state reads every SCAN_INTERVAL."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GlkvmAuthError,
    GlkvmClient,
    GlkvmConnectionError,
    GlkvmError,
)
from .const import (
    DOMAIN,
    ISSUE_MSD_OFFLINE,
    ISSUE_STREAMER_STOPPED,
    MANUFACTURER,
    SCAN_INTERVAL,
    SECTION_ATX,
    SECTION_GPIO,
    SECTION_HEALTH,
    SECTION_HID,
    SECTION_MSD,
    SECTION_STREAMER,
    SECTION_WOL,
    SECTIONS,
    STREAMER_STOPPED_POLLS,
)
from .models import FirmwareInfo, KvmData, SystemInfo

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

type GlkvmConfigEntry = ConfigEntry[GlkvmCoordinator]


class GlkvmCoordinator(DataUpdateCoordinator[KvmData]):
    """Reads the KVM's state and owns the client.

    Each section (ATX, MSD, streamer, HID, GPIO, health, WOL) is read on its
    own rather than through the bare /api/info, which GL.iNet's firmware
    makes expensive, and each is allowed to fail on its own: a 500 from one
    endpoint leaves the rest live and names that section in KvmData.failed,
    which is what makes its entities unavailable instead of stale. Only the
    unit being unreachable for every read fails the poll, and only a 401
    stops polling - GL.iNet locks the account after repeated failures.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GlkvmConfigEntry,
        client: GlkvmClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.system: SystemInfo | None = None
        self.firmware: FirmwareInfo | None = None
        self._streamer_stopped_polls = 0
        self._entry = entry

    @property
    def unique_id(self) -> str:
        """The stable key for the device and its entities: the unit's serial."""
        return str(self._entry.unique_id or self._entry.entry_id)

    @property
    def device_info(self) -> DeviceInfo:
        system = self.system or SystemInfo()
        firmware = self.firmware or FirmwareInfo()
        sw_version = firmware.version
        if sw_version is None and system.kvmd_version:
            sw_version = f"kvmd {system.kvmd_version}"
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer=MANUFACTURER,
            name=self._entry.title,
            model=firmware.model or system.platform_base,
            sw_version=sw_version,
            serial_number=system.serial,
            configuration_url=self.client.base_url,
        )

    async def _async_setup(self) -> None:
        """One-time identity reads, so device_info is complete from first load."""
        try:
            self.system = await self.client.get_system()
            self.firmware = await self.client.get_firmware()
        except GlkvmAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except GlkvmConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        except GlkvmError as err:
            # Identity is decoration on the device page; a unit that answers
            # its state reads but not /api/info still works.
            _LOGGER.debug("Could not read identity: %s", err)
        await self._async_refresh_mac()

    async def _async_refresh_mac(self) -> None:
        """Keep the unit's own MAC in entry data, for zeroconf to match on.

        It can change under the user (a swapped unit at the same address, a
        firmware that reports a different interface), so it is read at every
        setup rather than only when the entry was created.
        """
        try:
            network = await self.client.get_network_config()
        except GlkvmError as err:
            # Only discovery uses it. A firmware without the endpoint, or one
            # that errors on it, must not stop a setup that has authenticated.
            _LOGGER.debug("Could not read the network configuration: %s", err)
            return
        mac = network.mac if network else None
        if mac and mac != self._entry.data.get(CONF_MAC):
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_MAC: mac}
            )

    async def _async_update_data(self) -> KvmData:
        previous = self.data or KvmData()
        auth_failures: list[str] = []
        connection_failures: list[str] = []
        failed: list[str] = []

        async def guard(name: str, call: Callable[[], Awaitable[_T]]) -> _T | None:
            try:
                return await call()
            except GlkvmAuthError as err:
                auth_failures.append(f"{name}: {err}")
            except GlkvmConnectionError as err:
                connection_failures.append(f"{name}: {err}")
                failed.append(name)
            except GlkvmError as err:
                failed.append(name)
                _LOGGER.debug("%s read failed, keeping the last value: %s", name, err)
            return None

        client = self.client
        # Six in the gather and one after: typeshed types gather for up to six
        # positional awaitables, and a seventh collapses the result to a union.
        atx, msd, streamer, hid, gpio, health = await asyncio.gather(
            guard(SECTION_ATX, client.get_atx),
            guard(SECTION_MSD, client.get_msd),
            guard(SECTION_STREAMER, client.get_streamer),
            guard(SECTION_HID, client.get_hid),
            guard(SECTION_GPIO, client.get_gpio),
            guard(SECTION_HEALTH, client.get_health),
        )
        wol = await guard(SECTION_WOL, client.get_wol_targets)

        if auth_failures:
            # Stop here rather than retry: the next poll with the same
            # credentials would count towards GL.iNet's login lockout.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": auth_failures[0]},
            )
        if len(connection_failures) == len(SECTIONS):
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unreachable",
                translation_placeholders={"error": connection_failures[0]},
            )
        if connection_failures:
            _LOGGER.debug("Partial poll: %s", "; ".join(connection_failures))

        data = KvmData(
            atx=atx if atx is not None else previous.atx,
            msd=msd if msd is not None else previous.msd,
            streamer=streamer if streamer is not None else previous.streamer,
            hid=hid if hid is not None else previous.hid,
            gpio=gpio if gpio is not None else previous.gpio,
            # A None here is also the legitimate "this firmware has no health
            # section", so it must not be back-filled from a previous poll.
            health=health,
            wol=wol if wol is not None else previous.wol,
            failed=tuple(failed),
        )
        self._update_issues(data)
        return data

    # --------------------------------------------------------------- issues

    def issue_id(self, key: str) -> str:
        return f"{key}_{self._entry.entry_id}"

    def _update_issues(self, data: KvmData) -> None:
        if data.streamer is not None:
            if data.streamer.running:
                self._streamer_stopped_polls = 0
                ir.async_delete_issue(
                    self.hass, DOMAIN, self.issue_id(ISSUE_STREAMER_STOPPED)
                )
            else:
                self._streamer_stopped_polls += 1
                if self._streamer_stopped_polls >= STREAMER_STOPPED_POLLS:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        self.issue_id(ISSUE_STREAMER_STOPPED),
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key=ISSUE_STREAMER_STOPPED,
                        translation_placeholders={"name": self._entry.title},
                    )

        if data.msd is not None:
            if data.msd.enabled and not data.msd.online:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    self.issue_id(ISSUE_MSD_OFFLINE),
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_MSD_OFFLINE,
                    translation_placeholders={"name": self._entry.title},
                )
            else:
                ir.async_delete_issue(
                    self.hass, DOMAIN, self.issue_id(ISSUE_MSD_OFFLINE)
                )

    def clear_issues(self) -> None:
        for key in (ISSUE_STREAMER_STOPPED, ISSUE_MSD_OFFLINE):
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id(key))
