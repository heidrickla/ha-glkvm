"""Constants for the GL.iNet KVM integration."""

from datetime import timedelta

DOMAIN = "glkvm"
NAME = "GL.iNet KVM"
MANUFACTURER = "GL.iNet"

# Must match manifest.json; tools/validate_local.py refuses a mismatch.
VERSION = "0.3.0"

# The kvmd API is served over HTTPS with a self-signed certificate (CN
# "localhost", issued by "GLKVM"), so verification is off by default. A user
# who has installed their own certificate can turn it on.
DEFAULT_PORT = 443
DEFAULT_VERIFY_SSL = False

# Stock firmware's kvmd has one user, admin, the login its web interface
# checks too. A unit with authentication disabled accepts any login.
DEFAULT_USERNAME = "admin"

# The setup forms' collapsed section holding what has a working default.
CONF_ADVANCED = "advanced"

# Entry data, optional: the base32 TOTP secret of a unit with two-factor
# authentication on, as its 2FA setup screen shows it. The client appends the
# current code to the password on every request. Never logged; redacted from
# diagnostics.
CONF_TOTP_SECRET = "totp_secret"

# Entry data: SHA-256 of the certificate the unit presented at its last setup.
# A discovered address is trusted with the entry's credentials only over a
# connection presenting this certificate.
CONF_CERT_SHA256 = "cert_sha256"

# What changes on a KVM changes at human speed - a host powering off, a video
# signal dropping, an image being attached. Thirty seconds notices all of that
# while leaving the unit's CPU to the video encoder. The same state is
# available as a push stream over /api/ws.
SCAN_INTERVAL = timedelta(seconds=30)

# The eight sections one poll reads, each from its own endpoint. A section
# that fails keeps its last value and its name goes in KvmData.failed, which
# is what makes the entities reading it unavailable rather than stale.
# SECTION_SWITCH is the GL-RM4PE's built-in port switch; every other unit
# answers its endpoint with 404, which is absence, not a failure.
SECTION_ATX = "atx"
SECTION_MSD = "msd"
SECTION_STREAMER = "streamer"
SECTION_HID = "hid"
SECTION_GPIO = "gpio"
SECTION_HEALTH = "health"
SECTION_WOL = "wol"
SECTION_SWITCH = "switch"
SECTIONS = (
    SECTION_ATX,
    SECTION_MSD,
    SECTION_STREAMER,
    SECTION_HID,
    SECTION_GPIO,
    SECTION_HEALTH,
    SECTION_WOL,
    SECTION_SWITCH,
)

# Zeroconf. The units announce _glinet._tcp.local. with TXT mn=<model>,
# v=<firmware>, devid and mac=<base64 of the twelve hex digits>. The manifest
# filters on mn (rm10 for the Comet Pro, rm4pe for the Comet X), so only a
# Comet KVM reaches the flow; the MAC is the only key the announcement shares
# with the unit's own API.
ZEROCONF_MAC = "mac"

# Repair issues.
ISSUE_STREAMER_STOPPED = "streamer_stopped"
ISSUE_MSD_OFFLINE = "msd_offline"
# GL.iNet's own web UI stops kvmd's streamer for as long as a viewer sits in
# its "adaptive" WebRTC mode and brings it back on exit. Raising the issue on
# the first missing poll would make it flap every time someone opened the UI.
STREAMER_STOPPED_POLLS = 3

# Per-port power on a GL-RM4PE. Each port has its own rear USB-A socket for an
# ATX board, and switching ports powers only the new port's socket, so after a
# switch the board there has to enumerate before kvmd reports ATX enabled.
# How long to wait for that, and how often to ask.
ATX_PORT_TIMEOUT = 15.0
ATX_PORT_POLL_INTERVAL = 0.5

# Actions.
SERVICE_TYPE_TEXT = "type_text"
SERVICE_SEND_KEYS = "send_keys"
SERVICE_WAKE = "wake"
SERVICE_POWER = "power"
SERVICE_SET_ACTIVE_PORT = "set_active_port"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_TEXT = "text"
ATTR_SLOW = "slow"
ATTR_KEYS = "keys"
ATTR_MAC = "mac"
ATTR_ACTION = "action"
ATTR_WAIT = "wait"
ATTR_PORT = "port"

# The four ATX power actions kvmd accepts, in the order its own UI lists them.
POWER_ACTIONS = ["on", "off", "off_hard", "reset_hard"]
