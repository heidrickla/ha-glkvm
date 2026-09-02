"""Fixtures for the Home Assistant layer tests.

These run against Home Assistant, on Linux, in CI - not on a Windows
workstation, where the harness blocks sockets and the ProactorEventLoop needs a
local socket pair for its own self-pipe. They skip when the harness is absent,
so the pure suite one level up still runs on a bare checkout.

THIS CONFTEST LIVES IN ITS OWN DIRECTORY ON PURPOSE. Its autouse fixture pulls
in Home Assistant machinery, and a conftest applies to everything at or below
its directory; in tests/ it would attach to the pure tests and error them all.

The client is replaced by FakeClient, which answers from the same recorded
bodies the pure tests use, parsed by the real models. Commands are recorded
rather than sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glkvm.const import DOMAIN
from custom_components.glkvm.models import (
    AtxState,
    FirmwareInfo,
    GpioState,
    Health,
    HidState,
    MsdState,
    StreamerState,
    SystemInfo,
    WolTarget,
)
from tests.pure import result

SERIAL = "0123456789ABCDEF"
HOST = "192.0.2.15"
WOL_MAC = "02:00:00:00:00:01"

ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_PORT: 443,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_VERIFY_SSL: False,
}


@dataclass
class FakeClient:
    """Stands in for GlkvmClient. State comes from the recorded bodies."""

    host: str = HOST
    base_url: str = f"https://{HOST}"
    system: SystemInfo = field(
        default_factory=lambda: SystemInfo.from_info(result("info.json"))
    )
    firmware: FirmwareInfo | None = field(
        default_factory=lambda: FirmwareInfo.from_result(result("upgrade_version.json"))
    )
    hostname: str | None = "GL-RM10-Example"
    health: Health | None = field(
        default_factory=lambda: Health.from_info(result("info.json"))
    )
    atx: AtxState = field(
        default_factory=lambda: AtxState.from_result(result("atx.json"))
    )
    msd: MsdState = field(
        default_factory=lambda: MsdState.from_result(result("msd_with_image.json"))
    )
    streamer: StreamerState = field(
        default_factory=lambda: StreamerState.from_result(result("streamer.json"))
    )
    hid: HidState = field(
        default_factory=lambda: HidState.from_result(result("hid.json"))
    )
    gpio: GpioState = field(
        default_factory=lambda: GpioState.from_result(result("gpio_rich.json"))
    )
    wol: tuple[WolTarget, ...] = field(
        default_factory=lambda: WolTarget.list_from_result(result("wol_list.json"))
    )
    snapshot: bytes | None = b"\xff\xd8\xff\xe0jpeg"
    # When set, every call raises it - the way a whole unit fails.
    fail: Exception | None = None
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self._check()
        self.calls.append((name, args, kwargs))

    def names(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]

    # reads
    async def check_auth(self) -> None:
        self._check()

    async def get_system(self) -> SystemInfo:
        self._check()
        return self.system

    async def get_firmware(self) -> FirmwareInfo | None:
        self._check()
        return self.firmware

    async def get_hostname(self) -> str | None:
        self._check()
        return self.hostname

    async def get_health(self) -> Health | None:
        self._check()
        return self.health

    async def get_atx(self) -> AtxState:
        self._check()
        return self.atx

    async def get_msd(self) -> MsdState:
        self._check()
        return self.msd

    async def get_streamer(self) -> StreamerState:
        self._check()
        return self.streamer

    async def get_hid(self) -> HidState:
        self._check()
        return self.hid

    async def get_gpio(self) -> GpioState:
        self._check()
        return self.gpio

    async def get_wol_targets(self) -> tuple[WolTarget, ...]:
        self._check()
        return self.wol

    async def get_snapshot(self) -> bytes | None:
        self._check()
        return self.snapshot

    # commands
    async def atx_power(self, action: str, *, wait: bool = True) -> None:
        self._record("atx_power", action, wait=wait)

    async def atx_click(self, button: str, *, wait: bool = True) -> None:
        self._record("atx_click", button, wait=wait)

    async def msd_set_connected(self, connected: bool) -> None:
        self._record("msd_set_connected", connected)

    async def msd_select_image(self, name: str, *, cdrom: bool = True) -> None:
        self._record("msd_select_image", name, cdrom=cdrom)

    async def hid_type_text(self, text: str, *, slow: bool = False) -> None:
        self._record("hid_type_text", text, slow=slow)

    async def hid_send_shortcut(self, keys) -> None:
        self._record("hid_send_shortcut", list(keys))

    async def hid_set_jiggler(self, enabled: bool) -> None:
        self._record("hid_set_jiggler", enabled)

    async def hid_set_mouse_output(self, output: str) -> None:
        self._record("hid_set_mouse_output", output)

    async def hid_reset(self) -> None:
        self._record("hid_reset")

    async def gpio_switch(
        self, channel: str, state: bool, *, wait: bool = True
    ) -> None:
        self._record("gpio_switch", channel, state, wait=wait)

    async def gpio_pulse(self, channel: str, *, wait: bool = True) -> None:
        self._record("gpio_pulse", channel, wait=wait)

    async def wol_wake(self, mac: str) -> None:
        self._record("wol_wake", mac)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Required for Home Assistant to load a custom component in tests."""
    return


@pytest.fixture
def fake_client(monkeypatch) -> FakeClient:
    """Replace the real client wherever it is constructed."""
    fake = FakeClient()
    monkeypatch.setattr("custom_components.glkvm.GlkvmClient", lambda *a, **k: fake)
    monkeypatch.setattr(
        "custom_components.glkvm.config_flow.GlkvmClient", lambda *a, **k: fake
    )
    return fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    # Titled "KVM" so entity ids read kvm_<name>.
    return MockConfigEntry(
        domain=DOMAIN, title="KVM", unique_id=SERIAL, data=dict(ENTRY_DATA)
    )


async def setup_entry(hass, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
