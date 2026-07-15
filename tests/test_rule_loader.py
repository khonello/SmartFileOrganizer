"""Tests for preset loading and rule validation."""

from __future__ import annotations

import pytest

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
