# Lamello P-System CNC Toolpath Addin — Fusion 360

Generate **Trace** (and optional **Drill**) CAM operations for Lamello P-System connectors (Clamex P etc.) at user-selected anchor points, using fixed connector-relative toolpaths.

## Install

**App Store:** use the Autodesk installer from the Design and Make Marketplace. Then start Fusion; if needed, open **Utilities → Add-Ins**, select **LamelloPSystemCNC**, and click **Run**.

**Manual / development:**

1. Copy or symlink the `LamelloPSystemCNC` folder into your Fusion add-ins directory:
   - **macOS:** `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`
   - **Windows:** `%appdata%\Autodesk\Autodesk Fusion 360\API\AddIns\`
2. In Fusion, open **Utilities → Add-Ins**, find **LamelloPSystemCNC**, and click **Run**.

To rebuild the App Store `.bundle` package: `python3 scripts/build_store_bundle.py` (output under `dist/`).

If you previously installed the add-in as **ClamexToolpaths**, remove or unlink that folder first — this is the same add-in renamed for shipping.

During development, use **Stop** then **Run** to reload code changes — the add-in clears cached Python modules on each cycle. If something still looks stale, delete any `__pycache__` folders inside `LamelloPSystemCNC` and Stop/Run again.

The command **Lamello P-System CNC Toolpath Addin** is pinned on the **Manufacture → ADD-INS** toolbar (with its icon). If you unpin it, use the ADD-INS panel overflow (**…** → Pin to Toolbar) to show it again; a toolbar reset restores the pin.

## Usage

1. Open a design with placement points defined (Joint Origins, sketch points, vertices, or construction points).
2. Switch to the **Manufacture** workspace and ensure at least one **milling Setup** exists (with WCS defined). If the document tool library is empty, the add-in can install bundled Lamello sample tools; otherwise add your own tools first.
3. Run **Lamello P-System CNC Toolpath Addin**.
4. In the dialog:

   **Setup tab** — shared machining context
   - **Setup** — the milling setup whose WCS defines depth (+Z)
   - **Edge tool / Face tool / Drill tool** — document-library tools for each operation type
   - Each tool has an expandable **tool parameters** group (spindle speed, surface speed, cutting/plunge/ramp feedrates, feed per tooth). Edits are written back to the document tool library and apply to every operation using that tool.
   - **Add sample tools** — installs the bundled Lamello side cutter, vertical cutter, and drill into the document library (skips names that already exist).

   **Edge tab** — edge T-slot machining

   **Face tab** — top-face cavity machining

   Each milling tab has its own **placement sets** table and detail inputs:
   - **Anchor points**, **Feed axis**, **Connector type** (P14 / P10)
   - **Flip feed**, **Flip Z**
   - **Operation name prefix** — defaults to **P14 - Edge** / **P10 - Edge** (or `- Face`) and follows the connector type automatically until you type a custom prefix
   - Edge only: **Cutter Z Reference** (Flute Top / Centre / Bottom), **Drill key holes**, **Clearance above anchor (mm)**

   **Preview** — a global checkbox below the tabs toggles the live preview sketches for the active milling tab (drawn under **Clamex Toolpaths**). Every input has a tooltip explaining what it does.

5. Click **OK** to generate operations for the **active milling tab** only (Edge or Face, whichever you last had open).

## What the add-in creates

- A root-level component named **Clamex Toolpaths** (created once; the name is kept stable so re-runs replace existing geometry).
- **Edge:** `Clamex Path – {anchor}` sketches and `{prefix} – {anchor}` Trace ops; optional `{prefix} – Drill – {anchor}` Drill ops.
- **Face:** `Clamex Flat Path – {anchor}` sketches and `{prefix} – {anchor}` Trace ops.

## Geometry rules

### Edge (per anchor)

1. **Feed** — selected feed axis (optionally flipped).
2. **Cross-point** — anchor + `((tool diameter / 2) − cut depth)` along feed (cut depth is **14 mm** for P14, **10 mm** for P10; diameter from the selected edge tool).
3. **Depth** — setup WCS Z (optionally flipped); Z0 at anchor plane.
4. **Drill hole** (optional) — anchor − feed × offset (**7.5 mm** P14, **5.5 mm** P10).

### Face (per anchor)

1. **Feed** — selected feed axis (optionally flipped).
2. **Profile** — symmetric cavity along feed, surface at anchor (depth 0), max depth at centre:
   - **P14:** ±36.434 mm extent, **14 mm** max depth
   - **P10:** ±31.5 mm extent (63 mm total), **10 mm** max depth

## Developer notes

See [ARCHITECTURE.md](ARCHITECTURE.md) for module layout, naming conventions, settings shape, and a manual smoke checklist.

## Troubleshooting

- **"No CAM setups found..." on launch:** Create a milling Setup (with WCS defined) in the Manufacture workspace, then re-run.
- **Command not visible:** Ensure the add-in is **Run** and you are in **Manufacture**. Look for the pinned icon on the ADD-INS panel; if missing, open the panel overflow and enable **Pin to Toolbar**.
- **Preview not visible:** Check the **Preview** checkbox at the bottom of the dialog, then check **Clamex Toolpaths** for `__Preview__` sketches; ensure the component light bulb is on.
- **Error on OK:** The **active** milling tab needs at least one valid set (anchors + feed axis), and Setup and that tab's tool must be selected on the **Setup** tab. Edge generation with drill enabled also needs a Drill tool there.
- **Toolpath in wrong place:** Select the correct tab and set row; adjust feed axis, **Flip feed**, or **Flip Z**.
- **Geometry not found in CAM:** Ensure the setup includes the **Clamex Toolpaths** component.
