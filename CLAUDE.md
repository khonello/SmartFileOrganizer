# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The project is **scaffolded** and uses a **flat application layout** — the package modules live at the repo root (`models.py`, `organizer.py`, `core/`, `rules/`, `history/`, `gui/`), not under a nested `smart_file_organizer/` package. Imports are top-level (`from core.classifier import Classifier`, `from organizer import Organizer`). The deterministic core is real and tested (scan → classify → apply → commit/rollback, space preflight, dry-run, collision handling, preset/rule loading); the **metadata extractors** (`core/metadata.py`) and the **GUI** (`gui/`) are stubs that raise `NotImplementedError` with a docstring describing what to build. `README.md` is the functional/technical spec and `DESIGN_SPEC.md` the UI/visual spec — keep both in sync with what you build.

## What this app is

A **PySide6 desktop app** (Windows-only) that organizes files into a folder tree using a **deterministic rule engine — no AI/ML, no network, fully offline**. This is a hard product constraint, not an implementation detail: classification decisions must be traceable to an explicit rule. Do not introduce ML libraries, model inference, or cloud/API calls into the core classification path (an optional lightweight AI layer is listed only as out-of-scope future work).

## Commands

The project virtual environment is **`environ/`** at the repo root (gitignored) — activate it rather than creating a new one:

```bash
environ\Scripts\activate             # Windows (primary dev platform / only target)
pip install -r requirements-dev.txt  # runtime deps + pytest, ruff
python main.py                       # run the app (needs PySide6; GUI is a stub)

python -m pytest                     # run the test suite
python -m pytest tests/test_pipeline.py::test_rollback_restores_original  # single test
ruff check .                         # lint
```

The `tests/` suite covers the headless pipeline and imports no Qt, so the core is testable without PySide6 installed. Run commands from the repo root (pytest puts the root on `sys.path` via `pythonpath = ["."]`).

## Architecture (intended)

The app uses an **in-place before/after model** (a deliberate change from the README's original destructive move+undo design — the specs predate it; this section and `organizer.py` are the source of truth). Everything happens inside the *selected folder*, and planning stays separate from execution:

```
check_space → build_plan → [preview + approval] → apply → [review before/ vs after/] → commit
 (bail if      (classify,     (Preview Builder)      (move→before/,                      (discard before/,
  won't fit)    touch none)                           copy→after/, logged)                offload after/→root)
                                                                          └── rollback (discard after/, restore before/)
```

`apply` creates `before/` and `after/` subfolders: it **moves** the folder's originals into `before/` (same-volume rename, not duplicated) and builds an organized **copy** into `after/`. `commit` deletes `before/` and offloads `after/` into the root; `rollback` deletes `after/` and restores `before/`. Only the `after/` copy costs disk space, so `check_space` needs ~1× the folder size free.

Layout (flat, at repo root): `main.py` (entry point — `python main.py`), `models.py` (shared dataclasses — the contract between stages), `organizer.py` (headless service driving the whole lifecycle — the GUI drives this), `core/` (scanner, classifier, metadata, pattern_matcher, file_ops), `rules/` (presets + rule_loader), `history/` (SQLite db + undo_manager), `gui/` (main_window, preview_tree, settings_panel), `config/settings.json`.

`core/`, `models.py`, and `organizer.py` never import Qt, so they stay unit-testable in isolation; `main.py` and `gui/main_window.py` import Qt lazily inside functions.

### Rules that shape the code

- **Classifier only proposes; it never touches files.** `build_plan` is pure; all mutation lives in `apply`/`commit`/`rollback`. Keep these concerns separate.
- **Check space before applying.** `Organizer.check_space()` must pass before `apply` — never start a run that can't finish.
- **Classification is a layered pipeline with strict precedence** (highest to lowest): custom user rules → pattern-based → metadata-based → extension-based (fallback). Higher layers override lower ones. Metadata is **preset-driven** (only read when a rule/preset needs it).
- **Log before you copy.** Each copy is written to the SQLite history (source, destination, type, timestamp, `batch_id`) *before* the file is copied, so undo works after a mid-batch crash. `undo_manager` is the record-based/crash-recovery path; `Organizer.rollback` is the primary user-facing undo.
- **Collision handling** appends a suffix (`file (1).pdf`) by default; overwrite is opt-in only.
- **Dry-run mode** runs the full pipeline and produces the plan without touching the filesystem.

Rules and presets are JSON in `config/rules/*.json`; app settings in `config/settings.json`. Rule schema: `rule`, `pattern` (glob/regex), `match_type` (filename|extension|metadata), `destination` (template with `{year}/{month}/{project}`), `case_sensitive`, `priority`.

## UI / design constraints (from DESIGN_SPEC.md)

The visual design is deliberate and has **forbidden patterns** — read `DESIGN_SPEC.md` §7 before building or restyling any UI. Key non-negotiables:

- **Fixed 5:2 landscape aspect ratio** (`height = 0.4 × width`); the resize handler locks height on drag. Layout is composed in horizontal bands — no tall hero sections or multi-row toolbars.
- **Signature element:** the "Sorting Rail" (brass vertical line, left of the tree) where folder tabs animate in during scans. This is the one place the design spends energy.
- **QSS handles static states only** (default/hover/pressed/disabled). All timed motion (fades, slides, staggers) is done in code via `QPropertyAnimation` / `QGraphicsOpacityEffect`, since QSS has no animation syntax.
- **Forbidden:** colored left-edge accent bars (in any state), pill-shaped buttons/tags, drop shadows on dark surfaces, decorative gradients, numbered-sequence markers, stock icon-in-circle illustrations / emoji as functional icons. Selection/state is shown via fill, all-around border, glyph, or dot indicator.
- **Respect OS reduced-motion:** every animation must collapse to an instant state change; no animation is required to understand the UI.
- Design tokens (colors, type scale, fonts: Fraunces for section headers only, Inter for UI, IBM Plex Mono for filesystem values) are defined in `DESIGN_SPEC.md` §3 — use them rather than inventing new ones.
