"""Load and validate rule sets from JSON.

Presets ship in ``rules/presets/*.json``; user rules live in
``config/rules/*.json``. Both use the same schema (README "Rule Definition"),
so both go through :func:`load_rules`.

User rules outrank presets — see :func:`merge_rules` for how that precedence is
expressed and what happens when the two collide on a ``rule`` identifier.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import replace
from pathlib import Path

from models import MatchType, Rule

PRESETS_DIR = Path(__file__).parent / "presets"
USER_RULES_DIR = Path(__file__).resolve().parent.parent / "config" / "rules"
# The single file the in-app editor owns. Users may hand-author other *.json
# alongside it (all are loaded and merged); this is just the one the GUI writes.
USER_RULES_FILE = USER_RULES_DIR / "my_rules.json"


class RuleValidationError(ValueError):
    """Raised when a rule file is missing required fields or malformed."""


class RuleFileSkipped(UserWarning):
    """Warned when one user rule file is unusable and gets skipped."""


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


# -- user rules --------------------------------------------------------------


def user_rule_files(directory: Path | str | None = None) -> list[Path]:
    """Return the user rule files in ``directory``, in load order.

    Files whose name starts with ``_`` or ``.`` are ignored, which is how the
    shipped ``_example.json`` stays inert and how a user parks a rule set
    without deleting it.
    """
    directory = Path(directory) if directory is not None else USER_RULES_DIR
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.glob("*.json")
        if not p.name.startswith(("_", "."))
    )


def load_user_rules(
    directory: Path | str | None = None, *, strict: bool = False
) -> list[Rule]:
    """Load every rule file in the user rules directory.

    A missing directory yields no rules. One malformed file does not sink the
    rest: it is skipped with a :class:`RuleFileSkipped` warning naming the file,
    so a stray typo can't lock the user out of their own rule set. Pass
    ``strict=True`` (e.g. when validating a file the user just edited) to raise
    :class:`RuleValidationError` instead.
    """
    rules: list[Rule] = []
    for path in user_rule_files(directory):
        try:
            rules.extend(load_rules(path))
        except (RuleValidationError, OSError) as exc:
            if strict:
                raise
            warnings.warn(
                f"skipping user rule file {path}: {exc}",
                RuleFileSkipped,
                stacklevel=2,
            )
    return rules


def validate_rule(rule: Rule) -> None:
    """Raise :class:`RuleValidationError` if ``rule`` is unusable.

    The same invariants :func:`_parse_rule` enforces on file load, checked here
    on a Rule assembled from editor fields *before* it is written to disk — so
    the app never saves a rule that would then fail to load.
    """
    for name in ("rule", "pattern", "destination"):
        if not str(getattr(rule, name)).strip():
            raise RuleValidationError(f"{name} is required")
    if rule.match_type is MatchType.METADATA and not str(
        rule.metadata_key or ""
    ).strip():
        raise RuleValidationError(
            "a metadata rule needs a metadata_key naming the field to match"
        )
    # The destination template's placeholders must be real fields, or the rule
    # would only fail later at plan time. Lazily imported: the classifier owns
    # the placeholder vocabulary, but this module is imported widely (down to
    # history.database) and should not pull core in on every import.
    from core.classifier import validate_destination_template

    try:
        validate_destination_template(rule.destination)
    except ValueError as exc:
        raise RuleValidationError(str(exc)) from exc


def save_user_rules(
    rules: list[Rule], *, path: Path | str | None = None
) -> Path:
    """Persist the user's editable rule set to a single managed JSON file.

    Writes ``config/rules/my_rules.json`` by default — the file the shipped
    ``_example.json`` tells users to create. It is only one of the user rule
    files the loader merges, but the only one the in-app editor owns, so hand-
    authored files beside it are left alone. Overwrites wholesale: pass the
    complete desired list, and an empty list writes an empty rule set.
    """
    path = Path(path) if path is not None else USER_RULES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"rules": [rule_to_dict(r) for r in rules]}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def merge_rules(user_rules: list[Rule], preset_rules: list[Rule]) -> list[Rule]:
    """Combine user rules with preset rules, user rules winning.

    Two things need saying, because :class:`~core.classifier.Classifier` takes
    one flat list and orders it by ``priority`` alone — it has no idea where a
    rule came from, so list order buys nothing:

    * **Identifier collisions.** A user rule sharing a preset rule's ``rule``
      id *replaces* it. Re-declaring ``invoice_detection`` is how a user retunes
      a preset rule rather than fighting it with a second, near-duplicate rule.
    * **Precedence.** The surviving user rules are lifted above the highest
      preset priority (relative order among themselves preserved), so a user
      rule cannot be silently outranked by a preset that shipped with a high
      ``priority``. Priorities are rewritten on copies; the caller's Rule
      objects are untouched.
    """
    overridden = {r.rule for r in user_rules}
    kept = [r for r in preset_rules if r.rule not in overridden]
    if not user_rules or not kept:
        return [*user_rules, *kept]

    # Shift so the lowest-priority user rule sits one above the top preset.
    shift = max(r.priority for r in kept) + 1 - min(r.priority for r in user_rules)
    lifted = [replace(r, priority=r.priority + shift) for r in user_rules]
    return [*lifted, *kept]


def load_effective_rules(
    preset: str | None = None, *, user_dir: Path | str | None = None
) -> list[Rule]:
    """The rule set to hand :class:`~core.classifier.Classifier`: user + preset."""
    preset_rules = load_preset(preset) if preset else []
    return merge_rules(load_user_rules(user_dir), preset_rules)


# -- snapshotting ------------------------------------------------------------


def rule_to_dict(rule: Rule) -> dict:
    """Serialize a :class:`Rule` back to its JSON schema form.

    The inverse of :func:`_parse_rule`. ``metadata_key`` is omitted when unset
    so a filename rule doesn't round-trip with a meaningless null.
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


def _parse_rule(item: dict, *, source: Path | str) -> Rule:
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
