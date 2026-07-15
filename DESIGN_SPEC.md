# Smart File Organizer — Design Specification

## 1. Concept

**Theme: "Ledger"** — the visual language of an archivist's filing room translated into modern software. Deep charcoal-navy surfaces stand in for the drawer interior; a warm brass accent stands in for the hardware — the pull-tabs, hinges, and label-holders of a well-kept cabinet. Where a generic organizer app would use a folder icon and a progress spinner, Ledger uses the vocabulary of *filing*: rails, tabs, drawers sliding open, index cards. This is not decorative — the file tree and the metaphor share a spatial idea, so the motion of the UI reinforces what the app is actually doing to your files.

The app window is unusually shaped — wide and shallow, like a drawer pulled open — which reinforces the metaphor rather than fighting it.

**Signature element:** the **Sorting Rail** — a slim vertical brass line running down the left edge of the main tree panel. During a scan, folder "tabs" grow out from the rail and slide into position as the classifier resolves each batch, so the user watches structure assemble in real time rather than staring at a spinner. This is the one place the design spends its energy; everything else stays quiet.

---

## 2. Window & Layout Geometry

- **Orientation:** Landscape, fixed aspect ratio.
- **Aspect ratio rule:** `height = 0.4 × width` (5 : 2)
- **Default size:** `1440 × 576 px`
- **Minimum size:** `1100 × 440 px` (ratio preserved)
- **Resizable:** yes, but the window resize handler locks height to `0.4 × width` on drag — this is a deliberate constraint, not a suggestion, since the whole layout is composed for a short, wide canvas.

Because vertical space is scarce, the design avoids tall hero sections, deep vertical stacking, and multi-row toolbars. Everything is composed in horizontal bands.

### Wireframe

```
┌───────────────────────────────────────────────────────────────────────────┐
│  ●●●  Smart File Organizer            [ Downloads ▾ ]      ⚙  ⤢          │ ← titlebar, 32px
├───────────┬───────────────────────────────────────────────┬─────────────┤
│  RULES    │  ┃ SORTING RAIL                                │  DETAILS    │
│           │  ┃                                              │             │
│ ● Presets │  ┃ ⊟ Documents/           124 files             │  Selected:  │
│ ○ Downl.  │  ┃   ⊟ Invoices/           18                   │  invoice_   │
│ ○ Photos  │  ┃   ⊟ Reports/            9                    │  jan.pdf    │
│ ○ Work    │  ┃ ⊟ Images/               340 files            │             │
│           │  ┃   ⊟ Screenshots/2026/   210                  │  Rule hit:  │
│ + Custom  │  ┃ ⊟ Archives/             12 files             │  invoice_   │
│   rule    │  ┃                                              │  detection  │
│           │  ┃  [ before ]  ⇄  [ after ]                    │             │
├───────────┴───────────────────────────────────────────────┴─────────────┤
│  ▸ Dry run    ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░  62%     [ Undo ]   [ Apply changes ] │ ← status bar, 40px
└───────────────────────────────────────────────────────────────────────────┘
```

- **Left rail (Rules), ~200px:** preset list + custom rule entry point. Narrow, list-based, no icons wider than 16px.
- **Center (Tree/Preview), fluid:** the dominant region — always ≥ 55% of window width. The `[ before ] ⇄ [ after ]` toggle maps directly to the app's on-disk staging folders: **before** shows the folder's original contents (staged into a `before/` subfolder on Apply), **after** shows the organized copy (built in `after/`). Committing discards `before/` and offloads `after/` into the folder root; rollback restores `before/`.
- **Right panel (Details), ~220px, collapsible:** metadata for the currently selected file; collapses to 0 when nothing is selected, animated.
- **Status bar, 40px fixed:** dry-run toggle, progress, undo, apply — always visible, never scrolls away.
- **Titlebar, 32px fixed:** compact; folder selector is the primary control here since screen real estate is precious.

---

## 3. Design Tokens

### Color

| Token | Hex | Use |
|---|---|---|
| `ink` | `#161A20` | Base window background |
| `panel` | `#1E242C` | Rail / detail panel surfaces |
| `panel-raised` | `#262E38` | Cards, hovered rows, tree item background |
| `parchment` | `#F3EEE2` | Preview-pane paper surface (before/after tree), used sparingly |
| `brass` | `#C79A4B` | Primary accent — rail, active states, primary buttons |
| `brass-dim` | `#8C7038` | Brass at rest / disabled brass |
| `teal-safe` | `#4C8C82` | Success, applied, safe-to-proceed states |
| `rust-warn` | `#B75B3E` | Conflicts, undo, destructive actions |
| `ink-text` | `#E8E4DA` | Primary text on dark surfaces |
| `ink-text-dim` | `#9AA0A8` | Secondary/caption text on dark surfaces |

Only **one** bright accent (brass) is used for primary emphasis. Teal and rust are functional signal colors, not decorative — teal only appears on confirmed/safe states, rust only on undo/conflict states. This keeps the palette legible: color always means something specific in this app.

### Typography

| Role | Typeface | Weight/Style | Use |
|---|---|---|---|
| Display | **Fraunces** (optical size: 72pt, soft) | 500, italic for emphasis only | Section titles ("Preview", "Rules"), empty-state headlines |
| UI / Body | **Inter** | 400 / 500 / 600 | All controls, labels, buttons, list items |
| Utility / Data | **IBM Plex Mono** | 400 | File paths, extensions, rule patterns, byte counts, timestamps |

Fraunces is used **only** for the handful of section headers — it's the one place personality shows. Everywhere else is Inter, kept quiet and functional. Plex Mono appears anywhere a literal filesystem value is shown (`/Users/x/invoice_2026-01.pdf`), which also reinforces "this is a precise, technical tool" against the warmth of the brass/parchment palette.

Type scale:
```
Display / section title    20px / 26px   Fraunces 500
UI heading                 14px / 20px   Inter 600
Body                       13px / 18px   Inter 400
Caption / meta             11px / 16px   Inter 400, ink-text-dim
Mono / paths                12px / 18px   Plex Mono 400
```

### Spacing & Shape

- Base unit: `4px`. Standard gaps: 8 / 12 / 16 / 24px.
- Corner radius: `6px` on cards and buttons, `3px` on small controls (checkboxes, tags). No fully-rounded (pill) buttons — pill shapes read as "generic SaaS," and the brief calls for an archival, precise feel.
- Elevation: no drop shadows on dark surfaces (they muddy on `#161A20`); elevation is communicated by a lighter fill (`panel-raised`) plus a faint 1px all-around border (`rgba(255,255,255,0.06)`) — a full, even outline, not a single-edge accent bar.

---

## 4. Component Styling (QSS)

Qt Style Sheets handle static states (default/hover/pressed/disabled). Timed motion (fades, slides, staggered reveals) is implemented in code via `QPropertyAnimation` / `QGraphicsOpacityEffect`, since QSS has no transition/animation syntax — noted per component below.

### Primary Button ("Apply changes")

```css
QPushButton#primaryButton {
    background-color: #C79A4B;
    color: #161A20;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font: 600 13px "Inter";
}
QPushButton#primaryButton:hover {
    background-color: #D7AC5E;   /* +brightness, static QSS swap */
}
QPushButton#primaryButton:pressed {
    background-color: #A87F38;
}
QPushButton#primaryButton:disabled {
    background-color: #3A3F47;
    color: #6E747C;
}
```
*Animated in code:* a 120ms `QPropertyAnimation` on a `backgroundColor` custom property gives the hover a smooth ease rather than an instant QSS swap.

### Secondary / Ghost Button ("Undo")

```css
QPushButton#ghostButton {
    background-color: transparent;
    color: #B75B3E;
    border: 1px solid #B75B3E;
    border-radius: 6px;
    padding: 8px 18px;
    font: 600 13px "Inter";
}
QPushButton#ghostButton:hover {
    background-color: rgba(183, 91, 62, 0.12);
}
```

### Tree View (file/folder rows)

```css
QTreeView {
    background-color: #1E242C;
    color: #E8E4DA;
    border: none;
    outline: none;
    font: 400 13px "Inter";
}
QTreeView::item {
    height: 28px;
    border-radius: 4px;
    padding-left: 4px;
}
QTreeView::item:hover {
    background-color: #262E38;
}
QTreeView::item:selected {
    background-color: rgba(199, 154, 75, 0.18);   /* brass wash */
    color: #F3EEE2;
}
```
- **Pending-move** rows (staged in preview, not yet applied): a small filled brass dot (6px circle) precedes the filename in place of the default file-type glyph, and the row background shifts to `rgba(199,154,75,0.08)`. No border of any kind.
- **Conflict** rows (name collision detected): the leading glyph is replaced with a small triangular warning mark in `rust-warn`, row background shifts to `rgba(183,91,62,0.08)`, and the filename switches to `rust-warn`. No border of any kind.
- *Animated in code:* new rows returned by a scan fade+slide in from `x:-8px, opacity:0` to `x:0, opacity:1` over 180ms, staggered 30ms per row (capped at a 600ms total stagger window regardless of file count, so large scans don't feel sluggish).

### Progress Bar (status bar)

```css
QProgressBar {
    background-color: #262E38;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #C79A4B;
    border-radius: 3px;
}
```
*Animated in code:* the chunk includes a slow (1.6s loop) diagonal brass-on-brass sheen while scanning is active — a subtle `QLinearGradient` offset animation, disabled entirely once progress reaches 100% or when "reduced motion" is on.

### Toggle Switch ("Dry run")

```css
QCheckBox::indicator {
    width: 34px; height: 18px;
    border-radius: 9px;
    background-color: #3A3F47;
}
QCheckBox::indicator:checked {
    background-color: #4C8C82;
}
```
*Animated in code:* the knob slides 130ms ease-in-out; track color cross-fades rather than hard-swaps.

### Preset Card (left rail / preset picker)

```css
QFrame#presetCard {
    background-color: #1E242C;
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 6px;
    padding: 10px 12px;
}
QFrame#presetCard[active="true"] {
    background-color: #262E38;
    border: 1px solid rgba(199,154,75,0.35);
}
```
Active/selected state is additionally marked by the radio-style indicator dot (● filled brass / ○ empty outline) already shown in the wireframe — a standard settings-list convention — rather than by any border accent.

---

## 5. Motion & Animation Spec

Motion is used only where it clarifies *what the app is doing to your files* — never as ambient decoration.

| Moment | Motion | Duration | Easing |
|---|---|---|---|
| App launch | Sorting Rail draws downward from titlebar; panels fade in after | 400ms | ease-out |
| Folder scan | Tree rows stagger in (see above); rail "tabs" extend as each top-level category resolves | 180ms/row, 600ms cap | ease-out |
| Before/After toggle | Cross-fade between preview states | 220ms | ease-in-out |
| Hover (buttons, rows) | Color/opacity shift | 120–150ms | ease-out |
| Apply changes | Applied rows collapse upward out of the "before" list, matching row fades into "after" | 250ms | ease-in |
| Undo | Reverse of apply: rows slide back into prior position | 250ms | ease-in |
| Details panel open/close | Width animates 0 ↔ 220px | 200ms | ease-in-out |
| Conflict detected | Warning glyph briefly scales 1 → 1.15 → 1 and row background tint fades in (one cycle, not looping) | 300ms | ease-in-out |

**Reduced motion:** when the OS-level reduced-motion setting is on, all of the above collapse to instant state changes except the progress bar (which still fills, just without the sheen loop). No animation in this app is required to understand the interface — motion is always a clarity layer on top of a fully legible static state.

---

## 6. States

- **Empty state** (no folder selected): centered Fraunces headline — *"Nothing to sort yet."* — with a single primary button, "Choose a folder." No illustration; the Sorting Rail itself sits dim/inactive (`brass-dim`) as the only visual cue.
- **Dry-run banner:** a slim `teal-safe`-bordered strip above the status bar: "Dry run — no files will be moved." Persistent, not a dismissible toast, since it's a safety-relevant mode, not a notification.
- **Error state** (e.g., permission denied on a folder): row renders in `rust-warn`, inline caption in Plex Mono explaining exactly what failed (`Permission denied: /System/Library`), never a generic "Something went wrong."

---

## 7. Forbidden Patterns

These are excluded outright, not left to judgment call-by-call:

- **No colored left-edge accent bars** on cards, rows, or panels, in any state (selected, pending, conflict, elevation, or otherwise). This is a templated "AI dashboard" tell, not an interaction pattern used by expert-designed products. State and selection are communicated instead through fill color, an all-around border, an icon/glyph, weight, or a dot indicator — never a single colored edge.
- **No default "AI-generated" palette signatures** that aren't an explicit, deliberate choice for this brief: warm cream background with a terracotta/clay accent, near-black background with a single neon/acid accent, or a hairline-rule broadsheet layout with zero border-radius. If a palette or layout choice happens to resemble one of these, it must be traceable to something specific about filing/archival subject matter (as brass and parchment are here) — not reached for as a safe default.
- **No pill-shaped buttons or tags**, no drop shadows on dark surfaces, no decorative gradients outside the one functional progress-bar sheen.
- **No numbered-sequence markers (01 / 02 / 03)** anywhere in this UI — nothing here is an ordered sequence, so numbering would decorate rather than inform.
- **No stock icon-in-a-circle illustrations** or generic emoji as functional icons; icons are custom-drawn glyphs consistent with the mono/utility register (dot, triangle, rail-tab), not a general-purpose icon pack dropped in wholesale.

## 8. Restraint Checklist

- One bright accent (brass) — teal and rust are functional signals only, not decoration.
- One signature element (Sorting Rail) carries the personality; buttons, rows, and panels stay quiet and consistent.
- State and selection are always shown via fill, all-around border, icon, or weight — never a directional accent edge (see §7).
- Fraunces is capped to section headers only — never body copy, never buttons.
- All motion is optional to understanding the UI and respects reduced-motion settings.
- Keyboard focus is always visible: a 2px `brass` outline offset 2px from any focused control, on every interactive element without exception.
