# Publishing

Two destinations, in order: HACS as a custom integration, then Home Assistant
core. The code is built for both from the first commit; neither is submitted.

## What blocks a HACS submission today

| Blocker | Detail |
|---|---|
| **No green GitHub Actions run yet** | The two required workflows in `.github/workflows/` are gated to GitHub and have not run there. A submission needs links to *successful* job runs. |
| **No release** | HACS wants a full GitHub release on a green commit, not a tag. |

Neither is a code problem.

## The Home Assistant layer tests run on Linux, not here

`tests/ha/` covers setup and unload, the config, reconfigure and reauth flows
and their refusals, every entity's state against recorded bodies, every
command and action against a recorded client, the two repair issues, and
diagnostics redaction. They run in CI on the self-hosted Gitea runner under
the `Home Assistant layer` job (`workflow_dispatch`, because the runner is
shared and installing Home Assistant is slow). They do not run on Windows: the
harness blocks sockets and the ProactorEventLoop needs a local socket pair.

They skip when the harness is absent, so a bare checkout runs only the pure
suite and does not imply coverage it does not have.

## Quality scale

`custom_components/glkvm/quality_scale.yaml` tracks every rule with a written
reason on each exemption. `tools/validate_local.py` checks it against the
pinned rule list.

Rules marked `todo`, and what clears each:

| Rule | Clears when |
|---|---|
| `discovery`, `discovery-update-info` | The unit's mDNS service type and TXT records have been measured from a LAN host and a zeroconf flow keyed on the serial is implemented. Not guessed. |

`config-flow-test-coverage`, `test-coverage` and `strict-typing` were `todo`
until the `Home Assistant layer` job had run the suites and mypy strict green
with Home Assistant 2026.8.3 installed (2026-09-02). Written tests that have
never run are not coverage, and mypy without HA installed sees every HA class
as `Any` - that first real run found two typing gaps and one redaction gap a
local pass had not.

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
