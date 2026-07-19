"""Tests for settings loading and history retention.

Phase 4's theme is "config must never be the reason something breaks": absent
config falls back, malformed config fails loudly, and pruning never eats an undo
log that is still needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import settings as settings_module
from history.database import HistoryDB
from models import CollisionStrategy, Operation, OperationType
from settings import Settings, SettingsError, load_settings

# -- settings loading --------------------------------------------------------


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_settings_file_loads():
    s = load_settings()
    assert s.collision_strategy is CollisionStrategy.APPEND_SUFFIX
    assert s.dry_run_default is True
    assert s.history_retention_days == 30


def test_full_file_round_trips(tmp_path: Path):
    path = _write(
        tmp_path / "settings.json",
        {
            "collision_strategy": "skip",
            "dry_run_default": False,
            "history_retention_days": 7,
            "history_db_path": str(tmp_path / "history.sqlite3"),
        },
    )
    s = load_settings(path)
    assert s.collision_strategy is CollisionStrategy.SKIP
    assert s.dry_run_default is False
    assert s.history_retention_days == 7
    assert s.history_db_path == tmp_path / "history.sqlite3"


def test_missing_file_yields_defaults(tmp_path: Path):
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_empty_file_yields_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("   \n", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_partial_file_fills_the_rest_with_defaults(tmp_path: Path):
    path = _write(tmp_path / "settings.json", {"history_retention_days": 90})
    s = load_settings(path)
    assert s.history_retention_days == 90
    assert s.collision_strategy is Settings().collision_strategy


def test_db_path_defaults_under_local_appdata(tmp_path: Path, monkeypatch):
    # The db is per-user app data, not repo content.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = _write(tmp_path / "settings.json", {})
    s = load_settings(path)
    assert s.history_db_path == tmp_path / "SmartFileOrganizer" / "history.sqlite3"
    assert Path(__file__).parent.parent not in s.history_db_path.parents


def test_db_path_expands_environment_variables(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = _write(
        tmp_path / "settings.json", {"history_db_path": "%LOCALAPPDATA%/sfo/h.sqlite3"}
    )
    assert load_settings(path).history_db_path == tmp_path / "sfo" / "h.sqlite3"


# -- malformed config fails loudly -------------------------------------------


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"collision_strategy": "banana"}, "collision_strategy"),
        ({"dry_run_default": "yes"}, "dry_run_default"),
        ({"history_retention_days": -1}, "history_retention_days"),
        ({"history_retention_days": "30"}, "history_retention_days"),
        # bool is an int subclass; it must not sneak through as 1.
        ({"history_retention_days": True}, "history_retention_days"),
        ({"history_db_path": "  "}, "history_db_path"),
    ],
)
def test_malformed_value_raises_rather_than_defaulting(
    tmp_path: Path, data: dict, match: str
):
    path = _write(tmp_path / "settings.json", data)
    with pytest.raises(SettingsError, match=match):
        load_settings(path)


def test_invalid_json_raises(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsError, match="invalid JSON"):
        load_settings(path)


def test_non_object_json_raises(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(SettingsError, match="expected a JSON object"):
        load_settings(path)


def test_retention_zero_is_allowed_as_keep_forever(tmp_path: Path):
    path = _write(tmp_path / "settings.json", {"history_retention_days": 0})
    assert load_settings(path).history_retention_days == 0


# -- history retention -------------------------------------------------------


def _log(
    db: HistoryDB, batch: str, age_days: float, *, name: str = "f.txt"
) -> Operation:
    op = Operation(
        source_path=Path("before") / name,
        destination_path=Path("after") / name,
        operation_type=OperationType.COPY,
        batch_id=batch,
        timestamp=datetime.now() - timedelta(days=age_days),
    )
    db.log(op)
    return op


def test_db_creates_its_parent_directory(tmp_path: Path):
    # The default path is under %LOCALAPPDATA%\SmartFileOrganizer\, which does
    # not exist on first run; sqlite reports "unable to open database file"
    # rather than creating it.
    path = tmp_path / "nested" / "dir" / "history.sqlite3"
    with HistoryDB(path) as db:
        _log(db, "b", age_days=0)
    assert path.exists()


def test_prune_deletes_old_batches_and_keeps_recent(tmp_path: Path):
    with HistoryDB(":memory:") as db:
        _log(db, "old", age_days=60)
        _log(db, "recent", age_days=2)
        assert db.prune(30) == 1
        assert db.batches() == ["recent"]


def test_prune_boundary_keeps_a_batch_exactly_at_the_cutoff():
    now = datetime(2026, 7, 15, 12, 0)
    with HistoryDB(":memory:") as db:
        _log(db, "edge", age_days=0)
        db.conn.execute(
            "UPDATE operations SET timestamp = ?",
            ((now - timedelta(days=30)).isoformat(),),
        )
        assert db.prune(30, now=now) == 0, "exactly `retention_days` old is retained"
        # One second older and it goes.
        db.conn.execute(
            "UPDATE operations SET timestamp = ?",
            ((now - timedelta(days=30, seconds=1)).isoformat(),),
        )
        assert db.prune(30, now=now) == 1


def test_prune_retention_zero_keeps_everything():
    with HistoryDB(":memory:") as db:
        _log(db, "ancient", age_days=9999)
        assert db.prune(0) == 0
        assert db.batches() == ["ancient"]


def test_prune_protects_in_flight_batches():
    # A batch applied but not yet committed/rolled back still needs its log.
    with HistoryDB(":memory:") as db:
        _log(db, "pending", age_days=60)
        assert db.prune(30, protect_batches=["pending"]) == 0
        assert db.batches() == ["pending"]


def test_prune_keeps_a_batch_whose_newest_operation_is_recent():
    # A long-running batch straddling the cutoff must not be half-deleted:
    # a partial log would let UndoManager silently roll back only some files.
    with HistoryDB(":memory:") as db:
        _log(db, "straddle", age_days=60, name="first.txt")
        _log(db, "straddle", age_days=1, name="last.txt")
        assert db.prune(30) == 0
        assert len(db.operations_for_batch("straddle")) == 2


def test_prune_removes_undone_operations_too():
    # `undone` rows are spent history; age alone decides.
    with HistoryDB(":memory:") as db:
        op = _log(db, "old", age_days=60)
        assert op.id is not None
        db.mark_undone(op.id)
        assert db.prune(30) == 1
        assert db.operations_for_batch("old", include_undone=True) == []


def test_prune_honors_settings_retention(tmp_path: Path):
    path = _write(tmp_path / "settings.json", {"history_retention_days": 1})
    retention = load_settings(path).history_retention_days
    with HistoryDB(":memory:") as db:
        _log(db, "old", age_days=3)
        _log(db, "fresh", age_days=0.5)
        assert db.prune(retention) == 1
        assert db.batches() == ["fresh"]


def test_prune_survives_an_aware_timestamp():
    # db.log writes naive local datetimes, so lexicographic TEXT comparison
    # would work today — but one aware value would break it. Pruning parses
    # instead, so a stray offset stays correct rather than deleting live rows.
    now = datetime(2026, 7, 15, 12, 0)
    with HistoryDB(":memory:") as db:
        _log(db, "aware", age_days=0)
        db.conn.execute(
            "UPDATE operations SET timestamp = ?",
            ((now - timedelta(hours=1)).astimezone().isoformat(),),
        )
        assert db.prune(30, now=now) == 0


def test_settings_module_imports_no_qt():
    # settings.py must stay headless-testable alongside core/models/organizer.
    source = Path(settings_module.__file__).read_text(encoding="utf-8")
    assert "PySide6" not in source
