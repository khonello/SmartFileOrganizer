# Smart File Organizer

A desktop application that automatically organizes files into a logical, structured folder tree using **rule-based classification and metadata analysis**. No machine learning required — every organizational decision is deterministic, transparent, and traceable to an explicit rule.

---

## Table of Contents

- [Overview](#overview)
- [Core Objectives](#core-objectives)
- [Features](#features)
- [Classification Logic](#classification-logic)
- [Technical Architecture](#technical-architecture)
- [System Design](#system-design)
- [Data Model](#data-model)
- [User Workflow](#user-workflow)
- [Sample Output Structures](#sample-output-structures)
- [Installation](#installation)
- [Configuration](#configuration)
- [Development Timeline](#development-timeline)
- [Deliverables](#deliverables)
- [Design Rationale](#design-rationale)
- [Future Work](#future-work)

---

## Overview

Smart File Organizer scans a chosen folder (or drive), classifies every file using extension checks, metadata, and pattern matching, and proposes a clean folder structure. Users **preview** every proposed change before anything is moved. Organization is non-destructive: on Apply, the folder's originals are staged into a `before/` subfolder and an organized copy is built in `after/`, so the two can be compared side by side. The originals are only removed when the user explicitly **commits**; a **rollback** restores the folder at any time.

The project intentionally avoids AI/ML in favor of a rule engine. This keeps behavior predictable, keeps the app fast and fully offline, and keeps the codebase easy to reason about, test, and defend academically.

---

## Core Objectives

- Automate tedious manual file organization
- Use deterministic rules and file metadata — not AI/ML — for classification
- Provide a clean, trustworthy UI with preview and undo
- Allow power users to define their own custom rules
- Keep the system fully offline with no external dependencies

---

## Features

### Phase 1 — Core Engine
- Recursive folder/drive scanning
- Classification by file extension and basic metadata
- Automatic folder structure generation
- Safe file movement (handles name collisions and duplicates)
- Preview mode showing before/after tree comparison

### Phase 2 — Smart Rules (Non-AI "smart" layer)
- Regex/pattern matching on filenames (dates, invoice numbers, project names, version numbers)
- Metadata extraction: EXIF (photos), PDF metadata (author/date), audio/video tags
- Keyword matching in filenames (plain string/pattern matching — no NLP)
- Grouping files by name similarity, date range, or size

### Phase 3 — Usability & Safety
- Undo/rollback via operation history log
- User-defined custom rules (JSON/YAML)
- Preset templates: Downloads cleanup, Photo organization, Work files
- Dry-run mode
- Progress tracking for large batches

---

## Classification Logic

Files are classified through a layered pipeline. Each layer can override the previous one, with **custom rules always taking highest priority**.

### 1. Extension-based (baseline)
| Category | Extensions |
|---|---|
| Documents | `.pdf`, `.docx`, `.txt`, `.xlsx` |
| Images | `.jpg`, `.png`, `.gif`, `.svg` |
| Video | `.mp4`, `.avi`, `.mkv` |
| Audio | `.mp3`, `.wav`, `.flac` |
| Archives | `.zip`, `.rar`, `.7z` |
| Code | `.py`, `.js`, `.java`, `.cpp` |

### 2. Metadata-based
- Photos sorted by EXIF "date taken"
- Documents sorted by creation/modification date
- Optional size-based grouping (small / medium / large)

### 3. Pattern-based
| Input filename | Detected pattern | Destination |
|---|---|---|
| `Invoice_2026-01-26.pdf` | date + keyword | `2026/January/Invoices/` |
| `project_name_v1.2.docx` | project + version | `Projects/project_name/` |
| `Screenshot_2026-03-11.png` | screenshot prefix | `Screenshots/2026/` |

### 4. Custom rules (user-defined)
```json
{
  "rule": "contains_invoice",
  "pattern": "*invoice*",
  "destination": "Work/Invoices/{year}/{month}",
  "case_sensitive": false
}
```

**Rule precedence (highest to lowest):**
1. Custom user rules
2. Pattern-based rules
3. Metadata-based rules
4. Extension-based rules (fallback/default)

---

## Technical Architecture

| Layer | Technology | Purpose |
|---|---|---|
| GUI | PySide6 | Desktop interface, drag-and-drop support (Windows) |
| File operations | `pathlib`, `shutil`, `os` | Scanning, moving, renaming |
| Metadata reading | `Pillow` (EXIF), `PyPDF2` (PDF), `mutagen` (audio/video) | Extracting file metadata |
| Pattern matching | `re`, `fnmatch` | Filename pattern detection |
| Date parsing | `datetime`, `dateutil` | Normalizing dates from filenames/metadata |
| Storage | SQLite | Operation history, undo log |
| Storage | JSON / YAML | User rules, presets, app settings |

No ML libraries, no model inference, no cloud APIs — everything runs locally and instantly.

### Module Breakdown

The project uses a **flat application layout** — modules live at the repo root
(no nested package), imported top-level (`from core.classifier import Classifier`).
Run with `python main.py`.

```
SmartFileOragnizer/            # repo root = the project
├── main.py                    # Entry point (python main.py)
├── models.py                  # Shared dataclasses (the contract between stages)
├── organizer.py               # Headless service driving the before/after lifecycle
├── core/
│   ├── scanner.py             # Recursive directory scanning
│   ├── classifier.py          # Rule engine — applies classification layers
│   ├── metadata.py            # EXIF / PDF / audio metadata extraction (lazy)
│   ├── pattern_matcher.py     # Regex/fnmatch-based filename parsing + extension map
│   └── file_ops.py            # Copy/move, collision handling, disk-space preflight
├── rules/
│   ├── presets/               # Built-in preset rule sets (JSON)
│   │   ├── downloads_cleanup.json
│   │   ├── photo_organization.json
│   │   └── work_files.json
│   └── rule_loader.py         # Loads/validates preset + user-defined rules
├── history/
│   ├── database.py            # SQLite operation log + run records
│   └── undo_manager.py        # Record-based rollback (crash recovery)
├── gui/                       # PySide6 UI (stub)
│   ├── main_window.py
│   ├── preview_tree.py        # Before/after tree comparison widget
│   └── settings_panel.py
├── config/
│   └── settings.json
└── tests/                     # Headless pipeline tests (no Qt required)
```

---

## System Design

### Processing Pipeline (before/after model)

Organization happens **in place, inside the selected folder**, via a
non-destructive before/after staging model:

```
┌──────────────┐   ┌─────────────┐   ┌──────────────┐   ┌────────────────┐
│ Space check   │─▶ │   Scanner    │─▶ │  Classifier  │─▶ │ Preview Builder │
│ (bail if full)│   │ (recursive)  │   │ (rule engine)│   │ (tree diff)     │
└──────────────┘   └─────────────┘   └──────────────┘   └────────────────┘
                                                                  │
                                                                  ▼
                                                        ┌───────────────────┐
                                                        │  User Review/Edit  │
                                                        └───────────────────┘
                                                                  │  approve
                                                                  ▼
                          ┌──────────────┐          ┌────────────────────────────┐
                          │  Undo Log    │ ◀─ log ── │  Apply                      │
                          │  (SQLite)    │           │  move originals → before/   │
                          └──────────────┘           │  copy organized → after/    │
                                                      └────────────────────────────┘
                                                                  │
                                            ┌─────────────────────┴─────────────────────┐
                                            ▼                                             ▼
                            ┌────────────────────────────┐          ┌────────────────────────────┐
                            │  Commit ("discard old")     │          │  Rollback / Cancel          │
                            │  delete before/,            │          │  delete after/,             │
                            │  offload after/ → root      │          │  restore before/ → root     │
                            └────────────────────────────┘          └────────────────────────────┘
```

### Safety Principles
- **Check disk space first.** Because `before/` (the moved originals) and `after/` (the organized copy) coexist during review, Apply is refused up front if the copy won't fit — a run never starts unless it can finish. Only the `after/` copy costs space; moving originals into `before/` is a same-volume rename.
- **Nothing is destructive until you commit.** Apply only *stages* (originals move into `before/`, an organized copy is built in `after/`); the originals aren't deleted until you explicitly **commit** ("discard old directory"). **Rollback** at any point restores the folder exactly.
- **Nothing moves without preview approval.** The classifier only produces a proposed plan; Apply is a separate, explicit step, and Commit is a third.
- **Every copy is logged** with source path, destination path, and timestamp *before* it's performed, enabling recovery even if the app crashes mid-batch.
- **Collision handling**: if a destination file already exists, the app appends a suffix (`file (1).pdf`) rather than overwriting, unless the user opts into overwrite mode.
- **Dry-run mode**: runs the full pipeline and shows the resulting plan without touching the filesystem.

---

## Data Model

### Operation History (SQLite)

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Unique operation ID |
| `batch_id` | TEXT | Groups operations from the same run (for batch undo) |
| `source_path` | TEXT | Original file location |
| `destination_path` | TEXT | New file location |
| `operation_type` | TEXT | `copy` (Apply, default) / `move` (used when discarding) / `rename` |
| `timestamp` | DATETIME | When the operation was executed |
| `undone` | BOOLEAN | Whether this operation has been rolled back |

### Run Records (SQLite)

One row per organization run — *what produced it*, not just what it did.

| Column | Type | Description |
|---|---|---|
| `batch_id` | TEXT PK | Ties the run to its operations |
| `folder` | TEXT | The organized folder |
| `preset` | TEXT | Preset the run used, if any |
| `collision_strategy` | TEXT | Strategy in force for this run |
| `rules_json` | TEXT | **Snapshot** of the rules that produced the run |
| `status` | TEXT | `applied` / `committed` / `rolled_back` |
| `started_at` | DATETIME | When the run began |

Two properties this exists for:

**The rules are frozen, not referenced.** A run's rule trace ("this file matched
`invoice_detection`") only means something against the rules in force when it
ran. Presets get edited; a live reference would silently rewrite history.

**`status` is what makes undo honest.** `applied` means `before/` and `after/`
are real folders on disk awaiting a decision — a state that outlives the app,
so a run can be *resumed* in a later session (`Organizer.pending_batch`). Once
`committed`, undo is **impossible**: the originals are gone and the logged
`after/` paths no longer exist, so `UndoManager` raises `CannotUndoError`
rather than reporting a success it didn't perform. Pruning protects `applied`
runs automatically, and a run record is deleted with its operations.

### Rule Definition (JSON)

```json
{
  "rule": "string (unique identifier)",
  "pattern": "string (glob)",
  "match_type": "filename | extension | metadata",
  "metadata_key": "string (required when match_type is metadata)",
  "destination": "string (template with {year}/{month}/{project} etc.)",
  "case_sensitive": "boolean",
  "priority": "integer (higher = evaluated first)"
}
```

`metadata_key` names the metadata field `pattern` is tested against — one of
`date_taken`, `date_created`, `author`, `artist`, `album`, `release_year`
(`core.metadata.KNOWN_KEYS`). Loading a `metadata` rule without it is an error,
since there would be nothing to match. Dates are compared as ISO text, so
`"pattern": "2024-*"` selects a whole year.

Destination templates accept `{year}`, `{month}`, `{month_num}`, `{project}`,
`{category}`, and any of the metadata keys above. `{year}` stays date-derived
(EXIF capture date, else a date in the filename, else creation date, else
mtime) and is never shadowed by a metadata field.

**Presets and user rules.** Presets ship in `rules/presets/*.json`; user rules
live in `config/rules/*.json` and outrank them — a user rule reusing a preset's
`rule` id replaces it. Files prefixed `_` or `.` are ignored. Rules requiring
metadata are only evaluated when metadata is read, which happens *only* if some
rule asks for it (see Performance below).

---

## User Workflow

1. **Select folder** to organize
2. **Choose a preset strategy** (Downloads, Photos, Work Files) or define custom rules
3. App runs a **disk-space check**, then **scans** files and applies the rule pipeline
4. User **previews** the proposed tree structure with file counts
5. User can **adjust** individual files or tweak rules before applying
6. **Apply** — originals are staged into `before/`, an organized copy is built in `after/` (real-time progress bar)
7. **Review** `before/` vs `after/`, then either **Commit** (discard originals, offload `after/` into the folder) or **Rollback** (restore the original folder)

---

## Sample Output Structures

**Downloads cleanup**
```
Downloads/
├── Documents/ (by month)
├── Images/ (by date taken)
├── Installers/ (.exe, .dmg, .pkg)
├── Archives/ (.zip, .rar)
└── Others/
```

**Photo organization**
```
Photos/
├── 2026/
│   ├── January/
│   └── February/
├── Screenshots/
└── Edited/
```

**Work files**
```
Work/
├── Projects/
│   └── [project_name]/
├── Documents/
│   ├── Invoices/
│   └── Reports/
└── Archives/
```

---

## Installation

> Prototype/development instructions — Windows is the primary (and only) target.

```powershell
# Clone the repository
git clone <repo-url>
cd SmartFileOragnizer

# Activate the project virtual environment (named "environ")
environ\Scripts\activate
# (to create it fresh: python -m venv environ)

# Install dependencies
pip install -r requirements.txt      # add -dev for pytest/ruff

# Run the application
python main.py
```

### Requirements
```
PySide6
Pillow
PyPDF2
mutagen
python-dateutil
```

---

## Configuration

User rules and presets live in `config/rules/*.json`. Example custom rule file:

```json
{
  "rules": [
    {
      "rule": "invoice_detection",
      "pattern": "*invoice*",
      "match_type": "filename",
      "destination": "Work/Invoices/{year}/{month}",
      "case_sensitive": false,
      "priority": 10
    },
    {
      "rule": "screenshot_detection",
      "pattern": "Screenshot_*",
      "match_type": "filename",
      "destination": "Screenshots/{year}",
      "case_sensitive": false,
      "priority": 8
    }
  ]
}
```

App-level settings (`config/settings.json`), loaded by `settings.load_settings()`:
```json
{
  "default_preset": "downloads_cleanup",
  "collision_strategy": "append_suffix",
  "dry_run_default": true,
  "history_retention_days": 30,
  "history_db_path": "%LOCALAPPDATA%\\SmartFileOrganizer\\history.sqlite3"
}
```

| Key | Meaning |
|---|---|
| `default_preset` | Preset loaded when none is chosen |
| `collision_strategy` | `append_suffix` (default) / `overwrite` / `skip` |
| `dry_run_default` | Default for the dry-run toggle; `dry_run` stays a per-call argument |
| `history_retention_days` | Operations older than this are pruned; `0` keeps them forever |
| `history_db_path` | Operation log location; `%VARS%` and `~` are expanded |

A missing file or key falls back to the documented default, so the app always
starts. A key that is *present but unusable* (`"collision_strategy": "banana"`)
raises rather than silently organizing files under settings nobody chose.

---

## Development Timeline (12 weeks)

| Weeks | Focus |
|---|---|
| 1–2 | Requirements analysis, UI mockups, tech stack setup |
| 3–5 | Core scanning engine + rule engine implementation |
| 6–8 | GUI development (main window, tree view, preview, settings) |
| 9–10 | Metadata extraction, pattern matching, undo system |
| 11–12 | Testing, polish, documentation, demo preparation |

---

## Deliverables

1. Working desktop application
2. User manual with screenshots
3. Technical documentation (this document)
4. Test report across representative scenarios
5. Demo video
6. Written academic project report

---

## Design Rationale

**Why rule-based instead of AI/ML?**
- **Deterministic & debuggable** — every classification decision traces back to a specific rule, which matters for both user trust and academic defensibility.
- **Fast and fully offline** — no model inference latency, no GPU requirement, no API costs or network dependency.
- **Simpler scope for a semester project** — avoids the risk of AI integration eating the whole timeline while still leaving room to demonstrate strong engineering: system design, safe file I/O, rule engine architecture, and UX around preview/undo.
- **Easier to test** — rule-based logic has clear, enumerable test cases; ML classification would require labeled datasets and probabilistic evaluation.

**Why preview-before-apply?**
File organization tools that silently move files erode user trust. Separating "planning" from "execution" as distinct pipeline stages makes the system safer and makes the undo log meaningful (every executed operation was explicitly approved).

---

## Future Work

Potential extensions beyond the current scope, not required for the core deliverable:

- Optional lightweight AI layer (e.g., simple text/image classification) as a stretch goal if time permits
- Cloud storage integration (Google Drive, Dropbox)
- Scheduled/automatic organization via filesystem watching (`watchdog`)
- Cross-device sync of rules and presets
- Reinforcement-style feedback loop that adjusts rule priority based on user corrections
