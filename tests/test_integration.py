"""End-to-end integration tests over a realistic folder (no Qt required).

Where ``test_pipeline.py`` checks each stage in isolation, this module drives
one plausible user folder — nested subdirectories, mixed file types, and a
filename collision — through the whole lifecycle:

    check_space -> build_plan -> apply -> [review before/ vs after/] -> commit
                                                                    \\-> rollback

The assertions are about *content*, not just paths: a copy that lands in the
right place with the wrong bytes is the failure worth catching. Every file gets
unique text so a mix-up is visible, and each run is checked for conservation —
no file silently lost or duplicated between the folder going in and coming out.
"""

from __future__ import annotations

from pathlib import Path

from history.database import HistoryDB
from models import BatchStatus, OperationType, RuleLayer
from organizer import Organizer

# A "Downloads"-shaped folder: loose files at the root, a couple of nested
# subdirectories, and two different notes.txt that classify to the same
# destination -- forcing the append-suffix collision path.
SAMPLE_FILES = {
    "notes.txt": "root notes",
    "photo.jpg": "root photo bytes",
    "Invoice_2026-01-26.pdf": "january invoice",
    "Screenshot_2026-03-11.png": "screenshot bytes",
    "work/report_v1.2.docx": "quarterly report",
    "work/Invoice_2026-02-14.pdf": "february invoice",
    "archive/old/notes.txt": "archived notes",  # collides with root notes.txt
}


def _build_sample_folder(root: Path) -> Path:
    """Materialize :data:`SAMPLE_FILES` under ``root/Downloads``."""
    folder = root / "Downloads"
    for rel, content in SAMPLE_FILES.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return folder


def _files_under(root: Path) -> list[Path]:
    """Every file (not directory) under ``root``."""
    return [p for p in root.rglob("*") if p.is_file()]


def _contents_under(root: Path) -> list[str]:
    """The text of every file under ``root``, sorted -- for conservation checks."""
    return sorted(p.read_text() for p in _files_under(root))


# -- apply -> commit ---------------------------------------------------------


def test_end_to_end_apply_then_commit(tmp_path: Path):
    """The full happy path: plan, apply, review, commit the organized tree."""
    folder = _build_sample_folder(tmp_path)

    # The whole lifecycle runs against a live db: commit/rollback record the
    # run's status, so the history has to outlast them.
    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db, preset="downloads_cleanup")

        # Preflight: never start a run that can't finish.
        assert organizer.check_space(folder).ok

        plan = organizer.build_plan(folder)
        assert len(plan) == len(SAMPLE_FILES)
        # Planning is pure -- the folder is untouched until apply.
        assert not (folder / "before").exists()
        assert not (folder / "after").exists()

        batch_id = organizer.apply(folder, plan)

        # Every copy was logged, and logged as a COPY (before/ holds the
        # originals, so nothing was destroyed on the way in).
        operations = db.operations_for_batch(batch_id)
        assert len(operations) == len(SAMPLE_FILES)
        assert {op.operation_type for op in operations} == {OperationType.COPY}

        # -- the before/ + after/ review state ------------------------------
        before, after = folder / "before", folder / "after"

        # The run is now pending: its state is on disk, awaiting a decision.
        pending = organizer.pending_batch(folder)
        assert pending is not None and pending.batch_id == batch_id
        assert pending.status is BatchStatus.APPLIED
        assert pending.preset == "downloads_cleanup"
        assert organizer.is_scaffolded(folder)

        # Originals were moved out of the root and staged, keeping their layout.
        assert (before / "notes.txt").read_text() == "root notes"
        assert (before / "archive" / "old" / "notes.txt").read_text() == "archived notes"
        assert (before / "work" / "report_v1.2.docx").read_text() == "quarterly report"
        assert not (folder / "notes.txt").exists()

        # The organized copy: each layer of the classifier placed its file, and
        # the bytes made the trip intact.
        assert (after / "Images" / "photo.jpg").read_text() == "root photo bytes"
        assert (
            after / "Screenshots" / "2026" / "Screenshot_2026-03-11.png"
        ).read_text() == "screenshot bytes"
        assert (
            after / "Documents" / "Invoices" / "2026" / "January"
            / "Invoice_2026-01-26.pdf"
        ).read_text() == "january invoice"
        assert (
            after / "Documents" / "Invoices" / "2026" / "February"
            / "Invoice_2026-02-14.pdf"
        ).read_text() == "february invoice"
        assert (
            after / "Projects" / "report" / "report_v1.2.docx"
        ).read_text() == "quarterly report"

        # The collision: both notes.txt survive, the loser taking a suffix. Scan
        # order decides which is which, so assert on the pair, not on who won.
        documents = after / "Documents"
        assert (documents / "notes.txt").exists()
        assert (documents / "notes (1).txt").exists()
        assert {
            (documents / "notes.txt").read_text(),
            (documents / "notes (1).txt").read_text(),
        } == {"root notes", "archived notes"}

        # Conservation across the review state: originals staged once, copied once.
        assert len(_files_under(before)) == len(SAMPLE_FILES)
        assert len(_files_under(after)) == len(SAMPLE_FILES)

        # -- commit ---------------------------------------------------------
        organizer.commit(folder)

        assert not before.exists()
        assert not after.exists()
        assert (folder / "Images" / "photo.jpg").read_text() == "root photo bytes"
        assert (
            folder / "Documents" / "Invoices" / "2026" / "January"
            / "Invoice_2026-01-26.pdf"
        ).read_text() == "january invoice"

        # Count in == count out, and every byte accounted for.
        assert len(_files_under(folder)) == len(SAMPLE_FILES)
        assert _contents_under(folder) == sorted(SAMPLE_FILES.values())

        # The run is finished and no longer pending -- nothing left to resume.
        assert db.get_batch(batch_id).status is BatchStatus.COMMITTED
        assert organizer.pending_batch(folder) is None
        assert not organizer.is_scaffolded(folder)


# -- resume: the diff rebuilt from disk --------------------------------------


def test_review_plan_reconstructs_diff_from_disk(tmp_path: Path):
    """After apply, the before/after diff is rebuilt from disk, not memory.

    Review is a fact about the filesystem: a run resumed in a later session has
    no plan in memory, so ``review_plan`` reconstructs the rows from the
    operation log (the actual destinations, collision suffix and all) and
    re-derives each row's layer from the batch's snapshot rules. Rendered by the
    GUI, this is what makes a resumed run show the same honest diff as a fresh
    apply.
    """
    folder = _build_sample_folder(tmp_path)

    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db, preset="downloads_cleanup")
        organizer.apply(folder, organizer.build_plan(folder))

        # A fresh Organizer, no in-memory plan -- exactly a resumed session.
        resumed = Organizer(history=db, preset="downloads_cleanup")
        results = resumed.review_plan(folder)

        # One row per staged original.
        assert len(results) == len(SAMPLE_FILES)

        before, after = folder / "before", folder / "after"
        for result in results:
            # The source is a real staged file under before/, the destination a
            # real organized file under after/.
            assert before in result.entry.path.parents
            assert result.entry.path.is_file()
            assert after in result.destination.parents
            assert result.destination.is_file()

        # The log's actual destinations are used, so the collision suffix shows.
        dest_names = sorted(r.destination.name for r in results)
        assert "notes.txt" in dest_names
        assert "notes (1).txt" in dest_names

        # Layers came from the snapshot rules -- not everything fell back to E.
        assert {r.layer for r in results} - {RuleLayer.EXTENSION}


# -- apply -> rollback -------------------------------------------------------


def test_end_to_end_apply_then_rollback(tmp_path: Path):
    """The same run taken through rollback instead: no data lost, copy gone."""
    folder = _build_sample_folder(tmp_path)

    organizer = Organizer()
    assert organizer.check_space(folder).ok
    organizer.apply(folder, organizer.build_plan(folder))
    organizer.rollback(folder)

    # The scaffolding and the organized copy are gone.
    assert not (folder / "before").exists()
    assert not (folder / "after").exists()

    # Every original file is still here exactly once, with its bytes intact --
    # rollback must never cost the user data.
    assert len(_files_under(folder)) == len(SAMPLE_FILES)
    assert _contents_under(folder) == sorted(SAMPLE_FILES.values())


def test_rollback_restores_nested_layout(tmp_path: Path):
    """Rollback puts nested files back at their *original* paths.

    Apply leaves the originals' directories at the root, so promoting before/
    back over them has to merge rather than move-into — see
    ``file_ops.promote_children``.
    """
    folder = _build_sample_folder(tmp_path)
    original = {
        str(p.relative_to(folder)): p.read_text() for p in _files_under(folder)
    }

    organizer = Organizer()
    organizer.apply(folder, organizer.build_plan(folder))
    organizer.rollback(folder)

    restored = {
        str(p.relative_to(folder)): p.read_text() for p in _files_under(folder)
    }
    assert restored == original


def test_commit_merges_into_original_directory_of_same_name(tmp_path: Path):
    """An original folder sharing a category's name must not nest the result.

    ``Documents/a.txt`` classifies into ``after/Documents/`` while the empty
    original ``Documents/`` still sits at the root — commit has to merge the
    two, not produce ``Documents/Documents/a.txt``.
    """
    folder = tmp_path / "Downloads"
    (folder / "Documents").mkdir(parents=True)
    (folder / "Documents" / "a.txt").write_text("A")

    organizer = Organizer()
    organizer.apply(folder, organizer.build_plan(folder))
    organizer.commit(folder)

    assert (folder / "Documents" / "a.txt").read_text() == "A"
    assert not (folder / "Documents" / "Documents").exists()
    assert len(_files_under(folder)) == 1
