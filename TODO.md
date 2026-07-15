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
- [ ] Initial git commit of the scaffold

## Phase 1 — Core engine
- [x] `core/scanner.py` — recursive scan → `FileEntry` (size, mtime, extension)
- [x] `core/pattern_matcher.py` — extension→category map + date/version extraction
- [x] `core/classifier.py` — layered rule engine with strict precedence
      (custom → pattern → metadata → extension)
- [x] `core/file_ops.py` — copy/move, collision handling (append-suffix default),
      disk-space preflight, promote/remove primitives
- [x] `organizer.py` — before/after lifecycle: `check_space` → `build_plan` →
      `apply` (stage `before/`, copy `after/`) → `commit` / `rollback`
- [x] `history/db.py` — SQLite operation log (log-before-copy, `batch_id` grouping)
- [x] `history/undo_manager.py` — record-based rollback
- [x] `rules/rule_loader.py` + 3 presets (downloads / photos / work)
- [x] Headless pipeline tests (no Qt) — 14 passing

## Phase 2 — GUI design & preview  ⭐ current
> Swapped ahead of metadata so the UI can be seen and validated early.
> First design attempt was discarded; design direction restarts from scratch.

### 2A — Design direction (do this before building anything)
- [ ] Get an anchor from the user (reference app / screenshot / palette / mood)
- [ ] Agree a design language, then write it up as a fresh design spec
- [ ] Build a self-contained HTML prototype to validate look/feel before Qt
- [ ] **Review with user, iterate until approved**

### 2B — PySide6 implementation (port the approved design)
- [ ] `gui/main_window.py` — `QMainWindow` shell (layout per approved design)
- [ ] QSS design tokens + fonts; window chrome
- [ ] `gui/preview_tree.py` — before/after file view; pending / conflict / selection states
- [ ] `gui/settings_panel.py` — details / rule trace for the selected file
- [ ] Action controls — dry-run toggle, progress, Undo/Apply → Rollback/Commit
- [ ] Wire to `Organizer`: space check → preview → Apply → Commit / Rollback
- [ ] Empty / dry-run / insufficient-space / error states
- [ ] Respect OS reduced-motion; visible keyboard-focus outline on every control

## Phase 3 — Metadata & smart rules
- [ ] `core/metadata.py` — implement `extract_exif` (Pillow: `date_taken`)
- [ ] `core/metadata.py` — implement `extract_pdf` (PyPDF2: author, creation date)
- [ ] `core/metadata.py` — implement `extract_audio_tags` (mutagen: artist/album/year)
- [ ] Wire metadata layer into `classifier` — **preset-driven**: only read metadata
      when a rule's `match_type` is `metadata` or a destination template needs a
      metadata field (lazy `FileEntry.metadata` population)
- [ ] Metadata destination placeholders (e.g. `{exif_year}`, `{author}`) in templating
- [ ] Tests: metadata extraction (with sample fixture files) + preset-driven trigger

## Phase 4 — Config, settings & safety
- [ ] Load `config/settings.json` (default_preset, collision_strategy,
      dry_run_default, history_retention_days) into a settings object
- [ ] User custom-rule loading from `config/rules/*.json`
- [ ] Enforce `history_retention_days` (prune old operations)
- [ ] Collision strategy selection (overwrite / skip) surfaced through the config
- [ ] Progress callback plumbing verified end-to-end for large batches
- [ ] Tests: settings load + custom-rule precedence over presets

## Phase 5 — Testing, polish, delivery
- [ ] Integration test: full GUI-driven run on a sample folder
- [ ] Manual QA on Windows across the sample scenarios (Downloads / Photos / Work)
- [ ] `ruff check .` clean
- [ ] Package as a Windows app (installer / bundled exe)
- [ ] User manual with screenshots
- [ ] Demo video + project report

---

## Open questions / decisions to revisit
- [ ] Confirm `before/`/`after/` naming won't collide with real user folders
      (consider a `.sfo_before` / `.sfo_after` prefix if it does)
- [ ] Whether to update `README.md` further or keep it as the academic spec
- [ ] Optional: rename repo folder `SmartFileOragnizer` → `SmartFileOrganizer`
