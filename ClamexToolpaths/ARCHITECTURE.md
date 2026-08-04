# ClamexToolpaths — Architecture

Developer reference for the Fusion 360 add-in. User-facing install and usage notes live in [README.md](README.md).

## Overview

ClamexToolpaths generates Side and Flat Lamello Clamex connector CAM operations from user-selected anchor points and feed axes. Geometry is defined in connector-local millimetres, transformed into world space, written to sketches in a dedicated component, then assigned to Trace (and optional Drill) operations.

## Entry flow

```
ClamexToolpaths.run()
  → purge cached lib/commands modules
  → commands.generate_clamex.entry.start()
       → register Generate Clamex Toolpaths on CAMScriptsAddinsPanel

CommandCreated
  → dialog.build_dialog_inputs()
  → wire activate / inputChanged / executePreview / execute handlers

inputChanged / executePreview
  → dialog.read_preview_values()
  → preview.draw_toolpath_preview()

execute (OK)
  → dialog.read_dialog_values()
  → entry._execute_generation()
       → transform_* → path_geometry.create_*_sketch → cam_ops.create_*_operation
  → settings.save_settings()
```

## Module map

| Module | Responsibility |
|--------|----------------|
| `ClamexToolpaths.py` | Add-in bootstrap, `sys.path`, module purge on Stop/Run |
| `commands/generate_clamex/entry.py` | Command registration, event handlers, Side/Flat generation orchestration |
| `commands/generate_clamex/dialog.py` | Side/Flat tab UI, read preview/generation values, route `inputChanged` |
| `lib/placement_sets.py` | In-memory multi-set state per tab (`PlacementSetState`, `DialogState`) |
| `lib/toolpath_def.py` | Master connector geometry constants and local point chains (mm) |
| `lib/transform.py` | Resolve anchor/feed/WCS axes; map local chains to world `Point3D` |
| `lib/path_geometry.py` | Own the **Clamex Toolpaths** component; create/replace sketches |
| `lib/cam_ops.py` | Trace/Drill creation, tool/setup listing, idempotent op replace |
| `lib/preview.py` | Transient `__Preview__` sketches during dialog interaction |
| `lib/settings.py` | Load/save `clamex_settings.json` |
| `lib/units.py` | mm↔cm conversion and shared vector helpers |
| `lib/ui_helpers.py` | Shared Fusion dropdown read/select helpers |

## Side vs Flat

Both tabs share the same dialog pattern (placement sets table, anchors, feed axis, connector type, flip feed, flip Z, op prefix, tool). Side adds tool thickness offset and optional drill holes.

| Aspect | Side | Flat |
|--------|------|------|
| Local path | `feed_point_chain()` T-slot wiggle | `flat_point_chain()` top-face cavity |
| Transform | `transform_feed_chain()` | `transform_flat_chain()` |
| Sketch prefix | `Clamex Path – {anchor}` | `Clamex Flat Path – {anchor}` |
| CAM ops | Trace (+ optional Drill) | Trace only |
| Default op prefix | `P14 - Side` / `P10 - Side` | `P14 - Flat` / `P10 - Flat` |

Generation runs for the **active tab only** when the user clicks OK.

## Naming conventions

- Component: `Clamex Toolpaths` (created once at assembly root)
- Side sketches: `Clamex Path – {placement_name}`
- Flat sketches: `Clamex Flat Path – {placement_name}`
- Drill sketches: `Clamex Drill – {placement_name}`
- Preview sketches: `__Preview__` (and numbered variants)
- CAM ops: `{op_prefix} – {placement_name}`; drill uses `{prefix} – Drill – {anchor}`

`placement_display_name()` in `transform.py` produces stable names from Joint Origins, sketch points, vertices, or construction points.

## Settings persistence

File: `clamex_settings.json` in the add-in folder.

Current shape:

```json
{
  "setup_name": "Setup1",
  "side_tool_description": "...",
  "side_op_prefix": "P14 - Side",
  "side_flip_feed": false,
  "flat_tool_description": "...",
  "flat_flip_z": false
}
```

Keys are prefixed with `side_` or `flat_`. `setup_name` is global. `load_settings()` returns the raw dict; `dialog._load_set_defaults()` maps legacy unprefixed keys (`flip_feed`, `positive_direction`, etc.) when reading.

## Fusion quirks handled in code

- Internal geometry units are **centimetres**; master paths and UI offsets are **millimetres** (`lib/units.py`).
- Trace operations prefer 3D sketch following; contours are re-applied after `add()` where needed.
- Sketch/point entities use `createForAssemblyContext()` when the Clamex component is nested.
- Python modules are purged on Stop/Run so code edits reload without restarting Fusion.

## Reload during development

1. **Utilities → Add-Ins → Stop**, then **Run**
2. If stale, delete any `__pycache__` folders under `ClamexToolpaths` and Stop/Run again

## Manual smoke checklist

Run after code changes in Fusion Manufacture:

- [ ] Add-in Stop/Run succeeds; command appears under **Manufacture → ADD-INS**
- [ ] Command button shows icons from `resources/`
- [ ] **Side tab**: add a set, select anchors + feed axis, preview sketches appear under **Clamex Toolpaths**
- [ ] **Side tab**: OK creates Trace ops; optional drill creates Drill ops
- [ ] Re-run OK replaces same-named operations (idempotent regenerate)
- [ ] **Flat tab**: Flip feed and Flip Z affect preview and generated Trace ops
- [ ] Settings persist (`setup_name`, tab tool, flip flags) across command runs
- [ ] Setup must include the **Clamex Toolpaths** component for CAM geometry assignment
