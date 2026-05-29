"""Command-line entry point for worklogs."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from worklogs import __version__

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

VALID_KINDS = frozenset({"plan", "note", "investigation", "codereview"})
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
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

    kind: str
    project: str
    slug: str


@dataclass(frozen=True)
class WorklogConfig:
    """Resolved user defaults for worklog creation."""

    root: Path
    scope: str
    timezone: tzinfo


@dataclass(frozen=True)
class WorklogEntry:
    """A worklog file that should be created."""

    path: Path
    content: str


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="worklogs",
        description="Create and maintain local worklog files.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")
    new_parser = subparsers.add_parser(
        "new",
        help="create a dated markdown worklog file",
        description="Create a dated markdown worklog file.",
    )
    new_parser.add_argument(
        "identity",
        nargs="?",
        metavar="KIND--PROJECT--SLUG",
        help="compact identity token, for example plan--backend-api--deploy-notes",
    )
    new_parser.add_argument("--root", metavar="PATH", help="worklog root directory")
    new_parser.add_argument("--scope", metavar="NAME", help="worklog scope")
    new_parser.add_argument("--timezone", metavar="ZONE", help="IANA timezone name")
    new_parser.add_argument("--kind", choices=sorted(VALID_KINDS), help="worklog kind")
    new_parser.add_argument("--project", help="project slug")
    new_parser.add_argument("--slug", help="work item slug")
    new_parser.add_argument(
        "--link",
        action="append",
        default=[],
        metavar="VALUE",
        help="frontmatter link; repeat for multiple links",
    )
    new_parser.add_argument(
        "--folder",
        action="append",
        default=[],
        metavar="PATH",
        help="frontmatter folder; repeat for multiple folders",
    )
    new_parser.add_argument(
        "--no-companion",
        action="store_true",
        help="for plan files, skip the companion execution note",
    )
    new_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print target paths and rendered bodies without writing files",
    )
    new_parser.add_argument(
        "--print-path",
        action="store_true",
        help="print created path or paths",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worklogs command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "new":
            return _run_new(args)
    except WorklogsError as error:
        print(f"worklogs: error: {error}", file=sys.stderr)
        return 2

    print(f"worklogs: error: unknown command: {args.command}", file=sys.stderr)
    return 2


def _run_new(args: argparse.Namespace) -> int:
    identity = _resolve_identity(args)
    config = _resolve_config(args, os.environ)
    if args.no_companion and identity.kind != "plan":
        msg = "--no-companion only applies to plan worklogs"
        raise WorklogsError(msg)

    now = datetime.now(UTC).astimezone(config.timezone)
    entries = _build_entries(
        identity=identity,
        config=config,
        now=now,
        links=tuple(args.link),
        folders=tuple(args.folder),
        create_companion=not args.no_companion,
    )

    if args.dry_run:
        _print_dry_run(entries)
        return 0

    _write_entries(entries)
    if args.print_path:
        for entry in entries:
            print(entry.path)
    else:
        noun = "file" if len(entries) == 1 else "files"
        print(f"Created {len(entries)} worklog {noun}.")
    return 0


def _resolve_identity(args: argparse.Namespace) -> WorklogIdentity:
    explicit_fields = (args.kind, args.project, args.slug)
    has_explicit_fields = any(value is not None for value in explicit_fields)

    if args.identity is not None and has_explicit_fields:
        msg = "use either KIND--PROJECT--SLUG or --kind/--project/--slug, not both"
        raise WorklogsError(msg)

    if args.identity is not None:
        return _parse_identity_token(args.identity)

    if not all(explicit_fields):
        msg = "provide KIND--PROJECT--SLUG or all of --kind, --project, and --slug"
        raise WorklogsError(msg)

    return _validate_identity(
        kind=str(args.kind),
        project=str(args.project),
        slug=str(args.slug),
    )


def _parse_identity_token(token: str) -> WorklogIdentity:
    parts = token.split("--")
    if len(parts) != 3:
        msg = "identity must use exactly KIND--PROJECT--SLUG"
        raise WorklogsError(msg)
    kind, project, slug = parts
    return _validate_identity(kind=kind, project=project, slug=slug)


def _validate_identity(*, kind: str, project: str, slug: str) -> WorklogIdentity:
    if kind not in VALID_KINDS:
        valid = ", ".join(sorted(VALID_KINDS))
        msg = f"unknown kind {kind!r}; expected one of: {valid}"
        raise WorklogsError(msg)
    for field_name, value in (("project", project), ("slug", slug)):
        if not value:
            msg = f"{field_name} cannot be empty"
            raise WorklogsError(msg)
        if not SLUG_PATTERN.fullmatch(value):
            msg = (
                f"{field_name} must start with a lowercase letter or digit and "
                "contain only lowercase letters, digits, dots, underscores, or hyphens"
            )
            raise WorklogsError(msg)
    return WorklogIdentity(kind=kind, project=project, slug=slug)


def _resolve_config(
    args: argparse.Namespace,
    environment: Mapping[str, str],
) -> WorklogConfig:
    file_config = _load_config()

    root_value = _first_string(
        args.root,
        environment.get("WORKLOG_ROOT"),
        file_config.get("root"),
        "~/worklog",
    )
    if root_value is None:
        msg = "root is required"
        raise WorklogsError(msg)
    scope_value = _first_string(
        args.scope,
        environment.get("WORKLOG_SCOPE"),
        file_config.get("default_scope"),
    )
    if scope_value is None:
        msg = "scope is required; set --scope, WORKLOG_SCOPE, or default_scope"
        raise WorklogsError(msg)
    if not SLUG_PATTERN.fullmatch(scope_value):
        msg = (
            "scope must start with a lowercase letter or digit and contain only "
            "lowercase letters, digits, dots, underscores, or hyphens"
        )
        raise WorklogsError(msg)

    timezone_value = _first_string(
        args.timezone,
        environment.get("WORKLOG_TIMEZONE"),
        file_config.get("timezone"),
    )
    return WorklogConfig(
        root=Path(root_value).expanduser(),
        scope=scope_value,
        timezone=_resolve_timezone(timezone_value),
    )


def _load_config() -> dict[str, str]:
    config_path = CONFIG_PATH.expanduser()
    if not config_path.exists():
        return {}

    try:
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as error:
        msg = f"could not parse config file {config_path}: {error}"
        raise WorklogsError(msg) from error
    except OSError as error:
        msg = f"could not read config file {config_path}: {error}"
        raise WorklogsError(msg) from error

    config: dict[str, str] = {}
    for key in ("root", "default_scope", "timezone"):
        value = raw_config.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            msg = f"config field {key!r} must be a string"
            raise WorklogsError(msg)
        config[key] = value
    return config


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _resolve_timezone(timezone_name: str | None) -> tzinfo:
    if timezone_name is None:
        return datetime.now(UTC).astimezone().tzinfo or UTC
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        msg = f"unknown timezone {timezone_name!r}"
        raise WorklogsError(msg) from error


def _build_entries(
    *,
    identity: WorklogIdentity,
    config: WorklogConfig,
    now: datetime,
    links: Sequence[str],
    folders: Sequence[str],
    create_companion: bool,
) -> tuple[WorklogEntry, ...]:
    plan_companion = None
    if identity.kind == "plan" and create_companion:
        plan_companion = WorklogIdentity(
            kind="note",
            project=identity.project,
            slug=f"{identity.slug}-execution-log",
        )

    primary_path = _entry_path(identity=identity, config=config, now=now)
    companion_path = (
        _entry_path(identity=plan_companion, config=config, now=now)
        if plan_companion is not None
        else None
    )

    primary_content = _render_content(
        identity=identity,
        created=_format_created(now),
        links=links,
        folders=folders,
        own_path=primary_path,
        companion_path=companion_path,
        plan_path=None,
    )
    entries = [WorklogEntry(path=primary_path, content=primary_content)]

    if plan_companion is not None and companion_path is not None:
        companion_content = _render_content(
            identity=plan_companion,
            created=_format_created(now),
            links=(),
            folders=(),
            own_path=companion_path,
            companion_path=None,
            plan_path=primary_path,
        )
        entries.append(WorklogEntry(path=companion_path, content=companion_content))

    return tuple(entries)


def _entry_path(
    *,
    identity: WorklogIdentity,
    config: WorklogConfig,
    now: datetime,
) -> Path:
    return (
        config.root
        / config.scope
        / f"{now:%Y}"
        / f"{now:%m}"
        / f"{now:%d}"
        / f"{now:%H%M}--{identity.kind}--{identity.project}--{identity.slug}.md"
    )


def _render_content(
    *,
    identity: WorklogIdentity,
    created: str,
    links: Sequence[str],
    folders: Sequence[str],
    own_path: Path,
    companion_path: Path | None,
    plan_path: Path | None,
) -> str:
    frontmatter = _render_frontmatter(
        kind=identity.kind,
        created=created,
        project=identity.project,
        links=links,
        folders=folders,
    )
    if identity.kind == "plan":
        if companion_path is None:
            body = _render_plan_without_companion()
        else:
            body = _render_plan_with_companion(own_path, companion_path)
    elif identity.kind == "note" and plan_path is not None:
        body = _render_execution_note(identity, plan_path)
    elif identity.kind == "note":
        body = _render_note(identity)
    elif identity.kind == "investigation":
        body = _render_investigation(identity)
    elif identity.kind == "codereview":
        body = _render_codereview(identity)
    else:
        msg = f"cannot render unsupported kind {identity.kind!r}"
        raise WorklogsError(msg)
    return f"{frontmatter}\n\n{body}\n"


def _render_frontmatter(
    *,
    kind: str,
    created: str,
    project: str,
    links: Sequence[str],
    folders: Sequence[str],
) -> str:
    lines = [
        "---",
        f"kind: {kind}",
        "status: open",
        f'created: "{created}"',
        f"project: {project}",
        "links:",
        *_render_list_items(links),
        "folders:",
        *_render_list_items(folders),
        "---",
    ]
    return "\n".join(lines)


def _render_list_items(values: Sequence[str]) -> list[str]:
    if not values:
        return ["  -"]
    return [f"  - {value}" for value in values]


def _render_plan_with_companion(own_path: Path, companion_path: Path) -> str:
    plan_folder = own_path.with_suffix("")
    folder_plan_path = plan_folder / own_path.name
    return f"""# Working Rule

As you execute this plan, put running notes, commands, findings, failures,
validation results, PR links, and decisions in the companion note:

`{companion_path}`

Keep this plan for strategy, phase gates, decisions, and final status.

If the work produces bulky artifacts, convert the plan file into a same-named
folder and keep the markdown plan inside it. Put bulky output under clearly
named subfolders.

For example, this file can become:

```text
{plan_folder}/
|-- {folder_plan_path.name}
`-- artifacts/
    `-- <clear-artifact-name>
```

The companion note remains the running execution log. The plan folder is only
for artifacts that should stay next to the plan.

Companion note: [{companion_path.name}]({companion_path.name})

# Core Problem

# Goal

# Non-Goals

# Plan

## Phase 1

## Phase 2

## Phase N

# Done Criteria

# Notes"""


def _render_plan_without_companion() -> str:
    return """# Core Problem

# Goal

# Non-Goals

# Plan

## Phase 1

## Phase 2

## Phase N

# Done Criteria

# Notes"""


def _render_execution_note(identity: WorklogIdentity, plan_path: Path) -> str:
    return f"""# {identity.project}: {identity.slug}

Plan: [{plan_path.name}]({plan_path.name})

# Update Discipline

Use this note for running notes, commands, findings, failures, validation
results, PR links, and decisions while executing the plan.

# Timeline"""


def _render_note(identity: WorklogIdentity) -> str:
    return f"""# {identity.project}: {identity.slug}

# Notes"""


def _render_investigation(identity: WorklogIdentity) -> str:
    return f"""# {identity.project}: {identity.slug}

# Question

# Findings

# Evidence

# Conclusion"""


def _render_codereview(identity: WorklogIdentity) -> str:
    return f"""# {identity.project}: {identity.slug}

# Findings

# Open Questions

# Summary"""


def _format_created(value: datetime) -> str:
    hour = value.strftime("%I").lstrip("0")
    return (
        f"{value:%a}, {value:%b} {value.day}, {value:%Y}, "
        f"{hour}:{value:%M} {value:%p} {_format_timezone_label(value)}"
    )


def _format_timezone_label(value: datetime) -> str:
    key = getattr(value.tzinfo, "key", None)
    if isinstance(key, str) and key in GENERIC_TIMEZONE_LABELS:
        return GENERIC_TIMEZONE_LABELS[key]
    return value.tzname() or value.strftime("%z") or "UTC"


def _print_dry_run(entries: Sequence[WorklogEntry]) -> None:
    print("Would create:")
    for entry in entries:
        print(entry.path)
    for entry in entries:
        print()
        print(f"--- {entry.path} ---")
        print(entry.content, end="" if entry.content.endswith("\n") else "\n")


def _write_entries(entries: Sequence[WorklogEntry]) -> None:
    existing_paths = [entry.path for entry in entries if entry.path.exists()]
    if existing_paths:
        formatted_paths = "\n".join(str(path) for path in existing_paths)
        msg = f"refusing to overwrite existing worklog file(s):\n{formatted_paths}"
        raise WorklogsError(msg)

    created_paths: list[Path] = []
    try:
        for entry in entries:
            entry.path.parent.mkdir(parents=True, exist_ok=True)
            with entry.path.open("x", encoding="utf-8") as worklog_file:
                worklog_file.write(entry.content)
            created_paths.append(entry.path)
    except OSError as error:
        for path in created_paths:
            _unlink_created_file(path)
        msg = f"could not write worklog file: {error}"
        raise WorklogsError(msg) from error


def _unlink_created_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        print(
            f"worklogs: warning: could not clean up partial file {path}: {error}",
            file=sys.stderr,
        )
