# worklogs

Local markdown worklog helpers for developer workflows.

This initial package release establishes the public package name, metadata,
typed Python package layout, command entry point, CI, and PyPI trusted
publishing path. The worklog creation and companion-note workflow will be added
in follow-up releases.

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

```bash
worklogs --version
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
gh release create v0.1.0 \
  --title "v0.1.0" \
  --notes "Initial package metadata release."
```

Publishing is release-driven on purpose: normal pushes and pull requests build
and test the package, but only GitHub Releases publish to PyPI.
