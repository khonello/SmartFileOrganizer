# PyInstaller packaging spike

**Status: spike, not a deliverable. No working build has been produced, and none
can be yet.**

`gui/main_window.py`'s `MainWindow.__init__` raises `NotImplementedError` and no
production code constructs `Organizer`, so `python main.py` cannot open a window.
A frozen exe would therefore fail at exactly the point a build most needs
testing — launch. Everything below is a reasoned starting point derived from
reading the code plus PyInstaller/PySide6 behaviour; **the spec has never been
run**, and the sections marked *unverified* are the ones to re-check first once
the GUI exists.

`packaging/smart_file_organizer.spec` is the companion skeleton.

## Blocking dependency

**PyInstaller is not installed in `environ/`** (`import PyInstaller` →
`ModuleNotFoundError`). It was deliberately not installed, to avoid mutating the
shared venv while other agents are working in it. To proceed, add to
`requirements-dev.txt` (dev-only — it must not become a runtime dep):

```
pyinstaller>=6.0
```

Environment as measured: Python 3.10.0, PySide6 6.11.1, Windows 11.
PyInstaller 6.x is the right floor for that PySide6.

## Entry point

`main.py` at the repo root, which does `from gui.main_window import run` *inside*
`main()` to keep Qt out of the import path for the headless core.

This lazy import is fine for PyInstaller: its dependency graph is built by
scanning bytecode, not by executing it, so a function-level import is still
followed. The pattern to watch for is `importlib.import_module` on a computed
name — static analysis cannot see through that and the module would need a
`hiddenimports` entry. Nothing in the current tree does that.

The flat layout (`main.py`, `models.py`, `organizer.py` and the `core`/`rules`/
`history`/`gui` packages all at the repo root) means `pathex` must include the
project root; the spec sets it.

## Data files

Two trees need bundling, and they are **not** symmetric:

### `rules/presets/*.json` — must keep its relative path

`rules/rule_loader.py` resolves presets with:

```python
PRESETS_DIR = Path(__file__).parent / "presets"
```

Frozen, `__file__` for an archived module is a synthetic path under
`sys._MEIPASS`, so this evaluates to `<bundle>/rules/presets`. Mapping the
source dir to the bundle path `rules/presets` (as the spec does) makes that
path real on disk at runtime, and `load_preset()` / `available_presets()` keep
working **unmodified**. This is the reason for the specific destination string —
don't "tidy" it to `presets/`.

*Unverified:* `available_presets()` globs the directory. That is fine against
the extracted one-file temp dir and against a one-dir install, but it has not
been run frozen.

### `config/settings.json` — bundling it is necessary but not sufficient

The spec bundles `config/` so first-run defaults exist. **But a bundled config
is read-only in practice**, and in a one-file build it lives in a temp
directory that is deleted on exit — so any setting the user changes is silently
lost on the next launch.

This is the one finding here with a real design consequence, and it is worth
resolving *before* the settings layer hardens: bundled `config/` should be
treated as **read-only seed defaults**, with the writable copy living in
`%APPDATA%\SmartFileOrganizer\` (same place the history SQLite db should go —
it cannot live next to the exe either, e.g. under `C:\Program Files`).

Note a naming inconsistency worth a human decision: `CLAUDE.md` and
`rule_loader`'s docstring say user rules live in `config/rules/*.json`, but that
directory does not exist in the repo — only `config/settings.json` does. A
`settings.py` is being added concurrently by another agent; whoever owns it
should decide the writable-path story rather than inheriting a frozen-only bug.

## Hidden imports

**Qt needs none.** PySide6 ships its own PyInstaller hooks, which handle the Qt
DLLs, plugins (notably the `platforms/qwindows.dll` plugin — its absence is the
classic "This application failed to start because no Qt platform plugin could be
initialized" error), and `shiboken6`. Trust the hooks; don't hand-list Qt
modules.

The spec lists the metadata extractors' optional deps defensively (`PIL.Image`,
`PIL.ExifTags`, `PyPDF2`, `mutagen`). `core/metadata.py` is currently a stub —
its extractors raise `NotImplementedError` and nothing imports those libraries
yet. Once the extractors land (another agent is implementing them now), the
imports are expected to be found by static analysis anyway and these entries may
prove redundant. They are cheap insurance against a **silent** failure mode
specific to this module: `extract()` catches broad `Exception` and returns `{}`,
so a missing dependency in the frozen build would not crash — metadata
classification would just quietly stop working, and the extension fallback would
mask it. Verify by running a metadata-driven rule against the frozen build, not
by trusting the build log.

## Excludes — where the size actually is

A naive PySide6 freeze pulls in the entire Qt surface and lands around
300–400 MB. This app is plain QtWidgets (`QtCore`/`QtGui`/`QtWidgets` only), so
most of that is dead weight. `QtWebEngineCore` alone is a ~130 MB swing and is
the single highest-value exclude. `QtSql` is also excludable — `history/db.py`
uses stdlib `sqlite3`, not Qt's driver.

*Unverified:* every exclude in the spec is a hypothesis. Excludes are the most
likely thing to break a build (excluding something Qt loads indirectly fails at
runtime, not build time), so re-add them one at a time if launch breaks. All
size figures above are from general PySide6 experience, **not measured on this
project** — no build has run.

## One-file vs one-dir

**Recommendation: one-dir** (what the spec is configured for).

| | one-file (`--onefile`) | one-dir (`COLLECT`) |
|---|---|---|
| Distribution | single .exe | folder; needs an installer to look professional |
| Startup | Extracts the whole bundle to `%TEMP%\_MEIxxxx` on **every** launch — seconds of delay for a Qt app of this size | No extraction; near-native |
| `sys._MEIPASS` | Temp dir, deleted on exit | The install dir |
| Antivirus | Self-extracting behaviour is a frequent false-positive trigger on Windows | Better behaved |
| Debugging | Opaque | Can inspect what actually shipped |

The startup cost is the deciding factor: one-file re-extracts ~100 MB+ of Qt on
every launch, which is a poor first impression for a desktop utility that should
feel instant. One-file also makes the read-only-config problem worse, since the
bundle is destroyed on exit.

If a single-file download is a product requirement, the better answer is one-dir
plus an installer (Inno Setup / WiX), not `--onefile`.

## Also unresolved

- **No app icon.** The spec's `icon=` line is commented out; there is no visual
  design yet, so no `.ico` exists. The exe will carry the default PyInstaller
  icon until one does.
- **No code signing.** Unsigned exes get SmartScreen warnings on Windows. Needs
  a certificate — a business decision, not a technical one.
- **`console=False`** is set (correct for a GUI app), but it means an early
  crash before the window opens produces *no output at all*. Build with
  `console=True` while first debugging the freeze, then flip it back.

## What would confirm this spike

Once `main.py` opens a real window, in order:

1. `python -m PyInstaller packaging/smart_file_organizer.spec` completes.
2. `dist/SmartFileOrganizer/SmartFileOrganizer.exe` launches and shows a window
   (this is what catches a missing Qt platform plugin).
3. `available_presets()` returns all three presets from inside the bundle.
4. A full organize run against a scratch folder — the frozen build hitting the
   same paths `tests/test_integration.py` covers headless.
5. Settings survive a restart (this is the one expected to fail until the
   `%APPDATA%` decision above is made).
