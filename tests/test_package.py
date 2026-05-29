"""Tests for package import, metadata, and CLI behavior."""

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
    _parse_identity_token,
    _write_entries,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_version_is_exposed() -> None:
    """Verify the package exposes its current version."""
    assert worklogs.__version__ == "0.2.0"


def test_cli_accepts_no_arguments() -> None:
    """Verify the CLI entry point remains callable without a subcommand."""
    assert main([]) == 0


def test_parse_identity_token_accepts_fast_form() -> None:
    """Verify the compact worklog identity token is parsed correctly."""
    assert _parse_identity_token("plan--backend-api--improve-deploy-notes") == (
        WorklogIdentity(
            kind="plan",
            project="backend-api",
            slug="improve-deploy-notes",
        )
    )


def test_parse_identity_token_rejects_extra_delimiters() -> None:
    """Verify the compact token grammar rejects ambiguous identities."""
    with pytest.raises(WorklogsError, match="exactly KIND--PROJECT--SLUG"):
        _parse_identity_token("plan--backend-api--deploy--notes")


def test_build_entries_renders_plan_and_companion_paths(tmp_path: Path) -> None:
    """Verify plan creation renders deterministic paths and reciprocal links."""
    timezone = ZoneInfo("America/Toronto")
    config = WorklogConfig(
        root=tmp_path / "worklog",
        scope="work",
        timezone=timezone,
    )
    now = datetime(2026, 5, 29, 0, 47, tzinfo=timezone)

    entries = _build_entries(
        identity=WorklogIdentity(
            kind="plan",
            project="backend-api",
            slug="improve-deploy-notes",
        ),
        config=config,
        now=now,
        links=("https://example.com/context",),
        folders=("docs",),
        create_companion=True,
    )

    assert [entry.path for entry in entries] == [
        tmp_path
        / "worklog"
        / "work"
        / "2026"
        / "05"
        / "29"
        / "0047--plan--backend-api--improve-deploy-notes.md",
        tmp_path
        / "worklog"
        / "work"
        / "2026"
        / "05"
        / "29"
        / "0047--note--backend-api--improve-deploy-notes-execution-log.md",
    ]
    assert 'created: "Fri, May 29, 2026, 12:47 AM ET"' in entries[0].content
    assert "\n# Working Rule\n" in entries[0].content
    assert "0047--note--backend-api--improve-deploy-notes-execution-log.md" in (
        entries[0].content
    )
    assert "Plan: [0047--plan--backend-api--improve-deploy-notes.md]" in (
        entries[1].content
    )


def test_new_plan_uses_config_default_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify config defaults make the fast command work without --scope."""
    root = tmp_path / "worklog"
    _write_config(tmp_path, monkeypatch, root=root, default_scope="work")

    assert main(["new", "plan--backend-api--improve-deploy-notes", "--print-path"]) == 0

    created_files = sorted((root / "work").glob("*/*/*/*.md"))
    assert len(created_files) == 2
    created_names = {path.name for path in created_files}
    assert created_names == {
        f"{created_files[0].name[:4]}--plan--backend-api--improve-deploy-notes.md",
        (
            f"{created_files[0].name[:4]}--note--backend-api--"
            "improve-deploy-notes-execution-log.md"
        ),
    }
    output = capsys.readouterr().out
    assert str(root / "work") in output


def test_scope_flag_overrides_config_default_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --scope overrides config default_scope."""
    root = tmp_path / "worklog"
    _write_config(tmp_path, monkeypatch, root=root, default_scope="work")

    assert (
        main(
            [
                "new",
                "note--personal-site--theme-ideas",
                "--scope",
                "personal",
                "--print-path",
            ]
        )
        == 0
    )

    assert list((root / "work").glob("*/*/*/*.md")) == []
    created_files = list((root / "personal").glob("*/*/*/*.md"))
    assert len(created_files) == 1
    assert created_files[0].name.endswith("--note--personal-site--theme-ideas.md")


def test_note_creates_single_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify note creation does not create a companion file."""
    _isolate_home(tmp_path, monkeypatch)
    root = tmp_path / "worklog"

    assert (
        main(
            [
                "new",
                "note--personal-site--theme-ideas",
                "--root",
                str(root),
                "--scope",
                "personal",
            ]
        )
        == 0
    )

    created_files = list((root / "personal").glob("*/*/*/*.md"))
    assert len(created_files) == 1
    assert created_files[0].name.endswith("--note--personal-site--theme-ideas.md")


def test_dry_run_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify dry-run prints rendered files without creating paths."""
    _isolate_home(tmp_path, monkeypatch)
    root = tmp_path / "worklog"

    assert (
        main(
            [
                "new",
                "plan--backend-api--improve-deploy-notes",
                "--root",
                str(root),
                "--scope",
                "work",
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Would create:" in output
    assert "plan--backend-api--improve-deploy-notes.md" in output
    assert "note--backend-api--improve-deploy-notes-execution-log.md" in output
    assert not root.exists()


def test_scope_is_required_without_config_or_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify missing scope fails instead of guessing a package default."""
    _isolate_home(tmp_path, monkeypatch)

    assert (
        main(
            [
                "new",
                "note--backend-api--deploy-notes",
                "--root",
                str(tmp_path / "worklog"),
            ]
        )
        == 2
    )
    assert "scope is required" in capsys.readouterr().err


def test_write_entries_refuses_to_overwrite(tmp_path: Path) -> None:
    """Verify file writing refuses duplicate target paths."""
    target = tmp_path / "worklog.md"

    _write_entries((WorklogEntry(path=target, content="first\n"),))

    with pytest.raises(WorklogsError, match="refusing to overwrite"):
        _write_entries((WorklogEntry(path=target, content="second\n"),))
    assert target.read_text(encoding="utf-8") == "first\n"


def _write_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path,
    default_scope: str,
) -> None:
    home = _isolate_home(tmp_path, monkeypatch)
    config_path = home / ".config" / "worklogs" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f'root = "{root}"\n'
        f'default_scope = "{default_scope}"\n'
        'timezone = "America/Toronto"\n',
        encoding="utf-8",
    )


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("WORKLOG_ROOT", raising=False)
    monkeypatch.delenv("WORKLOG_SCOPE", raising=False)
    monkeypatch.delenv("WORKLOG_TIMEZONE", raising=False)
    return home
