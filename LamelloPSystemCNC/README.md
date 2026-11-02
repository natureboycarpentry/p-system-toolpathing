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

The command **Lamello P-System CNC Toolpath Addin** is on the **Manufacture → MILLING → 3D** panel (with its icon), next to **Lamello – Generate from Joints**. **Lamello – Joints** (Define / Find / Manage tabs) is on **Design → SOLID → ASSEMBLE**. If Fusion renames those panels, the buttons fall back to the ADD-INS panel.

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
   - **Anchor points**, **Connector type** (P14 / P10)
   - **Edge:** **Cut-in face** (planar face being machined into); **Face:** **Feed axis** (linear edge / sketch / construction line)
   - **Flip feed**, **Flip Z**
   - **Operation name prefix** — defaults to **P14 - Edge** / **P10 - Edge** (or `- Face`) and follows the connector type automatically until you type a custom prefix
   - Edge only: **Cutter Z Reference** (Flute Top / Centre / Bottom), **Drill key holes**, **Clearance above anchor (mm)**

   **Preview** — a global checkbox below the tabs toggles the live preview sketches for the active milling tab (drawn under **Clamex Toolpaths**). Every input has a tooltip explaining what it does.

5. Click **OK** to generate operations for every milling tab with at least one complete placement set (Edge, Face, or both). A tab with partial selections keeps OK greyed until it is completed or cleared.

## Joint workflow (no sketch points)

Instead of drawing anchor points, define joints once on the **assembled** model; they follow each part through **Modify → Arrange** in the Design workspace.

1. **Design → SOLID → ASSEMBLE → Lamello – Joints.** Each panel must be its own component. The dialog has three tabs; OK acts on the tab that is showing.
2. **Find** tab (fastest): select components (in the browser), bodies or faces, or nothing for the whole assembly. Every place a panel end touches another panel's face is listed; untick any you don't want, set connector type / end offset / count once, and **OK** saves them all. Joints that already exist are listed unticked (tick to replace). Face-to-face contacts (an end thicker than 60 mm) and contacts under 40 mm are ignored.
3. **Define** tab (one joint at a time): select the two touching faces: the **end face** of the panel that gets the Edge slot and the **face** it sits against (order doesn't matter, the smaller face is the edge; tick **Swap edge / face** if needed).
   Choose **Connector type**, **End offset** (default 100 mm, drag the arrow or type) and **Connectors** (count, evenly spaced between the end offsets). The preview shows the Edge cut (orange), Face cavity (blue), joint line (green) and key-hole axis (red); joints already saved show as grey markers.
   **OK** saves the joint. Re-selecting the same faces later edits that joint (or tick **Delete this joint**). Right-click → *Repeat* to define the next one.
4. **Manage** tab: every stored joint (Edge part → Face part, type × count). Select a row to highlight it; tick rows (or **Mark broken** / **Mark all / none**) and **OK** deletes them. *Broken* joints have lost one half (a part was deleted or re-made) and are skipped by Generate.
5. Arrange as usual. Arrange copies the components, so the stored joints come along.
6. **Manufacture → MILLING → 3D → Lamello – Generate from Joints.** Pick the setup (containing the Arrange layout; the **Clamex Toolpaths** component is added to its models automatically) and tools, then **Generate**. Each connector becomes `{prefix} – {part} – {partner} {n}` Trace ops (+ optional Drill ops).

Checks: an Edge part must lie flat; a Face cavity must face the setup's +Z. Parts Arrange laid face-down are skipped and listed, so flip them in the arrangement or machine them in a second setup. Key holes are drilled from the top face, so check that's the face you want them on.

Joints are stored per component: identical copies of one component share their joints.

## What the add-in creates

- A root-level component named **Clamex Toolpaths** (created once; the name is kept stable so re-runs replace existing geometry).
- **Edge:** `Clamex Path – {anchor}` sketches and `{prefix} – {anchor}` Trace ops; optional `{prefix} – Drill – {anchor}` Drill ops.
- **Face:** `Clamex Flat Path – {anchor}` sketches and `{prefix} – {anchor}` Trace ops.

## Geometry rules

### Edge (per anchor)

1. **Feed (cut-in)** — inward normal of the selected planar face (optionally flipped).
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
- **Command not visible:** Ensure the add-in is **Run**. Look in **Manufacture → MILLING → 3D** (open the panel's dropdown if it isn't pinned) or **Design → SOLID → ASSEMBLE**; if missing there, check the ADD-INS panels.
- **Preview not visible:** Check the **Preview** checkbox at the bottom of the dialog, then check **Clamex Toolpaths** for `__Preview__` sketches; ensure the component light bulb is on.
- **Error on OK / grey OK:** OK stays disabled until the **active** milling tab has at least one valid set (anchors + cut-in face on Edge, or anchors + feed axis on Face), and Setup and that tab's tool are selected on the **Setup** tab. Edge with drill enabled also needs a Drill tool there.
- **Toolpath in wrong place:** Select the correct tab and set row; adjust the cut-in face / feed axis, **Flip feed**, or **Flip Z**.
- **Geometry not found in CAM:** Both commands add the **Clamex Toolpaths** component to the setup's models automatically. If Fusion refuses, the result message says so: edit the setup and ⌘/Ctrl-click **Clamex Toolpaths** under **Model**.
