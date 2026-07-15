"""File metadata extraction (EXIF / PDF / audio tags).

Each extractor degrades gracefully: if the optional dependency is missing or
the file is malformed, it returns ``{}`` rather than raising, so a bad file
never aborts a scan. Populated into :attr:`FileEntry.metadata` lazily, only
when a rule's ``match_type`` is ``metadata``.

STUB: signatures and fallbacks are in place; real extraction is TODO.
"""

from __future__ import annotations

from pathlib import Path

# Categories of extension each extractor knows how to read.
_IMAGE_EXT = {"jpg", "jpeg", "png", "heic", "tiff"}
_PDF_EXT = {"pdf"}
_AUDIO_EXT = {"mp3", "flac", "m4a", "wav"}


def extract(path: Path, extension: str) -> dict[str, object]:
    """Dispatch to the right extractor based on ``extension``.

    Returns a flat dict of metadata keys (e.g. ``date_taken``, ``author``).
    Never raises — returns ``{}`` on any failure.
    """
    ext = extension.lower()
    try:
        if ext in _IMAGE_EXT:
            return extract_exif(path)
        if ext in _PDF_EXT:
            return extract_pdf(path)
        if ext in _AUDIO_EXT:
            return extract_audio_tags(path)
    except Exception:  # noqa: BLE001 - metadata is best-effort
        return {}
    return {}


def extract_exif(path: Path) -> dict[str, object]:
    """Read EXIF (notably ``date_taken``) from an image. TODO: use Pillow."""
    raise NotImplementedError("EXIF extraction via Pillow not yet implemented")


def extract_pdf(path: Path) -> dict[str, object]:
    """Read PDF metadata (author, creation date). TODO: use PyPDF2."""
    raise NotImplementedError("PDF metadata via PyPDF2 not yet implemented")


def extract_audio_tags(path: Path) -> dict[str, object]:
    """Read audio tags (artist, album, year). TODO: use mutagen."""
    raise NotImplementedError("Audio tags via mutagen not yet implemented")
