"""The rule engine — applies the layered classification pipeline.

Precedence (highest to lowest), per README:

    1. Custom user rules
    2. Pattern-based rules
    3. Metadata-based rules
    4. Extension-based fallback

The first layer to produce a destination wins; within the custom/pattern
layers, rules are tried in descending ``priority``. The classifier is pure:
it returns proposed :class:`ClassificationResult` objects and never touches
the filesystem (reading a file's metadata aside — it never writes).

Metadata is **preset-driven**: :meth:`Classifier.classify` opens a file only
when a rule actually asks for metadata. See :attr:`Classifier.needs_metadata`.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from string import Formatter

from core import metadata, pattern_matcher
from models import (
    ClassificationResult,
    FileEntry,
    MatchType,
    Rule,
    RuleLayer,
)

# Rendered in place of a metadata placeholder the file has no value for, so a
# PDF with no /Author lands in "By/Unknown" rather than crashing the plan.
UNKNOWN = "Unknown"

# Characters Windows forbids in a path component. Metadata is user data — a
# track tagged "AC/DC" must not silently become a nested directory.
_ILLEGAL_COMPONENT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Classifier:
    """Applies user rules then built-in layers to propose a destination."""

    def __init__(
        self,
        rules: list[Rule] | None = None,
        *,
        use_metadata_layer: bool = False,
        use_pattern_layer: bool = True,
        category_overrides: dict[str, str] | None = None,
    ) -> None:
        # Sorted once so classify() stays O(rules) per file with no re-sorting.
        self.rules = sorted(rules or [], key=lambda r: r.priority, reverse=True)
        self.use_metadata_layer = use_metadata_layer
        # The built-in invoice/screenshot/version heuristics. On by default;
        # the simple type->folder model (see mappings.py) turns them off so a
        # file is decided by its type alone.
        self.use_pattern_layer = use_pattern_layer
        # category -> destination folder, applied to the extension layer, so the
        # user can send "Images" to "Pictures/Camera" without writing a rule.
        self.category_overrides = dict(category_overrides or {})
        # Decided once per Classifier, not per file: reading metadata means
        # opening every file, so we only do it when something asks.
        self.needs_metadata = use_metadata_layer or any(
            _rule_needs_metadata(rule) for rule in self.rules
        )

    def classify(self, entry: FileEntry, *, base: Path) -> ClassificationResult:
        """Return the proposed destination for ``entry`` under ``base``.

        ``base`` is the output root the destination templates resolve against.
        """
        # Lazy, preset-driven metadata: this is the only place that knows
        # whether any rule needs it, so it is the only place that reads it.
        # Already-populated metadata is left alone (callers may pre-seed it).
        if self.needs_metadata and not entry.metadata:
            entry.metadata = metadata.extract(entry.path, entry.extension)

        for rule in self.rules:
            dest = self._apply_rule(rule, entry)
            if dest is not None:
                return ClassificationResult(
                    entry=entry,
                    destination=base / dest / entry.path.name,
                    layer=RuleLayer.CUSTOM,
                    rule_name=rule.rule,
                )

        if self.use_pattern_layer:
            pattern_hit = self._pattern_layer(entry)
            if pattern_hit is not None:
                dest, rule_name = pattern_hit
                return ClassificationResult(
                    entry=entry,
                    destination=base / dest / entry.path.name,
                    layer=RuleLayer.PATTERN,
                    rule_name=rule_name,
                )

        if self.use_metadata_layer:
            metadata_hit = self._metadata_layer(entry)
            if metadata_hit is not None:
                dest, rule_name = metadata_hit
                return ClassificationResult(
                    entry=entry,
                    destination=base / dest / entry.path.name,
                    layer=RuleLayer.METADATA,
                    rule_name=rule_name,
                )

        category = pattern_matcher.category_for_extension(entry.extension)
        folder = self._category_folder(category)
        return ClassificationResult(
            entry=entry,
            destination=base / folder / entry.path.name,
            layer=RuleLayer.EXTENSION,
            rule_name=f"type: {category}",
        )

    # -- layers --------------------------------------------------------------

    def _apply_rule(self, rule: Rule, entry: FileEntry) -> Path | None:
        """Return the templated destination if ``rule`` matches ``entry``.

        ``None`` means *this rule* did not match; classify() carries on to the
        next rule, so a metadata rule whose key is absent simply stands down.
        """
        if rule.match_type is MatchType.EXTENSION:
            target = entry.extension
        elif rule.match_type is MatchType.METADATA:
            # The loader rejects a metadata rule with no key; a hand-built Rule
            # could still omit it, in which case there is nothing to test.
            if not rule.metadata_key:
                return None
            value = entry.metadata.get(rule.metadata_key)
            if value is None:
                return None  # file carries no such key -> next rule
            # Values are typed (dates, ints); patterns are globs over text.
            target = _as_text(value)
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
                Path(self._category_folder("Documents"))
                / "Invoices"
                / str(d.year)
                / _month(d),
                "invoice_detection",
            )

        version = pattern_matcher.extract_version(name)
        if version is not None:
            project, _ = version
            return Path("Projects") / project, "project_version_detection"

        return None

    def _metadata_layer(self, entry: FileEntry) -> tuple[Path, str] | None:
        """Built-in metadata rules (photos by capture date, music by artist).

        Only consulted when ``use_metadata_layer`` is set — unlike the pattern
        layer, these cost a file read per entry, so they are opt-in.
        """
        taken = entry.metadata.get("date_taken")
        if isinstance(taken, date):
            return (
                Path(self._category_folder("Images"))
                / "Photos"
                / str(taken.year)
                / _month(taken),
                "exif_date_taken",
            )

        artist = entry.metadata.get("artist")
        if artist:
            dest = Path(self._category_folder("Audio")) / _safe_component(artist)
            album = entry.metadata.get("album")
            if album:
                dest = dest / _safe_component(album)
            return dest, "audio_artist_tag"

        return None

    def _category_folder(self, category: str) -> str:
        """The destination folder for a type category, honouring user overrides.

        So a Documents/Images/Audio override also moves the smart bits that nest
        under it (invoices, photos, music) — the standalone Screenshots/Projects
        roots have no category to override.
        """
        return self.category_overrides.get(category, category)

    # -- templating ----------------------------------------------------------

    def _render_template(self, template: str, entry: FileEntry) -> str:
        """Fill a rule destination's placeholders.

        Supported: ``{year}``, ``{month}``, ``{month_num}``, ``{project}``,
        ``{category}``, plus every metadata key in
        :data:`core.metadata.KNOWN_KEYS` (``{author}``, ``{artist}``, ...).

        Date placeholders resolve from EXIF capture date, else a date embedded
        in the filename, else a metadata creation date, else the file's mtime.
        Metadata placeholders the file has no value for render as ``Unknown``;
        a placeholder that is not a real field at all is a rule-authoring bug
        and raises, loudly, at plan time (before anything has been touched).
        """
        d = self._effective_date(entry)
        version = pattern_matcher.extract_version(entry.path.name)
        project = version[0] if version else entry.path.stem

        # Seed every known metadata key so an absent one falls back rather
        # than raising, then let the file's real metadata win.
        values: dict[str, object] = dict.fromkeys(metadata.KNOWN_KEYS, UNKNOWN)
        values.update({k: v for k, v in entry.metadata.items() if v is not None})
        # Reserved names last: {year} stays date-derived and cannot be
        # shadowed by a metadata key that happens to share its name.
        values.update(
            year=d.year,
            month=_month(d),
            month_num=f"{d.month:02d}",
            project=project,
            category=pattern_matcher.category_for_extension(entry.extension),
        )

        safe = {key: _safe_component(value) for key, value in values.items()}
        try:
            return template.format(**safe)
        except (KeyError, IndexError) as exc:
            raise ValueError(
                f"destination template {template!r} uses unknown placeholder "
                f"{{{exc.args[0]}}}; available: {', '.join(sorted(safe))}"
            ) from exc

    def _effective_date(self, entry: FileEntry) -> date:
        """Resolve the date ``{year}``/``{month}`` speak for.

        EXIF capture date wins outright — it is the only source that states
        when the content happened. A date the user typed into the filename
        beats a PDF creation date (which is often just when it was exported),
        and mtime is the last resort because copying rewrites it.
        """
        taken = entry.metadata.get("date_taken")
        if isinstance(taken, date):
            return taken

        from_name = pattern_matcher.extract_date(entry.path.name)
        if from_name is not None:
            return from_name

        created = entry.metadata.get("date_created")
        if isinstance(created, date):
            return created

        return entry.modified.date()


# -- helpers -----------------------------------------------------------------


def _rule_needs_metadata(rule: Rule) -> bool:
    """Whether ``rule`` can only be evaluated with metadata in hand."""
    if rule.match_type is MatchType.METADATA:
        return True
    return bool(_template_fields(rule.destination) & set(metadata.KNOWN_KEYS))


def _template_fields(template: str) -> set[str]:
    """Return the placeholder names used in a format template.

    A malformed template yields an empty set rather than raising here;
    :meth:`Classifier._render_template` is where that surfaces, with the
    context needed to fix it.
    """
    try:
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
    except ValueError:
        return set()
    # "{author.upper}" / "{tags[0]}" still hang off the base field name.
    return {re.split(r"[.\[]", name, maxsplit=1)[0] for name in fields}


def _as_text(value: object) -> str:
    """Render a typed metadata value as the text a glob pattern tests against.

    Dates become ISO ("2024-05-03"), so ``2024-*`` matches a whole year.
    """
    return value.isoformat() if isinstance(value, date) else str(value)


def _safe_component(value: object) -> str:
    """Coerce a value into one safe path component."""
    text = _ILLEGAL_COMPONENT_CHARS.sub("_", _as_text(value)).strip()
    # Windows silently drops trailing dots/spaces from directory names.
    text = text.strip(" .")
    return text or UNKNOWN


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _month(d: date) -> str:
    return _MONTHS[d.month - 1]
