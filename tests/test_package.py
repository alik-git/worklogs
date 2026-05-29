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
    WorksetConfig,
    _build_entries,
    _build_workset_path,
    _parse_identity_token,
    _parse_workset_path,
    _write_entries,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_version_is_exposed() -> None:
    """Verify the package exposes its current version."""
    assert worklogs.__version__ == "0.2.1"


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


def test_workset_new_uses_config_root_and_explicit_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify workset creation uses the configured root and dated layout."""
    worksets_root = tmp_path / "Projects" / "worksets"
    _write_config(
        tmp_path,
        monkeypatch,
        root=tmp_path / "worklog",
        default_scope="work",
        worksets_root=worksets_root,
    )

    assert (
        main(
            [
                "workset",
                "new",
                "release-tools/worklogs-0.2.1",
                "--date",
                "2026-05-29",
            ]
        )
        == 0
    )

    created_path = (
        worksets_root / "2026" / "05" / "29" / "release-tools" / "worklogs-0.2.1"
    )
    assert created_path.is_dir()
    assert f"Created workset directory: {created_path}" in capsys.readouterr().out


def test_workset_new_dry_run_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify workset dry-run prints the intended path without writing."""
    _isolate_home(tmp_path, monkeypatch)
    worksets_root = tmp_path / "worksets"

    assert (
        main(
            [
                "workset",
                "new",
                "release-tools/python-packaging/worklogs-0.2.1",
                "--worksets-root",
                str(worksets_root),
                "--date",
                "2026-05-29",
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Would create workset:" in output
    assert (
        str(
            worksets_root
            / "2026"
            / "05"
            / "29"
            / "release-tools"
            / "python-packaging"
            / "worklogs-0.2.1"
        )
        in output
    )
    assert not worksets_root.exists()


def test_workset_new_print_path_is_script_friendly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify --print-path prints only the created workset path."""
    _isolate_home(tmp_path, monkeypatch)
    worksets_root = tmp_path / "worksets"

    assert (
        main(
            [
                "workset",
                "new",
                "worklogs-0.2.1",
                "--worksets-root",
                str(worksets_root),
                "--date",
                "2026-05-29",
                "--print-path",
            ]
        )
        == 0
    )

    expected_path = worksets_root / "2026" / "05" / "29" / "worklogs-0.2.1"
    assert capsys.readouterr().out == f"{expected_path}\n"
    assert expected_path.is_dir()


def test_workset_new_refuses_existing_non_empty_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify workset creation refuses to reuse non-empty directories."""
    _isolate_home(tmp_path, monkeypatch)
    worksets_root = tmp_path / "worksets"
    existing_path = worksets_root / "2026" / "05" / "29" / "worklogs-0.2.1"
    existing_path.mkdir(parents=True)
    (existing_path / "README.md").write_text("existing\n", encoding="utf-8")

    assert (
        main(
            [
                "workset",
                "new",
                "worklogs-0.2.1",
                "--worksets-root",
                str(worksets_root),
                "--date",
                "2026-05-29",
            ]
        )
        == 2
    )
    assert "existing non-empty workset directory" in capsys.readouterr().err


def test_workset_new_requires_configured_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify workset creation does not guess a local machine default."""
    _isolate_home(tmp_path, monkeypatch)

    assert main(["workset", "new", "worklogs-0.2.1", "--date", "2026-05-29"]) == 2
    assert "worksets root is required" in capsys.readouterr().err


def test_parse_workset_path_rejects_unsafe_components() -> None:
    """Verify workset path parsing rejects absolute or escaping paths."""
    for value in (
        "/absolute/workset",
        "release-tools/../workset",
        "release-tools//workset",
    ):
        with pytest.raises(WorklogsError):
            _parse_workset_path(value)


def test_build_workset_path_renders_date_folders(tmp_path: Path) -> None:
    """Verify workset paths include YYYY/MM/DD before organizer folders."""
    workset_path = _build_workset_path(
        config=WorksetConfig(root=tmp_path / "worksets", timezone=ZoneInfo("UTC")),
        workset_date=datetime(2026, 5, 29, tzinfo=ZoneInfo("UTC")).date(),
        path_parts=("release-tools", "worklogs-0.2.1"),
    )

    assert (
        workset_path
        == tmp_path
        / "worksets"
        / "2026"
        / "05"
        / "29"
        / "release-tools"
        / "worklogs-0.2.1"
    )


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
    monkeypatch.delenv("WORKLOG_ROOT", raising=False)
    monkeypatch.delenv("WORKLOG_SCOPE", raising=False)
    monkeypatch.delenv("WORKLOG_TIMEZONE", raising=False)
    monkeypatch.delenv("WORKLOG_WORKSETS_ROOT", raising=False)
    return home
