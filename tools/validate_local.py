"""Local stand-in for the checks CI would run.

hassfest and the HACS action run on GitHub; this approximates the parts of
them that can be checked with no network at all, plus the cross-file
consistency that nothing else checks: translation keys against icons,
exceptions raised against exceptions declared, user-facing exceptions raised
without a translation key, actions registered against actions described, the
three version fields against each other, the quality scale against the pinned
rule list. Run it before a push so the push is not the first verification.

    python tools/validate_local.py
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from typing import Any

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOMAIN = "glkvm"
COMP = os.path.join(ROOT, "custom_components", DOMAIN)
PLATFORMS = ("binary_sensor", "button", "camera", "select", "sensor", "switch")

# hassfest requires these for a custom integration.
REQUIRED_MANIFEST = [
    "domain",
    "name",
    "documentation",
    "codeowners",
    "iot_class",
    "version",
]
VALID_IOT_CLASS = {
    "assumed_state",
    "cloud_polling",
    "cloud_push",
    "local_polling",
    "local_push",
    "calculated",
}

# Pinned from developers.home-assistant.io/docs/core/integration-quality-scale/checklist
# (checked 2026-09-02: 54 rules, none new or deprecated). The list is pinned
# here on purpose: a quality_scale.yaml that is missing a rule reads as
# complete, and checking against the full list turns an omission into a
# failure.
ALL_RULES = {
    # Bronze
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    # Gold
    "devices",
    "diagnostics",
    "discovery-update-info",
    "discovery",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    # Platinum
    "async-dependency",
    "inject-websession",
    "strict-typing",
}

failures: list[str] = []
notes: list[str] = []


def read(*parts: str) -> str:
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def read_json(*parts: str) -> Any:
    return json.loads(read(*parts))


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def constants(source: str, prefix: str) -> dict[str, str]:
    """Module-level string assignments whose name starts with prefix."""
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id.startswith(prefix)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[target.id] = node.value.value
    return found


# Every exception a user can see on the integration card or in an action
# error. A raise of one of these without translation_key shows an English
# f-string to every user, whatever their language.
TRANSLATED_EXCEPTIONS = {
    "HomeAssistantError",
    "ServiceValidationError",
    "ConfigEntryNotReady",
    "ConfigEntryAuthFailed",
    "ConfigEntryError",
    "UpdateFailed",
}


def untranslated_raises(source: str, filename: str) -> list[str]:
    """Raises of Home Assistant's user-facing exceptions that carry no key."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in TRANSLATED_EXCEPTIONS:
            continue
        keywords = {kw.arg for kw in node.exc.keywords}
        if "translation_key" not in keywords:
            found.append(
                f"{filename}:{node.lineno} raises {name} without translation_key"
            )
    return found


def pyproject_version() -> str | None:
    """The version in pyproject.toml, or None when the file does not carry one."""
    path = os.path.join(ROOT, "pyproject.toml")
    if not os.path.isfile(path):
        return None
    import tomllib

    with open(path, "rb") as fh:
        project = tomllib.load(fh).get("project", {})
    version = project.get("version")
    return str(version) if version is not None else None


def main() -> int:
    manifest = read_json(COMP, "manifest.json")
    const_src = read(COMP, "const.py")
    strings = read_json(COMP, "strings.json")

    # ---------------------------------------------------------- manifest
    for key in REQUIRED_MANIFEST:
        check(key in manifest, f"manifest.json missing required key {key!r}")
    check(
        manifest.get("domain") == DOMAIN,
        f"manifest domain is {manifest.get('domain')!r}",
    )
    check(
        manifest.get("iot_class") in VALID_IOT_CLASS,
        f"manifest iot_class {manifest.get('iot_class')!r} is not a valid value",
    )
    check(
        isinstance(manifest.get("codeowners"), list)
        and all(c.startswith("@") for c in manifest["codeowners"]),
        "manifest codeowners entries must start with @",
    )
    keys = list(manifest)
    check(
        keys[:2] == ["domain", "name"] and keys[2:] == sorted(keys[2:]),
        "manifest keys must be domain, name, then alphabetical (hassfest MANIFEST)",
    )
    if re.search(
        r"//(?:localhost|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)",
        manifest.get("documentation", ""),
    ):
        notes.append("documentation URL points at a LAN host - useless to a user")
    check(
        "quality_scale" not in manifest,
        "quality_scale in manifest.json: the badge is core-only, a custom "
        "integration builds to the rules and does not claim a tier",
    )

    const_version = constants(const_src, "VERSION").get("VERSION")
    check(
        const_version == manifest.get("version"),
        f"const.VERSION {const_version!r} != manifest version "
        f"{manifest.get('version')!r} - HA reports one and HACS the other",
    )
    project_version = pyproject_version()
    if project_version is not None:
        check(
            project_version == manifest.get("version"),
            f"pyproject version {project_version!r} != manifest version "
            f"{manifest.get('version')!r} - bump them together",
        )

    # ---------------------------------------------------------- hacs.json
    hacs = read_json(ROOT, "hacs.json")
    check("name" in hacs, "hacs.json must contain name")

    # ---------------------------------------------------------- brand images
    brand = os.path.join(COMP, "brand")
    for name in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png"):
        check(os.path.isfile(os.path.join(brand, name)), f"missing brand/{name}")

    # ---------------------------------------------------------- translations
    en = read_json(COMP, "translations", "en.json")
    check(
        strings == en,
        "strings.json and translations/en.json differ - copy strings.json over",
    )

    # ---------------------------------------------------------- actions
    services_yaml = os.path.join(COMP, "services.yaml")
    check(os.path.isfile(services_yaml), "services.yaml is missing")
    service_consts = set(constants(const_src, "SERVICE_").values())
    declared_services = set(strings.get("services", {}))
    check(
        declared_services == service_consts,
        f"strings.json describes {sorted(declared_services)} but const.py "
        f"registers {sorted(service_consts)}",
    )
    try:
        import yaml

        services = yaml.safe_load(read(services_yaml)) or {}
        check(
            set(services) == service_consts,
            f"services.yaml declares {sorted(services)} but const.py registers "
            f"{sorted(service_consts)}",
        )
        for name, spec in services.items():
            yaml_fields = set((spec or {}).get("fields", {}))
            described = set(strings.get("services", {}).get(name, {}).get("fields", {}))
            check(
                yaml_fields == described,
                f"action {name}: services.yaml fields {sorted(yaml_fields)} != "
                f"strings.json fields {sorted(described)}",
            )
            for field_spec in (spec or {}).get("fields", {}).values():
                selector = (field_spec or {}).get("selector", {})
                tkey = (selector.get("select") or {}).get("translation_key")
                if tkey:
                    check(
                        tkey in strings.get("selector", {}),
                        f"selector translation {tkey!r} missing from strings.json",
                    )
    except ImportError:
        notes.append("PyYAML not installed - services.yaml not parsed")

    # ---------------------------------------------------------- quality scale
    scale_path = os.path.join(COMP, "quality_scale.yaml")
    check(os.path.isfile(scale_path), "quality_scale.yaml is missing")
    declared: dict[str, Any] = {}
    if os.path.isfile(scale_path):
        try:
            import yaml

            declared = yaml.safe_load(read(scale_path)).get("rules", {})
            missing = ALL_RULES - set(declared)
            check(not missing, f"quality_scale.yaml does not mention {sorted(missing)}")
            unknown = set(declared) - ALL_RULES
            check(not unknown, f"quality_scale.yaml invents rules {sorted(unknown)}")
            for rule, value in sorted(declared.items()):
                if isinstance(value, dict):
                    check(
                        value.get("status") in {"done", "todo", "exempt"},
                        f"{rule}: status must be done/todo/exempt",
                    )
                    if value.get("status") != "done":
                        check(
                            bool(str(value.get("comment", "")).strip()),
                            f"{rule}: a non-done status needs a comment saying why",
                        )
                else:
                    check(value == "done", f"{rule}: bare value must be 'done'")
            todo = sorted(
                r
                for r, v in declared.items()
                if isinstance(v, dict) and v.get("status") == "todo"
            )
            if todo:
                notes.append(f"quality scale still todo: {', '.join(todo)}")
        except ImportError:
            notes.append("PyYAML not installed - quality_scale.yaml not parsed")

    # ------------------------------------------------- quality scale evidence
    # A rule filed `done` that the file set contradicts is worse than one
    # filed `todo`: the todo gets read, the done does not. Each check below is
    # the smallest fact that would be false if the mechanism were absent.
    flow_src = read(COMP, "config_flow.py")
    models_src = read(COMP, "models.py")
    entity_src = read(COMP, "entity.py")
    workflows = ""
    for root in (".github", ".gitea"):
        folder = os.path.join(ROOT, root, "workflows")
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                workflows += read(folder, name)

    def status(rule: str) -> str:
        value = declared.get(rule)
        if isinstance(value, dict):
            return str(value.get("status", ""))
        return str(value or "")

    def needs(rule: str, condition: bool, message: str) -> None:
        if status(rule) == "done":
            check(condition, f"{rule} is done but {message}")

    # Discovery is a manifest key plus the flow step that answers it.
    discovery_keys = ("zeroconf", "dhcp", "ssdp", "bluetooth", "homekit", "usb")
    found_discovery = [key for key in discovery_keys if key in manifest]
    needs(
        "discovery",
        bool(found_discovery),
        "manifest.json declares no discovery method",
    )
    for key in found_discovery:
        needs(
            "discovery",
            f"async_step_{key}(" in flow_src,
            f"manifest declares {key} with no async_step_{key} to answer it",
        )
    needs(
        "discovery-update-info",
        "_abort_if_unique_id_configured(updates=" in flow_src
        or "async_update_entry(" in flow_src,
        "no discovery path updates a configured entry's connection details",
    )
    needs(
        "reauthentication-flow",
        "async_step_reauth_confirm(" in flow_src
        and "_abort_if_unique_id_mismatch(" in flow_src,
        "reauth does not check that the unit answering is still this entry's",
    )
    needs(
        "reconfiguration-flow",
        "async_step_reconfigure(" in flow_src,
        "there is no reconfigure step",
    )
    needs(
        "entity-unavailable",
        "failed:" in models_src and "self.data.failed" in entity_src,
        "no entity consults the set of sections the last poll failed to read",
    )
    needs(
        "test-coverage",
        "--cov-fail-under" in workflows,
        "no workflow gates on a coverage threshold",
    )
    needs(
        "strict-typing",
        "strict = true" in read(ROOT, "pyproject.toml"),
        "pyproject.toml does not run mypy in strict mode",
    )
    for relaxation in (
        "disallow_subclassing_any = false",
        "disallow_untyped_decorators = false",
        "warn_unused_ignores = false",
        "disallow_untyped_defs = false",
        "ignore_errors = true",
    ):
        needs(
            "strict-typing",
            relaxation not in read(ROOT, "pyproject.toml").split("[[tool.mypy")[0],
            f"pyproject.toml relaxes mypy with {relaxation}",
        )

    # --------------------------------------------------- config flow strings
    # Every step the flow shows, every error it can put on a form and every
    # reason it aborts with has to have text. A missing one shows the user a
    # translation key.
    config_strings = strings.get("config", {})
    for step in set(re.findall(r'step_id="([a-z_]+)"', flow_src)):
        check(
            step in config_strings.get("step", {}),
            f"config flow shows step {step!r} with no strings.json entry",
        )
    for step in config_strings.get("step", {}):
        check(
            f"async_step_{step}(" in flow_src,
            f"strings.json describes step {step!r} that the flow does not have",
        )
    for error in set(re.findall(r'\{"base": "([a-z_]+)"\}', flow_src)):
        check(
            error in config_strings.get("error", {}),
            f"config flow returns error {error!r} with no strings.json entry",
        )
    # The three Home Assistant raises itself, whatever the flow says.
    abort_reasons = set(re.findall(r'reason="([a-z_]+)"', flow_src)) | {
        "already_configured",
        "reconfigure_successful",
        "reauth_successful",
    }
    for reason in abort_reasons:
        check(
            reason in config_strings.get("abort", {}),
            f"config flow aborts with {reason!r} with no strings.json entry",
        )
    for reason in config_strings.get("abort", {}):
        check(
            reason in abort_reasons,
            f"strings.json declares unused abort reason {reason!r}",
        )

    # ------------------------------------------------------ icon translations
    # Every translation key an entity uses needs an icon and a name, and every
    # icon and name needs an entity using it. Both forms are matched: the
    # class attribute and the EntityDescription keyword.
    icons = read_json(COMP, "icons.json")
    key_re = re.compile(r'(?:_attr_translation_key\s*=|\btranslation_key=)\s*"([^"]+)"')
    # An exception is raised with translation_domain=DOMAIN right before its
    # key; entity and issue keys never carry translation_domain. Subtracted
    # here so an error raised inside a platform file is not read as one of
    # that platform's entities.
    exc_re = re.compile(r'translation_domain=DOMAIN,\s*translation_key="([^"]+)"')
    for platform in PLATFORMS:
        source = read(COMP, f"{platform}.py")
        used = set(key_re.findall(source)) - set(exc_re.findall(source))
        declared_icons = set(icons.get("entity", {}).get(platform, {}))
        named = set(strings.get("entity", {}).get(platform, {}))
        check(
            used == declared_icons,
            f"{platform}: icons {sorted(declared_icons ^ used)} out of step",
        )
        check(used == named, f"{platform}: names {sorted(named ^ used)} out of step")
    service_icons = set(icons.get("services", {}))
    check(
        service_icons == service_consts,
        f"icons.json services {sorted(service_icons)} != {sorted(service_consts)}",
    )

    # ------------------------------------------------- exception translations
    # Two checks: every key raised is declared (and vice versa), and no
    # user-facing exception is raised without a key anywhere in the
    # component - setup and poll failures in __init__.py and coordinator.py
    # included, since those show on the integration card.
    raised: set[str] = set()
    for f in sorted(os.listdir(COMP)):
        if f.endswith(".py"):
            source = read(COMP, f)
            raised |= set(exc_re.findall(source))
            for message in untranslated_raises(source, f):
                failures.append(message)
    declared_exc = set(strings.get("exceptions", {}))
    check(
        raised <= declared_exc,
        f"code raises undeclared exception keys {sorted(raised - declared_exc)}",
    )
    check(
        declared_exc <= raised,
        f"strings.json declares unused exceptions {sorted(declared_exc - raised)}",
    )

    # ----------------------------------------------------- issue translations
    issue_consts = set(constants(const_src, "ISSUE_").values())
    declared_issues = set(strings.get("issues", {}))
    check(
        issue_consts == declared_issues,
        f"const.py issues {sorted(issue_consts)} != strings.json issues "
        f"{sorted(declared_issues)}",
    )

    # ------------------------------------------------------------ platforms
    init_src = read(COMP, "__init__.py")
    for platform in PLATFORMS:
        check(
            f"Platform.{platform.upper()}" in init_src,
            f"{platform}.py exists but Platform.{platform.upper()} is not forwarded",
        )
        check(
            "PARALLEL_UPDATES" in read(COMP, f"{platform}.py"),
            f"{platform}.py does not set PARALLEL_UPDATES",
        )

    # ---------------------------------------------------------- syntax
    for dirpath, _dirs, files in os.walk(COMP):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(dirpath, f)
                try:
                    ast.parse(read(path))
                except SyntaxError as err:
                    failures.append(f"{f}: {err}")

    # ---------------------------------------------------------- report
    print(f"manifest {manifest.get('domain')} {manifest.get('version')}")
    for n in notes:
        print(f"  NOTE   {n}")
    for f in failures:
        print(f"  FAIL   {f}")
    if not failures:
        print("  all offline checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
