"""Load and validate rule sets from JSON.

Presets ship in ``rules/presets/*.json``; user rules live in
``config/rules/*.json``. Both use the same schema (README "Rule Definition"),
so both go through :func:`load_rules`.
"""

from __future__ import annotations

import json
from pathlib import Path

from models import MatchType, Rule

PRESETS_DIR = Path(__file__).parent / "presets"


class RuleValidationError(ValueError):
    """Raised when a rule file is missing required fields or malformed."""


def load_rules(path: Path | str) -> list[Rule]:
    """Parse a rule file and return validated :class:`Rule` objects.

    Accepts either a bare list of rule objects or ``{"rules": [...]}``.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuleValidationError(f"{path}: invalid JSON — {exc}") from exc

    raw = data.get("rules", data) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise RuleValidationError(f"{path}: expected a list of rules")
    return [_parse_rule(item, source=path) for item in raw]


def load_preset(name: str) -> list[Rule]:
    """Load a built-in preset by name, e.g. ``"downloads_cleanup"``."""
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        raise RuleValidationError(f"unknown preset: {name!r}")
    return load_rules(path)


def available_presets() -> list[str]:
    """Return the names of all built-in presets."""
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def _parse_rule(item: dict, *, source: Path) -> Rule:
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
    return Rule(
        rule=item["rule"],
        pattern=item["pattern"],
        destination=item["destination"],
        match_type=match_type,
        case_sensitive=bool(item.get("case_sensitive", False)),
        priority=int(item.get("priority", 0)),
    )
