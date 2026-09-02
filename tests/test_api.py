"""The client, against a scripted aiohttp stand-in.

Every answer is a body recorded from a real unit (or the exact error shape kvmd
produces), so what is asserted is how the client treats what the device
actually says.
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from tests.pure import fixture, load

api = load("api")


class _Resp:
    def __init__(self, status: int, body: bytes, ctype: str) -> None:
        self.status = status
        self.headers = {"Content-Type": ctype}
        self._body = body

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _json(name_or_body: str | dict, status: int = 200) -> _Resp:
    body = fixture(name_or_body) if isinstance(name_or_body, str) else name_or_body
    return _Resp(status, json.dumps(body).encode(), "application/json; charset=utf-8")


class _Session:
    """Answers `request` from a script and records every call."""

    def __init__(self, responses: list[_Resp | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _client(session: _Session, **kwargs) -> api.GlkvmClient:
    kwargs.setdefault("username", "admin")
    kwargs.setdefault("password", "secret")
    return api.GlkvmClient(session, "192.0.2.15", **kwargs)


def _run(coro):
    return asyncio.run(coro)


def test_credentials_travel_as_kvmd_headers():
    session = _Session([_json("auth_check.json")])
    _run(_client(session).check_auth())
    call = session.calls[0]
    assert call["headers"] == {"X-KVMD-User": "admin", "X-KVMD-Passwd": "secret"}
    assert call["url"] == "https://192.0.2.15/api/auth/check"


def test_no_credentials_means_no_auth_headers():
    session = _Session([_json("auth_check.json")])
    _run(_client(session, username=None, password=None).check_auth())
    assert session.calls[0]["headers"] == {}


def test_base_url_honours_a_non_default_port():
    session = _Session([])
    assert _client(session).base_url == "https://192.0.2.15"
    assert _client(session, port=8888).base_url == "https://192.0.2.15:8888"


def test_verify_ssl_is_passed_through_to_aiohttp():
    session = _Session([_json("auth_check.json"), _json("auth_check.json")])
    _run(_client(session, verify_ssl=False).check_auth())
    _run(_client(session, verify_ssl=True).check_auth())
    assert session.calls[0]["ssl"] is False
    assert session.calls[1]["ssl"] is True


def test_a_401_is_an_auth_error():
    session = _Session([_json("unauthorized.json", status=401)])
    with pytest.raises(api.GlkvmAuthError):
        _run(_client(session).check_auth())


def test_a_200_with_ok_false_is_still_an_error():
    # Some of GL.iNet's own endpoints answer this way.
    session = _Session(
        [
            _json(
                {"ok": False, "result": {"error": "BadRequestError", "error_msg": "no"}}
            )
        ]
    )
    with pytest.raises(api.GlkvmResponseError) as excinfo:
        _run(_client(session).get_atx())
    assert excinfo.value.error == "BadRequestError"


def test_a_non_json_answer_is_an_error_not_a_crash():
    session = _Session([_Resp(200, b"<html>login</html>", "text/html")])
    with pytest.raises(api.GlkvmResponseError):
        _run(_client(session).get_atx())


def test_connection_failures_are_connection_errors():
    session = _Session([aiohttp.ClientConnectionError("refused"), TimeoutError()])
    with pytest.raises(api.GlkvmConnectionError):
        _run(_client(session).get_atx())
    with pytest.raises(api.GlkvmConnectionError):
        _run(_client(session).get_atx())


def test_get_system_asks_only_for_the_cheap_fields():
    session = _Session([_json("info.json")])
    info = _run(_client(session).get_system())
    assert info.serial == "0123456789ABCDEF"
    assert session.calls[0]["params"] == {"fields": "system,meta"}


def test_health_validator_error_means_not_available():
    # Firmware 1.8.1 has no health submanager and says so with a 400.
    session = _Session([_json("info_health_validator_error.json", status=400)])
    assert _run(_client(session).get_health()) is None


def test_health_on_1_10_0():
    session = _Session([_json("info.json")])
    health = _run(_client(session).get_health())
    assert health is not None and health.cpu_temp == 47.03
    assert session.calls[0]["params"] == {"fields": "health"}


def test_gl_only_endpoints_degrade_to_none_when_absent():
    session = _Session(
        [
            _Resp(404, b"<html>nginx 404</html>", "text/html"),
            _Resp(404, b"<html>nginx 404</html>", "text/html"),
            _Resp(404, b"<html>nginx 404</html>", "text/html"),
        ]
    )
    client = _client(session)
    assert _run(client.get_firmware()) is None
    assert _run(client.get_hostname()) is None
    assert _run(client.get_wol_targets()) == ()


def test_gl_endpoints_when_present():
    session = _Session([_json("upgrade_version.json"), _json("get_hostname.json")])
    client = _client(session)
    fw = _run(client.get_firmware())
    assert fw is not None and fw.model == "RM10"
    assert _run(client.get_hostname()) == "GL-RM10-Example"


def test_snapshot_returns_the_jpeg():
    session = _Session([_Resp(200, b"\xff\xd8\xff\xe0jpeg", "image/jpeg")])
    assert _run(_client(session).get_snapshot()) == b"\xff\xd8\xff\xe0jpeg"


def test_snapshot_503_means_no_frame_yet():
    # kvmd answers 503 while its streamer is not running.
    body = {"ok": False, "result": {"error": "UnavailableError", "error_msg": "No"}}
    session = _Session([_json(body, status=503)])
    assert _run(_client(session).get_snapshot()) is None


def test_snapshot_needs_credentials_too():
    session = _Session([_json("unauthorized.json", status=401)])
    with pytest.raises(api.GlkvmAuthError):
        _run(_client(session).get_snapshot())


def test_snapshot_that_is_not_an_image_is_an_error():
    session = _Session([_json({"ok": True, "result": {}})])
    with pytest.raises(api.GlkvmResponseError):
        _run(_client(session).get_snapshot())


def test_type_text_sends_the_text_as_the_body():
    # A ?text= query parameter returns 200 and types nothing.
    session = _Session([_json({"ok": True, "result": {}})])
    _run(_client(session).hid_type_text("echo hi\n"))
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/hid/print")
    assert call["data"] == b"echo hi\n"
    assert call["params"] == {"limit": "0", "slow": "0"}


def test_shortcut_joins_the_keys_for_kvmd():
    session = _Session([_json({"ok": True, "result": {}})])
    _run(_client(session).hid_send_shortcut(["ControlLeft", " AltLeft", "Delete"]))
    assert session.calls[0]["url"].endswith("/api/hid/events/send_shortcut")
    assert session.calls[0]["params"] == {"keys": "ControlLeft,AltLeft,Delete"}


def test_shortcut_with_no_keys_is_refused_before_any_request():
    session = _Session([])
    with pytest.raises(ValueError):
        _run(_client(session).hid_send_shortcut(["", "  "]))
    assert session.calls == []


def test_atx_power_validates_the_action_locally():
    session = _Session([_json({"ok": True, "result": {}})])
    client = _client(session)
    with pytest.raises(ValueError):
        _run(client.atx_power("explode"))
    assert session.calls == []
    _run(client.atx_power("off"))
    assert session.calls[0]["params"] == {"action": "off", "wait": "1"}


def test_atx_click():
    session = _Session([_json({"ok": True, "result": {}})])
    _run(_client(session).atx_click("power_long", wait=False))
    assert session.calls[0]["url"].endswith("/api/atx/click")
    assert session.calls[0]["params"] == {"button": "power_long", "wait": "0"}


def test_msd_commands():
    session = _Session([_json({"ok": True, "result": {}})] * 2)
    client = _client(session)
    _run(client.msd_select_image("ubuntu.iso"))
    _run(client.msd_set_connected(True))
    assert session.calls[0]["url"].endswith("/api/msd/set_params")
    assert session.calls[0]["params"] == {"image": "ubuntu.iso", "cdrom": "1"}
    assert session.calls[1]["url"].endswith("/api/msd/set_connected")
    assert session.calls[1]["params"] == {"connected": "1"}


def test_hid_params_and_reset():
    session = _Session([_json({"ok": True, "result": {}})] * 3)
    client = _client(session)
    _run(client.hid_set_jiggler(False))
    _run(client.hid_set_mouse_output("usb_rel"))
    _run(client.hid_reset())
    assert session.calls[0]["params"] == {"jiggler": "0"}
    assert session.calls[1]["params"] == {"mouse_output": "usb_rel"}
    assert session.calls[2]["url"].endswith("/api/hid/reset")


def test_gpio_and_wol_commands():
    session = _Session([_json({"ok": True, "result": {}})] * 3)
    client = _client(session)
    _run(client.gpio_switch("relay", True))
    _run(client.gpio_pulse("demo_button"))
    _run(client.wol_wake("02:00:00:00:00:01"))
    assert session.calls[0]["params"] == {"channel": "relay", "state": "1", "wait": "1"}
    assert session.calls[1]["params"] == {"channel": "demo_button", "wait": "1"}
    assert session.calls[2]["params"] == {"mac": "02:00:00:00:00:01"}
