"""Constants for the GL.iNet KVM integration."""

from datetime import timedelta

DOMAIN = "glkvm"
NAME = "GL.iNet KVM"
MANUFACTURER = "GL.iNet"

# Must match manifest.json; tools/validate_local.py refuses a mismatch.
VERSION = "0.2.0"

# The kvmd API is served over HTTPS with a self-signed certificate (CN
# "localhost", issued by "GLKVM"), so verification is off by default. A user
# who has installed their own certificate can turn it on.
DEFAULT_PORT = 443
DEFAULT_VERIFY_SSL = False

# What changes on a KVM changes at human speed - a host powering off, a video
# signal dropping, an image being attached. Thirty seconds notices all of that
# while leaving the unit's CPU to the video encoder that is its real job. The
# same state is available as a push stream over /api/ws; polling is the first
# implementation, not the last.
SCAN_INTERVAL = timedelta(seconds=30)

# The seven sections one poll reads, each from its own endpoint. A section
# that fails keeps its last value and its name goes in KvmData.failed, which
# is what makes the entities reading it unavailable rather than stale.
SECTION_ATX = "atx"
SECTION_MSD = "msd"
SECTION_STREAMER = "streamer"
SECTION_HID = "hid"
SECTION_GPIO = "gpio"
SECTION_HEALTH = "health"
SECTION_WOL = "wol"
SECTIONS = (
    SECTION_ATX,
    SECTION_MSD,
    SECTION_STREAMER,
    SECTION_HID,
    SECTION_GPIO,
    SECTION_HEALTH,
    SECTION_WOL,
)

# Zeroconf. The units announce _glinet._tcp.local. with TXT mn=<model>,
# v=<firmware>, devid and mac=<base64 of the twelve hex digits>. The manifest
# filters on mn, so only a Comet KVM reaches the flow; the MAC is the only key
# the announcement shares with the unit's own API.
ZEROCONF_MAC = "mac"

# Repair issues.
ISSUE_STREAMER_STOPPED = "streamer_stopped"
ISSUE_MSD_OFFLINE = "msd_offline"
# GL.iNet's own web UI stops kvmd's streamer for as long as a viewer sits in
# its "adaptive" WebRTC mode and brings it back on exit. Raising the issue on
# the first missing poll would make it flap every time someone opened the UI.
STREAMER_STOPPED_POLLS = 3

# Actions.
SERVICE_TYPE_TEXT = "type_text"
SERVICE_SEND_KEYS = "send_keys"
SERVICE_WAKE = "wake"
SERVICE_POWER = "power"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_TEXT = "text"
ATTR_SLOW = "slow"
ATTR_KEYS = "keys"
ATTR_MAC = "mac"
ATTR_ACTION = "action"
ATTR_WAIT = "wait"

# The four ATX power actions kvmd accepts, in the order its own UI lists them.
POWER_ACTIONS = ["on", "off", "off_hard", "reset_hard"]
