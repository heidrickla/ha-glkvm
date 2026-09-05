"""The host's screen, as a still-image camera.

kvmd serves the current capture frame as a JPEG at /api/streamer/snapshot.
There is no MJPEG or RTSP stream to hand to Home Assistant - GL.iNet's live
path is WebRTC and the raw H.264 elementary stream is not something the
camera platform can play - so this is a snapshot camera: the frontend polls
it and `camera.snapshot` saves a frame.

It only has a picture while kvmd's streamer is running. On GL.iNet firmware
the streamer starts on demand from their own web UI, so a stock unit answers
503 most of the time; `kvmd.streamer.forever: true` in the unit's
override.yaml keeps it running, and a repair issue says so when it is not.
"""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import GlkvmError
from .const import MANUFACTURER, SECTION_STREAMER
from .coordinator import GlkvmConfigEntry, GlkvmCoordinator
from .entity import GlkvmEntity

_LOGGER = logging.getLogger(__name__)

# Snapshot fetches are on demand, not coordinated updates.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GlkvmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GlkvmScreenCamera(entry.runtime_data)])


class GlkvmScreenCamera(GlkvmEntity, Camera):
    """What the attached host is showing right now."""

    _attr_translation_key = "screen"
    # The frontend's still-image "stream" refetches at this interval. Two
    # seconds keeps a card watchable without asking the unit's encoder for a
    # fresh JPEG twice a second, the default.
    _attr_frame_interval = 2.0

    def __init__(self, coordinator: GlkvmCoordinator) -> None:
        GlkvmEntity.__init__(self, coordinator, "screen", section=SECTION_STREAMER)
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        streamer = self.data.streamer
        return super().available and streamer is not None and streamer.running

    @property
    def brand(self) -> str:
        return MANUFACTURER

    @property
    def model(self) -> str | None:
        firmware = self.coordinator.firmware
        return firmware.model if firmware else None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        try:
            return await self.coordinator.client.get_snapshot()
        except GlkvmError as err:
            _LOGGER.debug("Snapshot failed: %s", err)
            return None
