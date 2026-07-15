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

### 2A — Structure  ✅ agreed
One navigation system (the sidebar), because splitting nav across sidebar and
bottom bar leaves the sidebar irrelevant on half the pages. The chain is:
**sidebar selects → body follows → buttons follow the body.**

- [x] Sidebar: `Organize` / `History` (expandable per run) / `Rules` / `Settings`
- [x] Body: two panes, read as a **diff**, not two file browsers — selecting a
      file on one side highlights its counterpart on the other. Pane meanings
      shift by state (Preview: now vs proposed; Review: real `before/` vs
      `after/`; Committed: collapse to one)
- [x] Top bar: inputs + view controls (folder, preset, search) — not decisions
- [x] Bottom bar: clickable status left (VS Code style), action set right
- [x] Rule-layer badge on **every** row (`[C]`/`[P]`/`[M]`/`[E]`) — makes the
      deterministic promise legible, and shows at a glance when rules aren't
      firing (all `[E]`)
- [x] Per-run rule snapshot, so history is reproducible — **landed**
- [x] Dropped the dry-run toggle: Preview *is* the dry run; a toggle would read
      as "apply, but don't apply"
- [ ] **Naming**: never ship "Discard" — ambiguous between commit (irreversible)
      and rollback (safe). Review's two choices are a *fork* and must sit side
      by side: "Keep Organized" (confirm required) / "Restore Original"

### 2B — Design direction (blocked)
- [ ] **Get an anchor from the user** (reference app / screenshot / palette / mood)
- [ ] Agree a design language, then write it up as a fresh design spec
- [ ] Build a self-contained HTML prototype to validate look/feel before Qt
- [ ] **Review with user, iterate until approved**

### 2C — PySide6 implementation (port the approved design)
- [ ] `gui/main_window.py` — `QMainWindow` shell (layout per approved design)
- [ ] QSS design tokens + fonts; window chrome
- [ ] `gui/preview_tree.py` — the diff panes; linked selection; layer badges;
      pending / conflict / collision states
- [ ] `gui/settings_panel.py` — details / rule trace for the selected file
- [ ] Sidebar with history from `db.recent_batches()`; pending runs badged
- [ ] Wire to `Organizer`: space check → preview → Apply → Commit / Rollback
- [ ] **Resume**: on folder select, check `is_scaffolded` / `pending_batch` and
      offer to finish the run — otherwise the plan is empty and reads as
      "nothing to organize" while the files sit in `before/`
- [ ] States: empty / scanning / no-space (a real state, not a dialog) /
      applying / review / committed / error
- [ ] **Threading**: `Organizer.apply` is a synchronous loop — it must run on a
      `QThread` with `progress` marshalled back, or the window freezes on a
      large folder. Not a polish item; it shapes `main_window` from day one
- [ ] **Cancel**: `apply` can't be interrupted mid-batch; needs a cooperative
      cancellation hook (changes the signature — decide before building)
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
- [ ] **Decide:** `Classifier(use_metadata_layer=True)` is opt-in and nothing sets
      it, so the built-in metadata layer is currently unreachable. Wire it to a
      setting (it costs a file read per entry, so it can't just default on).

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
