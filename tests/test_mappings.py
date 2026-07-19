"""Tests for the type -> folder model (mappings) and the classifier override."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import mappings
from core.classifier import Classifier
from models import FileEntry, RuleLayer


def _entry(name: str, extension: str, **metadata: object) -> FileEntry:
    return FileEntry(
        Path("src") / name, 1, datetime(2026, 7, 1), extension, dict(metadata)
    )


# -- the model ---------------------------------------------------------------


def test_categories_cover_the_extension_map_plus_others():
    cats = mappings.categories()
    assert "Others" == cats[-1]  # catch-all last
    assert {"Documents", "Images", "Audio", "Video"} <= set(cats)
    assert len(cats) == len(set(cats)), "no duplicates"


def test_default_destination_is_the_category_name():
    assert mappings.default_destination("Images") == "Images"


def test_effective_applies_overrides_over_defaults():
    resolved = mappings.effective({"Images": "Pictures/Camera"})
    assert resolved["Images"] == "Pictures/Camera"
    assert resolved["Documents"] == "Documents"  # untouched -> default


def test_clean_destination_keeps_it_relative_and_safe():
    assert mappings.clean_destination("  Pictures/Camera  ") == "Pictures/Camera"
    assert mappings.clean_destination("/etc/passwd") == "etc/passwd"
    assert mappings.clean_destination("..\\..\\Windows") == "Windows"
    assert mappings.clean_destination("   ") == ""


def test_save_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "mappings.json"
    mappings.save_mappings({"Images": "Pictures"}, path=path)
    assert mappings.load_mappings(path) == {"Images": "Pictures"}


def test_load_ignores_unknown_categories_and_junk(tmp_path: Path):
    path = tmp_path / "mappings.json"
    path.write_text(
        '{"Images": "Pics", "Bogus": "X", "Documents": 7, "Audio": ""}',
        encoding="utf-8",
    )
    assert mappings.load_mappings(path) == {"Images": "Pics"}


def test_missing_or_corrupt_file_yields_no_overrides(tmp_path: Path):
    assert mappings.load_mappings(tmp_path / "absent.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert mappings.load_mappings(bad) == {}


# -- the classifier in simple mode -------------------------------------------


def test_simple_mode_sorts_by_type_ignoring_keyword_heuristics():
    # "invoice" in the name would trigger the pattern layer — but it's off, so
    # this is decided by type alone.
    classifier = Classifier(use_pattern_layer=False)
    result = classifier.classify(_entry("invoice_2026.pdf", "pdf"), base=Path("out"))
    assert result.destination == Path("out/Documents/invoice_2026.pdf")
    assert result.layer is RuleLayer.EXTENSION
    assert result.rule_name == "type: Documents"


def test_category_override_redirects_a_type():
    classifier = Classifier(
        use_pattern_layer=False,
        category_overrides={"Images": "Pictures/Camera"},
    )
    result = classifier.classify(_entry("holiday.jpg", "jpg"), base=Path("out"))
    assert result.destination == Path("out/Pictures/Camera/holiday.jpg")


def test_pattern_layer_still_default_on_for_the_engine():
    # With the layer left on, the keyword heuristic wins over plain type.
    result = Classifier().classify(_entry("invoice.pdf", "pdf"), base=Path("out"))
    assert result.layer is RuleLayer.PATTERN


# -- smart bits honour category overrides ------------------------------------


def test_tier1_invoice_bit_respects_a_documents_override():
    # The app runs with the pattern layer on; an invoice nests under Documents,
    # so a Documents override moves it too.
    classifier = Classifier(category_overrides={"Documents": "Work/Docs"})
    result = classifier.classify(
        _entry("Invoice_2026-01-26.pdf", "pdf"), base=Path("out")
    )
    assert result.layer is RuleLayer.PATTERN
    assert result.destination == Path(
        "out/Work/Docs/Invoices/2026/January/Invoice_2026-01-26.pdf"
    )


def test_tier1_screenshot_bit_is_standalone_ignoring_image_override():
    # Screenshots go to their own root, not under Images, so an Images override
    # does not touch them.
    classifier = Classifier(category_overrides={"Images": "Pictures"})
    result = classifier.classify(
        _entry("Screenshot_2026-03-11.png", "png"), base=Path("out")
    )
    assert result.destination == Path("out/Screenshots/2026/Screenshot_2026-03-11.png")


def test_tier2_photo_bit_respects_an_images_override():
    entry = _entry("holiday.jpg", "jpg", date_taken=date(2024, 6, 15))
    classifier = Classifier(
        use_metadata_layer=True, category_overrides={"Images": "Pictures"}
    )
    result = classifier.classify(entry, base=Path("out"))
    assert result.layer is RuleLayer.METADATA
    assert result.destination == Path("out/Pictures/Photos/2024/June/holiday.jpg")


def test_tier2_is_off_without_the_toggle():
    # Same photo, metadata layer off: decided by plain type, no file opened.
    entry = _entry("holiday.jpg", "jpg", date_taken=date(2024, 6, 15))
    result = Classifier(use_pattern_layer=False).classify(entry, base=Path("out"))
    assert result.layer is RuleLayer.EXTENSION
    assert result.destination == Path("out/Images/holiday.jpg")
