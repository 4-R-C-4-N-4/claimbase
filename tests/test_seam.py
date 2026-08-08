"""Structural tests: the seam holds, or Phase 0's pass was partly illusory.

These are cheap and they fail loudly, which is the point. Phase 0 grew from three
adapters to five, each for a good reason, and the only thing keeping that from
becoming five special cases in core is a test that says so.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "claimbase"
CORE = SRC / "core"

# Vocabulary that belongs to one source and must never appear in core. If a term
# here shows up in core, an adapter's shape has leaked through the seam.
SOURCE_SPECIFIC = [
    "staged_tag",
    "auto_promote",
    "report.txt",
    "report_human",
    "cells.csv",
    "taxonomy.toml",
    ".todo",
    "analysis[]",
    "supersede_pending",
    "guru-review",
    "MEMORY.md",
    "mergedAt",
    "gh pr",
]


def core_modules() -> list[Path]:
    return sorted(CORE.rglob("*.py"))


def test_core_exists() -> None:
    assert core_modules(), "no core modules found — check the layout"


@pytest.mark.parametrize("path", core_modules(), ids=lambda p: p.name)
def test_core_does_not_import_sources(path: Path) -> None:
    """core must not depend on any adapter, directly or transitively."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        for m in mods:
            assert "sources" not in m.split("."), (
                f"{path.name} imports {m!r}. Core may not know an adapter exists — "
                f"if core needs something an adapter has, generalise the field."
            )


@pytest.mark.parametrize("path", core_modules(), ids=lambda p: p.name)
def test_core_names_no_source_vocabulary(path: Path) -> None:
    """Comments and docstrings may *cite* a source as a worked example; code may not
    branch on one. Checks executable text only, with strings and comments stripped."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue  # docstrings and literals are prose, not dispatch
        for attr in ("id", "attr", "name", "arg"):
            ident = getattr(node, attr, None)
            if not isinstance(ident, str):
                continue
            low = ident.lower()
            for term in SOURCE_SPECIFIC:
                assert term.lower().strip(".[]") not in low or len(term) < 5, (
                    f"{path.name} names {ident!r}, which is {term!r} vocabulary. "
                    f"Source shape has leaked into core."
                )


def test_no_adapter_specific_field_on_models() -> None:
    """The model vocabulary is the seam. A field named after one source is the
    single most likely way this design rots."""
    from claimbase.core import models

    for cls in (models.Event, models.Claim, models.Mention, models.Edge):
        for f in cls.__dataclass_fields__:
            for term in SOURCE_SPECIFIC:
                assert term.lower().strip(".[]") not in f.lower(), (
                    f"{cls.__name__}.{f} is named after a source"
                )
