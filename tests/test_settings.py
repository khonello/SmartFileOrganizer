"""Tests for settings loading, user rule discovery, and history retention.

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
from models import CollisionStrategy, Operation, OperationType, Rule
from rules import rule_loader
from rules.rule_loader import RuleFileSkipped, RuleValidationError
from settings import Settings, SettingsError, load_settings

# -- settings loading --------------------------------------------------------


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_settings_file_loads():
    s = load_settings()
    assert s.default_preset in rule_loader.available_presets()
    assert s.collision_strategy is CollisionStrategy.APPEND_SUFFIX
    assert s.dry_run_default is True
    assert s.history_retention_days == 30


def test_full_file_round_trips(tmp_path: Path):
    path = _write(
        tmp_path / "settings.json",
        {
            "default_preset": "work_files",
            "collision_strategy": "skip",
            "dry_run_default": False,
            "history_retention_days": 7,
            "history_db_path": str(tmp_path / "history.sqlite3"),
        },
    )
    s = load_settings(path)
    assert s.default_preset == "work_files"
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
    assert s.default_preset == Settings().default_preset
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
        ({"default_preset": ""}, "default_preset"),
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


# -- user rule discovery -----------------------------------------------------


def _write_rules(directory: Path, name: str, *ids: str) -> Path:
    """Write a rule file containing one trivial catch-all rule per id."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    rules = [
        {"rule": i, "pattern": f"*{i}*", "destination": i.upper()} for i in ids
    ]
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return path


def test_shipped_user_rules_dir_exists_and_example_is_inert():
    assert rule_loader.USER_RULES_DIR.is_dir()
    assert (rule_loader.USER_RULES_DIR / "_example.json").exists()
    # The example ships valid but disabled, so a fresh install classifies with
    # presets alone.
    assert rule_loader.load_user_rules() == []
    assert rule_loader.load_rules(rule_loader.USER_RULES_DIR / "_example.json")


def test_load_user_rules_reads_every_file(tmp_path: Path):
    _write_rules(tmp_path, "a.json", "a")
    _write_rules(tmp_path, "b.json", "b")
    assert {r.rule for r in rule_loader.load_user_rules(tmp_path)} == {"a", "b"}


def test_missing_user_rules_dir_is_not_an_error(tmp_path: Path):
    assert rule_loader.load_user_rules(tmp_path / "absent") == []
    assert rule_loader.user_rule_files(tmp_path / "absent") == []


def test_underscored_and_dotted_files_are_skipped(tmp_path: Path):
    _write_rules(tmp_path, "_off.json", "x")
    _write_rules(tmp_path, ".hidden.json", "y")
    _write_rules(tmp_path, "on.json", "z")
    assert [p.name for p in rule_loader.user_rule_files(tmp_path)] == ["on.json"]


def test_one_bad_file_does_not_sink_the_others(tmp_path: Path):
    _write_rules(tmp_path, "good.json", "g")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")

    with pytest.warns(RuleFileSkipped, match="bad.json"):
        rules = rule_loader.load_user_rules(tmp_path)
    assert [r.rule for r in rules] == ["g"]


def test_strict_mode_raises_on_a_bad_file(tmp_path: Path):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RuleValidationError):
        rule_loader.load_user_rules(tmp_path, strict=True)


# -- user rules outrank presets ----------------------------------------------


def test_user_rule_outranks_higher_priority_preset_rule():
    # Classifier sorts on priority alone, so a merge that only reorders the list
    # would let this preset rule (priority 20) beat the user's rule (0).
    user = [Rule(rule="mine", pattern="*invoice*", destination="Mine")]
    presets = rule_loader.load_preset("downloads_cleanup")
    merged = rule_loader.merge_rules(user, presets)

    mine = next(r for r in merged if r.rule == "mine")
    assert all(mine.priority > r.priority for r in merged if r.rule != "mine")


def test_merge_preserves_relative_order_within_user_rules():
    user = [
        Rule(rule="low", pattern="*", destination="L", priority=-5),
        Rule(rule="high", pattern="*", destination="H", priority=50),
    ]
    presets = [Rule(rule="p", pattern="*", destination="P", priority=100)]
    merged = {r.rule: r.priority for r in rule_loader.merge_rules(user, presets)}
    assert merged["high"] > merged["low"] > merged["p"]


def test_merge_does_not_mutate_caller_rules():
    user = [Rule(rule="mine", pattern="*", destination="M", priority=0)]
    presets = [Rule(rule="p", pattern="*", destination="P", priority=9)]
    rule_loader.merge_rules(user, presets)
    assert user[0].priority == 0


def test_same_rule_id_replaces_the_preset_rule():
    user = [Rule(rule="invoice_detection", pattern="*inv*", destination="Mine")]
    merged = rule_loader.merge_rules(user, rule_loader.load_preset("downloads_cleanup"))

    matching = [r for r in merged if r.rule == "invoice_detection"]
    assert len(matching) == 1, "user rule should replace the preset rule, not shadow it"
    assert matching[0].destination == "Mine"


def test_merge_with_no_user_rules_leaves_presets_untouched():
    presets = rule_loader.load_preset("downloads_cleanup")
    assert rule_loader.merge_rules([], presets) == presets


def test_load_effective_rules_combines_user_dir_and_preset(tmp_path: Path):
    _write_rules(tmp_path, "mine.json", "m")
    rules = rule_loader.load_effective_rules("downloads_cleanup", user_dir=tmp_path)
    names = {r.rule for r in rules}
    assert "m" in names and "installers" in names


def test_load_effective_rules_without_preset(tmp_path: Path):
    _write_rules(tmp_path, "mine.json", "m")
    rules = rule_loader.load_effective_rules(user_dir=tmp_path)
    assert [r.rule for r in rules] == ["m"]


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
