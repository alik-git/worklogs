"""Tests for worklogs CLI — HHMM--name--kind.md format."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

import worklogs
from worklogs.cli import (
    WorklogConfig,
    WorklogEntry,
    WorklogIdentity,
    WorklogsError,
    _build_entries,
    _entry_path,
    _find_plan_by_name,
    _parse_identity_token,
    _write_entries,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_version_is_exposed() -> None:
    """Package exposes its current version."""
    assert worklogs.__version__ == "0.3.2"


def test_cli_accepts_no_arguments() -> None:
    """CLI is callable without a subcommand."""
    assert main([]) == 0


def test_parse_identity_token_name_kind() -> None:
    """Parse compact NAME--KIND token."""
    assert _parse_identity_token("leansim2sim--plan") == WorklogIdentity(
        name="leansim2sim",
        kind="plan",
    )


def test_parse_identity_token_rejects_three_parts() -> None:
    """Reject tokens that are not exactly NAME--KIND."""
    with pytest.raises(WorklogsError, match="exactly NAME--KIND"):
        _parse_identity_token("plan--project--slug")


def test_parse_identity_token_rejects_unknown_kind() -> None:
    """Reject unrecognised kind values."""
    with pytest.raises(WorklogsError, match="unknown kind"):
        _parse_identity_token("my-task--sprint")


def test_entry_path_format(tmp_path: Path) -> None:
    """Path uses HHMM--name--kind.md format."""
    tz = ZoneInfo("America/Toronto")
    config = WorklogConfig(
        root=tmp_path / "worklog",
        scope="work",
        timezone=tz,
        worksets_root=None,
    )
    now = datetime(2026, 6, 12, 14, 21, tzinfo=tz)

    path = _entry_path(
        identity=WorklogIdentity(name="leansim2sim", kind="plan"),
        config=config,
        now=now,
    )

    assert path == (
        tmp_path
        / "worklog"
        / "work"
        / "2026"
        / "06"
        / "12"
        / "1421--leansim2sim--plan.md"
    )


def test_plan_creates_companion_with_same_name(tmp_path: Path) -> None:
    """Plan creates two files: name--plan.md and name--note.md."""
    tz = ZoneInfo("America/Toronto")
    config = WorklogConfig(
        root=tmp_path / "worklog",
        scope="work",
        timezone=tz,
        worksets_root=None,
    )
    now = datetime(2026, 6, 12, 14, 21, tzinfo=tz)

    entries = _build_entries(
        identity=WorklogIdentity(name="leansim2sim", kind="plan"),
        config=config,
        now=now,
        project="minerva-sim2sim",
        links=(),
        folders=(),
        create_companion=True,
    )

    assert len(entries) == 2
    assert entries[0].path.name == "1421--leansim2sim--plan.md"
    assert entries[1].path.name == "1421--leansim2sim--note.md"
    assert "leansim2sim--note.md" in entries[0].content
    assert "leansim2sim--plan.md" in entries[1].content


def test_note_creates_single_file(tmp_path: Path) -> None:
    """Note creates a single file with no companion."""
    tz = ZoneInfo("UTC")
    config = WorklogConfig(
        root=tmp_path / "worklog",
        scope="personal",
        timezone=tz,
        worksets_root=None,
    )
    now = datetime(2026, 6, 12, 10, 0, tzinfo=tz)

    entries = _build_entries(
        identity=WorklogIdentity(name="quick-observation", kind="note"),
        config=config,
        now=now,
        project="",
        links=(),
        folders=(),
        create_companion=True,
    )

    assert len(entries) == 1
    assert entries[0].path.name == "1000--quick-observation--note.md"


def test_new_creates_new_format_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worklogs new`` creates HHMM--name--kind.md files."""
    root = tmp_path / "worklog"
    _write_config(tmp_path, monkeypatch, root=root, default_scope="work")

    assert main(["new", "leansim2sim--plan"]) == 0

    created = sorted((root / "work").glob("*/*/*/*.md"))
    assert len(created) == 2
    names = {p.name[6:] for p in created}  # strip HHMM-- prefix
    assert names == {"leansim2sim--plan.md", "leansim2sim--note.md"}


def test_new_note_is_single_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worklogs new`` for a note creates one file."""
    root = tmp_path / "worklog"
    _write_config(tmp_path, monkeypatch, root=root, default_scope="personal")

    assert main(["new", "my-observation--note"]) == 0

    created = list((root / "personal").glob("*/*/*/*.md"))
    assert len(created) == 1
    assert created[0].name.endswith("--my-observation--note.md")


def test_new_rejects_bad_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Three-part token is rejected with clear error."""
    _isolate_home(tmp_path, monkeypatch)
    assert (
        main(["new", "plan--project--slug", "--root", str(tmp_path), "--scope", "w"])
        == 2
    )
    assert "exactly NAME--KIND" in capsys.readouterr().err


def test_scope_is_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing scope fails with clear error."""
    _isolate_home(tmp_path, monkeypatch)
    assert main(["new", "task--plan", "--root", str(tmp_path)]) == 2
    assert "scope is required" in capsys.readouterr().err


def test_dry_run_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run prints paths without writing files."""
    _isolate_home(tmp_path, monkeypatch)
    root = tmp_path / "worklog"

    assert (
        main(
            [
                "new",
                "leansim2sim--plan",
                "--root",
                str(root),
                "--scope",
                "w",
                "--dry-run",
            ]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "leansim2sim--plan.md" in out
    assert "leansim2sim--note.md" in out
    assert not root.exists()


def test_find_plan_by_name_finds_match(tmp_path: Path) -> None:
    """Return the matching plan path."""
    plan = tmp_path / "work" / "2026" / "06" / "12" / "1421--leansim2sim--plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("", encoding="utf-8")

    assert _find_plan_by_name("leansim2sim", tmp_path) == plan


def test_find_plan_by_name_raises_on_zero(tmp_path: Path) -> None:
    """Raise clearly when no plan matches."""
    with pytest.raises(WorklogsError, match="no plan found"):
        _find_plan_by_name("nonexistent", tmp_path)


def test_find_plan_by_name_raises_on_multiple(tmp_path: Path) -> None:
    """Raise with list when multiple plans match."""
    for scope in ("work", "personal"):
        plan = tmp_path / scope / "2026" / "06" / "12" / "1421--leansim2sim--plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("", encoding="utf-8")

    with pytest.raises(WorklogsError, match="multiple plans found"):
        _find_plan_by_name("leansim2sim", tmp_path)


def test_write_entries_refuses_overwrite(tmp_path: Path) -> None:
    """Writing refuses to overwrite existing files."""
    target = tmp_path / "entry.md"
    _write_entries((WorklogEntry(path=target, content="first\n"),))
    with pytest.raises(WorklogsError, match="refusing to overwrite"):
        _write_entries((WorklogEntry(path=target, content="second\n"),))
    assert target.read_text(encoding="utf-8") == "first\n"


def test_no_companion_rejected_for_non_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-companion on a non-plan is an error."""
    _isolate_home(tmp_path, monkeypatch)
    assert (
        main(
            [
                "new",
                "my-obs--note",
                "--root",
                str(tmp_path),
                "--scope",
                "w",
                "--no-companion",
            ]
        )
        == 2
    )
    assert "no-companion" in capsys.readouterr().err


def _write_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path,
    default_scope: str,
    worksets_root: Path | None = None,
) -> None:
    home = _isolate_home(tmp_path, monkeypatch)
    config_path = home / ".config" / "worklogs" / "config.toml"
    config_path.parent.mkdir(parents=True)
    lines = [
        f'root = "{root}"',
        f'default_scope = "{default_scope}"',
        'timezone = "America/Toronto"',
    ]
    if worksets_root is not None:
        lines.append(f'worksets_root = "{worksets_root}"')
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for var in (
        "WORKLOG_ROOT",
        "WORKLOG_SCOPE",
        "WORKLOG_TIMEZONE",
        "WORKLOG_WORKSETS_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)
    return home
