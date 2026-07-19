# TODO

Step-by-step build plan for Smart File Organizer. Check items off (`- [x]`) as
they land. Ordering is roughly dependency-first: core → metadata → services →
GUI → polish. See `README.md` (functional spec) and `CLAUDE.md` (architecture +
decisions). No UI/visual design exists yet — it will be created from scratch.

---

## Phase 0 — Project setup
- [x] Scaffold flat application layout (modules at repo root, `python main.py` entry)
- [x] `models.py` shared dataclasses (the contract between stages)
- [x] `pyproject.toml`, `requirements.txt` / `requirements-dev.txt`, `.gitignore`
- [x] Virtual environment (`environ/`)
- [x] Docs: `README.md`, `CLAUDE.md`
- [x] Initial git commit of the scaffold

## Phase 1 — Core engine
- [x] `core/scanner.py` — recursive scan → `FileEntry` (size, mtime, extension)
- [x] `core/pattern_matcher.py` — extension→category map + date/version extraction
- [x] `core/classifier.py` — layered rule engine with strict precedence
      (custom → pattern → metadata → extension)
- [x] `core/file_ops.py` — copy/move, collision handling (append-suffix default),
      disk-space preflight, promote/remove primitives
- [x] `organizer.py` — before/after lifecycle: `check_space` → `build_plan` →
      `apply` (stage `before/`, copy `after/`) → `commit` / `rollback`
- [x] `history/database.py` — SQLite operation log (log-before-copy, `batch_id` grouping)
- [x] `history/undo_manager.py` — record-based rollback
- [x] `rules/rule_loader.py` + 3 presets (downloads / photos / work)
- [x] Headless pipeline tests (no Qt) — 14 passing

## Phase 2 — GUI  ⭐ current
> Swapped ahead of metadata so the UI can be seen and validated early.
> First design attempt was discarded; visual direction restarts from scratch.

### 2A — Structure  ✅ agreed → **`UI_STRUCTURE.md`**
Settled by argument and written up with the reasoning intact. The chain is
**sidebar selects → body follows → buttons follow the body**; one navigation
system; the body is a *diff*, not two file browsers. `UI_STRUCTURE.md` is the
source of truth — read it before building any of 2C.

- [x] Regions, state machine, per-status action matrix, naming rules
- [x] Per-run rule snapshot, so history is reproducible — **landed** (`batches`)
- [x] Dropped the dry-run toggle: Preview *is* the dry run

### 2B — Design direction  ✅ anchored → **`DESIGN.md`**
- [x] **Anchor from the user**: neutral base + single amber accent
      (`#000000 #14213d #fca311 #e5e5e5 #ffffff`), chosen over a monochrome blue
      ramp because this app needs hue contrast for caution and for the badges
- [x] Design language written up as a fresh spec — `DESIGN.md` (tokens, button
      roles, badges, diff, light+dark, contrast rules)
- [~] No HTML prototype — QSS ≠ HTML, and the greybox already validates the
      structure in the real medium; styling goes straight onto it (see 2D)

### 2C — Greybox shell  ✅ built (unstyled, run it: `python main.py`)
Structure proved in the real medium before any styling. Drives the real
`Organizer` end to end.

- [x] `gui/main_window.py` — shell, the `AppState` machine, one `_sync()` that
      decides every button's legality
- [x] `gui/preview_tree.py` — the diff panes; linked selection; layer badges
- [x] `gui/settings_panel.py` — inspector: rule trace for the selected file
- [x] `gui/worker.py` — scan/apply off the UI thread, progress marshalled back
- [x] Sidebar with history from `db.recent_batches()`; pending runs badged
- [x] Wire to `Organizer`: space check → preview → Apply → Commit / Rollback
- [x] **Resume** on folder select via `is_scaffolded` / `pending_batch`
- [x] States: empty / scanning / no-space / applying / review / committed / error
- [x] Threading — and it immediately found two real bugs (see `UI_STRUCTURE.md`):
      `HistoryDB` needed a lock, and a stale `QThread` handle crashed the app on
      close after any run
- [x] Review/Resume panes read from `before/`/`after/` on disk via
      `Organizer.review_plan` — rebuilt from the operation log (actual
      destinations, collision suffix and all) with badges re-derived from the
      batch's snapshot rules. A resumed run now shows the same honest diff as a
      fresh apply (test: `test_review_plan_reconstructs_diff_from_disk`)
- [x] Rules page (`gui/rules_panel.py`) — **sort by type, overridable, + smart
      bits.** A table of file types → destination folders (Change… / Reset;
      `mappings.py`, `config/mappings.json`), plus a smart-media toggle. Tier-1
      filename smarts (screenshots / invoices / versioned) are always on; Tier-2
      metadata smarts (photos by date, music by artist) are the toggle, off by
      default (opens files). Smart bits honour category overrides. The full
      pattern/regex rule engine was pulled as over-complex; the smart bits are
      the curated slice kept on (`use_pattern_layer` / `use_metadata_layer`).
- [x] Settings page shows the loaded `Settings` (read-only). Editing deferred.
- [ ] **Cancel**: `apply` can't be interrupted mid-batch; needs a cooperative
      cancellation hook (changes the signature — decide before styling)
- [x] Editor validates destination-template placeholders on save
      (`classifier.validate_destination_template`, via `rule_loader.validate_rule`):
      a typo'd or malformed `{key}` is rejected in the dialog naming what's
      available, instead of surfacing as an ERROR state on the next scan.
- [ ] Stale pending runs (folder deleted) stay in the sidebar forever
- [ ] `review_plan` runs on the UI thread; fine at folder scale, but push it to
      the worker if a resume of a huge folder janks (it re-scans `before/`)

### 2D — Styling (after the anchor)
- [ ] QSS design tokens + fonts; window chrome
- [ ] Conflict/collision row states in the diff
- [ ] Respect OS reduced-motion; visible keyboard-focus outline on every control

## Phase 3 — Metadata & smart rules  ✅ done
- [x] `core/metadata.py` — implement `extract_exif` (Pillow: `date_taken`)
- [x] `core/metadata.py` — implement `extract_pdf` (PyPDF2: author, creation date)
- [x] `core/metadata.py` — implement `extract_audio_tags` (mutagen: artist/album/
      `release_year` — named to avoid colliding with the `{year}` placeholder)
- [x] `Rule.metadata_key` — which field a `match_type: metadata` rule tests against
- [x] Wire metadata layer into `classifier` — **preset-driven**: only read metadata
      when a rule's `match_type` is `metadata` or a destination template needs a
      metadata field (lazy `FileEntry.metadata` population)
- [x] Metadata destination placeholders (`{author}`, `{artist}`, `{date_taken}`, …)
- [x] Tests: metadata extraction (fixtures generated at runtime) + preset-driven
      trigger + a laziness assertion (no rule needs metadata ⇒ no file opened)
- [x] `Classifier(use_metadata_layer=True)` is now wired to a user setting
      (`Settings.use_metadata_layer`, a Rules-page toggle saved to
      `settings.json`) — off by default since it costs a file read per entry.

## Phase 4 — Config, settings & safety  ✅ done
- [x] Load `config/settings.json` into a `Settings` object (`settings.py`), incl.
      a new `history_db_path` (defaults under `%LOCALAPPDATA%`)
- [x] User custom-rule loading from `config/rules/*.json` (`load_effective_rules`)
- [x] Enforce `history_retention_days` (prune old operations, batch-atomic)
- [x] Collision strategy selection (overwrite / skip) surfaced through the config
- [x] Tests: settings load + defaults/malformed + custom-rule precedence + pruning
- [ ] Progress callback plumbing verified end-to-end for large batches (needs a
      real caller — deferred to the GUI)
- [ ] **Review:** `merge_rules` rewrites user-rule priorities to lift them above
      presets, because `Classifier` sorts one flat list by `priority` and can't
      tell a user rule from a preset one. The alternative is teaching `Classifier`
      about layers. Revisit if rule precedence gets more complex.
- [ ] Nothing *calls* `load_settings()` / `prune()` in production yet — GUI wiring.

## Phase 5 — Testing, polish, delivery
- [x] Headless end-to-end integration test on a sample folder (`tests/test_integration.py`)
- [x] `ruff check .` clean
- [~] Packaging spike — PyInstaller spec skeleton + findings in `packaging/`.
      **Unverified**: no build has ever run, because `main.py` opens no window.
      Add `pyinstaller>=6.0` to requirements-dev when the GUI exists.
- [ ] Integration test: full GUI-driven run on a sample folder — **blocked on Phase 2**
- [ ] Manual QA on Windows across the sample scenarios — **blocked on Phase 2**
- [ ] Package as a Windows app (installer / bundled exe) — **blocked on Phase 2**
- [ ] User manual with screenshots — **blocked on Phase 2**
- [ ] Demo video + project report — **blocked on Phase 2**

### Carried over from the packaging spike (decide before the GUI hardens)
- [ ] A bundled `config/` is **read-only** at runtime (under one-file it lives in
      a temp dir deleted on exit), so user setting changes would silently vanish.
      Settings and the history db need a writable `%LOCALAPPDATA%` location —
      `history_db_path` already defaults there; `settings.json` does not.

---

## Open questions / decisions to revisit
- [ ] Confirm `before/`/`after/` naming won't collide with real user folders
      (consider a `.sfo_before` / `.sfo_after` prefix if it does). Now looks
      like a genuine bug, not just a naming nicety: `_is_scaffold` skips
      anything under `before/`, so a user's real `before/` folder is silently
      excluded from the plan *and* then has staged originals mixed into it.
      Worth an explicit "this folder is already scaffolded / that name is
      taken" guard in `apply`.
- [ ] Whether to update `README.md` further or keep it as the academic spec
- [ ] Optional: rename repo folder `SmartFileOragnizer` → `SmartFileOrganizer`
