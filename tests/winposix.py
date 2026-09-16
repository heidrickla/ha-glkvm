"""Windows stand-ins for the POSIX facilities the Home Assistant test harness needs.

Four separate blocks stop the HA-layer suite on a Windows workstation, in this
order:

| Blocker | Where | Fixed by |
|---|---|---|
| `import fcntl` | `homeassistant/runner.py` | `install_posix_modules` |
| `import resource` | `homeassistant/util/resource.py` | `install_posix_modules` |
| `socketpair` refused | ProactorEventLoop self-pipe | `install_socketpair_escape` |
| `aiodns` refuses Proactor | `homeassistant.runner` | `use_selector_event_loop` |

The first two are reached while pytest is still loading the
pytest-homeassistant-custom-component entry point plugin, before any conftest
runs, so they must be installed earlier than a conftest can act. Loading this
module with `-p tests.winposix` from `pyproject.toml` is early enough: pytest
handles `-p` before entry point plugins. `install_posix_modules()` therefore
runs at import.

The last two need Home Assistant importable and belong to the HA-layer suite
only, so `tests/ha/conftest.py` calls `install_ha_layer_shims()` itself.

Every function returns immediately on anything but Windows, so importing this
module changes nothing on Linux and nothing in CI.

Neither replaced module does anything a test depends on: the lock file is never
taken under pytest and the descriptor limit is a process setting.
"""

from __future__ import annotations

import socket
import sys
from types import ModuleType
from typing import Any

_WINDOWS = sys.platform == "win32"


def _fcntl_module() -> ModuleType:
    """A fcntl with the two names Home Assistant's runner reads."""
    module = ModuleType("fcntl")
    module.LOCK_EX = 2  # type: ignore[attr-defined]
    module.LOCK_NB = 4  # type: ignore[attr-defined]

    def flock(fd: int, operation: int) -> None:
        """Windows has no flock; nothing under pytest takes the lock file."""

    module.flock = flock  # type: ignore[attr-defined]
    return module


def _resource_module() -> ModuleType:
    """A resource whose file descriptor limit is fixed and unchangeable."""
    module = ModuleType("resource")
    module.RLIMIT_NOFILE = 7  # type: ignore[attr-defined]

    def getrlimit(resource_id: int) -> tuple[int, int]:
        """Report a limit already high enough, so nothing tries to raise it."""
        return (sys.maxsize, sys.maxsize)

    def setrlimit(resource_id: int, limits: tuple[int, int]) -> None:
        """Windows has no per-process descriptor limit to set."""

    module.getrlimit = getrlimit  # type: ignore[attr-defined]
    module.setrlimit = setrlimit  # type: ignore[attr-defined]
    return module


def install_posix_modules() -> None:
    """Put the stand-ins in place before Home Assistant is imported."""
    if not _WINDOWS:
        return
    builders: dict[str, Any] = {"fcntl": _fcntl_module, "resource": _resource_module}
    for name, build in builders.items():
        if name not in sys.modules:
            sys.modules[name] = build()


def install_socketpair_escape() -> None:
    """Let `socket.socketpair()` through the harness's socket block.

    ProactorEventLoop builds its self-pipe from `socket.socketpair()`, which
    pytest-socket refuses because it is not a unix socket, so every test errors
    before it runs. Hand socketpair the real socket class for the length of
    that one call; every other socket stays blocked, here and on Linux CI.

    Idempotent: calling it twice leaves one wrapper.
    """
    if not _WINDOWS or getattr(socket.socketpair, "_winposix", False):
        return
    real_socket = socket.socket
    real_socketpair = socket.socketpair

    def _unguarded_socketpair(*args: Any, **kwargs: Any) -> Any:
        guarded = socket.socket
        socket.socket = real_socket  # type: ignore[misc]
        try:
            return real_socketpair(*args, **kwargs)
        finally:
            socket.socket = guarded  # type: ignore[misc]

    _unguarded_socketpair._winposix = True  # type: ignore[attr-defined]
    socket.socketpair = _unguarded_socketpair


def use_selector_event_loop() -> None:
    """Run the suite on the selector loop.

    aiodns, which aiohttp resolves with, refuses to run on the Proactor loop
    Home Assistant picks on Windows. The selector loop runs the same tests.
    """
    if not _WINDOWS:
        return
    import asyncio

    from homeassistant import runner

    runner.HassEventLoopPolicy._loop_factory = asyncio.SelectorEventLoop


def install_ha_layer_shims() -> None:
    """Both shims the HA-layer suite needs. Call from `tests/ha/conftest.py`."""
    install_socketpair_escape()
    use_selector_event_loop()


install_posix_modules()
