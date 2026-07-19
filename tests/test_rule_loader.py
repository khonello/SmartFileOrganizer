"""Tests for preset loading and rule validation."""

from __future__ import annotations

import pytest

from models import MatchType, Rule
from rules import rule_loader
from rules.rule_loader import RuleValidationError


def test_all_presets_load():
    presets = rule_loader.available_presets()
    assert {"downloads_cleanup", "photo_organization", "work_files"} <= set(presets)
    for name in presets:
        rules = rule_loader.load_preset(name)
        assert rules, f"preset {name} produced no rules"


def test_missing_required_field_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"rules": [{"rule": "x", "pattern": "*"}]}', encoding="utf-8")
    with pytest.raises(RuleValidationError, match="destination"):
        rule_loader.load_rules(bad)


def test_unknown_preset_raises():
    with pytest.raises(RuleValidationError):
        rule_loader.load_preset("does_not_exist")


# -- editor seam: save + validate --------------------------------------------


def test_save_user_rules_round_trips(tmp_path):
    """What the editor writes must load straight back as equal rules."""
    path = tmp_path / "my_rules.json"
    rules = [
        Rule(
            rule="my_invoices",
            pattern="*facture*.pdf",
            destination="Documents/FR/{year}",
            match_type=MatchType.FILENAME,
            priority=10,
        ),
        Rule(
            rule="by_author",
            pattern="Jane*",
            destination="Papers/{author}",
            match_type=MatchType.METADATA,
            metadata_key="author",
            priority=5,
        ),
    ]
    rule_loader.save_user_rules(rules, path=path)
    assert rule_loader.load_rules(path) == rules


def test_save_user_rules_default_location(tmp_path, monkeypatch):
    """With no path, it writes the managed file the loader then picks up."""
    managed = tmp_path / "rules" / "my_rules.json"
    monkeypatch.setattr(rule_loader, "USER_RULES_FILE", managed)
    monkeypatch.setattr(rule_loader, "USER_RULES_DIR", managed.parent)

    rule = Rule(rule="zips", pattern="*.zip", destination="Archives")
    rule_loader.save_user_rules([rule])

    assert managed.exists()
    assert rule_loader.load_user_rules(managed.parent) == [rule]


def test_save_empty_clears_the_rule_set(tmp_path):
    path = tmp_path / "my_rules.json"
    rule_loader.save_user_rules([Rule("x", "*", "X")], path=path)
    rule_loader.save_user_rules([], path=path)
    assert rule_loader.load_rules(path) == []


def test_validate_rule_requires_core_fields():
    with pytest.raises(RuleValidationError, match="pattern"):
        rule_loader.validate_rule(Rule(rule="x", pattern="  ", destination="X"))


def test_validate_rule_metadata_needs_a_key():
    metadata_rule = Rule(
        rule="m", pattern="*", destination="X", match_type=MatchType.METADATA
    )
    with pytest.raises(RuleValidationError, match="metadata_key"):
        rule_loader.validate_rule(metadata_rule)
    # A key makes it valid.
    rule_loader.validate_rule(
        Rule(
            rule="m",
            pattern="*",
            destination="X",
            match_type=MatchType.METADATA,
            metadata_key="author",
        )
    )


def test_validate_rule_rejects_unknown_template_placeholder():
    """A typo'd placeholder is caught at save, not as a failed scan later."""
    with pytest.raises(RuleValidationError, match="unknown placeholder"):
        rule_loader.validate_rule(Rule("x", "*", "Documents/{yeer}"))


def test_validate_rule_rejects_malformed_template():
    with pytest.raises(RuleValidationError, match="malformed"):
        rule_loader.validate_rule(Rule("x", "*", "Documents/{year"))


def test_validate_rule_accepts_known_placeholders():
    # Reserved date/name fields and a metadata key all resolve.
    rule_loader.validate_rule(
        Rule("x", "*", "Documents/{year}/{month}/{project}/{author}")
    )
