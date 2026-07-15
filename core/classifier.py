"""The rule engine — applies the layered classification pipeline.

Precedence (highest to lowest), per README:

    1. Custom user rules
    2. Pattern-based rules
    3. Metadata-based rules
    4. Extension-based fallback

The first layer to produce a destination wins; within the custom/pattern
layers, rules are tried in descending ``priority``. The classifier is pure:
it returns proposed :class:`ClassificationResult` objects and never touches
the filesystem.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from core import pattern_matcher
from models import (
    ClassificationResult,
    FileEntry,
    MatchType,
    Rule,
    RuleLayer,
)


class Classifier:
    """Applies user rules then built-in layers to propose a destination."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        # Sorted once so classify() stays O(rules) per file with no re-sorting.
        self.rules = sorted(rules or [], key=lambda r: r.priority, reverse=True)

    def classify(self, entry: FileEntry, *, base: Path) -> ClassificationResult:
        """Return the proposed destination for ``entry`` under ``base``.

        ``base`` is the output root the destination templates resolve against.
        """
        for rule in self.rules:
            dest = self._apply_rule(rule, entry)
            if dest is not None:
                return ClassificationResult(
                    entry=entry,
                    destination=base / dest / entry.path.name,
                    layer=RuleLayer.CUSTOM,
                    rule_name=rule.rule,
                )

        pattern_hit = self._pattern_layer(entry)
        if pattern_hit is not None:
            dest, rule_name = pattern_hit
            return ClassificationResult(
                entry=entry,
                destination=base / dest / entry.path.name,
                layer=RuleLayer.PATTERN,
                rule_name=rule_name,
            )

        # Metadata layer is a TODO hook (see metadata.py); falls through for now.

        category = pattern_matcher.category_for_extension(entry.extension)
        return ClassificationResult(
            entry=entry,
            destination=base / category / entry.path.name,
            layer=RuleLayer.EXTENSION,
            rule_name="extension_fallback",
        )

    # -- layers --------------------------------------------------------------

    def _apply_rule(self, rule: Rule, entry: FileEntry) -> Path | None:
        """Return the templated destination if ``rule`` matches ``entry``."""
        if rule.match_type is MatchType.EXTENSION:
            target = entry.extension
        elif rule.match_type is MatchType.METADATA:
            return None  # TODO: wire once metadata extraction lands
        else:
            target = entry.path.name

        if pattern_matcher.matches(
            target, rule.pattern, case_sensitive=rule.case_sensitive
        ):
            return Path(self._render_template(rule.destination, entry))
        return None

    def _pattern_layer(self, entry: FileEntry) -> tuple[Path, str] | None:
        """Built-in pattern rules (invoices, screenshots, versioned projects)."""
        name = entry.path.name
        lower = name.lower()

        if lower.startswith("screenshot"):
            d = pattern_matcher.extract_date(name) or entry.modified.date()
            return Path("Screenshots") / str(d.year), "screenshot_detection"

        if "invoice" in lower:
            d = pattern_matcher.extract_date(name) or entry.modified.date()
            return (
                Path("Documents") / "Invoices" / str(d.year) / _month(d),
                "invoice_detection",
            )

        version = pattern_matcher.extract_version(name)
        if version is not None:
            project, _ = version
            return Path("Projects") / project, "project_version_detection"

        return None

    # -- templating ----------------------------------------------------------

    def _render_template(self, template: str, entry: FileEntry) -> str:
        """Fill ``{year}``/``{month}``/``{project}`` placeholders in a rule dest.

        Date placeholders resolve from a date embedded in the filename, else
        the file's modification time.
        """
        d = pattern_matcher.extract_date(entry.path.name) or entry.modified.date()
        version = pattern_matcher.extract_version(entry.path.name)
        project = version[0] if version else entry.path.stem
        return template.format(
            year=d.year,
            month=_month(d),
            month_num=f"{d.month:02d}",
            project=project,
            category=pattern_matcher.category_for_extension(entry.extension),
        )


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _month(d: date) -> str:
    return _MONTHS[d.month - 1]
