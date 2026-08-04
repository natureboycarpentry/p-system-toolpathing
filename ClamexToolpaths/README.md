# Clamex Toolpaths — Fusion 360 Add-in

Generate **Trace** CAM operations at user-selected anchor points using fixed Clamex connector-relative toolpaths.

## Install

1. Copy or symlink the `ClamexToolpaths` folder into your Fusion add-ins directory:
   - **macOS:** `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`
   - **Windows:** `%appdata%\Autodesk\Autodesk Fusion 360\API\AddIns\`
2. In Fusion, open **Utilities → Add-Ins**, find **ClamexToolpaths**, and click **Run**.

During development, use **Stop** then **Run** to reload code changes — the add-in clears cached Python modules on each cycle. If something still looks stale, delete any `__pycache__` folders inside `ClamexToolpaths` and Stop/Run again.

The command **Generate Clamex Toolpaths** appears under **Manufacture → ADD-INS**.

## Usage

1. Open a design with placement points defined (Joint Origins, sketch points, vertices, or construction points).
2. Switch to the **Manufacture** workspace and ensure at least one **milling Setup** exists with a suitable tool in the document library.
3. Run **Generate Clamex Toolpaths**.
4. In the dialog:

   **Side tab** — side T-slot machining (existing workflow)

   **Flat tab** — top-face cavity machining (simpler: anchors, feed axis, connector type, flip feed, op prefix)

   Each tab has its own **placement sets** table, **Tool** dropdown, and detail inputs. **Setup** is shared globally below the tabs.

   **Side set details**
   - **Anchor points**, **Feed axis**, **Connector type** (P14 / P10)
   - **Flip feed**, **Flip Z**, **Tool thickness offset**
   - **Operation name prefix** — defaults to **P14 - Side** / **P10 - Side**
   - **Drill key holes** (optional), **Drill tool**, **Clearance above anchor (mm)**

   **Flat set details**
   - **Anchor points**, **Feed axis**, **Connector type** (P14 / P10)
   - **Flip feed**, **Flip Z**
   - **Operation name prefix** — defaults to **P14 - Flat** / **P10 - Flat**

   A **live preview** for the **active tab** appears as temporary sketches under **Clamex Toolpaths**.

5. Click **OK** to generate operations for the **active tab** only (Side or Flat, whichever is open).

## What the add-in creates

- A root-level component named **Clamex Toolpaths** (created once).
- **Side:** `Clamex Path – {anchor}` sketches and `{prefix} – {anchor}` Trace ops; optional `{prefix} – Drill – {anchor}` Drill ops.
- **Flat:** `Clamex Flat Path – {anchor}` sketches and `{prefix} – {anchor}` Trace ops.

## Geometry rules

### Side (per anchor)

1. **Feed** — selected feed axis (optionally flipped).
2. **Cross-point** — anchor + connector offset along feed (**36.2 mm** P14, **40.2 mm** P10).
3. **Depth** — setup WCS Z (optionally flipped); Z0 at anchor plane.
4. **Drill hole** (optional) — anchor − feed × offset (**7.5 mm** P14, **5.5 mm** P10).

### Flat (per anchor)

1. **Feed** — selected feed axis (optionally flipped).
2. **Profile** — symmetric cavity along feed, surface at anchor (depth 0), max depth at centre:
   - **P14:** ±36.434 mm extent, **14 mm** max depth
   - **P10:** ±31.5 mm extent (63 mm total), **10 mm** max depth

## Developer notes

See [ARCHITECTURE.md](ARCHITECTURE.md) for module layout, naming conventions, settings shape, and a manual smoke checklist.

## Troubleshooting

- **Command not visible:** Ensure the add-in is **Run** and you are in **Manufacture**.
- **Preview not visible:** Check **Clamex Toolpaths** for `__Preview__` sketches; ensure the component light bulb is on.
- **Error on OK:** The **active** tab needs at least one valid set (anchors + feed axis), Setup must be selected, and that tab's Tool must be selected. Side sets with drill enabled also need a drill tool.
- **Toolpath in wrong place:** Select the correct tab and set row; adjust feed axis, **Flip feed**, or **Flip Z** (Side and Flat).
- **Geometry not found in CAM:** Ensure the setup includes the **Clamex Toolpaths** component.
