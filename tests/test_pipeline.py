"""Smoke tests for the headless pipeline (no Qt required).

These exercise the deterministic core end-to-end: scan a temp tree, classify,
apply through a real move, and undo it back. They double as living
documentation of the intended behavior while the GUI is built out.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core import file_ops, pattern_matcher
from core.classifier import Classifier
from core.file_ops import resolve_collision
from history.database import HistoryDB
from models import CollisionStrategy, FileEntry, MatchType, Rule
from organizer import Organizer


def _make_files(root: Path) -> None:
    (root / "photo.jpg").write_text("x")
    (root / "notes.txt").write_text("x")
    (root / "Invoice_2026-01-26.pdf").write_text("x")
    (root / "Screenshot_2026-03-11.png").write_text("x")


# -- classification layers ---------------------------------------------------


def test_extension_fallback():
    entry = FileEntry(Path("a/notes.txt"), 1, datetime(2026, 7, 1), "txt")
    result = Classifier().classify(entry, base=Path("out"))
    assert result.destination == Path("out/Documents/notes.txt")
    assert result.rule_name == "extension_fallback"


def test_pattern_layer_invoice_beats_extension():
    entry = FileEntry(
        Path("a/Invoice_2026-01-26.pdf"), 1, datetime(2026, 7, 1), "pdf"
    )
    result = Classifier().classify(entry, base=Path("out"))
    assert result.destination == Path("out/Documents/Invoices/2026/January/Invoice_2026-01-26.pdf")
    assert result.rule_name == "invoice_detection"


def test_custom_rule_beats_pattern_layer():
    rule = Rule(
        rule="my_invoices",
        pattern="*invoice*",
        destination="Custom/{year}",
        match_type=MatchType.FILENAME,
        priority=100,
    )
    entry = FileEntry(
        Path("a/Invoice_2026-01-26.pdf"), 1, datetime(2026, 7, 1), "pdf"
    )
    result = Classifier([rule]).classify(entry, base=Path("out"))
    assert result.destination == Path("out/Custom/2026/Invoice_2026-01-26.pdf")


# -- pattern extraction ------------------------------------------------------


def test_extract_date_and_version():
    assert pattern_matcher.extract_date("Invoice_2026-01-26.pdf").year == 2026
    assert pattern_matcher.extract_version("project_name_v1.2.docx") == (
        "project_name",
        "1.2",
    )


# -- collision handling ------------------------------------------------------


def test_resolve_collision_appends_suffix(tmp_path: Path):
    target = tmp_path / "file.pdf"
    target.write_text("x")
    assert resolve_collision(target, CollisionStrategy.APPEND_SUFFIX) == (
        tmp_path / "file (1).pdf"
    )
    assert resolve_collision(target, CollisionStrategy.SKIP) is None


# -- disk-space preflight ----------------------------------------------------


def test_check_space_ok_for_tiny_folder(tmp_path: Path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    _make_files(folder)
    # Zero margin so the check reflects only the (tiny) copy size vs real disk.
    check = file_ops.check_space(folder, margin=0)
    assert check.ok
    assert check.shortfall == 0


def test_check_space_bails_when_margin_exceeds_free(tmp_path: Path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    _make_files(folder)
    huge = file_ops.free_space(folder) + 1
    check = file_ops.check_space(folder, margin=huge)
    assert not check.ok
    assert check.shortfall > 0


# -- before/after lifecycle --------------------------------------------------


def test_apply_stages_before_and_builds_after(tmp_path: Path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    _make_files(folder)

    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        plan = organizer.build_plan(folder)
        organizer.apply(folder, plan)

    # Original moved into before/ (not left at root); organized copy in after/.
    assert (folder / "before" / "notes.txt").exists()
    assert not (folder / "notes.txt").exists()
    assert (folder / "after" / "Documents" / "notes.txt").exists()
    assert (folder / "after" / "Documents" / "Invoices" / "2026" / "January").exists()


def test_commit_offloads_after_into_root(tmp_path: Path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    _make_files(folder)

    organizer = Organizer()
    plan = organizer.build_plan(folder)
    organizer.apply(folder, plan)
    organizer.commit(folder)

    # before/ and after/ gone; organized structure now at the folder root.
    assert not (folder / "before").exists()
    assert not (folder / "after").exists()
    assert (folder / "Documents" / "notes.txt").exists()
    assert (folder / "Images" / "photo.jpg").exists()


def test_rollback_restores_original(tmp_path: Path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    _make_files(folder)
    before_names = sorted(p.name for p in folder.iterdir())

    organizer = Organizer()
    plan = organizer.build_plan(folder)
    organizer.apply(folder, plan)
    organizer.rollback(folder)

    # Folder back to exactly its pre-apply contents.
    assert not (folder / "before").exists()
    assert not (folder / "after").exists()
    assert sorted(p.name for p in folder.iterdir()) == before_names


def test_dry_run_touches_nothing(tmp_path: Path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    _make_files(folder)

    organizer = Organizer()
    plan = organizer.build_plan(folder)
    organizer.apply(folder, plan, dry_run=True)

    assert (folder / "notes.txt").exists()
    assert not (folder / "before").exists()
    assert not (folder / "after").exists()
