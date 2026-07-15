"""Run records: rule snapshots, lifecycle status, resume, and undo's limits.

A batch records *what produced a run*, not just what it did. Two things depend
on that and are tested here:

* A run's trace is only meaningful against the rules in force when it ran, so
  the rules are frozen onto the batch rather than referenced.
* ``commit`` moves the copies out of ``after/`` and deletes the originals, so
  the logged paths stop existing. Undo has to *refuse* past that point — the
  bug being pinned is that it used to report success and do nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from history.database import HistoryDB
from history.undo_manager import CannotUndoError, UndoManager
from models import Batch, BatchStatus, CollisionStrategy, MatchType, Rule
from organizer import Organizer
from rules import rule_loader

RULES = [
    Rule(rule="by_author", pattern="Acme*", destination="Work/{author}",
         match_type=MatchType.METADATA, metadata_key="author", priority=10),
    Rule(rule="invoices", pattern="*invoice*", destination="Docs/{year}",
         priority=5),
]


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello")
    (folder / "photo.jpg").write_text("image bytes")
    return folder


# -- rule snapshots ----------------------------------------------------------


def test_rules_round_trip_through_json():
    """A frozen rule set thaws back to exactly what went in."""
    assert rule_loader.rules_from_json(rule_loader.rules_to_json(RULES)) == RULES


def test_rule_to_dict_omits_an_unset_metadata_key():
    """A filename rule shouldn't round-trip carrying a meaningless null."""
    plain = rule_loader.rule_to_dict(RULES[1])
    assert "metadata_key" not in plain
    assert rule_loader.rule_to_dict(RULES[0])["metadata_key"] == "author"


def test_batch_snapshots_the_rules_that_produced_it(tmp_path: Path):
    """Editing a rule afterwards must not rewrite what an old run says it did."""
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer(RULES, history=db, preset="work_files")
        batch_id = organizer.apply(folder, organizer.build_plan(folder))

        # The caller mutates its own rule set after the run.
        RULES[1].destination = "SOMEWHERE/ELSE"
        try:
            recorded = db.get_batch(batch_id)
            assert recorded is not None
            assert recorded.preset == "work_files"
            assert recorded.folder == folder
            assert recorded.collision_strategy is CollisionStrategy.APPEND_SUFFIX
            assert [r.destination for r in recorded.rules] == [
                "Work/{author}",
                "Docs/{year}",
            ], "the snapshot must be frozen, not a live reference"
        finally:
            RULES[1].destination = "Docs/{year}"


# -- lifecycle status --------------------------------------------------------


def test_apply_records_the_run_as_pending(tmp_path: Path):
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        batch_id = organizer.apply(folder, organizer.build_plan(folder))
        assert db.get_batch(batch_id).status is BatchStatus.APPLIED
        assert [b.batch_id for b in db.pending_batches(folder)] == [batch_id]


def test_rollback_marks_the_run_rolled_back(tmp_path: Path):
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        batch_id = organizer.apply(folder, organizer.build_plan(folder))
        organizer.rollback(folder)
        assert db.get_batch(batch_id).status is BatchStatus.ROLLED_BACK
        assert db.pending_batches(folder) == []


def test_dry_run_records_no_batch(tmp_path: Path):
    """Dry run touches nothing -- including the history."""
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        plan = organizer.build_plan(folder)
        organizer.apply(folder, plan, dry_run=True)
        assert db.recent_batches() == []


def test_recent_batches_is_newest_first(tmp_path: Path):
    with HistoryDB(":memory:") as db:
        now = datetime.now()
        for index, name in enumerate(["oldest", "middle", "newest"]):
            db.start_batch(
                Batch(
                    batch_id=name,
                    folder=tmp_path / name,
                    collision_strategy=CollisionStrategy.APPEND_SUFFIX,
                    started_at=now + timedelta(minutes=index),
                )
            )
        assert [b.batch_id for b in db.recent_batches()] == [
            "newest",
            "middle",
            "oldest",
        ]
        assert [b.batch_id for b in db.recent_batches(limit=1)] == ["newest"]


# -- resuming ----------------------------------------------------------------


def test_pending_batch_survives_a_new_session(tmp_path: Path):
    """A run's state lives on disk, so a fresh Organizer must still find it."""
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        first = Organizer(history=db)
        batch_id = first.apply(folder, first.build_plan(folder))

        # A new session: same db, no memory of the run.
        resumed = Organizer(history=db)
        pending = resumed.pending_batch(folder)
        assert pending is not None and pending.batch_id == batch_id

        # It can be finished without being told the batch id.
        resumed.commit(folder)
        assert db.get_batch(batch_id).status is BatchStatus.COMMITTED


def test_is_scaffolded_spots_an_unfinished_run_without_a_db(tmp_path: Path):
    """The disk-level check: a scaffolded folder plans as empty, which reads as
    "nothing to organize" while the user's files sit staged in before/."""
    folder = _folder(tmp_path)
    organizer = Organizer()
    assert not organizer.is_scaffolded(folder)

    organizer.apply(folder, organizer.build_plan(folder))
    assert organizer.is_scaffolded(folder)
    assert organizer.build_plan(folder) == [], "scaffolding is skipped on re-scan"


# -- undo's limits -----------------------------------------------------------


def test_undo_refuses_a_committed_batch(tmp_path: Path):
    """The bug this pins: undo used to report success and change nothing.

    commit() moves the copies out of after/ into the folder root and deletes
    the originals, so undo_copy's logged paths no longer exist and unlink
    (missing_ok=True) silently no-ops.
    """
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        batch_id = organizer.apply(folder, organizer.build_plan(folder))
        organizer.commit(folder)

        before = sorted(p.name for p in folder.rglob("*") if p.is_file())
        with pytest.raises(CannotUndoError, match="committed"):
            UndoManager(db).undo_batch(batch_id)

        # It refused, and nothing was touched or falsely marked undone.
        assert sorted(p.name for p in folder.rglob("*") if p.is_file()) == before
        assert not any(
            op.undone for op in db.operations_for_batch(batch_id, include_undone=True)
        )


def test_undo_allows_a_pending_batch(tmp_path: Path):
    """The case undo is actually for: applied, not yet committed."""
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        batch_id = organizer.apply(folder, organizer.build_plan(folder))

        assert UndoManager(db).undo_batch(batch_id) == 2
        assert not list((folder / "after").rglob("*.txt"))


def test_undo_allows_a_batch_with_no_run_record(tmp_path: Path):
    """Crash recovery: operations logged without a batch row stay undoable."""
    folder = _folder(tmp_path)
    with HistoryDB(":memory:") as db:
        organizer = Organizer()  # no history -> no run record
        batch_id = organizer.apply(folder, organizer.build_plan(folder))
        # Log the copies after the fact, as a recovery path would find them.
        for path in (folder / "after").rglob("*"):
            if path.is_file():
                from models import Operation, OperationType

                db.log(
                    Operation(
                        source_path=folder / "before" / path.name,
                        destination_path=path,
                        operation_type=OperationType.COPY,
                        batch_id=batch_id,
                    )
                )
        assert db.get_batch(batch_id) is None
        assert UndoManager(db).undo_batch(batch_id) == 2


def test_undo_last_skips_a_committed_batch(tmp_path: Path):
    """"Undo the last thing" means the last *undoable* thing."""
    committed = tmp_path / "committed"
    committed.mkdir()
    (committed / "a.txt").write_text("A")
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "b.txt").write_text("B")

    with HistoryDB(":memory:") as db:
        organizer = Organizer(history=db)
        organizer.apply(pending, organizer.build_plan(pending))
        later = Organizer(history=db)
        later.apply(committed, later.build_plan(committed))
        later.commit(committed)

        # The newest batch is the committed one; undo_last must step past it.
        assert UndoManager(db).undo_last() == 1
        assert not list((pending / "after").rglob("*.txt"))


# -- pruning -----------------------------------------------------------------


def test_prune_protects_a_pending_run_automatically(tmp_path: Path):
    """A pending run's log must survive: before/ and after/ are still on disk."""
    with HistoryDB(":memory:") as db:
        old = datetime.now() - timedelta(days=90)
        db.start_batch(
            Batch(
                batch_id="pending",
                folder=tmp_path,
                collision_strategy=CollisionStrategy.APPEND_SUFFIX,
                status=BatchStatus.APPLIED,
                started_at=old,
            )
        )
        db.start_batch(
            Batch(
                batch_id="done",
                folder=tmp_path,
                collision_strategy=CollisionStrategy.APPEND_SUFFIX,
                status=BatchStatus.COMMITTED,
                started_at=old,
            )
        )
        for batch_id in ("pending", "done"):
            from models import Operation, OperationType

            db.log(
                Operation(
                    source_path=tmp_path / "s",
                    destination_path=tmp_path / "d",
                    operation_type=OperationType.COPY,
                    batch_id=batch_id,
                    timestamp=old,
                )
            )

        assert db.prune(30) == 1, "only the committed run is eligible"
        assert db.get_batch("pending") is not None
        assert db.get_batch("done") is None, "the record dies with its operations"
