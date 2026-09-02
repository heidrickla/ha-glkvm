"""Client for the kvmd HTTP API on a GL.iNet KVM.

GL.iNet's firmware is a fork of PiKVM's kvmd (4.82), so the API is PiKVM's:
`https://<host>/api/...`, every answer wrapped as `{"ok": bool, "result": ...}`
and errors as `{"ok": false, "result": {"error": "...", "error_msg": "..."}}`.
GL.iNet's own endpoints sit alongside (`/api/upgrade/version`, `/api/wol/*`,
`/api/system/*`). Everything here was measured against a GL-RM10 (Comet Pro)
on firmware 1.10.0; the places where the fork differs from upstream PiKVM are
noted where they matter.

No Home Assistant import and no dependency beyond aiohttp, so this module and
models.py can be tested on a bare interpreter and lifted into a standalone
library when the integration goes to core.

Authentication is stateless: kvmd accepts `X-KVMD-User` / `X-KVMD-Passwd` on
every request, so there is no session to expire and nothing to store. A unit
with authentication disabled ignores the headers. GL.iNet added a lockout
after repeated failed logins, which is one more reason a caller must stop
polling on the first 401 rather than retrying with the same credentials.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import aiohttp

from .models import (
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

# Reads are small JSON documents; commands may hold a button for seconds
# (`power_long` holds the ATX power line for about five) when asked to wait.
_TIMEOUT_STATE = aiohttp.ClientTimeout(total=15)
_TIMEOUT_COMMAND = aiohttp.ClientTimeout(total=40)
_TIMEOUT_SNAPSHOT = aiohttp.ClientTimeout(total=20)

POWER_ACTIONS: tuple[str, ...] = ("on", "off", "off_hard", "reset_hard")
ATX_BUTTONS: tuple[str, ...] = ("power", "power_long", "reset")


class GlkvmError(Exception):
    """Base error for anything the KVM conversation can raise."""


class GlkvmConnectionError(GlkvmError):
    """The unit could not be reached, or did not answer in time."""


class GlkvmAuthError(GlkvmError):
    """The unit refused the credentials (401) or the action (403)."""


class GlkvmResponseError(GlkvmError):
    """The unit answered, and the answer was an error."""

    def __init__(self, status: int, error: str, message: str) -> None:
        super().__init__(f"{error}: {message} (HTTP {status})")
        self.status = status
        self.error = error
        self.message = message


class GlkvmUnavailableError(GlkvmResponseError):
    """503: the resource exists but has nothing to give right now.

    kvmd answers this for a snapshot while its streamer is not running.
    """


def _flag(value: bool) -> str:
    # kvmd's valid_bool accepts 1/0, true/false, yes/no; 1/0 is the shortest.
    return "1" if value else "0"


class GlkvmClient:
    """Talks to one KVM on behalf of the integration."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        port: int = 443,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool = False,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._headers: dict[str, str] = {}
        if username:
            self._headers["X-KVMD-User"] = username
            self._headers["X-KVMD-Passwd"] = password or ""
        # aiohttp takes ssl=False to skip verification; True means the default
        # context. The unit's certificate is self-signed for "localhost", so
        # the default is off (see const.DEFAULT_VERIFY_SSL).
        self._ssl: bool = verify_ssl

    @property
    def host(self) -> str:
        return self._host

    @property
    def base_url(self) -> str:
        if self._port == 443:
            return f"https://{self._host}"
        return f"https://{self._host}:{self._port}"

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    # ------------------------------------------------------------ transport

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        data: bytes | None = None,
        timeout: aiohttp.ClientTimeout = _TIMEOUT_STATE,
    ) -> tuple[int, str, bytes]:
        """One HTTP exchange. Returns (status, content type, body)."""
        try:
            async with self._session.request(
                method,
                self._url(path),
                params=dict(params) if params else None,
                data=data,
                headers=self._headers,
                ssl=self._ssl,
                timeout=timeout,
            ) as resp:
                body = await resp.read()
                return resp.status, resp.headers.get("Content-Type", ""), body
        except aiohttp.ClientError as err:
            raise GlkvmConnectionError(f"{method} {path}: {err}") from err
        except TimeoutError as err:
            raise GlkvmConnectionError(f"{method} {path}: timed out") from err

    @staticmethod
    def _decode(status: int, body: bytes, path: str) -> Any:
        """Unwrap kvmd's envelope, turning every failure into an exception.

        Some of GL.iNet's own endpoints return HTTP 200 with `"ok": false` in
        the body, so the body is checked even on a 2xx.
        """
        payload: Any = None
        if body:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None

        error = "Error"
        message = f"HTTP {status}"
        if isinstance(payload, Mapping):
            result = payload.get("result")
            if isinstance(result, Mapping):
                error = str(result.get("error") or error)
                message = str(result.get("error_msg") or message)

        if status in (401, 403):
            raise GlkvmAuthError(f"{error}: {message}")
        if status == 503:
            raise GlkvmUnavailableError(status, error, message)
        if status >= 400:
            raise GlkvmResponseError(status, error, message)
        if not isinstance(payload, Mapping):
            raise GlkvmResponseError(status, "NotJson", f"{path} did not return JSON")
        if payload.get("ok") is False:
            raise GlkvmResponseError(status, error, message)
        return payload.get("result")

    async def _get(self, path: str, **params: str) -> Any:
        status, _ctype, body = await self._call("GET", path, params=params or None)
        return self._decode(status, body, path)

    async def _post(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        data: bytes | None = None,
    ) -> Any:
        status, _ctype, body = await self._call(
            "POST", path, params=params, data=data, timeout=_TIMEOUT_COMMAND
        )
        return self._decode(status, body, path)

    @staticmethod
    def _mapping(result: Any) -> Mapping[str, Any]:
        return result if isinstance(result, Mapping) else {}

    # ---------------------------------------------------------------- reads

    async def check_auth(self) -> None:
        """Raise GlkvmAuthError unless the credentials are accepted.

        On a unit with authentication disabled this succeeds with anything,
        which is the correct answer: whatever was entered will work.
        """
        await self._get("/api/auth/check")

    async def get_system(self) -> SystemInfo:
        """Serial, versions and hostname. `fields` keeps it cheap."""
        result = await self._get("/api/info", fields="system,meta")
        return SystemInfo.from_info(self._mapping(result))

    async def get_firmware(self) -> FirmwareInfo | None:
        """GL.iNet's model and firmware build; None where the endpoint is absent."""
        try:
            result = await self._get("/api/upgrade/version")
        except GlkvmResponseError as err:
            if err.status == 404:
                return None
            raise
        return FirmwareInfo.from_result(self._mapping(result))

    async def get_hostname(self) -> str | None:
        """GL.iNet's hostname (kvmd's own `meta` reports localhost.localdomain)."""
        try:
            result = await self._get("/api/system/get_hostname")
        except GlkvmResponseError as err:
            if err.status == 404:
                return None
            raise
        hostname = self._mapping(result).get("hostname")
        return hostname if isinstance(hostname, str) and hostname else None

    async def get_health(self) -> Health | None:
        """CPU, memory, temperature and network of the KVM itself.

        Firmware 1.8.1 has no `health` submanager and answers the fields
        request with a 400 ValidatorError; that is "not available", not a
        fault.
        """
        try:
            result = await self._get("/api/info", fields="health")
        except GlkvmResponseError as err:
            if err.status == 400:
                return None
            raise
        return Health.from_info(self._mapping(result))

    async def get_atx(self) -> AtxState:
        return AtxState.from_result(self._mapping(await self._get("/api/atx")))

    async def get_msd(self) -> MsdState:
        return MsdState.from_result(self._mapping(await self._get("/api/msd")))

    async def get_streamer(self) -> StreamerState:
        return StreamerState.from_result(
            self._mapping(await self._get("/api/streamer"))
        )

    async def get_hid(self) -> HidState:
        return HidState.from_result(self._mapping(await self._get("/api/hid")))

    async def get_gpio(self) -> GpioState:
        return GpioState.from_result(self._mapping(await self._get("/api/gpio")))

    async def get_wol_targets(self) -> tuple[WolTarget, ...]:
        """GL.iNet's stored Wake-on-LAN targets; empty where the API is absent."""
        try:
            result = await self._get("/api/wol/list")
        except GlkvmResponseError as err:
            if err.status == 404:
                return ()
            raise
        return WolTarget.list_from_result(self._mapping(result))

    async def get_snapshot(self) -> bytes | None:
        """The current frame as JPEG, or None while the streamer has no frame."""
        status, ctype, body = await self._call(
            "GET", "/api/streamer/snapshot", timeout=_TIMEOUT_SNAPSHOT
        )
        if status == 200 and ctype.startswith("image/"):
            return body
        try:
            self._decode(status, body, "/api/streamer/snapshot")
        except GlkvmUnavailableError:
            return None
        raise GlkvmResponseError(
            status, "NotAnImage", "the snapshot endpoint did not return an image"
        )

    # ------------------------------------------------------------- commands

    async def atx_power(self, action: str, *, wait: bool = True) -> None:
        """on / off / off_hard / reset_hard, as kvmd defines them.

        `on` and `off` are the graceful pair (a short press of the power
        button); `off_hard` holds it; `reset_hard` pulses reset.
        """
        if action not in POWER_ACTIONS:
            raise ValueError(f"unknown ATX power action {action!r}")
        await self._post(
            "/api/atx/power", params={"action": action, "wait": _flag(wait)}
        )

    async def atx_click(self, button: str, *, wait: bool = True) -> None:
        """Press a front-panel button: power, power_long or reset."""
        if button not in ATX_BUTTONS:
            raise ValueError(f"unknown ATX button {button!r}")
        await self._post(
            "/api/atx/click", params={"button": button, "wait": _flag(wait)}
        )

    async def msd_set_connected(self, connected: bool) -> None:
        """Attach or detach the selected image to the host's USB."""
        await self._post(
            "/api/msd/set_connected", params={"connected": _flag(connected)}
        )

    async def msd_select_image(self, name: str, *, cdrom: bool = True) -> None:
        """Choose which stored image the drive presents (while detached)."""
        await self._post(
            "/api/msd/set_params", params={"image": name, "cdrom": _flag(cdrom)}
        )

    async def hid_type_text(self, text: str, *, slow: bool = False) -> None:
        """Type text into the host over the USB keyboard.

        kvmd takes the text as the request BODY. A `?text=` query parameter
        returns 200 and types nothing. `limit=0` lifts the 1024-character cap.
        """
        await self._post(
            "/api/hid/print",
            params={"limit": "0", "slow": _flag(slow)},
            data=text.encode("utf-8"),
        )

    async def hid_send_shortcut(self, keys: Iterable[str]) -> None:
        """Press the keys together and release them in reverse order.

        Key names are the web ones kvmd uses: KeyA, Digit1, Enter, MetaLeft,
        ControlLeft, AltLeft, ShiftLeft, F5, Escape, Delete.
        """
        joined = ",".join(k.strip() for k in keys if k.strip())
        if not joined:
            raise ValueError("no keys to send")
        await self._post("/api/hid/events/send_shortcut", params={"keys": joined})

    async def hid_set_jiggler(self, enabled: bool) -> None:
        await self._post("/api/hid/set_params", params={"jiggler": _flag(enabled)})

    async def hid_set_mouse_output(self, output: str) -> None:
        await self._post("/api/hid/set_params", params={"mouse_output": output})

    async def hid_reset(self) -> None:
        await self._post("/api/hid/reset")

    async def gpio_switch(
        self, channel: str, state: bool, *, wait: bool = True
    ) -> None:
        await self._post(
            "/api/gpio/switch",
            params={"channel": channel, "state": _flag(state), "wait": _flag(wait)},
        )

    async def gpio_pulse(self, channel: str, *, wait: bool = True) -> None:
        await self._post(
            "/api/gpio/pulse", params={"channel": channel, "wait": _flag(wait)}
        )

    async def wol_wake(self, mac: str) -> None:
        """Send a magic packet from the KVM to a machine on its LAN."""
        await self._post("/api/wol/wake", params={"mac": mac})
