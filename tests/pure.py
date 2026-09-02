"""Load the Home Assistant-free modules by path.

The package's __init__ imports Home Assistant, so `custom_components.glkvm`
cannot be imported on a workstation without it. models.py and api.py are
deliberately free of that import; this registers a stand-in package whose
__path__ points at the component directory, so their relative imports resolve
and they load exactly as written.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "glkvm"
FIXTURES = ROOT / "tests" / "fixtures"

_PACKAGE = "glkvm_pure"


def load(name: str) -> types.ModuleType:
    """Import custom_components/glkvm/<name>.py without Home Assistant."""
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [str(COMPONENT)]
        sys.modules[_PACKAGE] = package
    full = f"{_PACKAGE}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, COMPONENT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


def fixture(name: str) -> dict[str, Any]:
    """The recorded body of one API answer, as the unit sent it."""
    with open(FIXTURES / name, encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def result(name: str) -> dict[str, Any]:
    """Just the `result` of a recorded answer, as the client hands it on."""
    body = fixture(name)["result"]
    assert isinstance(body, dict)
    return body
