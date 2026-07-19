"""The organization model: sort files into folders by type.

Every file falls into a **category** by its extension (Images, Documents, …);
each category has a **default destination** (its own name), and the user may
**override** where any category goes. That's the whole model — no patterns, no
priorities, no templates. Overrides live in ``config/mappings.json``; a category
with no override uses its default, so the app works out of the box.

Headless, no Qt — lives at the repo root next to :mod:`settings`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.pattern_matcher import DEFAULT_CATEGORY, EXTENSION_CATEGORIES

CONFIG_DIR = Path(__file__).resolve().parent / "config"
MAPPINGS_PATH = CONFIG_DIR / "mappings.json"


def categories() -> list[str]:
    """The categories a file can fall into, in display order.

    Derived from the extension map (so it can't drift from what the classifier
    actually produces), with the catch-all ``Others`` last.
    """
    ordered = list(dict.fromkeys(EXTENSION_CATEGORIES.values()))
    ordered.append(DEFAULT_CATEGORY)
    return ordered


def default_destination(category: str) -> str:
    """Where a category goes with no override — its own name."""
    return category


def clean_destination(text: str) -> str:
    """Normalize user input to a safe relative folder path (may be empty).

    Strips drive/leading separators and ``.``/``..`` segments so an override
    can never escape the organized root or become absolute. Empty means "no
    override" (fall back to the default).
    """
    parts = [p for p in re.split(r"[\\/]+", text.strip()) if p not in ("", ".", "..")]
    return "/".join(parts)


def load_mappings(path: Path | str | None = None) -> dict[str, str]:
    """Load the category overrides. Missing/unreadable/corrupt file -> none.

    Only known categories with a non-empty string destination are kept, so a
    hand-edited file can't inject junk into the classifier.
    """
    path = Path(path) if path is not None else MAPPINGS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    valid = set(categories())
    return {
        key: value
        for key, value in data.items()
        if key in valid and isinstance(value, str) and value.strip()
    }


def save_mappings(
    mappings: dict[str, str], *, path: Path | str | None = None
) -> Path:
    """Write the overrides wholesale (empty dict clears them all)."""
    path = Path(path) if path is not None else MAPPINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mappings, indent=2), encoding="utf-8")
    return path


def effective(mappings: dict[str, str]) -> dict[str, str]:
    """The full category -> destination map: defaults with overrides applied."""
    resolved = {category: default_destination(category) for category in categories()}
    resolved.update({k: v for k, v in mappings.items() if k in resolved})
    return resolved
