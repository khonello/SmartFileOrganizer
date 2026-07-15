# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The project is **scaffolded** and uses a **flat application layout** — the package modules live at the repo root (`models.py`, `organizer.py`, `core/`, `rules/`, `history/`, `gui/`), not under a nested `smart_file_organizer/` package. Imports are top-level (`from core.classifier import Classifier`, `from organizer import Organizer`). The deterministic core is real and tested (scan → classify → apply → commit/rollback, space preflight, dry-run, collision handling, preset/rule loading, metadata extraction, settings + user-rule loading, history retention). The **GUI** (`gui/`) is the only remaining stub — it raises `NotImplementedError` with a docstring describing what to build. `README.md` is the functional/technical spec — keep it in sync with what you build. **There is no UI/visual design yet** — the design direction is being decided from scratch; don't assume a look until it's set.

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

Layout (flat, at repo root): `main.py` (entry point — `python main.py`), `models.py` (shared dataclasses — the contract between stages), `organizer.py` (headless service driving the whole lifecycle — the GUI drives this), `settings.py` (loads `config/settings.json`), `core/` (scanner, classifier, metadata, pattern_matcher, file_ops), `rules/` (presets + rule_loader), `history/` (SQLite db + undo_manager), `gui/` (main_window, preview_tree, settings_panel), `config/` (`settings.json` + user rules in `rules/`).

`core/`, `models.py`, `organizer.py`, and `settings.py` never import Qt, so they stay unit-testable in isolation; `main.py` and `gui/main_window.py` import Qt lazily inside functions.

### Rules that shape the code

- **Classifier only proposes; it never touches files.** `build_plan` is pure; all mutation lives in `apply`/`commit`/`rollback`. Keep these concerns separate.
- **Check space before applying.** `Organizer.check_space()` must pass before `apply` — never start a run that can't finish.
- **Classification is a layered pipeline with strict precedence** (highest to lowest): custom user rules → pattern-based → metadata-based → extension-based (fallback). Higher layers override lower ones.
- **Metadata is preset-driven, and this is a hard constraint, not an optimization.** Reading metadata means opening every file, so `Classifier.needs_metadata` is decided once per Classifier: true only if a rule has `match_type: metadata` or a destination template uses a key from `metadata.KNOWN_KEYS`. `Classifier.classify` is the *only* place that populates `FileEntry.metadata` — never do it in `scanner`. Classifying a folder with no metadata rules must not open a single file; there is a test asserting exactly this. Note `{year}` is date-derived and deliberately does **not** count as needing metadata (nearly every template uses it, so it would gut the laziness) — EXIF `date_taken` wins for `{year}` only when something else already justified the read.
- **`Classifier(use_metadata_layer=True)` is opt-in and currently unset by any caller** — the built-in metadata layer (photos by EXIF date, music by artist) costs a read per file, so it must be wired to a user-facing setting rather than switched on by default.
- **Log before you copy.** Each copy is written to the SQLite history (source, destination, type, timestamp, `batch_id`) *before* the file is copied, so undo works after a mid-batch crash. `undo_manager` is the record-based/crash-recovery path; `Organizer.rollback` is the primary user-facing undo. `apply` records the run itself the same way — before any file moves.
- **A run's state lives on disk, not in the app.** `BatchStatus.APPLIED` means `before/` and `after/` are real folders awaiting a decision; that survives closing the app. So `Organizer.pending_batch(folder)` / `is_scaffolded(folder)` exist to *resume* a run from a previous session. Check one of them before planning: a scaffolded folder plans as empty (everything in it is skipped as scaffolding), which reads as "nothing to organize" while the user's files sit staged in `before/`.
- **A batch snapshots the rules that produced it** (`batches.rules_json`). A run's trace is only meaningful against the rules in force when it ran, and presets get edited — a live reference would silently rewrite history. Global prefs (retention, db path) are *not* snapshotted; they're properties of the app, not of a run.
- **Undo is impossible after commit, not merely unimplemented.** The log records destinations under `after/`, but `commit` deletes `before/` and moves those copies to the folder root — the logged paths cease to exist and the originals are gone. `UndoManager` raises `CannotUndoError` rather than silently succeeding (it used to report success and do nothing). Never offer post-commit undo in the UI.
- **Collision handling** appends a suffix (`file (1).pdf`) by default; overwrite is opt-in only.
- **Dry-run mode** runs the full pipeline and produces the plan without touching the filesystem.

Rules and presets are JSON in `config/rules/*.json`; app settings in `config/settings.json`. Rule schema: `rule`, `pattern` (glob/regex), `match_type` (filename|extension|metadata), `destination` (template with `{year}/{month}/{project}`), `case_sensitive`, `priority`.

## UI

Two separate things, at different stages — don't conflate them:

**Structure is settled: see `UI_STRUCTURE.md`, which is the source of truth.** It
fixes the regions, the state machine, the per-run-status action matrix, and the
naming rules, with the reasoning for each. Highlights that are easy to get wrong:
the chain runs **sidebar selects → body follows → buttons follow the body**, with
*one* navigation system (the sidebar); the body is a **diff** with linked
selection, not two file browsers; `Review` state lives **on disk**, so a folder
can hold an unfinished run from a previous session (check `is_scaffolded` /
`pending_batch` before planning, or the plan comes back empty and reads as
"nothing to organize"); never ship the word **"Discard"** (ambiguous between the
irreversible commit and the safe rollback), and never offer undo after commit.

**Visual design does not exist.** A previous design spec and HTML prototype were
discarded. Do not assume a palette, typeface, or theme until the user establishes
one — ask for an anchor (a reference app, screenshot, palette, or mood) before
designing. Two prior attempts failed precisely because they were invented without
one. The fixed facts: it's a **PySide6** app on **Windows**, styled with **QSS**
(a limited subset of CSS — no flexbox/grid, no transitions) plus code-driven
animation (`QPropertyAnimation` / `QGraphicsOpacityEffect`), and it must respect
OS reduced-motion. The GUI modules in `gui/` are still stubs.
