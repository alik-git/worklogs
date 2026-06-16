# worklogs

Local markdown worklog helpers for developer workflows.

`worklogs` creates dated markdown files under a scope, date folder, and compact
filename:

```text
~/worklog/<scope>/YYYY/MM-month/DD-ddd/HHMM-Ha--name--kind.md
```

## Installation

```bash
uv tool install worklogs
```

Or with pip:

```bash
python -m pip install worklogs
```

Install `workset` too if you want `worklogs` to create git worksets:

```bash
uv tool install workset
```

## Usage

Check the installed version:

```bash
worklogs --version
```

Create your first note:

```bash
worklogs new first-note--note --scope personal
```

Create a plan:

```bash
worklogs new api-refactor--plan --scope work
```

Plans create a linked companion note by default:

```text
HHMM-Ha--api-refactor--plan.md
HHMM-Ha--api-refactor--note.md
```

Preview the generated paths and markdown without writing files:

```bash
worklogs new api-refactor--plan --scope work --dry-run
```

Print created paths for scripts:

```bash
worklogs new first-note--note --scope personal --print-path
```

Supported kinds:

```text
plan
note
investigation
codereview
```

## Worksets

`worklogs` can create or attach a git workset through the `workset` package.
Configure repo aliases in `~/.config/workset/repos.toml`:

```toml
[workset]
root = "~/worksets"
date_prefix = true
timezone = "America/Toronto"

[repos]
api = "~/repos/api"
web = "~/repos/web"
```

Create the plan first, then attach a workset:

```bash
worklogs new api-refactor--plan --scope work
worklogs workset api-refactor api:feat/refactor
```

Or create the worklog and workset in one command:

```bash
worklogs new checkout-flow--plan --scope work \
  --workset api:feat/checkout-flow \
  --workset web:main
```

For a first successful zero-to-workset example:

```bash
git clone git@github.com:your-org/api.git ~/repos/api
worklogs new api-refactor--plan --scope work
worklogs workset api-refactor api:feat/refactor
```

Worksets are created under:

```text
<worksets-root>/YYYY/MM-month/DD-ddd/<workset-path>/
```

## Config

Optional defaults live in:

```text
~/.config/worklogs/config.toml
```

Example:

```toml
root = "~/worklog"
default_scope = "work"
timezone = "America/Toronto"
worksets_root = "~/worksets"
```

Resolution order:

1. CLI flags
2. environment variables: `WORKLOG_ROOT`, `WORKLOG_SCOPE`,
   `WORKLOG_TIMEZONE`, `WORKLOG_WORKSETS_ROOT`
3. config file
4. package defaults

With `default_scope` configured, the fast path can omit `--scope`:

```bash
worklogs new api-refactor--plan
```

With `worksets_root` configured, the workset path can omit `--worksets-root`:

```bash
worklogs workset api-refactor api:feat/refactor
```

For shorter personal shell usage, add a local alias:

```bash
alias wl='worklogs'
```

The package installs the explicit `worklogs` command; `wl` is intentionally left
as a shell-level shortcut so it cannot shadow another global command.

## Development Workflow

Run the standard checks before opening a PR:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

If you are using standard Python tools instead of uv:

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
python -m build
```

## CI / GitHub Actions

GitHub Actions runs:

- fast Ruff-only checks
- Ruff, mypy, and pytest
- package build and wheel smoke test with pip
- package build and wheel smoke test with uv

The release workflow in [`.github/workflows/release.yml`](.github/workflows/release.yml)
builds and publishes the package to PyPI when a GitHub Release is published.

## Publishing

This project uses PyPI Trusted Publishing. The PyPI pending publisher should be:

```text
PyPI project name: worklogs
Owner: alik-git
Repository name: worklogs
Workflow name: release.yml
Environment name: pypi
```

Create a GitHub Release for the version in [`pyproject.toml`](pyproject.toml):

```bash
gh release create v0.3.6 \
  --title "v0.3.6" \
  --notes "Clarify worklog and workset onboarding."
```

Publishing is release-driven on purpose: normal pushes and pull requests build
and test the package, but only GitHub Releases publish to PyPI.
