# Publishing

Two destinations, in order: HACS as a custom integration, then Home Assistant
core. The code is built for both from the first commit; neither is submitted.

## Status

| Step | State |
|---|---|
| Public GitHub repository | Done: `heidrickla/ha-glkvm`, issues on, topics set. |
| HACS and hassfest actions green | Done on `main`; both run on every push. |
| Release after green | `v0.2.0`, created on the green head that carries discovery, MAC-following and the per-section unavailability. `v0.1.0` was created on `b030256`. Nothing is unreleased; `CHANGELOG.md` lists both. |
| `hacs/default` pull request | **Not opened.** The branch is staged on the `heidrickla/default` fork; see below. |
| Forge (`gitea`) copy | **Behind GitHub.** Pushes go to `origin` only while the shared runner is busy; one catch-up push when it is quiet. |

### Opening the pull request

The fork carries branch `add-heidrickla-ha-glkvm` with the one-line insert.
Open it from the fork against `hacs/default` `master`, titled
`Adds new integration [heidrickla/ha-glkvm]`, body = their template with
every box ticked and the three links. Current links come from:

```bash
gh release view v0.2.0 --repo heidrickla/ha-glkvm --json url --jq .url
gh run list --repo heidrickla/ha-glkvm --workflow Validate --branch main --limit 1 --json databaseId,conclusion
```

The HACS and hassfest links are the two *job* URLs inside that Validate run.
After opening, leave it alone: the queue is oldest-first and comments delay it.

## The Home Assistant layer tests run on Linux, not here

`tests/ha/` covers setup and unload, the config, zeroconf, reconfigure and
reauth flows with their refusals and their recovery from each, every entity's
state against recorded bodies, a poll in which each of the seven sections
fails on its own, every command and action against a recorded client, the two
repair issues, and diagnostics redaction. The GitHub `Tests` workflow
(`.github/workflows/tests.yml`) runs them on every push against the pinned
Home Assistant release, gates coverage of both suites together at 95%, and
runs mypy in strict mode with Home Assistant installed. The forge's `Home
Assistant layer` job (`.gitea/workflows/validate.yml`) runs the same suite on
`workflow_dispatch` only, because that runner is shared. They do not run on
Windows: the harness blocks sockets and the ProactorEventLoop needs a local
socket pair.

They skip when the harness is absent, so a bare checkout runs only the pure
suite and does not imply coverage it does not have.

## Quality scale

`custom_components/glkvm/quality_scale.yaml` tracks every rule with a written
reason on each exemption. `tools/validate_local.py` checks it against the
pinned rule list, and refuses a `done` the file set contradicts: `discovery`
without a discovery key in the manifest and a step to answer it,
`reauthentication-flow` without the unique-id check, `entity-unavailable`
without an entity that consults the failed sections, `test-coverage` without
a workflow that gates on a threshold, `strict-typing` with a relaxation in
pyproject.

| Rule | Status |
|---|---|
| Every rule at every tier | `done` or `exempt` with a written reason. Nothing is `todo`. |
| Exemptions | `dependency-transparency` (no external dependency), `docs-conditions` and `docs-triggers` (none provided), `docs-configuration-parameters` (no options), `dynamic-devices` and `stale-devices` (one entry is one KVM). |

A rule is `done` when a test or a CI run shows it, not when the code looks
right. Written tests that have never run are not coverage, and mypy without
Home Assistant installed sees every HA class as `Any`; the first real run of
each found gaps a local pass had not.

`quality_scale` is deliberately absent from `manifest.json`. The badge is
core-only; the validator refuses a manifest that claims a tier.

## HACS, in order (the order is load-bearing)

1. **Make the GitHub repo public** with description, topics, licence, README
   and issues enabled. `documentation` and `issue_tracker` in
   `manifest.json` already point at it.
2. **Push and wait for green.** A push is not done until CI is green.
3. **Bump `manifest.json` AND `const.VERSION` together** to the version about
   to be tagged, push, wait for green *again*.
4. **Create a full GitHub release on that green commit.** Not a tag - a
   release. `--target` needs a branch name or a full 40-character SHA.
5. **Submit to `hacs/default`**: fork, branch, one-line textual insert into
   their `integration` file (insert textually - `json.dumps` reflows an
   existing mis-indented entry and turns a 1-line diff into 2), PR titled
   `Adds new integration [<owner>/<repo>]`, body = their template with every
   box ticked and three links: the release, the successful HACS action job,
   the successful hassfest job.
6. **Then leave it alone.** The queue is oldest-first; commenting delays it.

No brands PR is needed: the brand images are in-repo under
`custom_components/glkvm/brand/` and HACS reads them first (Home Assistant
2026.3 and later).

## Core, when the time comes

A core integration cannot speak a protocol itself; the client has to be a
published library. `api.py` and `models.py` were written for that move: they
import nothing from Home Assistant and nothing from each other's neighbours.

1. **Lift `api.py` and `models.py` into a package** (`pyglkvm`, say), typed
   (`py.typed`), async, on PyPI with a pinned version. Keep the tests in
   `tests/test_api.py` and `tests/test_models.py` with it.
2. **Point the integration at it**: `requirements: ["pyglkvm==x.y.z"]`, the
   imports become `from pyglkvm import ...`, `dependency-transparency` flips
   from exempt to done (the package must build from source on CI).
3. **Brand images** go to `home-assistant/brands` instead of the in-repo
   folder.
4. **`quality_scale.yaml`** moves as-is; the same rules apply and the same
   validator logic exists in core's hassfest.
5. **Zeroconf discovery** is already in the manifest and answered by
   `async_step_zeroconf`. A core submission adds `glkvm` to
   `homeassistant/generated/zeroconf.py`, which hassfest generates.
6. Open the PR against `home-assistant/core` with the documentation PR against
   `home-assistant/home-assistant.io`; the README sections here map onto the
   documentation page's required headings (installation, configuration,
   supported devices and functions, data updates, actions, known limitations,
   troubleshooting, removal).

Nothing in the entity layer needs to change for core. What changes is where
the client lives.
