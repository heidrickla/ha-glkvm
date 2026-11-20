"""Typed shapes for what a GL.iNet KVM reports.

Free of Home Assistant imports so the parsing can be tested on a bare
interpreter against bodies recorded from a real unit, and so this module and
api.py can be lifted into a standalone library unchanged.

Every field is optional where the firmware could plausibly omit it. kvmd here
is GL.iNet's fork of PiKVM, keys have already appeared and vanished between
their releases (`health` exists on 1.10.0 and not on 1.8.1; `hw` is gone), and
a renamed key must degrade to None rather than take the whole poll down.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

# kvmd lists every file on the media partition. Windows leaves this directory
# behind on any exfat volume it has touched, and nothing in it is an image.
IGNORED_IMAGE_DIRS: tuple[str, ...] = ("System Volume Information",)


def _dig(data: Any, *path: str) -> Any:
    """Walk nested mappings; None as soon as anything is missing or not a mapping."""
    cur = data
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class SystemInfo:
    """The static facts from /api/info: what the unit is."""

    serial: str | None = None
    kvmd_version: str | None = None
    kernel_release: str | None = None
    platform_base: str | None = None
    hostname: str | None = None
    streamer_app: str | None = None
    streamer_version: str | None = None

    @classmethod
    def from_info(cls, result: Mapping[str, Any]) -> SystemInfo:
        system = _dig(result, "system")
        return cls(
            serial=_as_str(_dig(system, "platform", "serial")),
            kvmd_version=_as_str(_dig(system, "kvmd", "version")),
            kernel_release=_as_str(_dig(system, "kernel", "release")),
            platform_base=_as_str(_dig(system, "platform", "base")),
            hostname=_as_str(_dig(result, "meta", "server", "host")),
            streamer_app=_as_str(_dig(system, "streamer", "app")),
            streamer_version=_as_str(_dig(system, "streamer", "version")),
        )


@dataclass(frozen=True)
class FirmwareInfo:
    """GL.iNet's /api/upgrade/version: the product model and firmware build."""

    model: str | None = None
    version: str | None = None

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> FirmwareInfo:
        return cls(
            model=_as_str(result.get("model")),
            version=_as_str(result.get("version")),
        )


@dataclass(frozen=True)
class NetworkConfig:
    """GL.iNet's /api/system/get_network_config: the unit's own LAN identity.

    The MAC matters because it is the only key the unit shares with its mDNS
    announcement. The serial an entry is keyed on is behind authentication
    and is not in the TXT records, so a discovered unit is recognised by MAC.
    """

    mac: str | None = None
    ip: str | None = None
    interface: str | None = None
    is_dhcp: bool | None = None

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> NetworkConfig:
        config = _dig(result, "config")
        mac = _as_str(_dig(config, "mac_address"))
        return cls(
            mac=mac.lower() if mac else None,
            ip=_as_str(_dig(config, "ip_address")),
            interface=_as_str(_dig(config, "interface")),
            is_dhcp=_as_bool(_dig(config, "is_dhcp")),
        )


@dataclass(frozen=True)
class Health:
    """The `health` info section: the KVM's own CPU, memory and network."""

    cpu_percent: float | None = None
    mem_percent: float | None = None
    mem_available: int | None = None
    mem_total: int | None = None
    cpu_temp: float | None = None
    rx_rate: int | None = None
    tx_rate: int | None = None
    bytes_recv: int | None = None
    bytes_sent: int | None = None

    @classmethod
    def from_info(cls, result: Mapping[str, Any]) -> Health | None:
        health = _dig(result, "health")
        if not isinstance(health, Mapping):
            return None
        return cls(
            cpu_percent=_as_float(_dig(health, "cpu", "percent")),
            mem_percent=_as_float(_dig(health, "mem", "percent")),
            mem_available=_as_int(_dig(health, "mem", "available")),
            mem_total=_as_int(_dig(health, "mem", "total")),
            cpu_temp=_as_float(_dig(health, "temp", "cpu")),
            rx_rate=_as_int(_dig(health, "net", "rx_rate")),
            tx_rate=_as_int(_dig(health, "net", "tx_rate")),
            bytes_recv=_as_int(_dig(health, "net", "bytes_recv")),
            bytes_sent=_as_int(_dig(health, "net", "bytes_sent")),
        )


@dataclass(frozen=True)
class AtxState:
    """ATX power control.

    GL.iNet's ATX plugin talks to a USB board on /dev/ttyACM0. `enabled` is
    true only while that board is present, and `power` is the board's own
    reading of the host ("on"/"off"). The upstream `leds` block is still
    emitted but is never populated by GL.iNet's plugin, so it is not modelled.
    """

    enabled: bool = False
    busy: bool = False
    power: str | None = None

    @property
    def power_on(self) -> bool | None:
        if self.power not in ("on", "off"):
            return None
        return self.power == "on"

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> AtxState:
        return cls(
            enabled=bool(_as_bool(result.get("enabled"))),
            busy=bool(_as_bool(result.get("busy"))),
            power=_as_str(result.get("power")),
        )


@dataclass(frozen=True)
class MsdImage:
    name: str
    size: int | None = None
    complete: bool = True


@dataclass(frozen=True)
class MsdState:
    """The virtual mass-storage drive and the image store behind it.

    `online` is false when the gadget's storage functions are not linked -
    the state a stock 1.10.0 unit boots into - and `drive` is null while the
    module is disabled, so both are tolerated.
    """

    enabled: bool = False
    online: bool = False
    busy: bool = False
    connected: bool | None = None
    image: str | None = None
    cdrom: bool | None = None
    rw: bool | None = None
    images: tuple[MsdImage, ...] = ()
    storage_free: int | None = None
    storage_size: int | None = None

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> MsdState:
        drive = _dig(result, "drive")
        image = _dig(drive, "image")
        image_name = (
            _as_str(image.get("name")) if isinstance(image, Mapping) else _as_str(image)
        )

        images: list[MsdImage] = []
        listed = _dig(result, "storage", "images")
        if isinstance(listed, Mapping):
            for name, meta in listed.items():
                if not isinstance(name, str) or not name:
                    continue
                if name.split("/", 1)[0] in IGNORED_IMAGE_DIRS:
                    continue
                complete = _as_bool(_dig(meta, "complete"))
                images.append(
                    MsdImage(
                        name=name,
                        size=_as_int(_dig(meta, "size")),
                        complete=True if complete is None else complete,
                    )
                )
        images.sort(key=lambda img: img.name.lower())

        parts = _dig(result, "storage", "parts")
        part: Any = None
        if isinstance(parts, Mapping) and parts:
            part = parts.get("") if "" in parts else next(iter(parts.values()))

        return cls(
            enabled=bool(_as_bool(result.get("enabled"))),
            online=bool(_as_bool(result.get("online"))),
            busy=bool(_as_bool(result.get("busy"))),
            connected=_as_bool(_dig(drive, "connected")),
            image=image_name,
            cdrom=_as_bool(_dig(drive, "cdrom")),
            rw=_as_bool(_dig(drive, "rw")),
            images=tuple(images),
            storage_free=_as_int(_dig(part, "free")),
            storage_size=_as_int(_dig(part, "size")),
        )


@dataclass(frozen=True)
class StreamerState:
    """kvmd's capture pipeline.

    `running` is false when `streamer` is null - on GL.iNet firmware that is
    the resting state unless `kvmd.streamer.forever` is set, because their UI
    starts the streamer on demand. `signal` is GL.iNet's `hdmi.signal`, which
    is the honest "the host is outputting video" bit; `source_online` goes
    stale across an HDMI re-plug and is kept only for completeness.
    """

    running: bool = False
    signal: bool | None = None
    source_online: bool | None = None
    width: int | None = None
    height: int | None = None
    captured_fps: int | None = None
    clients: int | None = None
    h264_bitrate_bps: int | None = None
    encoder: str | None = None
    quality: int | None = None
    desired_fps: int | None = None
    h264_bitrate_kbps: int | None = None

    @property
    def resolution(self) -> str | None:
        if not self.width or not self.height:
            return None
        return f"{self.width}x{self.height}"

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> StreamerState:
        streamer = _dig(result, "streamer")
        source = _dig(streamer, "source")
        params = _dig(result, "params")
        return cls(
            running=isinstance(streamer, Mapping),
            signal=_as_bool(_dig(streamer, "hdmi", "signal")),
            source_online=_as_bool(_dig(source, "online")),
            width=_as_int(_dig(source, "resolution", "width")),
            height=_as_int(_dig(source, "resolution", "height")),
            captured_fps=_as_int(_dig(source, "captured_fps")),
            clients=_as_int(_dig(streamer, "stream", "clients")),
            h264_bitrate_bps=_as_int(_dig(streamer, "h264", "bitrate")),
            encoder=_as_str(_dig(streamer, "encoder", "type")),
            quality=_as_int(_dig(params, "quality")),
            desired_fps=_as_int(_dig(params, "desired_fps")),
            h264_bitrate_kbps=_as_int(_dig(params, "h264_bitrate")),
        )


@dataclass(frozen=True)
class HidState:
    """The USB keyboard and mouse gadget.

    The `online` flags are lazy: kvmd only updates them on the next write, so
    a host that has stopped polling the gadget still reads online until
    something is typed.

    Jiggler: `jiggler_enabled` is the unit's configuration (may the jiggler be
    used at all), `jiggler_active` is whether it is running now. The API's
    set_params?jiggler= sets the button half of `active`; GL.iNet's schedule
    can OR it on as well. Measured on the unit 2026-09-02 after a switch that
    read `enabled` showed on while nothing jiggled.
    """

    enabled: bool = False
    online: bool = False
    connected: bool | None = None
    keyboard_online: bool | None = None
    mouse_online: bool | None = None
    caps_lock: bool | None = None
    num_lock: bool | None = None
    scroll_lock: bool | None = None
    jiggler_enabled: bool | None = None
    jiggler_active: bool | None = None
    mouse_output: str | None = None
    mouse_outputs: tuple[str, ...] = ()

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> HidState:
        available = _dig(result, "mouse", "outputs", "available")
        outputs = (
            tuple(item for item in available if isinstance(item, str) and item)
            if isinstance(available, list)
            else ()
        )
        return cls(
            enabled=bool(_as_bool(result.get("enabled"))),
            online=bool(_as_bool(result.get("online"))),
            connected=_as_bool(result.get("connected")),
            keyboard_online=_as_bool(_dig(result, "keyboard", "online")),
            mouse_online=_as_bool(_dig(result, "mouse", "online")),
            caps_lock=_as_bool(_dig(result, "keyboard", "leds", "caps")),
            num_lock=_as_bool(_dig(result, "keyboard", "leds", "num")),
            scroll_lock=_as_bool(_dig(result, "keyboard", "leds", "scroll")),
            jiggler_enabled=_as_bool(_dig(result, "jiggler", "enabled")),
            jiggler_active=_as_bool(_dig(result, "jiggler", "active")),
            mouse_output=_as_str(_dig(result, "mouse", "outputs", "active")),
            mouse_outputs=outputs,
        )


@dataclass(frozen=True)
class GpioChannel:
    """One user-GPIO channel: a relay, a smart plug, a KVM switch port."""

    channel: str
    is_input: bool
    switch: bool = False
    pulse_delay: float | None = None
    state: bool | None = None
    online: bool | None = None
    busy: bool | None = None


@dataclass(frozen=True)
class GpioState:
    inputs: tuple[GpioChannel, ...] = ()
    outputs: tuple[GpioChannel, ...] = ()

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> GpioState:
        scheme = _dig(result, "model", "scheme")
        state = _dig(result, "state")
        parsed: dict[str, list[GpioChannel]] = {"inputs": [], "outputs": []}
        for kind in ("inputs", "outputs"):
            defined = _dig(scheme, kind)
            if not isinstance(defined, Mapping):
                continue
            for channel, spec in defined.items():
                if not isinstance(channel, str) or not channel:
                    continue
                current = _dig(state, kind, channel)
                parsed[kind].append(
                    GpioChannel(
                        channel=channel,
                        is_input=kind == "inputs",
                        switch=bool(_as_bool(_dig(spec, "switch"))),
                        pulse_delay=_as_float(_dig(spec, "pulse", "delay")),
                        state=_as_bool(_dig(current, "state")),
                        online=_as_bool(_dig(current, "online")),
                        busy=_as_bool(_dig(current, "busy")),
                    )
                )
            parsed[kind].sort(key=lambda ch: ch.channel)
        return cls(inputs=tuple(parsed["inputs"]), outputs=tuple(parsed["outputs"]))


@dataclass(frozen=True)
class WolTarget:
    """One entry in GL.iNet's Wake-on-LAN list."""

    mac: str
    name: str
    ip: str | None = None

    @classmethod
    def list_from_result(cls, result: Mapping[str, Any]) -> tuple[WolTarget, ...]:
        devices = result.get("devices")
        if not isinstance(devices, list):
            return ()
        targets: list[WolTarget] = []
        for item in devices:
            mac = _as_str(_dig(item, "mac"))
            if mac is None:
                continue
            mac = mac.lower()
            targets.append(
                cls(
                    mac=mac,
                    name=_as_str(_dig(item, "name")) or mac,
                    ip=_as_str(_dig(item, "ip")),
                )
            )
        targets.sort(key=lambda t: (t.name.lower(), t.mac))
        return tuple(targets)


def _name(value: Any) -> str | None:
    """A user-given label, stripped; None for null, blank or not a string."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def port_names_from_config(result: Mapping[str, Any]) -> tuple[str | None, ...] | None:
    """`config.port_names` out of GL.iNet's /api/system/get_config answer.

    GL's web UI stores one entry per port, null for a port it has no name
    for. Everything else in that document is the UI's own settings and is
    not read. None when the key is missing or not a list.
    """
    names = _dig(result, "config", "port_names")
    if not isinstance(names, list):
        return None
    return tuple(_name(item) for item in names)


@dataclass(frozen=True)
class SwitchPort:
    """One input of the multi-port switch, as kvmd's switch model lists it."""

    index: int
    id: str | None = None
    name: str | None = None
    unit: int | None = None
    channel: int | None = None


@dataclass(frozen=True)
class SwitchState:
    """The built-in KVM switch of a GL-RM4PE (Comet X), from /api/switch.

    `active_port` is 0-based, as kvmd counts; the labels printed on the unit
    and everything user-facing in this integration count from 1. kvmd
    reports -1 when no port is selected, which is None here.

    Port names come from two places. GL.iNet's web UI keeps its own in the
    user config (`ui_names`, filled in by the coordinator from
    /api/system/get_config); kvmd's switch model carries a name per port too,
    which on the RM4PE does not survive a kvmd restart. `label()` prefers
    the UI's, then kvmd's, then "Port N".
    """

    active_port: int | None = None
    active_id: str | None = None
    synced: bool | None = None
    video_links: tuple[bool | None, ...] = ()
    usb_links: tuple[bool | None, ...] = ()
    ports: tuple[SwitchPort, ...] = ()
    ui_names: tuple[str | None, ...] = ()

    @property
    def port_count(self) -> int:
        return len(self.ports) if self.ports else len(self.video_links)

    def label(self, index: int) -> str:
        """The name to show for a 0-based port."""
        if 0 <= index < len(self.ui_names) and self.ui_names[index]:
            return str(self.ui_names[index])
        if 0 <= index < len(self.ports) and self.ports[index].name:
            return str(self.ports[index].name)
        return f"Port {index + 1}"

    @property
    def labels(self) -> tuple[str, ...]:
        """One distinct label per port, in port order.

        Names are typed by people, so two ports can share one, or one can
        read the same as another port's "Port N" fallback. A select needs
        distinct options, so a repeated label gets its port number appended.
        """
        bases = [self.label(i) for i in range(self.port_count)]
        seen: set[str] = set()
        labels: list[str] = []
        for index, base in enumerate(bases):
            candidate = base
            if bases.count(base) > 1:
                candidate = f"{base} ({index + 1})"
            while candidate in seen:
                candidate = f"{candidate} ({index + 1})"
            seen.add(candidate)
            labels.append(candidate)
        return tuple(labels)

    def video_link(self, index: int) -> bool | None:
        """Whether a source is putting out video on a 0-based port's HDMI."""
        if 0 <= index < len(self.video_links):
            return self.video_links[index]
        return None

    def with_ui_names(self, names: tuple[str | None, ...] | None) -> SwitchState:
        return replace(self, ui_names=tuple(names or ()))

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> SwitchState:
        active = _as_int(_dig(result, "summary", "active_port"))
        listed = _dig(result, "model", "ports")
        ports: list[SwitchPort] = []
        if isinstance(listed, list):
            for index, item in enumerate(listed):
                ports.append(
                    SwitchPort(
                        index=index,
                        id=_as_str(_dig(item, "id")),
                        name=_name(_dig(item, "name")),
                        unit=_as_int(_dig(item, "unit")),
                        channel=_as_int(_dig(item, "channel")),
                    )
                )
        return cls(
            active_port=active if active is not None and active >= 0 else None,
            active_id=_as_str(_dig(result, "summary", "active_id")),
            synced=_as_bool(_dig(result, "summary", "synced")),
            video_links=_links(_dig(result, "video", "links")),
            usb_links=_links(_dig(result, "usb_otg", "links")),
            ports=tuple(ports),
        )


def _links(value: Any) -> tuple[bool | None, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_as_bool(item) for item in value)


@dataclass
class KvmData:
    """One poll's worth of state.

    A section that failed to read keeps the value the last good poll left, so
    the entity set does not churn, and its name goes in `failed`. Entities
    reading a failed section report unavailable rather than that stale value.
    """

    atx: AtxState | None = None
    msd: MsdState | None = None
    streamer: StreamerState | None = None
    hid: HidState | None = None
    gpio: GpioState | None = None
    health: Health | None = None
    wol: tuple[WolTarget, ...] = field(default_factory=tuple)
    # None on every unit without the built-in switch, which is all but the
    # GL-RM4PE; that is absence, not a failure.
    switch: SwitchState | None = None
    failed: tuple[str, ...] = field(default_factory=tuple)
