"""
Joint-storage spike for the Lamello P-System add-in.

Question: if joint positions are stored per component (component-local
coordinates, as attributes), can we recover their world positions after a
Design-workspace Arrange by applying each occurrence's transform?

Modes (typed into the prompt):
  TAG    run on the ASSEMBLED model (before Arrange, or timeline rolled back).
         Stores a probe point (body bbox centre) + largest planar face normal
         on every component, and a world-space snapshot on the design.
  CHECK  run on the ARRANGED model. Maps each probe back to world space via
         occurrence.transform2, drops sketch points in '__JointSpike__',
         and writes spike_report.txt next to this script.
  CLEAN  removes all spike attributes and the spike sketch.
"""

import json
import math
import os
import traceback

import adsk.core
import adsk.fusion

GROUP = 'LamelloPSystemCNC_spike'
SKETCH_NAME = '__JointSpike__'
HERE = os.path.dirname(os.path.realpath(__file__))
REPORT = os.path.join(HERE, 'spike_report.txt')


def _mm(v):
    return round(v * 10.0, 2)


def _fmt(p):
    return f'({_mm(p.x)}, {_mm(p.y)}, {_mm(p.z)}) mm'


def _set_attr(attrs, name, value):
    existing = attrs.itemByName(GROUP, name)
    if existing:
        existing.deleteMe()
    attrs.add(GROUP, name, value)


def _local_probe(comp):
    """Probe in component space: bbox centre of native bodies + largest planar face normal."""
    bbox = None
    best = None
    for body in comp.bRepBodies:
        bb = body.boundingBox
        if bbox is None:
            bbox = bb.copy()
        else:
            bbox.combine(bb)
        for face in body.faces:
            if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
                continue
            if best is None or face.area > best[0] + 1e-9:
                ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
                if ok:
                    best = (face.area, normal)
    if bbox is None:
        return None
    lo, hi = bbox.minPoint, bbox.maxPoint
    centre = [(lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2]
    normal = [best[1].x, best[1].y, best[1].z] if best else None
    return {'centre': centre, 'normal': normal, 'body_count': comp.bRepBodies.count}


def _to_world(occ, xyz):
    p = adsk.core.Point3D.create(*xyz)
    p.transformBy(occ.transform2)
    return p


def _dir_to_world(occ, xyz):
    """Transform a direction (rotation only) by transforming two points."""
    o = adsk.core.Point3D.create(0, 0, 0)
    t = adsk.core.Point3D.create(*xyz)
    o.transformBy(occ.transform2)
    t.transformBy(occ.transform2)
    v = o.vectorTo(t)
    v.normalize()
    return v


def _probed_occurrences(root):
    for occ in root.allOccurrences:
        if occ.component.bRepBodies.count:
            yield occ


def _timeline_lines(design):
    lines = []
    try:
        tl = design.timeline
        lines.append(f'Timeline: {tl.count} items, marker at {tl.markerPosition}')
        for i in range(tl.count):
            item = tl.item(i)
            try:
                ent = item.entity
                obj_type = ent.objectType if ent else '?'
            except Exception:
                obj_type = '?'
            if 'arrange' in obj_type.lower() or 'arrange' in item.name.lower():
                lines.append(
                    f'  [{i}] {item.name} ({obj_type}) '
                    f'suppressed={item.isSuppressed} rolledBack={item.isRolledBack}'
                )
    except Exception:
        lines.append('Timeline: not available (direct modelling?)')
    return lines


def _tag(design, root):
    snapshot = {}
    tagged = set()
    for occ in _probed_occurrences(root):
        comp = occ.component
        probe = _local_probe(comp)
        if not probe:
            continue
        if comp.name not in tagged:
            _set_attr(comp.attributes, 'probe', json.dumps(probe))
            _set_attr(comp.bRepBodies.item(0).attributes, 'body_probe', '1')
            tagged.add(comp.name)
        w = _to_world(occ, probe['centre'])
        entry = {'world': [w.x, w.y, w.z]}
        if probe['normal']:
            n = _dir_to_world(occ, probe['normal'])
            entry['normal'] = [n.x, n.y, n.z]
        snapshot[occ.fullPathName] = entry
    _set_attr(design.attributes, 'assembled', json.dumps({'occurrences': snapshot}))
    lines = [
        'TAG complete.',
        f'Components tagged: {len(tagged)}',
        f'Occurrences snapshotted: {len(snapshot)}',
    ]
    lines += _timeline_lines(design)
    return lines


def _check(design, root):
    lines = ['CHECK report']
    lines += _timeline_lines(design)

    snap_attr = design.attributes.itemByName(GROUP, 'assembled')
    snapshot = json.loads(snap_attr.value)['occurrences'] if snap_attr else {}
    if not snap_attr:
        lines.append('!! No design-level snapshot found (did TAG run on this document?)')

    for sk in list(root.sketches):
        if sk.name == SKETCH_NAME:
            sk.deleteMe()
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = SKETCH_NAME

    seen = 0
    for occ in _probed_occurrences(root):
        seen += 1
        comp = occ.component
        name = occ.fullPathName
        a = comp.attributes.itemByName(GROUP, 'probe')
        body_attr = comp.bRepBodies.item(0).attributes.itemByName(GROUP, 'body_probe')
        if not a:
            lines.append(f'- {name}: NO component attribute (body attr: {bool(body_attr)})')
            continue
        probe = json.loads(a.value)
        w = _to_world(occ, probe['centre'])
        sketch.sketchPoints.add(sketch.modelToSketchSpace(w))

        parts = [f'- {name}: comp attr OK, body attr {"OK" if body_attr else "MISSING"}',
                 f'    probe now at {_fmt(w)}']
        prev = snapshot.get(name)
        if prev:
            pw = adsk.core.Point3D.create(*prev['world'])
            parts.append(f'    moved {_mm(pw.distanceTo(w))} mm from assembled position')
        else:
            parts.append('    not in snapshot (new/renamed occurrence?)')
        if probe['normal']:
            n = _dir_to_world(occ, probe['normal'])
            dz = n.z
            facing = 'UP (+Z)' if dz > 0.99 else 'DOWN (-Z)' if dz < -0.99 else 'SIDEWAYS'
            parts.append(
                f'    largest face normal now ({n.x:.3f}, {n.y:.3f}, {n.z:.3f}) -> {facing}'
            )
            if prev and 'normal' in prev:
                pn = adsk.core.Vector3D.create(*prev['normal'])
                ang = math.degrees(pn.angleTo(n))
                parts.append(f'    rotated {ang:.1f} deg from assembled orientation')
        lines += parts

    lines.append(f'Occurrences with bodies now: {seen}; in snapshot: {len(snapshot)}')
    return lines


def _clean(design, root):
    removed = 0
    for attr in list(design.findAttributes(GROUP, '')):
        attr.deleteMe()
        removed += 1
    for sk in list(root.sketches):
        if sk.name == SKETCH_NAME:
            sk.deleteMe()
    return [f'CLEAN removed {removed} attributes and the spike sketch.']


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Switch to the Design workspace first.')
            return
        root = design.rootComponent

        result = ui.inputBox('Type TAG, CHECK or CLEAN', 'Joint spike', 'CHECK')
        value, cancelled = result[0], result[1]
        if cancelled:
            return
        mode = value.strip().upper()
        if mode == 'TAG':
            lines = _tag(design, root)
        elif mode == 'CHECK':
            lines = _check(design, root)
        elif mode == 'CLEAN':
            lines = _clean(design, root)
        else:
            ui.messageBox(f'Unknown mode: {value}')
            return

        text = '\n'.join(lines)
        with open(REPORT, 'a', encoding='utf-8') as fh:
            fh.write(text + '\n\n')
        shown = text if len(text) < 1500 else text[:1500] + '\n...'
        ui.messageBox(f'{shown}\n\nFull report: {REPORT}', 'Joint spike')
    except Exception:
        if ui:
            ui.messageBox(f'Spike failed:\n{traceback.format_exc()}')
