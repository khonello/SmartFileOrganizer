"""Tests for metadata extraction and the metadata classification layer.

Fixtures are real files written at runtime (a JPEG with EXIF, a tagged MP3, a
PDF with document info) rather than committed binaries, so the suite stays
text-only and the fixtures cannot drift from what the libraries actually emit.

Like the rest of the suite these import no Qt.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from core import metadata
from core.classifier import Classifier
from models import FileEntry, MatchType, Rule, RuleLayer

# One MPEG1 Layer III frame: 128 kbps @ 44.1 kHz -> 417 bytes. mutagen needs a
# syncable frame to recognise the file as an MP3 at all.
_MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


# -- fixture builders --------------------------------------------------------


def _make_jpeg(path: Path, taken: str | None = "2024:05:03 10:11:12") -> Path:
    """Write a tiny JPEG, optionally carrying an EXIF capture date."""
    from PIL import Image

    img = Image.new("RGB", (4, 4), "red")
    exif = img.getexif()
    if taken is not None:
        exif[306] = taken  # DateTime (base IFD)
        exif.get_ifd(0x8769)[36867] = taken  # DateTimeOriginal (Exif IFD)
    img.save(path, exif=exif)
    return path


def _make_pdf(
    path: Path,
    author: str | None = "Ada Lovelace",
    created: str | None = "D:20240503101112Z",
) -> Path:
    """Write a one-page PDF with the given document info."""
    from PyPDF2 import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    info = {}
    if author is not None:
        info["/Author"] = author
    if created is not None:
        info["/CreationDate"] = created
    if info:
        writer.add_metadata(info)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _make_mp3(
    path: Path,
    artist: str | None = "Daft Punk",
    album: str | None = "Discovery",
    released: str | None = "2001",
) -> Path:
    """Write a tiny MP3, optionally tagged."""
    import mutagen

    path.write_bytes(_MP3_FRAME * 20)
    if artist is None and album is None and released is None:
        return path
    audio = mutagen.File(path, easy=True)
    if artist is not None:
        audio["artist"] = artist
    if album is not None:
        audio["album"] = album
    if released is not None:
        audio["date"] = released
    audio.save()
    return path


def _entry(path: Path, *, modified: datetime | None = None) -> FileEntry:
    return FileEntry(
        path=path,
        size=path.stat().st_size if path.exists() else 1,
        modified=modified or datetime(2026, 7, 1),
        extension=path.suffix.lower().lstrip("."),
    )


# -- extractors: happy paths -------------------------------------------------


def test_extract_exif_reads_date_taken(tmp_path: Path):
    meta = metadata.extract_exif(_make_jpeg(tmp_path / "photo.jpg"))
    assert meta["date_taken"] == date(2024, 5, 3)


def test_extract_pdf_reads_author_and_creation_date(tmp_path: Path):
    meta = metadata.extract_pdf(_make_pdf(tmp_path / "doc.pdf"))
    assert meta["author"] == "Ada Lovelace"
    assert meta["date_created"] == date(2024, 5, 3)


def test_extract_audio_tags_reads_artist_album_year(tmp_path: Path):
    meta = metadata.extract_audio_tags(_make_mp3(tmp_path / "song.mp3"))
    assert meta["artist"] == "Daft Punk"
    assert meta["album"] == "Discovery"
    assert meta["release_year"] == 2001


def test_extract_dispatches_by_extension(tmp_path: Path):
    assert metadata.extract(_make_jpeg(tmp_path / "p.jpg"), "jpg") == {
        "date_taken": date(2024, 5, 3)
    }
    assert metadata.extract(_make_pdf(tmp_path / "d.pdf"), "pdf")["author"]
    assert metadata.extract(_make_mp3(tmp_path / "s.mp3"), "mp3")["artist"]


def test_extract_year_only_audio_date_tag(tmp_path: Path):
    """A full ISO date tag still yields just the year."""
    meta = metadata.extract_audio_tags(
        _make_mp3(tmp_path / "song.mp3", released="2001-05-03")
    )
    assert meta["release_year"] == 2001


# -- extractors: degradation -------------------------------------------------


def test_corrupt_files_return_empty(tmp_path: Path):
    for name, blob in (
        ("bad.jpg", b"not an image at all"),
        ("bad.pdf", b"%PDF-1.4 then garbage"),
        ("bad.mp3", b"garbage" * 20),
    ):
        path = tmp_path / name
        path.write_bytes(blob)
        assert metadata.extract(path, path.suffix.lstrip(".")) == {}


def test_missing_file_returns_empty(tmp_path: Path):
    assert metadata.extract(tmp_path / "gone.jpg", "jpg") == {}


def test_files_without_metadata_return_empty(tmp_path: Path):
    assert metadata.extract_exif(_make_jpeg(tmp_path / "bare.jpg", taken=None)) == {}
    assert (
        metadata.extract_audio_tags(
            _make_mp3(tmp_path / "bare.mp3", artist=None, album=None, released=None)
        )
        == {}
    )


def test_pdf_without_author_omits_the_key(tmp_path: Path):
    meta = metadata.extract_pdf(_make_pdf(tmp_path / "anon.pdf", author=None))
    assert "author" not in meta
    assert meta["date_created"] == date(2024, 5, 3)


def test_unhandled_extension_returns_empty_without_reading(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    assert metadata.extract(path, "txt") == {}


def test_extract_does_not_swallow_programming_errors(tmp_path: Path, monkeypatch):
    """A corrupt file yields {}; a bug in an extractor must not look the same."""

    def boom(_path: Path) -> dict[str, object]:
        raise NotImplementedError("stub")

    monkeypatch.setattr(metadata, "extract_exif", boom)
    with pytest.raises(NotImplementedError):
        metadata.extract(_make_jpeg(tmp_path / "photo.jpg"), "jpg")


# -- metadata rules ----------------------------------------------------------


def test_metadata_rule_matches_via_metadata_key(tmp_path: Path):
    rule = Rule(
        rule="ada_papers",
        pattern="Ada*",
        destination="Papers/{author}",
        match_type=MatchType.METADATA,
        metadata_key="author",
        priority=10,
    )
    result = Classifier([rule]).classify(
        _entry(_make_pdf(tmp_path / "doc.pdf")), base=Path("out")
    )
    assert result.destination == Path("out/Papers/Ada Lovelace/doc.pdf")
    assert result.layer is RuleLayer.CUSTOM
    assert result.rule_name == "ada_papers"


def test_metadata_rule_matches_typed_non_string_value(tmp_path: Path):
    """release_year is an int; date_taken is a date. Globs still apply."""
    year_rule = Rule(
        rule="noughties",
        pattern="200*",
        destination="Music/{release_year}",
        match_type=MatchType.METADATA,
        metadata_key="release_year",
    )
    result = Classifier([year_rule]).classify(
        _entry(_make_mp3(tmp_path / "song.mp3")), base=Path("out")
    )
    assert result.destination == Path("out/Music/2001/song.mp3")

    date_rule = Rule(
        rule="may_2024",
        pattern="2024-05-*",
        destination="Shots",
        match_type=MatchType.METADATA,
        metadata_key="date_taken",
    )
    result = Classifier([date_rule]).classify(
        _entry(_make_jpeg(tmp_path / "photo.jpg")), base=Path("out")
    )
    assert result.destination == Path("out/Shots/photo.jpg")


def test_metadata_rule_stands_down_when_key_absent(tmp_path: Path):
    """A file without the key falls through to the next rule, not out of the loop."""
    rules = [
        Rule(
            rule="by_author",
            pattern="*",
            destination="Papers",
            match_type=MatchType.METADATA,
            metadata_key="author",
            priority=10,
        ),
        Rule(
            rule="catch_all_pdfs",
            pattern="*.pdf",
            destination="Fallback",
            priority=5,
        ),
    ]
    result = Classifier(rules).classify(
        _entry(_make_pdf(tmp_path / "anon.pdf", author=None)), base=Path("out")
    )
    assert result.destination == Path("out/Fallback/anon.pdf")
    assert result.rule_name == "catch_all_pdfs"


def test_metadata_rule_without_key_is_inert(tmp_path: Path):
    """The loader rejects this; a hand-built Rule must not crash the classifier."""
    rule = Rule(
        rule="keyless",
        pattern="*",
        destination="Nope",
        match_type=MatchType.METADATA,
    )
    result = Classifier([rule]).classify(
        _entry(_make_pdf(tmp_path / "doc.pdf")), base=Path("out")
    )
    assert result.rule_name == "extension_fallback"


# -- built-in metadata layer + precedence ------------------------------------


def test_metadata_layer_folders_photos_by_capture_date(tmp_path: Path):
    result = Classifier(use_metadata_layer=True).classify(
        _entry(_make_jpeg(tmp_path / "photo.jpg")), base=Path("out")
    )
    assert result.destination == Path("out/Images/Photos/2024/May/photo.jpg")
    assert result.layer is RuleLayer.METADATA
    assert result.rule_name == "exif_date_taken"


def test_metadata_layer_folders_music_by_artist_and_album(tmp_path: Path):
    result = Classifier(use_metadata_layer=True).classify(
        _entry(_make_mp3(tmp_path / "song.mp3")), base=Path("out")
    )
    assert result.destination == Path("out/Audio/Daft Punk/Discovery/song.mp3")
    assert result.layer is RuleLayer.METADATA


def test_metadata_layer_sanitises_tags_into_one_component(tmp_path: Path):
    """A tag with a separator must not silently nest directories."""
    result = Classifier(use_metadata_layer=True).classify(
        _entry(_make_mp3(tmp_path / "song.mp3", artist="AC/DC", album=None)),
        base=Path("out"),
    )
    assert result.destination == Path("out/Audio/AC_DC/song.mp3")


def test_layer_precedence_custom_beats_pattern_beats_metadata_beats_extension(
    tmp_path: Path,
):
    photo = _make_jpeg(tmp_path / "photo.jpg")
    screenshot = _make_jpeg(tmp_path / "Screenshot_2020-01-01.jpg")

    # extension: no metadata layer, nothing else matches.
    plain = Classifier().classify(_entry(photo), base=Path("out"))
    assert plain.layer is RuleLayer.EXTENSION

    # metadata beats extension.
    meta = Classifier(use_metadata_layer=True).classify(_entry(photo), base=Path("out"))
    assert meta.layer is RuleLayer.METADATA

    # pattern beats metadata (screenshot naming wins over EXIF date).
    pattern = Classifier(use_metadata_layer=True).classify(
        _entry(screenshot), base=Path("out")
    )
    assert pattern.layer is RuleLayer.PATTERN
    assert pattern.destination == Path("out/Screenshots/2020/Screenshot_2020-01-01.jpg")

    # custom beats everything.
    rule = Rule(rule="mine", pattern="*.jpg", destination="Mine", priority=100)
    custom = Classifier([rule], use_metadata_layer=True).classify(
        _entry(screenshot), base=Path("out")
    )
    assert custom.layer is RuleLayer.CUSTOM
    assert custom.destination == Path("out/Mine/Screenshot_2020-01-01.jpg")


# -- laziness (hard product requirement) -------------------------------------


def _spy_on_extract(monkeypatch) -> list[Path]:
    """Record every file metadata.extract is asked to open."""
    seen: list[Path] = []
    real = metadata.extract

    def spy(path: Path, extension: str) -> dict[str, object]:
        seen.append(path)
        return real(path, extension)

    monkeypatch.setattr(metadata, "extract", spy)
    return seen


def test_no_extraction_when_no_rule_needs_metadata(tmp_path: Path, monkeypatch):
    seen = _spy_on_extract(monkeypatch)
    classifier = Classifier([Rule(rule="pics", pattern="*.jpg", destination="Pics")])
    assert not classifier.needs_metadata

    classifier.classify(_entry(_make_jpeg(tmp_path / "photo.jpg")), base=Path("out"))
    classifier.classify(_entry(_make_mp3(tmp_path / "song.mp3")), base=Path("out"))

    assert seen == []  # not a single file opened


def test_metadata_match_type_triggers_extraction(tmp_path: Path, monkeypatch):
    seen = _spy_on_extract(monkeypatch)
    classifier = Classifier(
        [
            Rule(
                rule="by_author",
                pattern="Ada*",
                destination="Papers",
                match_type=MatchType.METADATA,
                metadata_key="author",
            )
        ]
    )
    assert classifier.needs_metadata

    path = _make_pdf(tmp_path / "doc.pdf")
    classifier.classify(_entry(path), base=Path("out"))
    assert seen == [path]


def test_metadata_placeholder_in_destination_triggers_extraction(
    tmp_path: Path, monkeypatch
):
    """A filename-matched rule still needs metadata if its template asks for it."""
    seen = _spy_on_extract(monkeypatch)
    classifier = Classifier(
        [Rule(rule="by_author", pattern="*.pdf", destination="Papers/{author}")]
    )
    assert classifier.needs_metadata

    result = classifier.classify(_entry(_make_pdf(tmp_path / "doc.pdf")), base=Path("out"))
    assert seen  # the {author} placeholder alone justified the read
    assert result.destination == Path("out/Papers/Ada Lovelace/doc.pdf")


def test_metadata_layer_triggers_extraction(tmp_path: Path, monkeypatch):
    seen = _spy_on_extract(monkeypatch)
    classifier = Classifier(use_metadata_layer=True)
    assert classifier.needs_metadata

    classifier.classify(_entry(_make_jpeg(tmp_path / "photo.jpg")), base=Path("out"))
    assert seen


def test_prepopulated_metadata_is_not_re_read(tmp_path: Path, monkeypatch):
    seen = _spy_on_extract(monkeypatch)
    entry = _entry(_make_jpeg(tmp_path / "photo.jpg"))
    entry.metadata = {"date_taken": date(1999, 12, 31)}

    result = Classifier(use_metadata_layer=True).classify(entry, base=Path("out"))
    assert seen == []
    assert result.destination == Path("out/Images/Photos/1999/December/photo.jpg")


# -- templating --------------------------------------------------------------


def test_absent_metadata_placeholder_falls_back(tmp_path: Path):
    rule = Rule(rule="by_author", pattern="*.pdf", destination="Papers/{author}")
    result = Classifier([rule]).classify(
        _entry(_make_pdf(tmp_path / "anon.pdf", author=None)), base=Path("out")
    )
    assert result.destination == Path("out/Papers/Unknown/anon.pdf")


def test_unknown_placeholder_raises_at_plan_time(tmp_path: Path):
    rule = Rule(rule="typo", pattern="*.pdf", destination="Papers/{authr}")
    with pytest.raises(ValueError, match="unknown placeholder"):
        Classifier([rule]).classify(
            _entry(_make_pdf(tmp_path / "doc.pdf")), base=Path("out")
        )


def test_date_taken_beats_filename_date_and_mtime_for_year(tmp_path: Path):
    # Filename says 2019, mtime says 2026, EXIF says 2024 -> EXIF wins.
    path = _make_jpeg(tmp_path / "holiday_2019-08-01.jpg")
    rule = Rule(rule="by_year", pattern="*.jpg", destination="Pics/{year}/{month}")
    result = Classifier([rule], use_metadata_layer=True).classify(
        _entry(path, modified=datetime(2026, 7, 1)), base=Path("out")
    )
    assert result.destination == Path("out/Pics/2024/May/holiday_2019-08-01.jpg")


def test_year_placeholder_alone_does_not_force_a_read(tmp_path: Path, monkeypatch):
    """Laziness beats EXIF precedence: {year} is not a metadata placeholder.

    date_taken outranks the filename/mtime chain *when it is present*, but a
    template asking only for {year} is not a reason to open every file. Such a
    rule keeps the cheap chain; opting in ({date_taken}, a metadata rule, or
    the metadata layer) is what buys EXIF accuracy.
    """
    seen = _spy_on_extract(monkeypatch)
    path = _make_jpeg(tmp_path / "holiday_2019-08-01.jpg")
    rule = Rule(rule="by_year", pattern="*.jpg", destination="Pics/{year}")
    classifier = Classifier([rule])
    assert not classifier.needs_metadata

    result = classifier.classify(
        _entry(path, modified=datetime(2026, 7, 1)), base=Path("out")
    )
    assert seen == []
    assert result.destination == Path("out/Pics/2019/holiday_2019-08-01.jpg")


def test_filename_date_beats_pdf_creation_date(tmp_path: Path):
    # PDF /CreationDate is 2024; the user typed 2019 into the name -> name wins.
    path = _make_pdf(tmp_path / "report_2019-08-01.pdf")
    rule = Rule(rule="by_year", pattern="*.pdf", destination="Docs/{year}/{author}")
    result = Classifier([rule]).classify(_entry(path), base=Path("out"))
    assert result.destination == Path(
        "out/Docs/2019/Ada Lovelace/report_2019-08-01.pdf"
    )


def test_creation_date_beats_mtime_for_year(tmp_path: Path):
    # {author} in the template is what justifies reading the PDF at all; once
    # read, its /CreationDate outranks mtime for {year}.
    path = _make_pdf(tmp_path / "report.pdf")
    rule = Rule(rule="by_year", pattern="*.pdf", destination="Docs/{year}/{author}")
    result = Classifier([rule]).classify(
        _entry(path, modified=datetime(2026, 7, 1)), base=Path("out")
    )
    assert result.destination == Path("out/Docs/2024/Ada Lovelace/report.pdf")


def test_metadata_key_cannot_shadow_the_year_placeholder(tmp_path: Path):
    """{year} is date-derived; a metadata dict cannot hijack it."""
    entry = _entry(_make_jpeg(tmp_path / "photo.jpg"))
    entry.metadata = {"date_taken": date(2024, 5, 3), "year": 1900}
    rule = Rule(rule="by_year", pattern="*.jpg", destination="Pics/{year}")
    result = Classifier([rule]).classify(entry, base=Path("out"))
    assert result.destination == Path("out/Pics/2024/photo.jpg")
