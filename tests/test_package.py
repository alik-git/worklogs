"""Tests for package import and metadata behavior."""

from __future__ import annotations

import worklogs
from worklogs.cli import main


def test_version_is_exposed() -> None:
    """Verify the package exposes its initial version."""
    assert worklogs.__version__ == "0.1.0"


def test_cli_accepts_no_arguments() -> None:
    """Verify the initial CLI entry point is callable."""
    assert main([]) == 0
