"""Command-line entry point for worklogs."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from worklogs import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worklogs command-line interface."""
    build_parser().parse_args(argv)
    return 0
