# UI Structure

**Scope: structure, not looks.** This document settles *what regions exist, what
drives what, and which actions are legal when*. It says nothing about palette,
typeface, spacing, or motion — that is the design spec's job, and it does not
exist yet (see `CLAUDE.md`). Everything here was decided by argument and holds
regardless of how the app eventually looks.

Read alongside `README.md` (functional spec) and `CLAUDE.md` (architecture).

---

## The organizing principle

```
sidebar selects  →  body follows  →  buttons follow the body
```

One direction, no exceptions. Every enabled/disabled state in the app derives
from this chain, so there is exactly one question to answer when adding a
control: *what is the body showing, and what does its state permit?*

**One navigation system: the sidebar.** Navigation was considered for the bottom
bar as well; it was rejected. If the sidebar navigates history while the bottom
bar navigates to Rules/Settings, then standing on Settings the sidebar is
showing history entries irrelevant to the page you are on. It goes dead on half
the app, which is the tell that two systems are fighting. History is not a peer
of navigation — it is one of the pages, which happens to have children.

---

## The state machine

Everything else is downstream of this. The states are not UI modes; they are
facts about the folder.

```
Empty ──▶ Scanning ──▶ Preview ────▶ Applying ──▶ Review ────▶ Committed
                          │                          │
                          ├──▶ NoSpace               └──▶ RolledBack
                          │
   (folder already        │
    scaffolded) ──▶ Resume ──────────────────────────▶ (Review)
```

| State | Means | Legal actions |
|---|---|---|
| `Empty` | No folder chosen | Choose folder |
| `Scanning` | Building the plan | — (transient) |
| `Preview` | Plan built, **nothing touched** | Organize N Files; re-scan |
| `NoSpace` | `check_space` failed | Choose another folder; retry |
| `Applying` | Copying, progress running | Cancel (see Gaps) |
| `Review` | `before/` + `after/` **on disk** | Keep Organized; Restore Original |
| `Committed` | Originals gone | Reuse These Rules; new run |
| `RolledBack` | Copies gone, originals back | Reuse These Rules; new run |
| `Resume` | Folder was already scaffolded | Review it; Keep; Restore |

**`NoSpace` is a state, not an error dialog.** `check_space` must pass before
`apply` — never start a run that can't finish. So the Organize button is
disabled and the bottom bar says *why*, with the shortfall named ("needs 1.2 GB,
400 MB free"). This is a first-class outcome of the safety model, not an
exception to it.

**`Resume` is not optional.** See "What lives on disk" below.

---

## What lives on disk (the load-bearing insight)

**`Review` is not application state. It is a fact about the user's filesystem.**
When a run is in Review, `before/` and `after/` are real folders. That survives
navigating away, closing the app, and crashing.

Three consequences the UI must honor:

1. **Navigating to Settings mid-Review cannot abandon the run.** The sidebar's
   Organize entry carries a badge; a pending run is unfinished business and the
   user must be able to find their way back to it.
2. **On folder select, check for scaffolding first.** `Organizer.is_scaffolded()`
   (disk) and `pending_batch()` (history). Skip this and a previously-scaffolded
   folder produces an *empty plan* — everything in it is skipped as scaffolding —
   which the UI would render as "nothing to organize" while the user's files sit
   staged in `before/`. That is a silent dead end, and it is why `Resume` exists.
3. **The history sidebar must show pending runs**, because they are the ones that
   still need something from the user.

---

## Regions

```
┌──────────────────────────────────────────────────────────────────┐
│  C:\Users\…\Downloads          [Choose folder…]           🔍   │  top: inputs
├──────────┬───────────────────────┬───────────────────────────────┤
│ Organize │ BEFORE                │ AFTER (proposed)              │
│ History  │  📄 invoice.pdf ──────┼──▸ ▾ Documents/Invoices/…     │
│  · 2h ⬤  │  📄 notes.txt         │      📄 invoice.pdf      [P]  │  body
│  · Mon   │  📷 photo.jpg         │    📄 notes.txt          [E]  │
│ Rules    │                       │  ▾ Images/                    │
│ Settings │                       │    📷 photo.jpg          [E]  │
├──────────┴───────────────────────┴───────────────────────────────┤
│ 247 files → 12 folders · 340 GB free                             │  bottom:
│                                    [Restore Original] [Keep →]   │  status+actions
└──────────────────────────────────────────────────────────────────┘
```

**Top bar — inputs and view controls, never decisions.** Folder picker and
search/filter. Things you *choose*, not things you *commit to*.

**Bottom bar — status left, actions right.** The left half is clickable status
in the manner of VS Code's status bar: "Downloads (12 rules)" navigates to
Rules. That is a shortcut, not a second navigation system — the sidebar route
still exists and stays authoritative.

**Why the primary action sits bottom-right, not top:** it follows the reading
direction. You scan the diff, then act at the end of it.

**Sidebar** holds `Organize`, `History` (expandable, one child per run), `Rules`,
`Settings`. Pending runs are badged.

**Inspector** (not sketched) — a collapsible right panel, default closed, opening
on selection, carrying the full rule trace for one file. Sidebar and inspector
both collapse; four columns at once does not fit a laptop. `QSplitter` handles
this natively.

---

## The body is a diff, not two file browsers

This is the difference between the product and a worse Explorer. The value is
not "here are two trees" — it is answering **where did this file go, and why**.

- **Selection is linked.** Selecting a file on one side highlights its
  counterpart on the other. If the panes are independently scrolling lists that
  do not talk to each other, the design has failed.
- **Pane meanings shift by state, and that is correct** — it is the same question
  each time:
  - `Preview`: left = the folder as it is now; right = the proposed tree, drawn
    from `build_plan`. Nothing exists on disk yet.
  - `Review`: left = the real `before/`; right = the real `after/`. Rebuilt
    from disk by `Organizer.review_plan` (the operation log gives the actual
    staged→organized pairs; the batch's snapshot rules re-derive each badge), so
    a run *resumed* from an earlier session — no plan in memory — shows the same
    honest diff, badges and all, as one just applied.
  - `Committed`: nothing to compare — **collapse to one pane.** Do not keep an
    empty half.

---

## Rule-layer badges on every row

Every row carries a badge for the layer that decided it: `[C]` custom, `[P]`
pattern, `[M]` metadata, `[E]` extension fallback. Sourced from
`ClassificationResult.layer` and `.rule_name`.

**On every row, not just the selected one.** Two reasons:

1. The product's whole claim is that decisions trace to an explicit rule — that
   is what makes it not-an-AI-organizer. The badge is that claim, made visible.
2. It is genuinely diagnostic. If every row reads `[E]`, no rules are firing —
   you have none, or none of them match. You would never learn that from a
   details panel you have to click into.

Clicking opens the inspector: which rule fired, its pattern, the value matched
against, the destination template, the resolved path, and any metadata read.

---

## Naming rules

**Never ship the word "Discard".** After Apply there are two things to discard
and they are opposites:

- Discard the originals = `commit` = **irreversible**
- Discard the changes = `rollback` = **safe**

A user who guesses wrong on the irreversible one has lost their folder layout.
Name the outcome instead:

| Internal | User-facing | Notes |
|---|---|---|
| `apply` | **Organize 247 Files** | States what and how much |
| `commit` | **Keep Organized** | Destructive — confirm, naming what is deleted |
| `rollback` | **Restore Original** | Safe — no confirmation |

`commit` / `rollback` are correct in `organizer.py`. They must not reach the user.

**Review's two choices are a fork, not primary-and-secondary.** They are equal
weight, and one is irreversible. **They must sit side by side.** Splitting them —
Undo in a top toolbar, Keep at the bottom — means someone acts on the one they
saw without registering the other existed. Choices that are opposites live
together at the moment of decision.

---

## Actions per run status

The chain, made concrete. A history entry's status determines its action set:

| Status | Enabled | Disabled | Why |
|---|---|---|---|
| `applied` (pending) | Keep Organized; Restore Original | — | `before/`+`after/` are live on disk. This *is* Resume, reached via the sidebar. |
| `committed` | — | **Undo** | Undo is impossible, not unimplemented — see below. |
| `rolled_back` | — | Undo | The copies are gone. |

**History is read-only.** You inspect a finished run — its rule trace, where each
file went — but you do not *act* on it. A committed or rolled-back entry offers no
buttons at all. This is deliberate: the bottom-bar actions (Organize / Restore
Original / Keep Organized) are all about the *Organize* body, so the bottom bar
has one subject, and history is a record rather than a control surface.

**Undo must never be offered after commit.** `commit` deletes `before/` and moves
the copies from `after/` to the folder root, so the logged destinations cease to
exist and the originals are gone. `UndoManager` raises `CannotUndoError`; it
previously reported success and silently did nothing. The UI's job is to never
put the user in front of that button.

**Reuse-a-past-run's-rules is deferred, not dropped.** A finished run snapshots
the exact rules that produced it (`batches.rules_json`) — that powers the honest
per-run trace. Rules are now a single editable set, so a run's snapshot *can*
differ from your current rules (you may have changed them since). So "start a new
run from this run's rules" is a meaningful future action — it belongs *inside the
history body*, living with the run you're viewing, not as a bottom-bar button
disabled whenever you're not in History. Until it exists, history stays read-only.

---

## Deliberately excluded

**The dry-run toggle.** Preview already touches nothing — *the preview is the dry
run*. A toggle beside Apply would read as "apply, but don't apply". `dry_run`
keeps earning its place in the API and the tests; it does not belong in this UI.

**Post-commit undo.** See above. Selling it would mean selling something the
engine cannot do.

---

## Structural gaps

**Threading — done.** `Organizer.apply` and `build_plan` are synchronous loops;
on the UI thread they freeze the window. Both now run on a `QThread` via
`gui/worker.py`, with `progress` marshalled back by Qt's queued connections.

Two things this surfaced that no headless test could, both fixed:

* **`HistoryDB` had to become thread-safe.** sqlite pins a connection to its
  creating thread, and the worker writes to a db opened on the UI thread.
  Browsing history mid-run is a *supported* flow, so the connection is genuinely
  shared: it now opts out of the thread check and serializes on an `RLock`.
* **Holding a `QThread` reference past `deleteLater` crashes the app.** The
  wrapper points at freed C++ memory, so `closeEvent` asking `isRunning()` was
  an access violation — a hard crash on closing the app after any run, not a
  Python error. The handle is dropped when the worker finishes.

**Cancellation — still open.** `apply` cannot be interrupted mid-batch; there is
no cooperative cancellation hook. `Applying` lists Cancel as a legal action and
the engine cannot honor it, so `closeEvent` can only *wait* for a run to finish.
Decide before the GUI hardens — it changes the signature.

**Stale pending runs.** A run whose folder was deleted stays `applied` forever
and shows in the sidebar badged as unfinished business that can never be
finished. Needs either a liveness check when listing (does the folder still hold
`before/`?) or a way to dismiss a run.

---

## Open

- **Rules editing in v1?** ✅ Settled small: **sort by type, overridable.** No
  rule engine in the UI — the Rules page is a table of file types (Images,
  Documents, …) and where each goes, with sensible defaults you can override or
  reset (`mappings.py`, saved to `config/mappings.json`). It works out of the
  box, so there's nothing to set up before organizing. The full pattern/regex
  rule engine was tried and pulled as over-complex; it survives in the backend
  (`core/classifier.py`) for future "smart" behaviours but is off in the app.
- **Settings as a sidebar page or a dialog?** Page is consistent with the chain;
  dialog is more conventional on Windows and keeps the sidebar on the work.
- **Filtering the diff.** Many files land in `Others/` or barely move. Worth a
  "show only changed" filter so the diff highlights what actually changed.
- **Visual direction.** ✅ Anchored: a neutral base with a single amber accent —
  see `DESIGN.md`. Nothing in this document depended on it; the greybox's `role`
  hooks and badge slots are where it attaches.
