"""Command-line entry point for worklogs."""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from workset.paths import dated_dir

from worklogs import __version__

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

VALID_KINDS = frozenset({"plan", "note", "investigation", "codereview"})
_LOG_FORMAT = "[%(levelname)s] %(message)s"
_COLOR_FORMAT = "%(log_color)s[%(levelname)s]%(reset)s %(message)s"
_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "bold_white",
    "WARNING": "yellow",
    "ERROR": "red",
}
LOGGER = logging.getLogger(__name__)
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CONFIG_PATH = Path("~/.config/worklogs/config.toml")

GENERIC_TIMEZONE_LABELS = {
    "America/Detroit": "ET",
    "America/New_York": "ET",
    "America/Toronto": "ET",
    "America/Chicago": "CT",
    "America/Denver": "MT",
    "America/Los_Angeles": "PT",
    "America/Vancouver": "PT",
}


class WorklogsError(Exception):
    """Raised for user-facing worklogs command errors."""


@dataclass(frozen=True)
class WorklogIdentity:
    """The compact identity fields used to render a worklog filename."""

    name: str
    kind: str


@dataclass(frozen=True)
class WorklogConfig:
    """Resolved user defaults for worklog creation."""

    root: Path
    scope: str
    timezone: tzinfo
    worksets_root: Path | None


@dataclass(frozen=True)
class WorklogEntry:
    """A worklog file that should be created."""

    path: Path
    content: str


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="worklogs",
        description="Create and maintain local worklog files.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    sub = parser.add_subparsers(dest="command")

    # worklogs new
    new = sub.add_parser("new", help="create a dated worklog file")
    new.add_argument(
        "identity",
        nargs="?",
        metavar="NAME--KIND",
        help="compact identity token, e.g. api-refactor--plan",
    )
    new.add_argument("--name", help="work item name slug")
    new.add_argument("--kind", choices=sorted(VALID_KINDS))
    new.add_argument("--root", metavar="PATH")
    new.add_argument("--scope", metavar="NAME")
    new.add_argument("--project", metavar="NAME", help="project label for frontmatter")
    new.add_argument("--timezone", metavar="ZONE")
    new.add_argument("--link", action="append", default=[], metavar="VALUE")
    new.add_argument("--folder", action="append", default=[], metavar="PATH")
    new.add_argument(
        "--workset",
        action="append",
        default=[],
        metavar="REPO:BRANCH",
        help="create a git workset alongside the plan; repeat for multiple repos",
    )
    new.add_argument("--no-companion", action="store_true")
    new.add_argument("--dry-run", action="store_true")
    new.add_argument("--print-path", action="store_true")

    # worklogs workset
    wset = sub.add_parser("workset", help="attach a git workset to an existing plan")
    wset.add_argument(
        "name", metavar="NAME", help="plan name slug to attach workset to"
    )
    wset.add_argument("repo_specs", nargs="+", metavar="REPO:BRANCH")
    wset.add_argument("--root", metavar="PATH")
    wset.add_argument("--worksets-root", metavar="PATH")
    wset.add_argument("--no-env", action="store_true")
    wset.add_argument("--no-smoke", action="store_true")

    # worklogs find
    find = sub.add_parser("find", help="search worklog files by keyword")
    find.add_argument("query", metavar="QUERY")
    find.add_argument("--root", metavar="PATH")
    find.add_argument("--scope", metavar="NAME")

    return parser


def _configure_logging() -> None:
    """Configure color console logging for the worklogs CLI."""
    use_color = not os.environ.get("NO_COLOR") and sys.stderr.isatty()
    handler = logging.StreamHandler()
    if use_color:
        try:
            import colorlog

            handler.setFormatter(
                colorlog.ColoredFormatter(_COLOR_FORMAT, log_colors=_LOG_COLORS)
            )
        except ImportError:
            handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    else:
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worklogs command-line interface."""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "new":
            return _run_new(args)
        if args.command == "workset":
            return _run_workset(args)
        if args.command == "find":
            return _run_find(args)
    except WorklogsError as error:
        LOGGER.error("%s", error)
        return 2

    LOGGER.error("unknown command: %s", args.command)
    return 2


def _run_new(args: argparse.Namespace) -> int:
    """Handle ``worklogs new``."""
    identity = _resolve_identity(args)
    config = _resolve_config(args, os.environ)

    if args.no_companion and identity.kind != "plan":
        raise WorklogsError("--no-companion only applies to plan worklogs")

    now = datetime.now(UTC).astimezone(config.timezone)
    entries = _build_entries(
        identity=identity,
        config=config,
        now=now,
        project=args.project or "",
        links=tuple(args.link),
        folders=tuple(args.folder),
        create_companion=not args.no_companion,
    )

    if args.dry_run:
        _print_dry_run(entries)
    else:
        _write_entries(entries)
        if args.print_path:
            for entry in entries:
                print(entry.path)
        else:
            noun = "file" if len(entries) == 1 else "files"
            print(f"Created {len(entries)} worklog {noun}.")

    if args.workset and not args.dry_run:
        _create_workset_for_plan(
            identity=identity,
            config=config,
            plan_path=entries[0].path,
            repo_specs=args.workset,
        )

    return 0


def _run_workset(args: argparse.Namespace) -> int:
    """Handle ``worklogs workset`` — attach a git workset to an existing plan."""
    _require_workset_package()
    from workset import create_workset

    config = _resolve_config(args, os.environ)
    worksets_root = _resolve_worksets_root(config)
    plan = _find_plan_by_name(args.name, config.root)

    day_dir = plan.parent
    year, month, day = day_dir.parts[-3], day_dir.parts[-2], day_dir.parts[-1]
    dest = worksets_root / year / month / day / args.name

    try:
        result = create_workset(
            slug=args.name,
            repo_specs=args.repo_specs,
            dest=dest,
            no_env=args.no_env,
            no_smoke=args.no_smoke,
        )
    except Exception as exc:
        raise WorklogsError(str(exc)) from exc
    _print_workset_result(result)
    return 0 if result.ok else 1


def _run_find(args: argparse.Namespace) -> int:
    """Handle ``worklogs find`` — search worklog body and filenames."""
    config = _resolve_config(args, os.environ)
    search_root = config.root / args.scope if args.scope else config.root

    name_matches = sorted(
        p
        for p in search_root.rglob("*.md")
        if args.query.lower() in p.name.lower()
        and "gitignored_artifacts" not in p.parts
    )
    if name_matches:
        print("Filename matches:")
        for p in name_matches:
            print(f"  {p}")
        print()

    rg_result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "rg",
            "--heading",
            "--line-number",
            "--color",
            "auto",
            "--glob",
            "*.md",
            "--glob",
            "!gitignored_artifacts",
            "-i",
            args.query,
            str(search_root),
        ],
        check=False,
    )
    return rg_result.returncode if not name_matches else 0


def _find_plan_by_name(name: str, root: Path) -> Path:
    """Find a plan file by name slug, erroring on zero or multiple matches."""
    pattern = f"*/*/*/*/[0-9]*--{name}--plan.md"
    matches = sorted(root.glob(pattern))
    if not matches:
        raise WorklogsError(
            f"no plan found for name {name!r} under {root}\n"
            f"Create one with: worklogs new {name}--plan",
        )
    if len(matches) > 1:
        listed = "\n".join(f"  {p}" for p in matches)
        raise WorklogsError(
            f"multiple plans found for name {name!r}:\n{listed}\n"
            "Use --scope to narrow the search.",
        )
    return matches[0]


def _create_workset_for_plan(
    *,
    identity: WorklogIdentity,
    config: WorklogConfig,
    plan_path: Path,
    repo_specs: list[str],
) -> None:
    """Call workset.create_workset with a dest mirroring the plan path."""
    _require_workset_package()
    from workset import create_workset

    if config.worksets_root is None:
        LOGGER.warning("--workset given but worksets_root not configured; skipping")
        return

    day_dir = plan_path.parent
    year, month, day = day_dir.parts[-3], day_dir.parts[-2], day_dir.parts[-1]
    dest = config.worksets_root / year / month / day / identity.name
    try:
        result = create_workset(slug=identity.name, repo_specs=repo_specs, dest=dest)
    except Exception as exc:
        raise WorklogsError(str(exc)) from exc
    _print_workset_result(result)


def _print_workset_result(result: object) -> None:
    """Log workset creation summary."""
    LOGGER.info("workset ready: %s", result.path)  # type: ignore[attr-defined]
    for repo in result.repos:  # type: ignore[attr-defined]
        smoke = (
            "✓"
            if repo.smoke_passed is True
            else ("✗" if repo.smoke_passed is False else "~")
        )
        label = f"[{repo.env_backend}]" if repo.env_backend != "none" else "[no env]"
        LOGGER.info("  %s %s  %s  %s", smoke, repo.name, label, repo.branch)
        if not repo.env_ok:
            LOGGER.warning("    %s", repo.env_message)


def _require_workset_package() -> None:
    """Raise a clear error if the direct workset dependency is unavailable."""
    try:
        import workset  # noqa: F401
    except ImportError as exc:
        raise WorklogsError(
            "the workset package is required but could not be imported.\n"
            "Reinstall worklogs so its dependencies are present.",
        ) from exc


def _resolve_identity(args: argparse.Namespace) -> WorklogIdentity:
    """Resolve worklog identity from CLI args."""
    has_explicit = args.name is not None or args.kind is not None
    if args.identity is not None and has_explicit:
        raise WorklogsError("use either NAME--KIND or --name/--kind, not both")
    if args.identity is not None:
        return _parse_identity_token(args.identity)
    if args.name is None or args.kind is None:
        raise WorklogsError("provide NAME--KIND or both --name and --kind")
    return _validate_identity(name=args.name, kind=args.kind)


def _parse_identity_token(token: str) -> WorklogIdentity:
    """Parse a compact NAME--KIND token."""
    parts = token.split("--")
    if len(parts) != 2:
        raise WorklogsError(
            "identity must use exactly NAME--KIND (e.g. api-refactor--plan)",
        )
    name, kind = parts
    return _validate_identity(name=name, kind=kind)


def _validate_identity(*, name: str, kind: str) -> WorklogIdentity:
    """Validate identity fields and return a WorklogIdentity."""
    if kind not in VALID_KINDS:
        valid = ", ".join(sorted(VALID_KINDS))
        raise WorklogsError(f"unknown kind {kind!r}; expected one of: {valid}")
    if not name:
        raise WorklogsError("name cannot be empty")
    if not NAME_PATTERN.fullmatch(name):
        raise WorklogsError(
            "name must start with a lowercase letter or digit and contain only "
            "lowercase letters, digits, dots, underscores, or hyphens",
        )
    return WorklogIdentity(name=name, kind=kind)


def _resolve_config(
    args: argparse.Namespace, environment: Mapping[str, str]
) -> WorklogConfig:
    """Resolve config from args, environment, and config file."""
    file_config = _load_config()
    root_value = _first_string(
        getattr(args, "root", None),
        environment.get("WORKLOG_ROOT"),
        file_config.get("root"),
        "~/worklog",
    )
    scope_value = _first_string(
        getattr(args, "scope", None),
        environment.get("WORKLOG_SCOPE"),
        file_config.get("default_scope"),
    )
    if scope_value is None and args.command not in {"find"}:
        raise WorklogsError(
            "scope is required; set --scope, WORKLOG_SCOPE, or default_scope"
        )
    if scope_value is not None and not NAME_PATTERN.fullmatch(scope_value):
        raise WorklogsError("scope must match the name pattern")

    timezone_value = _first_string(
        getattr(args, "timezone", None),
        environment.get("WORKLOG_TIMEZONE"),
        file_config.get("timezone"),
    )
    worksets_raw = _first_string(
        getattr(args, "worksets_root", None),
        environment.get("WORKLOG_WORKSETS_ROOT"),
        file_config.get("worksets_root"),
    )
    return WorklogConfig(
        root=Path(root_value or "~/worklog").expanduser(),
        scope=scope_value or "",
        timezone=_resolve_timezone(timezone_value),
        worksets_root=Path(worksets_raw).expanduser() if worksets_raw else None,
    )


def _resolve_worksets_root(config: WorklogConfig) -> Path:
    """Resolve worksets_root, raising if not configured."""
    if config.worksets_root is not None:
        return config.worksets_root
    raise WorklogsError(
        "worksets_root is required; set --worksets-root, WORKLOG_WORKSETS_ROOT, "
        "or worksets_root in config",
    )


def _load_config() -> dict[str, str]:
    """Load the worklogs config file."""
    config_path = CONFIG_PATH.expanduser()
    if not config_path.exists():
        return {}
    try:
        with config_path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as error:
        raise WorklogsError(
            f"could not parse config file {config_path}: {error}"
        ) from error
    except OSError as error:
        raise WorklogsError(
            f"could not read config file {config_path}: {error}"
        ) from error

    result: dict[str, str] = {}
    for key in ("root", "default_scope", "timezone", "worksets_root"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise WorklogsError(f"config field {key!r} must be a string")
        result[key] = value
    return result


def _first_string(*values: object) -> str | None:
    """Return the first non-empty string value."""
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _resolve_timezone(timezone_name: str | None) -> tzinfo:
    """Resolve a timezone name to a tzinfo object."""
    if timezone_name is None:
        return datetime.now(UTC).astimezone().tzinfo or UTC
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise WorklogsError(f"unknown timezone {timezone_name!r}") from error


def _build_entries(
    *,
    identity: WorklogIdentity,
    config: WorklogConfig,
    now: datetime,
    project: str,
    links: Sequence[str],
    folders: Sequence[str],
    create_companion: bool,
) -> tuple[WorklogEntry, ...]:
    """Build worklog entries to create."""
    primary_path = _entry_path(identity=identity, config=config, now=now)

    companion_identity = None
    companion_path = None
    if identity.kind == "plan" and create_companion:
        companion_identity = WorklogIdentity(name=identity.name, kind="note")
        companion_path = _entry_path(
            identity=companion_identity, config=config, now=now
        )

    primary_content = _render_content(
        identity=identity,
        created=_format_created(now),
        project=project,
        links=links,
        folders=folders,
        companion_path=companion_path,
        plan_path=None,
    )
    entries = [WorklogEntry(path=primary_path, content=primary_content)]

    if companion_identity is not None and companion_path is not None:
        companion_content = _render_content(
            identity=companion_identity,
            created=_format_created(now),
            project=project,
            links=(),
            folders=(),
            companion_path=None,
            plan_path=primary_path,
        )
        entries.append(WorklogEntry(path=companion_path, content=companion_content))

    return tuple(entries)


def _entry_path(
    *, identity: WorklogIdentity, config: WorklogConfig, now: datetime
) -> Path:
    """Compute the file path for a worklog entry."""
    hour12 = int(now.strftime("%I"))
    period = "a" if now.hour < 12 else "p"
    time_prefix = f"{now:%H%M}-{hour12}{period}"
    day_dir = dated_dir(config.root / config.scope, now)
    return day_dir / f"{time_prefix}--{identity.name}--{identity.kind}.md"


def _render_content(
    *,
    identity: WorklogIdentity,
    created: str,
    project: str,
    links: Sequence[str],
    folders: Sequence[str],
    companion_path: Path | None,
    plan_path: Path | None,
) -> str:
    """Render full markdown content for a worklog entry."""
    frontmatter = _render_frontmatter(
        kind=identity.kind,
        created=created,
        project=project,
        links=links,
        folders=folders,
    )
    if identity.kind == "plan":
        body = _render_plan(companion_path)
    elif identity.kind == "note" and plan_path is not None:
        body = _render_execution_note(identity, plan_path)
    elif identity.kind == "note":
        body = _render_note(identity)
    elif identity.kind == "investigation":
        body = _render_investigation(identity)
    elif identity.kind == "codereview":
        body = _render_codereview(identity)
    else:
        raise WorklogsError(f"cannot render unsupported kind {identity.kind!r}")
    return f"{frontmatter}\n\n{body}\n"


def _render_frontmatter(
    *,
    kind: str,
    created: str,
    project: str,
    links: Sequence[str],
    folders: Sequence[str],
) -> str:
    """Render YAML frontmatter block."""
    lines = ["---", f"kind: {kind}", "status: open", f'created: "{created}"']
    if project:
        lines.append(f"project: {project}")
    lines += [
        "links:",
        *_render_list_items(links),
        "folders:",
        *_render_list_items(folders),
        "---",
    ]
    return "\n".join(lines)


def _render_list_items(values: Sequence[str]) -> list[str]:
    """Render frontmatter list items."""
    if not values:
        return ["  -"]
    return [f"  - {value}" for value in values]


def _render_plan(companion_path: Path | None) -> str:
    """Render plan body."""
    if companion_path is None:
        return """# Core Problem

# Goal

# Non-Goals

# Plan

## Phase 1

## Phase N

# Done Criteria

# Notes"""
    return f"""# Working Rule

As you execute this plan, put running notes, commands, findings, failures,
validation results, PR links, and decisions in the companion note:

`{companion_path}`

Keep this plan for strategy, phase gates, and decisions.

Companion note: [{companion_path.name}]({companion_path.name})

# Core Problem

# Goal

# Non-Goals

# Plan

## Phase 1

## Phase N

# Done Criteria

# Notes"""


def _render_execution_note(identity: WorklogIdentity, plan_path: Path) -> str:
    """Render companion execution note body."""
    return f"""# {identity.name}

Plan: [{plan_path.name}]({plan_path.name})

# Update Discipline

Use this note for running notes, commands, findings, failures, validation
results, PR links, and decisions. Update it before opening a PR.

# Timeline"""


def _render_note(identity: WorklogIdentity) -> str:
    """Render standalone note body."""
    return f"""# {identity.name}

# Notes"""


def _render_investigation(identity: WorklogIdentity) -> str:
    """Render investigation body."""
    return f"""# {identity.name}

# Question

# Findings

# Evidence

# Conclusion"""


def _render_codereview(identity: WorklogIdentity) -> str:
    """Render code review body."""
    return f"""# {identity.name}

# Findings

# Open Questions

# Summary"""


def _format_created(value: datetime) -> str:
    """Format datetime for the created frontmatter field."""
    hour = value.strftime("%I").lstrip("0")
    return (
        f"{value:%a}, {value:%b} {value.day}, {value:%Y}, "
        f"{hour}:{value:%M} {value:%p} {_format_timezone_label(value)}"
    )


def _format_timezone_label(value: datetime) -> str:
    """Return a short display label for the timezone."""
    key = getattr(value.tzinfo, "key", None)
    if isinstance(key, str) and key in GENERIC_TIMEZONE_LABELS:
        return GENERIC_TIMEZONE_LABELS[key]
    return value.tzname() or value.strftime("%z") or "UTC"


def _print_dry_run(entries: Sequence[WorklogEntry]) -> None:
    """Print dry-run summary without writing files."""
    print("Would create:")
    for entry in entries:
        print(entry.path)
    for entry in entries:
        print()
        print(f"--- {entry.path} ---")
        print(entry.content, end="" if entry.content.endswith("\n") else "\n")


def _write_entries(entries: Sequence[WorklogEntry]) -> None:
    """Write worklog entries, refusing to overwrite existing files."""
    existing = [e.path for e in entries if e.path.exists()]
    if existing:
        formatted = "\n".join(str(p) for p in existing)
        raise WorklogsError(
            f"refusing to overwrite existing worklog file(s):\n{formatted}"
        )
    created: list[Path] = []
    try:
        for entry in entries:
            entry.path.parent.mkdir(parents=True, exist_ok=True)
            with entry.path.open("x", encoding="utf-8") as f:
                f.write(entry.content)
            created.append(entry.path)
    except OSError as error:
        for path in created:
            _unlink_created_file(path)
        raise WorklogsError(f"could not write worklog file: {error}") from error


def _unlink_created_file(path: Path) -> None:
    """Attempt to remove a partially-written file, ignoring errors."""
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        LOGGER.warning("could not clean up partial file %s: %s", path, error)
