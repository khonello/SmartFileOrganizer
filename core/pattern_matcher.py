"""Filename pattern detection via ``re`` / ``fnmatch``.

Two responsibilities:

* the baseline **extension -> category** map (the lowest classification layer);
* higher-level **pattern extraction** (dates, invoice/screenshot keywords,
  project + version) used by the pattern layer and by destination templating.

Everything here is plain string/glob/regex matching — deliberately no NLP.
"""

from __future__ import annotations

import fnmatch
import re
from datetime import date

# --- Extension -> category baseline (README "Extension-based") -------------

EXTENSION_CATEGORIES: dict[str, str] = {
    # Documents
    "pdf": "Documents", "doc": "Documents", "docx": "Documents",
    "txt": "Documents", "rtf": "Documents", "odt": "Documents",
    "md": "Documents", "tex": "Documents", "log": "Documents",
    "xls": "Documents", "xlsx": "Documents", "csv": "Documents",
    "ods": "Documents", "ppt": "Documents", "pptx": "Documents",
    "odp": "Documents", "pages": "Documents", "key": "Documents",
    "numbers": "Documents",
    # Ebooks
    "epub": "Ebooks", "mobi": "Ebooks", "azw": "Ebooks",
    "azw3": "Ebooks", "fb2": "Ebooks",
    # Images
    "jpg": "Images", "jpeg": "Images", "png": "Images", "gif": "Images",
    "bmp": "Images", "tiff": "Images", "tif": "Images", "svg": "Images",
    "webp": "Images", "heic": "Images", "avif": "Images", "ico": "Images",
    "psd": "Images", "ai": "Images", "raw": "Images", "cr2": "Images",
    "nef": "Images", "arw": "Images", "dng": "Images",
    # Video
    "mp4": "Video", "m4v": "Video", "avi": "Video", "mkv": "Video",
    "mov": "Video", "wmv": "Video", "flv": "Video", "webm": "Video",
    "mpg": "Video", "mpeg": "Video", "3gp": "Video",
    # Audio
    "mp3": "Audio", "wav": "Audio", "flac": "Audio", "m4a": "Audio",
    "aac": "Audio", "ogg": "Audio", "opus": "Audio", "wma": "Audio",
    "aiff": "Audio", "mid": "Audio", "midi": "Audio",
    # Archives
    "zip": "Archives", "rar": "Archives", "7z": "Archives",
    "tar": "Archives", "gz": "Archives", "bz2": "Archives",
    "xz": "Archives", "tgz": "Archives", "zst": "Archives",
    "iso": "Archives", "cab": "Archives",
    # Code
    "py": "Code", "js": "Code", "ts": "Code", "jsx": "Code", "tsx": "Code",
    "java": "Code", "kt": "Code", "c": "Code", "h": "Code", "cpp": "Code",
    "cs": "Code", "go": "Code", "rs": "Code", "rb": "Code", "php": "Code",
    "swift": "Code", "sh": "Code", "sql": "Code", "r": "Code", "lua": "Code",
    "pl": "Code", "dart": "Code", "scala": "Code", "vue": "Code",
    "html": "Code", "css": "Code", "scss": "Code", "json": "Code",
    "xml": "Code", "yaml": "Code", "yml": "Code", "toml": "Code",
    "ini": "Code", "ipynb": "Code",
    # Fonts
    "ttf": "Fonts", "otf": "Fonts", "woff": "Fonts", "woff2": "Fonts",
    # Installers / packages
    "exe": "Installers", "msi": "Installers", "dmg": "Installers",
    "pkg": "Installers", "deb": "Installers", "rpm": "Installers",
    "appimage": "Installers", "apk": "Installers",
    # Torrents
    "torrent": "Torrents",
}

DEFAULT_CATEGORY = "Others"


def category_for_extension(extension: str) -> str:
    """Map a bare extension (no dot, any case) to its baseline category."""
    return EXTENSION_CATEGORIES.get(extension.lower().lstrip("."), DEFAULT_CATEGORY)


# --- Pattern extraction -----------------------------------------------------

# ISO-ish date embedded in a filename, e.g. Invoice_2026-01-26.pdf
_DATE_RE = re.compile(r"(?P<year>\d{4})[-_.](?P<month>\d{2})(?:[-_.](?P<day>\d{2}))?")
# project_name_v1.2 -> ("project_name", "1.2")
_VERSION_RE = re.compile(r"(?P<name>.+?)[-_ ]v(?P<version>\d+(?:\.\d+)*)", re.IGNORECASE)


def extract_date(filename: str) -> date | None:
    """Return the first date embedded in ``filename``, or ``None``.

    Day defaults to the 1st when the filename carries only year+month.
    """
    m = _DATE_RE.search(filename)
    if not m:
        return None
    try:
        return date(
            int(m.group("year")),
            int(m.group("month")),
            int(m.group("day") or 1),
        )
    except ValueError:
        return None


def extract_version(filename: str) -> tuple[str, str] | None:
    """Return ``(project_name, version)`` if a ``vX.Y`` marker is present."""
    m = _VERSION_RE.search(filename)
    if not m:
        return None
    return m.group("name").strip("_- "), m.group("version")


def matches(name: str, pattern: str, *, case_sensitive: bool = False) -> bool:
    """Glob-match ``name`` against ``pattern`` (fnmatch semantics)."""
    if case_sensitive:
        return fnmatch.fnmatchcase(name, pattern)
    return fnmatch.fnmatch(name.lower(), pattern.lower())
