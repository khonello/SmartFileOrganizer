"""Freeze and thaw rule sets as JSON — for snapshotting a run onto its history.

A batch records the rules that produced it (``batches.rules_json``) so its trace
can't be rewritten by later edits. That round-trip is all that remains here; the
preset / user-rule loading and the pattern-rule editor were removed with the
rule-engine UI — the app now sorts by file type (see ``mappings.py``).
"""

from __future__ import annotations

import json

from models import MatchType, Rule


class RuleValidationError(ValueError):
    """Raised when a serialized rule is missing required fields or malformed."""


def rule_to_dict(rule: Rule) -> dict:
    """Serialize a :class:`Rule` to its JSON schema form.

    ``metadata_key`` is omitted when unset so a plain rule doesn't round-trip
    with a meaningless null.
    """
    item = {
        "rule": rule.rule,
        "pattern": rule.pattern,
        "destination": rule.destination,
        "match_type": rule.match_type.value,
        "case_sensitive": rule.case_sensitive,
        "priority": rule.priority,
    }
    if rule.metadata_key is not None:
        item["metadata_key"] = rule.metadata_key
    return item


def rules_to_json(rules: list[Rule]) -> str:
    """Freeze a rule set as JSON, for snapshotting onto a history batch."""
    return json.dumps([rule_to_dict(r) for r in rules])


def rules_from_json(text: str, *, source: str = "<snapshot>") -> list[Rule]:
    """Thaw a rule set frozen by :func:`rules_to_json`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuleValidationError(f"{source}: invalid JSON — {exc}") from exc
    if not isinstance(data, list):
        raise RuleValidationError(f"{source}: expected a list of rules")
    return [_parse_rule(item, source=source) for item in data]


def _parse_rule(item: dict, *, source: str) -> Rule:
    required = ("rule", "pattern", "destination")
    missing = [k for k in required if k not in item]
    if missing:
        raise RuleValidationError(
            f"{source}: rule missing required field(s): {', '.join(missing)}"
        )
    try:
        match_type = MatchType(item.get("match_type", "filename"))
    except ValueError as exc:
        raise RuleValidationError(f"{source}: {exc}") from exc

    metadata_key = item.get("metadata_key")
    if match_type is MatchType.METADATA and not metadata_key:
        raise RuleValidationError(
            f"{source}: rule {item['rule']!r} has match_type 'metadata' but no "
            f"'metadata_key' saying which key to match against"
        )

    return Rule(
        rule=item["rule"],
        pattern=item["pattern"],
        destination=item["destination"],
        match_type=match_type,
        case_sensitive=bool(item.get("case_sensitive", False)),
        priority=int(item.get("priority", 0)),
        metadata_key=metadata_key,
    )
