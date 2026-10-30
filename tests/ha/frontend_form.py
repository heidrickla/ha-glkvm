"""What the Home Assistant frontend submits for a form step left as it opened.

A port of home-assistant/frontend 20260930.5, the frontend Home Assistant
2026.10.4 ships: computeInitialHaFormData in
src/components/ha-form/compute-initial-ha-form-data.ts with its selector table
in get-selector-initial-value.ts, and the required-field check and send filter
in _submitStep of src/dialogs/config-flow/step-flow-form.ts.

Backend tests that build the submitted dict by hand cannot see what the dialog
would send. These helpers start from the schema the frontend receives instead.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.helpers import config_validation as cv

try:
    from probatio import to_field_list
except ImportError:  # Core before 2026.10 serialized with voluptuous-serialize.
    from voluptuous_serialize import convert as to_field_list

# The JS `undefined`: a key that is absent, as opposed to one holding null.
_UNDEFINED = object()


class UnportedSelectorError(Exception):
    """A required field uses a selector this port does not cover."""


def serialize(schema: Any) -> list[dict[str, Any]]:
    """The form's schema as core sends it to the frontend."""
    # As _prepare_result_json in homeassistant/helpers/data_entry_flow.py does,
    # a form with no fields goes out as an empty list.
    if schema is None:
        return []
    return to_field_list(schema, custom_serializer=cv.custom_serializer)


def _multiple_or(config: dict[str, Any], single: Any) -> Any:
    return [] if config.get("multiple") else single


def _select_initial(config: dict[str, Any]) -> Any:
    options = config.get("options") or []
    if not options:
        return _UNDEFINED
    first = options[0]
    value = first if isinstance(first, str) else first["value"]
    return [value] if config.get("multiple") else value


# SELECTOR_INITIAL_VALUES for the selectors these integrations use, plus the
# simple ones. A selector missing here raises, as getSelectorInitialValue does
# for a type whose table entry is undefined.
_SELECTOR_INITIAL: dict[str, Any] = {
    "action": lambda c: [],
    "addon": lambda c: "",
    "area": lambda c: _multiple_or(c, ""),
    "attribute": lambda c: "",
    "boolean": lambda c: False,
    "color_rgb": lambda c: [0, 0, 0],
    "condition": lambda c: [],
    "constant": lambda c: c.get("value", _UNDEFINED),
    "device": lambda c: _multiple_or(c, ""),
    "duration": lambda c: {"hours": 0, "minutes": 0, "seconds": 0},
    "entity": lambda c: _multiple_or(c, ""),
    "file": lambda c: "",
    "icon": lambda c: "",
    "label": lambda c: _multiple_or(c, ""),
    "number": lambda c: c.get("min", 0),
    "object": lambda c: _multiple_or(c, ""),
    "select": _select_initial,
    "serial_port": lambda c: "",
    "state": lambda c: _multiple_or(c, ""),
    "target": lambda c: {},
    "template": lambda c: "",
    "text": lambda c: _multiple_or(c, ""),
    "theme": lambda c: "",
    "time": lambda c: "00:00:00",
    "trigger": lambda c: [],
}


def _selector_initial(selector: dict[str, Any]) -> Any:
    kind = next(iter(selector))
    initial = _SELECTOR_INITIAL.get(kind)
    if initial is None:
        raise UnportedSelectorError(kind)
    return initial(selector[kind] or {})


def _set_default_value(field: dict[str, Any], value: Any) -> Any:
    choose = (field.get("selector") or {}).get("choose")
    if choose is not None and choose.get("choices"):
        first = next(iter(choose["choices"]))
        return {"active_choice": first, first: value}
    return value


def initial_data(schema: list[dict[str, Any]]) -> dict[str, Any]:
    """computeInitialHaFormData: the dialog's data before anything is typed."""
    data: dict[str, Any] = {}
    for field in schema:
        if "visible" in field:
            raise NotImplementedError("conditional fields are not ported")
        name = field["name"]
        suggested = (field.get("description") or {}).get("suggested_value")
        kind = field.get("type")
        if suggested is not None:
            data[name] = _set_default_value(field, suggested)
        elif "default" in field:
            data[name] = _set_default_value(field, field["default"])
        elif kind == "expandable":
            inner = initial_data(field["schema"])
            if field.get("required") or inner:
                data[name] = inner
        elif not field.get("required"):
            continue
        elif kind == "boolean":
            data[name] = False
        elif kind == "string":
            data[name] = ""
        elif kind == "integer":
            data[name] = field.get("valueMin", 0)
        elif kind == "constant":
            data[name] = field["value"]
        elif kind == "float":
            data[name] = 0.0
        elif kind == "select":
            if field["options"]:
                first = field["options"][0]
                data[name] = first[0] if isinstance(first, list | tuple) else first
        elif kind == "positive_time_period_dict":
            data[name] = {"hours": 0, "minutes": 0, "seconds": 0}
        elif "selector" in field:
            value = _selector_initial(field["selector"])
            if value is not _UNDEFINED:
                data[name] = value
    return data


def all_required_filled(schema: list[dict[str, Any]], data: Any) -> bool:
    """checkAllRequiredFields in _submitStep; False shows not_all_required_fields."""
    for field in schema:
        value = (
            data.get(field["name"], _UNDEFINED)
            if isinstance(data, dict)
            else _UNDEFINED
        )
        if field.get("required") and (value is _UNDEFINED or value == ""):
            return False
        if field.get("type") != "expandable":
            continue
        if not field.get("required") and value is _UNDEFINED:
            continue
        if not all_required_filled(field["schema"], value):
            return False
    return True


def to_send(schema: list[dict[str, Any]], data: dict[str, Any]) -> dict[str, Any]:
    """toSendData in _submitStep: empty and read-only top-level values are dropped."""
    fields = {field["name"]: field for field in schema}
    sent: dict[str, Any] = {}
    for key, value in data.items():
        if value == "":
            continue
        selector = (fields.get(key) or {}).get("selector") or {}
        config = next(iter(selector.values()), None) if selector else None
        if isinstance(config, dict) and config.get("read_only"):
            continue
        sent[key] = value
    return json.loads(json.dumps(sent))


def frontend_submission(
    result: dict[str, Any], typed: dict[str, Any] | None = None
) -> dict[str, Any]:
    """What pressing Submit sends: the opening data plus top-level fields typed in.

    Sections stay as they opened; `typed` may name only top-level, non-section
    fields, the ones a user fills in without expanding anything.
    """
    schema = serialize(result["data_schema"])
    data = initial_data(schema)
    sections = {f["name"] for f in schema if f.get("type") == "expandable"}
    # A section field with a default must open holding it; otherwise Advanced,
    # once expanded, shows it empty.
    for field in schema:
        if field["name"] in sections:
            opened = data.get(field["name"]) or {}
            for inner in field["schema"]:
                assert "default" not in inner or inner["name"] in opened, (
                    f"{field['name']}.{inner['name']} opens empty, not at its default"
                )
    for key, value in (typed or {}).items():
        assert key in {f["name"] for f in schema}, f"no field {key} on the form"
        assert key not in sections, f"{key} is a section; the guard leaves it closed"
        data[key] = value
    assert all_required_filled(schema, data), (
        f"the dialog would refuse Submit (not_all_required_fields): {data}"
    )
    return to_send(schema, data)
