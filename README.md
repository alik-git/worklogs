# worklogs

Local markdown worklog helpers for developer workflows.

`worklogs` creates dated markdown files under a scope, date folder, and compact
filename:

```text
~/worklog/<scope>/YYYY/MM/DD/HHMM--kind--project--slug.md
```

## Installation

```bash
python -m pip install worklogs
```

For local development:

```bash
uv sync --extra dev
```

Standard Python fallback:

```bash
python -m pip install -e ".[dev]"
```

## Usage

Check the installed version:

```bash
worklogs --version
```

Create a plan with explicit fields:

```bash
worklogs new --scope work --kind plan --project backend-api --slug improve-deploy-notes
```

Create the same plan with the fast filename-shaped token:

```bash
worklogs new plan--backend-api--improve-deploy-notes --scope work
```

Plans create a linked companion execution note by default:

```text
HHMM--plan--backend-api--improve-deploy-notes.md
HHMM--note--backend-api--improve-deploy-notes-execution-log.md
```

Create a standalone note:

```bash
worklogs new note--personal-site--theme-ideas --scope personal
```

Preview the generated paths and markdown without writing files:

```bash
worklogs new plan--backend-api--improve-deploy-notes --scope work --dry-run
```

Print created paths for scripts:

```bash
worklogs new note--personal-site--theme-ideas --scope personal --print-path
```

Create a dated project workset directory:

```bash
worklogs workset new backend-api-refactor --worksets-root ~/worksets
```

Create a dated workset under organizer folders:

```bash
worklogs workset new release-tools/python-packaging/worklogs-0.2.1 \
  --worksets-root ~/worksets
```

Worksets are created under:

```text
<worksets-root>/YYYY/MM/DD/<workset-path>/
```

Preview a workset path without creating it:

```bash
worklogs workset new release-tools/python-packaging/worklogs-0.2.1 \
  --worksets-root ~/worksets \
  --dry-run
```

Print only the created path for scripts:

```bash
worklogs workset new backend-api-refactor \
  --worksets-root ~/worksets \
  --print-path
```

Supported kinds:

```text
plan
note
investigation
codereview
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
worklogs new plan--backend-api--improve-deploy-notes
```

With `worksets_root` configured, the workset path can omit `--worksets-root`:

```bash
worklogs workset new backend-api-refactor
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
gh release create v0.2.1 \
  --title "v0.2.1" \
  --notes "Add dated workset directory creation."
```

Publishing is release-driven on purpose: normal pushes and pull requests build
and test the package, but only GitHub Releases publish to PyPI.
