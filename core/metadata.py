"""File metadata extraction (EXIF / PDF / audio tags).

Each extractor degrades gracefully: if the optional dependency is missing or
the file is malformed, it returns ``{}`` rather than raising, so a bad file
never aborts a scan. Populated into :attr:`FileEntry.metadata` lazily, only
when a rule's ``match_type`` is ``metadata`` (or a destination template asks
for a metadata placeholder) — see :meth:`core.classifier.Classifier.classify`.

Key/value schema
----------------
Every key an extractor can produce is listed in :data:`KNOWN_KEYS`. Values are
typed, not stringly-typed — the classifier's template renderer and metadata
layer both rely on these:

===============  ==============  =========================================
key              type            source
===============  ==============  =========================================
``date_taken``   ``datetime.date``  EXIF DateTimeOriginal / DateTime
``date_created`` ``datetime.date``  PDF ``/CreationDate``
``author``       ``str``            PDF ``/Author``
``artist``       ``str``            audio artist tag
``album``        ``str``            audio album tag
``release_year`` ``int``            audio date/year tag (year part only)
===============  ==============  =========================================

A key is *absent* rather than ``None`` when the file does not carry it, so
``entry.metadata.get(key)`` is the only check callers need.

.. note::
   The audio year tag is exposed as ``release_year``, not ``year``, to keep it
   distinct from the date-derived ``{year}`` destination placeholder (which
   answers "when was this file dated", not "when was this track released").
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

# Categories of extension each extractor knows how to read.
_IMAGE_EXT = {"jpg", "jpeg", "png", "heic", "tiff"}
_PDF_EXT = {"pdf"}
_AUDIO_EXT = {"mp3", "flac", "m4a", "wav"}

# Every metadata key the extractors below can emit. The classifier seeds its
# template namespace from this, so a placeholder for a key that is merely
# absent for one file renders a fallback instead of raising.
KNOWN_KEYS: tuple[str, ...] = (
    "date_taken",
    "date_created",
    "author",
    "artist",
    "album",
    "release_year",
)

# EXIF tag ids. DateTimeOriginal/DateTimeDigitized live in the Exif sub-IFD;
# DateTime is in the base IFD and is the weakest of the three (it is the last
# *modification* time, which editors rewrite).
_EXIF_IFD_POINTER = 0x8769
_DATETIME_ORIGINAL = 36867
_DATETIME_DIGITIZED = 36868
_DATETIME = 306


def extract(path: Path, extension: str) -> dict[str, object]:
    """Dispatch to the right extractor based on ``extension``.

    Returns a flat dict of metadata keys (see :data:`KNOWN_KEYS`). Extensions
    no extractor handles return ``{}`` without opening the file.

    Does not raise on *extraction* failures — a corrupt, truncated or
    unreadable file is a normal outcome and yields ``{}``. Each extractor
    catches its own library's error types; the ``OSError`` net here covers a
    file that vanished or turned unreadable between the scan and this call.
    Programming errors (``TypeError``, ``AttributeError``, ...) deliberately
    propagate rather than masquerading as "this file has no metadata".
    """
    ext = extension.lower()
    try:
        if ext in _IMAGE_EXT:
            return extract_exif(path)
        if ext in _PDF_EXT:
            return extract_pdf(path)
        if ext in _AUDIO_EXT:
            return extract_audio_tags(path)
    except OSError:  # file vanished / unreadable since the scan
        return {}
    return {}


def extract_exif(path: Path) -> dict[str, object]:
    """Read EXIF (``date_taken``) from an image via Pillow."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return {}

    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return {}
            # get_ifd() reads lazily, so it must happen inside the context.
            sub = exif.get_ifd(_EXIF_IFD_POINTER)
            raw = (
                sub.get(_DATETIME_ORIGINAL)
                or sub.get(_DATETIME_DIGITIZED)
                or exif.get(_DATETIME)
            )
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        # Pillow raises SyntaxError from some corrupt-file decoders.
        return {}

    taken = _parse_exif_datetime(raw)
    return {"date_taken": taken} if taken is not None else {}


def extract_pdf(path: Path) -> dict[str, object]:
    """Read PDF metadata (``author``, ``date_created``) via PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        from PyPDF2.errors import PyPdfError
    except ImportError:
        return {}

    try:
        info = PdfReader(str(path)).metadata
    except (PyPdfError, OSError, ValueError):
        return {}
    if info is None:
        return {}

    out: dict[str, object] = {}
    try:
        author = info.author
    except (PyPdfError, ValueError, KeyError):
        author = None
    if author and str(author).strip():
        out["author"] = str(author).strip()

    try:
        created = info.creation_date  # parses /CreationDate; may reject junk
    except (PyPdfError, ValueError, KeyError, TypeError):
        created = None
    if isinstance(created, datetime):
        out["date_created"] = created.date()
    return out


def extract_audio_tags(path: Path) -> dict[str, object]:
    """Read audio tags (``artist``, ``album``, ``release_year``) via mutagen."""
    try:
        import mutagen
    except ImportError:
        return {}

    try:
        # easy=True normalises ID3/Vorbis/MP4 tag names to a common vocabulary.
        audio = mutagen.File(path, easy=True)
    except (mutagen.MutagenError, OSError, ValueError):
        return {}
    if audio is None or not audio.tags:
        return {}

    out: dict[str, object] = {}
    for key in ("artist", "album"):
        value = _first_tag(audio.tags, key)
        if value:
            out[key] = value

    year = _parse_year(_first_tag(audio.tags, "date"))
    if year is not None:
        out["release_year"] = year
    return out


# -- parsing helpers ---------------------------------------------------------


def _parse_exif_datetime(raw: object) -> date | None:
    """Parse EXIF's ``YYYY:MM:DD HH:MM:SS`` into a ``date``.

    Cameras emit blank/zeroed stamps ("0000:00:00 00:00:00") for "unknown",
    which strptime rejects — treated the same as absent.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip().rstrip("\x00").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S").date()
    except ValueError:
        pass
    try:  # some writers omit the time half
        return datetime.strptime(text[:10], "%Y:%m:%d").date()
    except ValueError:
        return None


def _first_tag(tags: object, key: str) -> str | None:
    """Return the first value of ``key``, which mutagen exposes as a list."""
    try:
        value = tags.get(key)  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_year(raw: str | None) -> int | None:
    """Pull the year out of an audio date tag ("2001", "2001-05-03", ...)."""
    if not raw:
        return None
    head = raw.strip()[:4]
    if not head.isdigit():
        return None
    year = int(head)
    # Guard against nonsense tags rendering as folder names.
    return year if 1000 <= year <= 9999 else None
