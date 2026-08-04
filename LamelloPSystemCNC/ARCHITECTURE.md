# Lamello P-System CNC Toolpath Addin — Architecture

Developer reference for the Fusion 360 add-in. User-facing install and usage notes live in [README.md](README.md).

## Overview

The add-in (folder `LamelloPSystemCNC`, formerly `ClamexToolpaths`) generates Side and Flat Lamello P-System connector CAM operations from user-selected anchor points and feed axes. Geometry is defined in connector-local millimetres, transformed into world space, written to sketches in a dedicated component, then assigned to Trace (and optional Drill) operations.

The command id (`ClamexGenerateToolpathsCmd`) and the design component name (**Clamex Toolpaths**) are intentionally kept stable across the rename so existing documents and customizations keep working.

## Entry flow

```
LamelloPSystemCNC.run()
  → purge cached lib/commands modules
  → commands.generate_clamex.entry.start()
       → register Lamello P-System CNC Toolpath Addin on CAMScriptsAddinsPanel
         (entry imports only adsk.core — heavy libs stay deferred)

CommandCreated (lazy)
  → import commands.generate_clamex.command
  → dialog.build_dialog_inputs()      (raises UserFacingError → clean message box)
  → wire activate / inputChanged / executePreview / execute handlers

inputChanged / executePreview
  → dialog.handle_input_changed()     (tabs, sets, tool params, preview toggle)
  → dialog.read_preview_values()
  → preview.draw_toolpath_preview()   (skipped/cleared when Preview is off)

execute (OK)
  → dialog.read_dialog_values()
  → command._execute_generation()
       → transform_* → path_geometry.create_*_sketch → cam_ops.create_*_operation
  → settings.save_settings()
```

## Module map

| Module | Responsibility |
|--------|----------------|
| `LamelloPSystemCNC.py` | Add-in bootstrap, `sys.path`, module purge on Stop/Run |
| `commands/generate_clamex/entry.py` | Lightweight command registration (`start`/`stop`) only |
| `commands/generate_clamex/command.py` | Event handlers and Side/Flat generation (lazy-loaded on command use) |
| `commands/generate_clamex/dialog.py` | Three-tab UI + Preview footer, read preview/generation values, route `inputChanged` |
| `lib/placement_sets.py` | In-memory multi-set state per milling tab (`PlacementSetState`, `DialogState`) |
| `lib/tool_params.py` | Setup-and-Tool tab tool dropdowns + editable feed/speed groups (`ToolParamsController`) |
| `lib/errors.py` | `UserFacingError` — precondition failures shown without a traceback |
| `lib/toolpath_def.py` | Master connector geometry constants and local point chains (mm) |
| `lib/transform.py` | Resolve anchor/feed/WCS axes; map local chains to world `Point3D` |
| `lib/path_geometry.py` | Own the **Clamex Toolpaths** component; create/replace sketches |
| `lib/cam_ops.py` | Trace/Drill creation, tool/setup listing, idempotent op replace |
| `lib/preview.py` | Transient `__Preview__` sketches; `clear_toolpath_preview()` when Preview is off |
| `lib/settings.py` | Load/save `clamex_settings.json` in per-user AppData (side/flat prefixed + global keys) |
| `lib/units.py` | mm↔cm conversion and shared vector helpers |
| `lib/ui_helpers.py` | Shared Fusion dropdown read/select helpers |

## Dialog layout

```
Command dialog: "Lamello P-System CNC Toolpath Addin"
├── Tab: Setup (setupToolTab)
│   ├── Dropdown: Setup
│   ├── Dropdown: Side tool  + Group: Side tool parameters
│   ├── Dropdown: Flat tool  + Group: Flat tool parameters
│   └── Dropdown: Drill tool + Group: Drill tool parameters
├── Tab: Side (sideTab)           — placement sets + side detail inputs
├── Tab: Flat (flatTab)           — placement sets + flat detail inputs
└── Footer: Preview checkbox (previewEnabled), separated below the tabs
```

Key behaviours:

- **Tool parameters** (spindle speed, surface speed, cutting/plunge/ramp feedrates, feed per tooth) are read from the selected tool's default preset (falling back to the tool). Edits set the parameter expression and push the tool back through `cam.documentToolLibrary.update()`, so all operations using the tool pick up the change. Surface speed is read-only (derived).
- **Op prefix auto-update:** while the Operation name prefix still holds an automatic default (`P14 - Side`, `P10 - Flat`, etc.), changing Connector type rewrites it for the new type. Custom prefixes are never touched (`dialog._auto_update_op_prefix`).
- **Tab switching:** `DialogState.visible_tab` tracks which tab is showing. Leaving a milling tab saves its detail to memory and clears its selection UI; preview and OK read from memory (`sync_from_ui=False`) while the Setup tab is visible, so cleared selection inputs never wipe state.
- **Preview checkbox:** when off, `executePreview` clears any `__Preview__` sketches and skips drawing. The state persists in settings (`preview_enabled`).
- **Preconditions:** missing CAM product, setups, or document tools raise `UserFacingError` during `CommandCreated`, shown as a single-line message box (no traceback). Unexpected exceptions still show the full traceback.

## Side vs Flat

Both milling tabs share the same dialog pattern (placement sets table, anchors, feed axis, connector type, flip feed, flip Z, op prefix). Side adds cutter Z reference (Flute Top / Centre / Bottom) and optional drill holes + clearance. Tools live on the Setup tab (the Drill tool is global, not per-set).

| Aspect | Side | Flat |
|--------|------|------|
| Local path | `feed_point_chain()` T-slot wiggle | `flat_point_chain()` top-face cavity |
| Transform | `transform_feed_chain()` | `transform_flat_chain()` |
| Sketch prefix | `Clamex Path – {anchor}` | `Clamex Flat Path – {anchor}` |
| CAM ops | Trace (+ optional Drill) | Trace only |
| Default op prefix | `P14 - Side` / `P10 - Side` | `P14 - Flat` / `P10 - Flat` |

Generation runs for the **active milling tab only** when the user clicks OK (the last milling tab visited if OK is clicked from the Setup tab).

## Naming conventions

- Component: `Clamex Toolpaths` (created once at assembly root; name kept for idempotent regenerate)
- Side sketches: `Clamex Path – {placement_name}`
- Flat sketches: `Clamex Flat Path – {placement_name}`
- Drill sketches: `Clamex Drill – {placement_name}`
- Preview sketches: `__Preview__` (and numbered variants)
- CAM ops: `{op_prefix} – {placement_name}`; drill uses `{prefix} – Drill – {anchor}`

`placement_display_name()` in `transform.py` produces stable names from Joint Origins, sketch points, vertices, or construction points.

## Settings persistence

File: `clamex_settings.json` under the per-user AppData folder (`~/Library/Application Support/LamelloPSystemCNC` on macOS, `%APPDATA%\LamelloPSystemCNC` on Windows). A legacy copy in the add-in folder is migrated once if present.

Current shape:

```json
{
  "setup_name": "Setup1",
  "preview_enabled": true,
  "side_tool_description": "...",
  "side_drill_tool_description": "...",
  "side_op_prefix": "P14 - Side",
  "side_flip_feed": false,
  "side_cutter_z_reference": "Flute Centre",
  "flat_tool_description": "...",
  "flat_flip_z": false
}
```

Keys are prefixed with `side_` or `flat_`; `setup_name` and `preview_enabled` are global. `load_settings()` returns the raw dict; `dialog._load_set_defaults()` maps legacy unprefixed keys (`flip_feed`, `positive_direction`, etc.) when reading.

## Fusion quirks handled in code

- Internal geometry units are **centimetres**; master paths and UI offsets are **millimetres** (`lib/units.py`).
- Trace operations prefer 3D sketch following; contours are re-applied after `add()` where needed.
- Sketch/point entities use `createForAssemblyContext()` when the component is nested.
- Tool feed/speed edits try `param.expression` first, then `param.value.value`, and push through `documentToolLibrary.update()` with a signature fallback.
- Python modules are purged on Stop/Run so code edits reload without restarting Fusion.

## Reload during development

1. **Utilities → Add-Ins → Stop**, then **Run**
2. If stale, delete any `__pycache__` folders under `LamelloPSystemCNC` and Stop/Run again

## Manual smoke checklist

Run after code changes in Fusion Manufacture:

- [ ] Add-in Stop/Run succeeds; command appears under **Manufacture → ADD-INS** with the P-System profile icon and the new name
- [ ] Launch with **no** CAM setup → single-line "No CAM setups found..." message, no traceback
- [ ] **Setup tab**: Setup + Side/Flat/Drill tool dropdowns populate; parameter groups show the selected tool's feeds/speeds
- [ ] Edit spindle speed / cutting feedrate → value persists in the Fusion Tool Library and on newly generated ops
- [ ] **Side Milling tab**: add a set, select anchors + feed axis, preview sketches appear under **Clamex Toolpaths**
- [ ] Connector type P14→P10 updates the op prefix while it is a default; a custom prefix is left alone
- [ ] **Preview** checkbox off clears preview sketches; on redraws them
- [ ] **Side Milling**: OK creates Trace ops; drill enabled creates Drill ops using the global Drill tool
- [ ] Re-run OK replaces same-named operations (idempotent regenerate)
- [ ] **Flat Milling**: Flip feed and Flip Z affect preview and generated Trace ops
- [ ] Switch tabs (including Setup) and back — selections restore, preview follows the active milling tab
- [ ] Settings persist (`setup_name`, tools, flip flags, `preview_enabled`) across command runs
- [ ] Setup must include the **Clamex Toolpaths** component for CAM geometry assignment
