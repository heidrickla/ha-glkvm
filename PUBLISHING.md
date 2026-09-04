# Publishing

Two destinations, in order: HACS as a custom integration, then Home Assistant
core. The code is built for both from the first commit; neither is submitted.

## Status

| Step | State |
|---|---|
| Public GitHub repository | Done: `heidrickla/ha-glkvm`, issues on, topics set. |
| HACS and hassfest actions green | Done on `main`; both run on every push. |
| Release after green | `v0.1.0`, created on a green commit. |
| `hacs/default` pull request | **Not opened.** The branch is staged on the `heidrickla/default` fork; see below. |

### Opening the pull request

The fork carries branch `add-heidrickla-ha-glkvm` with the one-line insert.
Open it from the fork against `hacs/default` `master`, titled
`Adds new integration [heidrickla/ha-glkvm]`, body = their template with
every box ticked and the three links. Current links come from:

```bash
gh release view v0.1.0 --repo heidrickla/ha-glkvm --json url --jq .url
gh run list --repo heidrickla/ha-glkvm --workflow Validate --branch main --limit 1 --json databaseId,conclusion
```

The HACS and hassfest links are the two *job* URLs inside that Validate run.
After opening, leave it alone: the queue is oldest-first and comments delay it.

## The Home Assistant layer tests run on Linux, not here

`tests/ha/` covers setup and unload, the config, reconfigure and reauth flows
with their refusals and their recovery from each, every entity's state
against recorded bodies, every command and action against a recorded client,
the two repair issues, and diagnostics redaction. The GitHub `Tests` workflow
(`.github/workflows/tests.yml`) runs them on every push against the pinned
Home Assistant release, reports coverage, and runs mypy in strict mode with
Home Assistant installed. The forge's `Home Assistant layer` job
(`.gitea/workflows/validate.yml`) runs the same suite on `workflow_dispatch`
only, because that runner is shared. They do not run on Windows: the harness
blocks sockets and the ProactorEventLoop needs a local socket pair.

They skip when the harness is absent, so a bare checkout runs only the pure
suite and does not imply coverage it does not have.

## Quality scale

`custom_components/glkvm/quality_scale.yaml` tracks every rule with a written
reason on each exemption. `tools/validate_local.py` checks it against the
pinned rule list.

Rules marked `todo`, and what clears each:

| Rule | Clears when |
|---|---|
| `test-coverage` | The `Tests` job reports 95% or more for every module and `--cov-fail-under=95` is added so it stays there. Coverage is reported today, not gated. |
| `entity-unavailable` | Entities whose section failed to read in a partial poll (one to six of the seven endpoints) become unavailable rather than keeping their last value. |
| `reauthentication-flow` | The reauth step sets the unique id and aborts on a mismatch, so a swapped unit at the same address is refused. |
| `strict-typing` | The `Tests` job's mypy run, with Home Assistant installed and no relaxations in pyproject, is green. |
| `discovery`, `discovery-update-info` | The unit's mDNS service type and TXT records have been measured from a LAN host and a zeroconf flow keyed on the serial is implemented. Not guessed. |

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
5. **Measure discovery** before submitting. A core reviewer will ask why a
   device with an mDNS responder has no discovery.
6. Open the PR against `home-assistant/core` with the documentation PR against
   `home-assistant/home-assistant.io`; the README sections here map onto the
   documentation page's required headings (installation, configuration,
   supported devices and functions, data updates, actions, known limitations,
   troubleshooting, removal).

Nothing in the entity layer needs to change for core. What changes is where
the client lives.
