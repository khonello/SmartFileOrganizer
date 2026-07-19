"""Application settings loaded from ``config/settings.json``.

Lives at the repo root next to :mod:`models` and :mod:`organizer` rather than in
``config/`` — ``config/`` holds data, not code, and the flat layout keeps
importable modules at the top level.

Two failure modes, deliberately handled differently:

* **Absent** — a missing file, an empty file, or a missing key falls back to the
  documented default. The app must never refuse to start because nobody has
  written a config yet.
* **Malformed** — a key that *is* present but holds a value the app cannot honor
  (``"collision_strategy": "banana"``) raises :class:`SettingsError`. Silently
  substituting a default there would organize the user's files under settings
  they never chose, which is worse than a loud failure.

Like ``core``/``models``/``organizer``, this module never imports Qt.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from models import CollisionStrategy

CONFIG_DIR = Path(__file__).resolve().parent / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

APP_NAME = "SmartFileOrganizer"

DEFAULT_COLLISION_STRATEGY = CollisionStrategy.APPEND_SUFFIX
DEFAULT_DRY_RUN = True
DEFAULT_RETENTION_DAYS = 30


class SettingsError(ValueError):
    """Raised when settings.json holds a value the app cannot honor."""


def default_db_path() -> Path:
    """Where the operation history lives when settings don't say otherwise.

    ``%LOCALAPPDATA%\\SmartFileOrganizer\\history.sqlite3`` — the Windows
    convention for per-user, machine-local, non-roaming app data. The repo root
    is wrong for it: the db is user data, not source, and an installed app's
    program directory is typically read-only. Falls back to a home-relative
    directory off Windows so the headless tests stay portable.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path.home() / ".local" / "share"
    return base / APP_NAME / "history.sqlite3"


@dataclass(frozen=True)
class Settings:
    """Resolved app settings. Constructing with no arguments yields defaults."""

    collision_strategy: CollisionStrategy = DEFAULT_COLLISION_STRATEGY
    # The default only; `dry_run` stays a per-call keyword on Organizer.apply /
    # commit / rollback, so a single Organizer can plan a dry run and then a real
    # one. The caller (the GUI) passes this value through per call.
    dry_run_default: bool = DEFAULT_DRY_RUN
    # 0 disables pruning (keep history forever).
    history_retention_days: int = DEFAULT_RETENTION_DAYS
    # Opt-in "smart media": sort photos by EXIF date and music by artist/album.
    # Off by default because it opens every file — a real cost the plain
    # type→folder model never pays. Wired to a Rules-page toggle.
    use_metadata_layer: bool = False
    history_db_path: Path = field(default_factory=default_db_path)


def load_settings(path: Path | str | None = None) -> Settings:
    """Read settings from ``path`` (default ``config/settings.json``).

    Missing file, empty file, or missing keys -> defaults. A present-but-invalid
    value raises :class:`SettingsError`.
    """
    path = Path(path) if path is not None else SETTINGS_PATH
    return _from_dict(_read_json(path), source=path)


def _read_json(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:  # unreadable file: report it rather than guess
        raise SettingsError(f"{path}: could not be read — {exc}") from exc

    if not text.strip():  # zero-byte file == never written
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{path}: invalid JSON — {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: expected a JSON object")
    return data


def _from_dict(data: dict, *, source: Path) -> Settings:
    defaults = Settings()
    return Settings(
        collision_strategy=_collision_strategy(
            data, defaults.collision_strategy, source
        ),
        dry_run_default=_bool(
            data, "dry_run_default", defaults.dry_run_default, source
        ),
        history_retention_days=_retention_days(
            data, defaults.history_retention_days, source
        ),
        use_metadata_layer=_bool(
            data, "use_metadata_layer", defaults.use_metadata_layer, source
        ),
        history_db_path=_db_path(data, defaults.history_db_path, source),
    )


def save_settings(settings: Settings, *, path: Path | str | None = None) -> Path:
    """Write settings back to ``config/settings.json`` (for the Rules toggle).

    Serializes the known keys only; ``history_db_path`` is written as text.
    """
    path = Path(path) if path is not None else SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "collision_strategy": settings.collision_strategy.value,
        "dry_run_default": settings.dry_run_default,
        "history_retention_days": settings.history_retention_days,
        "use_metadata_layer": settings.use_metadata_layer,
        "history_db_path": str(settings.history_db_path),
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# -- per-key coercion --------------------------------------------------------
#
# Each helper returns the default when the key is absent and raises when it is
# present but unusable. `bool` is checked explicitly where an int is wanted:
# it is an int subclass, so `"history_retention_days": true` would otherwise
# sail through as 1.


def _bool(data: dict, key: str, default: bool, source: Path) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise SettingsError(f"{source}: {key} must be true or false, got {value!r}")
    return value


def _collision_strategy(
    data: dict, default: CollisionStrategy, source: Path
) -> CollisionStrategy:
    value = data.get("collision_strategy", default)
    try:
        # CollisionStrategy subclasses str, so the raw JSON value parses directly.
        return CollisionStrategy(value)
    except ValueError as exc:
        known = ", ".join(s.value for s in CollisionStrategy)
        raise SettingsError(
            f"{source}: unknown collision_strategy {value!r} (expected one of: {known})"
        ) from exc


def _retention_days(data: dict, default: int, source: Path) -> int:
    value = data.get("history_retention_days", default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SettingsError(
            f"{source}: history_retention_days must be a non-negative integer "
            f"(0 = keep forever), got {value!r}"
        )
    return value


def _db_path(data: dict, default: Path, source: Path) -> Path:
    value = data.get("history_db_path")
    if value is None:  # absent or explicitly null -> platform default
        return default
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(
            f"{source}: history_db_path must be a non-empty string, got {value!r}"
        )
    # Let users write %LOCALAPPDATA%\... or ~\... as they would in any Windows path.
    return Path(os.path.expandvars(value)).expanduser()
