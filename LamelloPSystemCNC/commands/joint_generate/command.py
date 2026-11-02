"""
Generate from Joints command (Manufacture workspace).

Finds every part in the chosen setup that carries joints (lib/joints.py),
prefers the copies Design-workspace Arrange made, maps the stored connectors
into world space, checks each part is laid out so it can be machined from the
setup's +Z, then runs the same sketch + Trace / Drill pipeline as the manual
Edge / Face tabs.

Imported lazily from entry.py.
"""

import os
import traceback

import adsk.cam
import adsk.core
import adsk.fusion

from lib import joint_math as jm
from lib import joints as jt
from lib import trace_log
from lib.cam_ops import (
    create_drill_operation,
    create_trace_operation,
    default_tool_preset,
    find_tool_by_description,
    list_document_tools,
    list_milling_setups,
    operation_display_name,
    setup_wcs_z_axis,
    tool_diameter_mm,
    tool_flute_length_mm,
)
from lib.errors import UserFacingError
from lib.example_tools import (
    SAMPLE_DRILL_DESCRIPTION,
    SAMPLE_FLAT_DESCRIPTION,
    SAMPLE_SIDE_DESCRIPTION,
    prompt_add_example_tools_if_empty,
)
from lib.path_geometry import (
    ADD_TO_SETUP_HINT,
    CLAMEX_COMPONENT_NAME,
    _setup_model_paths,
    create_drill_point_sketch,
    create_feed_path_sketch,
    create_flat_path_sketch,
    geometry_for_assembly,
    ensure_clamex_in_setup,
    get_or_create_clamex_component,
    point_for_assembly,
    setup_model_components,
)
from lib.settings import load_settings, save_settings
from lib.toolpath_def import (
    CUTTER_Z_REFERENCE_OPTIONS,
    DEFAULT_CONNECTOR_TYPE,
    DEFAULT_DRILL_CLEARANCE_MM,
    cross_offset_mm,
    default_flat_op_prefix,
    default_op_prefix,
    feed_point_chain,
    flat_point_chain,
    half_flute_mm,
    migrate_cutter_z_reference,
)
from lib.transform import (
    drill_hole_point_at,
    transform_feed_chain_at,
    transform_flat_chain_at,
)
from lib.ui_helpers import read_dropdown, select_dropdown

TITLE = 'Lamello P-System – Generate from Joints'

INPUT_SETUP = 'jgSetup'
INPUT_EDGE_TOOL = 'jgEdgeTool'
INPUT_FACE_TOOL = 'jgFaceTool'
INPUT_DRILL_TOOL = 'jgDrillTool'
INPUT_CUTTER_Z = 'jgCutterZ'
INPUT_EDGE_FLIP_Z = 'jgEdgeFlipZ'
INPUT_FACE_FLIP_Z = 'jgFaceFlipZ'
INPUT_DRILL = 'jgDrill'
INPUT_CLEARANCE = 'jgClearance'
INPUT_SUMMARY = 'jgSummary'


def _addin_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def _cam():
    return adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)


def _design():
    app = adsk.core.Application.get()
    return adsk.fusion.Design.cast(
        app.activeDocument.products.itemByProductType('DesignProductType')
    )


# --- planning ---------------------------------------------------------------

def _in_paths(occurrence, paths):
    segments = occurrence.fullPathName.split('+')
    return any('+'.join(segments[:k]) in paths for k in range(1, len(segments) + 1))


def _jointed_occurrences(design, setup):
    """Occurrences in the setup carrying joints, preferring Arrange copies."""
    include_all, paths = _setup_model_paths(design, setup)
    components = setup_model_components(design, setup)
    by_component = {}
    for occurrence in design.rootComponent.allOccurrences:
        if not jt.read_component_joints(occurrence.component):
            continue
        if not include_all and not _in_paths(occurrence, paths) and not any(
            component == occurrence.component for component in components
        ):
            continue
        key = occurrence.component.entityToken
        by_component.setdefault(key, []).append(occurrence)

    chosen = []
    for occurrences in by_component.values():
        arranged = [occ for occ in occurrences if jt.is_arranged_occurrence(occ)]
        chosen.extend(arranged or occurrences)
    return chosen, include_all, paths


def _describe_model(model):
    """Short label for a setup model entity: type, path and owning design."""
    kind = getattr(model, 'objectType', '?').split('::')[-1]
    for attr in ('fullPathName', 'name'):
        try:
            label = getattr(model, attr)
            break
        except Exception:
            label = '?'
    try:
        context = model.assemblyContext if hasattr(model, 'assemblyContext') else None
        if context:
            label = context.fullPathName
        elif hasattr(model, 'assemblyContext'):
            label += ' (no path)'
    except Exception:
        pass
    owner = ''
    try:
        parent = model.parentDesign if hasattr(model, 'parentDesign') else None
        if parent is None and hasattr(model, 'assemblyContext') and model.assemblyContext:
            parent = model.assemblyContext.component.parentDesign
        if parent is None and hasattr(model, 'parentComponent'):
            parent = model.parentComponent.parentDesign
        if parent is not None:
            owner = f' [design: {parent.parentDocument.name if parent.parentDocument else "?"}]'
    except Exception:
        pass
    return f'{kind} "{label}"{owner}'


def diagnose_no_joints(design, setup):
    """Lines explaining why a setup produced no connectors (shown + logged)."""
    jointed = []
    for occurrence in design.rootComponent.allOccurrences:
        if jt.read_component_joints(occurrence.component):
            jointed.append(occurrence.fullPathName)
    root_joints = len(jt.read_component_joints(design.rootComponent))

    models = []
    try:
        for index in range(setup.models.count):
            models.append(_describe_model(setup.models.item(index)))
    except Exception:
        models.append('(could not read setup models)')

    lines = []
    if not jointed and not root_joints:
        lines.append('No joints are stored anywhere in this design. Re-run Define Joints and press OK.')
    else:
        lines.append(
            f'Joints exist on {len(jointed)} part(s), but none are in this setup\'s models.'
        )
        if root_joints:
            lines.append(
                f'{root_joints} joint(s) are on the root component – parts must be components.'
            )
        lines.append('Jointed: ' + ', '.join(path.split('+')[-1] for path in jointed[:8]))
    lines.append('Setup models: ' + ('; '.join(models[:6]) if models else '(none – whole design)'))

    adsk.core.Application.get().log(
        f'{TITLE} diagnose:\n  jointed occurrences: {jointed}\n'
        f'  root joints: {root_joints}\n  setup models: {models}\n'
        f'  active design: {design.parentDocument.name if design.parentDocument else "?"}'
    )
    return lines


def plan_connectors(design, setup):
    """Return (jobs, problems, notes). Each job is one connector half to machine."""
    z_axis = setup_wcs_z_axis(setup)
    z = (z_axis.x, z_axis.y, z_axis.z)
    occurrences, include_all, paths = _jointed_occurrences(design, setup)

    usage = {}
    for occurrence in occurrences:
        key = occurrence.component.entityToken
        usage[key] = usage.get(key, 0) + 1

    jobs = []
    problems = []
    for occurrence in occurrences:
        component = occurrence.component
        base = occurrence.name if usage[component.entityToken] > 1 else component.name
        partner_seen = {}
        record_labels = {}
        for connector in jt.occurrence_connectors(occurrence):
            record = connector['record']
            joint_id = record.get('id')
            if joint_id not in record_labels:
                partner = record.get('partner') or 'joint'
                partner_seen[partner] = partner_seen.get(partner, 0) + 1
                suffix = f' ({partner_seen[partner]})' if partner_seen[partner] > 1 else ''
                record_labels[joint_id] = f'{base} – {partner}{suffix}'
            name = f'{record_labels[joint_id]} {connector["index"] + 1}'

            role = connector['role']
            orientation = jm.orientation_against(connector['axis'], z)
            problem = None
            if role == jt.ROLE_EDGE and orientation == jm.ORIENT_TILTED:
                problem = 'edge panel is not lying flat'
            elif role == jt.ROLE_FACE and orientation == jm.ORIENT_DOWN:
                problem = 'cavity face is facing down – flip this part in the arrangement'
            elif role == jt.ROLE_FACE and orientation == jm.ORIENT_TILTED:
                problem = 'cavity face is not lying flat'
            if problem:
                problems.append(f'{name}: {problem}')
                continue
            jobs.append(
                {
                    'role': role,
                    'name': name,
                    'point': connector['point'],
                    'feed': jt.vector3d(connector['feed']),
                    'connector_type': record.get('connector_type') or DEFAULT_CONNECTOR_TYPE,
                }
            )

    notes = []
    if not include_all and not any(
        path.split('+')[-1].startswith(CLAMEX_COMPONENT_NAME) for path in paths
    ):
        notes.append(
            f'"{CLAMEX_COMPONENT_NAME}" will be added to this setup\'s models automatically.'
        )
    return jobs, problems, notes


# --- generation -------------------------------------------------------------

def _depth_axis(setup, flip):
    axis = setup_wcs_z_axis(setup)
    if flip:
        axis.scaleBy(-1.0)
    return axis


def generate(cam, design, setup, options, jobs):
    """Design-side half of generation: the Clamex component + every sketch.

    Returns pending. Each pending entry is (kind, display name,
    sketch entity tokens) with kind 'edge' / 'face' / 'drill'; the CAM
    operations are created later by create_operations(), after the command
    transaction has committed. Setups that live in a CAM-side assembly only see
    design changes once committed; handing CAM uncommitted sketch geometry
    crashes Fusion in applyCurveSelections.
    """
    component, _occurrence = get_or_create_clamex_component(design)

    edge_tool = find_tool_by_description(cam, options['edge_tool'])
    face_tool = find_tool_by_description(cam, options['face_tool'])
    drill_tool = find_tool_by_description(cam, options['drill_tool']) if options['drill'] else None

    edge_jobs = [job for job in jobs if job['role'] == jt.ROLE_EDGE]
    face_jobs = [job for job in jobs if job['role'] == jt.ROLE_FACE]

    # Each pending entry: (kind, display name, tool, sketch entities, preset).
    pending = []

    if edge_jobs:
        if not edge_tool:
            raise RuntimeError(f'Edge tool "{options["edge_tool"]}" was not found.')
        diameter = tool_diameter_mm(edge_tool)
        if not diameter or diameter <= 0:
            raise RuntimeError('Edge tool diameter could not be read from the tool library.')
        half_flute = half_flute_mm(tool_flute_length_mm(edge_tool))
        preset = default_tool_preset(edge_tool)
        drill_preset = default_tool_preset(drill_tool) if drill_tool else None
        depth_axis = _depth_axis(setup, options['edge_flip_z'])
        chain = feed_point_chain()
        for job in edge_jobs:
            connector_type = job['connector_type']
            prefix = default_op_prefix(connector_type)
            try:
                world_points = transform_feed_chain_at(
                    job['point'],
                    job['feed'],
                    depth_axis,
                    chain,
                    cross_offset_mm(connector_type, diameter),
                    options['cutter_z_reference'],
                    half_flute,
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            _sketch, lines = create_feed_path_sketch(component, job['name'], world_points)
            pending.append(
                ('edge', operation_display_name(job['name'], prefix), edge_tool, lines, preset)
            )

            if drill_tool:
                hole = drill_hole_point_at(job['point'], job['feed'], connector_type)
                _drill_sketch, point = create_drill_point_sketch(component, job['name'], hole)
                pending.append(
                    (
                        'drill',
                        operation_display_name(job['name'], f'{prefix} – Drill'),
                        drill_tool,
                        point,
                        drill_preset,
                    )
                )

    if face_jobs:
        if not face_tool:
            raise RuntimeError(f'Face tool "{options["face_tool"]}" was not found.')
        preset = default_tool_preset(face_tool)
        depth_axis = _depth_axis(setup, options['face_flip_z'])
        for job in face_jobs:
            connector_type = job['connector_type']
            world_points = transform_flat_chain_at(
                job['point'], job['feed'], depth_axis, flat_point_chain(connector_type)
            )
            _sketch, lines = create_flat_path_sketch(component, job['name'], world_points)
            pending.append(
                (
                    'face',
                    operation_display_name(job['name'], default_flat_op_prefix(connector_type)),
                    face_tool,
                    lines,
                    preset,
                )
            )

    tokens = []
    for kind, display_name, tool, entities, _preset in pending:
        items = [entities] if kind == 'drill' else list(entities)
        tokens.append((kind, display_name, [item.entityToken for item in items]))
    return tokens


def _resolve(design, token):
    found = design.findEntityByToken(token)
    if not found:
        raise RuntimeError('A Clamex sketch disappeared before its operation was created.')
    return found[0]


def create_operations(cam, design, setup, options, pending):
    """CAM-side half: Clamex into the setup, then one Trace / Drill per pending entry."""
    resolved = [
        (kind, display_name, [_resolve(design, token) for token in tokens])
        for kind, display_name, tokens in pending
    ]
    # Use the component the sketches really live in, never a second name lookup.
    sketch_component = resolved[0][2][0].parentSketch.parentComponent if resolved else None
    _component, clamex_occurrence, in_setup = ensure_clamex_in_setup(
        design, setup, sketch_component
    )
    counts = {'edge': 0, 'face': 0, 'drill': 0, 'in_setup': in_setup}
    tools = {
        'edge': find_tool_by_description(cam, options['edge_tool']),
        'face': find_tool_by_description(cam, options['face_tool']),
        'drill': find_tool_by_description(cam, options['drill_tool']) if options['drill'] else None,
    }
    presets = {kind: default_tool_preset(tool) if tool else None for kind, tool in tools.items()}
    for kind, display_name, entities in resolved:
        if kind == 'drill':
            create_drill_operation(
                setup,
                cam,
                display_name,
                tools['drill'],
                [point_for_assembly(entities[0], clamex_occurrence)],
                options['clearance_mm'],
                presets['drill'],
            )
        else:
            create_trace_operation(
                setup,
                cam,
                display_name,
                tools[kind],
                geometry_for_assembly(entities, clamex_occurrence),
                presets[kind],
            )
        counts[kind] += 1
    return counts


# --- dialog -----------------------------------------------------------------

def _dropdown(inputs, input_id, label, names, default, tooltip):
    dropdown = inputs.addDropDownCommandInput(
        input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle
    )
    for name in names:
        dropdown.listItems.add(name, False, '')
    select_dropdown(dropdown, default)
    dropdown.tooltip = tooltip
    return dropdown


def _pick_default(saved_value, sample, names):
    if saved_value in names:
        return saved_value
    if sample in names:
        return sample
    return None


def _read_options(inputs):
    def dd(input_id):
        return read_dropdown(adsk.core.DropDownCommandInput.cast(inputs.itemById(input_id)))

    def flag(input_id):
        item = adsk.core.BoolValueCommandInput.cast(inputs.itemById(input_id))
        return bool(item and item.value)

    clearance_input = adsk.core.StringValueCommandInput.cast(inputs.itemById(INPUT_CLEARANCE))
    try:
        clearance = float(clearance_input.value)
    except (TypeError, ValueError, AttributeError):
        clearance = DEFAULT_DRILL_CLEARANCE_MM
    return {
        'setup_name': dd(INPUT_SETUP),
        'edge_tool': dd(INPUT_EDGE_TOOL),
        'face_tool': dd(INPUT_FACE_TOOL),
        'drill_tool': dd(INPUT_DRILL_TOOL),
        'cutter_z_reference': dd(INPUT_CUTTER_Z),
        'edge_flip_z': flag(INPUT_EDGE_FLIP_Z),
        'face_flip_z': flag(INPUT_FACE_FLIP_Z),
        'drill': flag(INPUT_DRILL),
        'clearance_mm': clearance,
    }


def _find_setup(cam, name):
    for setup in list_milling_setups(cam):
        if setup.name == name:
            return setup
    return None


class _State:
    def __init__(self):
        self.jobs = []
        self.problems = []
        self.notes = []


def _refresh_plan(inputs, state):
    state.jobs, state.problems, state.notes = [], [], []
    summary = adsk.core.TextBoxCommandInput.cast(inputs.itemById(INPUT_SUMMARY))
    options = _read_options(inputs)
    cam = _cam()
    design = _design()
    setup = _find_setup(cam, options['setup_name']) if cam else None
    if not setup or not design:
        if summary:
            summary.formattedText = 'Select a setup.'
        return
    try:
        state.jobs, state.problems, state.notes = plan_connectors(design, setup)
    except Exception:
        adsk.core.Application.get().log(f'{TITLE} plan: {traceback.format_exc()}')
        if summary:
            summary.formattedText = 'Could not read joints for this setup.'
        return

    if not summary:
        return
    edges = sum(1 for job in state.jobs if job['role'] == jt.ROLE_EDGE)
    faces = sum(1 for job in state.jobs if job['role'] == jt.ROLE_FACE)
    lines = [f'Ready: <b>{edges}</b> Edge slot(s), <b>{faces}</b> Face cavit(ies).']
    if not state.jobs and not state.problems:
        try:
            lines.extend(diagnose_no_joints(design, setup))
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} diagnose: {traceback.format_exc()}')
            lines.append(
                'No joints found on the parts in this setup. Define joints in the Design '
                'workspace first.'
            )
    if state.problems:
        lines.append(f'<b>Skipped {len(state.problems)}:</b>')
        lines.extend(state.problems[:12])
        if len(state.problems) > 12:
            lines.append(f'… and {len(state.problems) - 12} more')
    for note in state.notes:
        lines.append(f'<b>Note:</b> {note}')
    summary.formattedText = '<br>'.join(lines)


def _update_drill_visibility(inputs):
    drill = adsk.core.BoolValueCommandInput.cast(inputs.itemById(INPUT_DRILL))
    clearance = inputs.itemById(INPUT_CLEARANCE)
    if clearance:
        clearance.isVisible = bool(drill and drill.value)


def handle_command_created(args, handlers):
    ui = adsk.core.Application.get().userInterface
    try:
        cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
        cam = _cam()
        if not cam:
            raise UserFacingError(
                'Switch to the Manufacture workspace with an active CAM document, then re-run.'
            )
        setups = list_milling_setups(cam)
        if not setups:
            raise UserFacingError(
                'No CAM setups found. Create a milling setup (with WCS defined) first.'
            )
        tools = prompt_add_example_tools_if_empty(cam, _addin_dir())
        tool_names = [description for description, _tool in tools] or [
            description for description, _tool in list_document_tools(cam)
        ]
        saved = load_settings(_addin_dir())
        inputs = cmd.commandInputs
        cmd.okButtonText = 'Generate'

        _dropdown(inputs, INPUT_SETUP, 'Setup', [s.name for s in setups], saved.get('setup_name'),
                  'Milling setup whose WCS +Z is the machining direction. Joints are read '
                  'from the parts in this setup (the arranged copies when present).')
        _dropdown(inputs, INPUT_EDGE_TOOL, 'Edge tool', tool_names,
                  _pick_default(saved.get('side_tool_description'), SAMPLE_SIDE_DESCRIPTION, tool_names),
                  'Side cutter for Edge T-slots.')
        _dropdown(inputs, INPUT_FACE_TOOL, 'Face tool', tool_names,
                  _pick_default(saved.get('flat_tool_description'), SAMPLE_FLAT_DESCRIPTION, tool_names),
                  'Cutter for Face cavities.')
        _dropdown(inputs, INPUT_DRILL_TOOL, 'Drill tool', tool_names,
                  _pick_default(saved.get('side_drill_tool_description'), SAMPLE_DRILL_DESCRIPTION,
                                tool_names),
                  'Drill for the connector key holes.')
        _dropdown(inputs, INPUT_CUTTER_Z, 'Cutter Z Reference', CUTTER_Z_REFERENCE_OPTIONS,
                  migrate_cutter_z_reference(saved.get('side_cutter_z_reference')),
                  'Which part of the edge-cutter flute sits on the panel mid-thickness.')

        edge_flip = inputs.addBoolValueInput(INPUT_EDGE_FLIP_Z, 'Flip Z (Edge)', True, '',
                                             bool(saved.get('side_flip_z', False)))
        edge_flip.tooltip = 'Same as Flip Z on the Edge tab of the manual command.'
        face_flip = inputs.addBoolValueInput(INPUT_FACE_FLIP_Z, 'Flip Z (Face)', True, '',
                                             bool(saved.get('flat_flip_z', False)))
        face_flip.tooltip = 'Same as Flip Z on the Face tab of the manual command.'

        drill = inputs.addBoolValueInput(INPUT_DRILL, 'Drill key holes', True, '',
                                         bool(saved.get('side_drill_holes', False)))
        drill.tooltip = 'Also drill the key hole for every Edge connector, from the top (+Z) face.'
        clearance = inputs.addStringValueInput(
            INPUT_CLEARANCE, 'Clearance above anchor (mm)',
            str(saved.get('side_drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM)),
        )
        clearance.tooltip = 'Drill retract/clearance height above the anchor plane, in millimetres.'

        inputs.addTextBoxCommandInput(INPUT_SUMMARY, '', '', 10, True)
        _update_drill_visibility(inputs)

        state = _State()
        for event, handler in (
            (cmd.activate, _ActivateHandler(state)),
            (cmd.inputChanged, _InputChangedHandler(state)),
            (cmd.validateInputs, _ValidateHandler(state)),
            (cmd.execute, _ExecuteHandler(state)),
        ):
            event.add(handler)
            handlers.append(handler)
        _register_create_ops_event(handlers)
    except UserFacingError as exc:
        ui.messageBox(str(exc), TITLE)
    except Exception:
        ui.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


class _ActivateHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            _refresh_plan(adsk.core.CommandEventArgs.cast(args).command.commandInputs, self._state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} activate: {traceback.format_exc()}')


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.InputChangedEventArgs.cast(args)
            if event_args.input.id == INPUT_DRILL:
                _update_drill_visibility(event_args.inputs)
            if event_args.input.id == INPUT_SETUP:
                _refresh_plan(event_args.inputs, self._state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} inputChanged: {traceback.format_exc()}')


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        event_args = adsk.core.ValidateInputsEventArgs.cast(args)
        try:
            options = _read_options(event_args.inputs)
            jobs = self._state.jobs
            ok = bool(options['setup_name'] and jobs)
            if any(job['role'] == jt.ROLE_EDGE for job in jobs) and not options['edge_tool']:
                ok = False
            if any(job['role'] == jt.ROLE_FACE for job in jobs) and not options['face_tool']:
                ok = False
            if options['drill'] and not options['drill_tool']:
                ok = False
            event_args.areInputsValid = ok
        except Exception:
            event_args.areInputsValid = False


class _ExecuteHandler(adsk.core.CommandEventHandler):
    """Design-side work only; queues the CAM operations for after commit."""

    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        global _pending_run
        app = adsk.core.Application.get()
        ui = app.userInterface
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            options = _read_options(inputs)
            cam = _cam()
            design = _design()
            setup = _find_setup(cam, options['setup_name'])
            if not setup:
                raise RuntimeError(f'Setup "{options["setup_name"]}" was not found.')
            trace_log.start(f'{TITLE} execute: setup {setup.name}')
            jobs, problems, _notes = plan_connectors(design, setup)
            trace_log.step(f'planned {len(jobs)} job(s); creating sketches')
            pending = generate(cam, design, setup, options, jobs)
            trace_log.step(f'sketches done; queueing {len(pending)} operation(s)')

            save_settings(
                _addin_dir(),
                setup_name=options['setup_name'],
                side_settings={
                    'tool_description': options['edge_tool'],
                    'drill_tool_description': options['drill_tool'],
                    'cutter_z_reference': options['cutter_z_reference'],
                    'flip_z': options['edge_flip_z'],
                    'drill_holes': options['drill'],
                    'drill_clearance_mm': options['clearance_mm'],
                },
                flat_settings={
                    'tool_description': options['face_tool'],
                    'flip_z': options['face_flip_z'],
                },
            )

            _pending_run = {
                'options': options,
                'pending': pending,
                'problems': problems,
            }
            app.fireCustomEvent(CREATE_OPS_EVENT_ID, '')
        except RuntimeError as exc:
            trace_log.step(f'runtime error: {exc}')
            ui.messageBox(str(exc), TITLE)
        except Exception:
            trace_log.step(f'python error: {traceback.format_exc()}')
            ui.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


# --- post-commit operation creation ------------------------------------------

CREATE_OPS_EVENT_ID = 'LamelloPSystemCNC_JointGenerateCreateOps'
_pending_run = None
_create_ops_event = None


class _CreateOpsHandler(adsk.core.CustomEventHandler):
    """Runs after Generate's transaction commits, so CAM sees the new sketches."""

    def notify(self, args):
        global _pending_run
        run, _pending_run = _pending_run, None
        if not run:
            return
        app = adsk.core.Application.get()
        ui = app.userInterface
        try:
            options = run['options']
            cam = _cam()
            design = _design()
            setup = _find_setup(cam, options['setup_name']) if cam else None
            if not setup or not design:
                raise RuntimeError(f'Setup "{options["setup_name"]}" was not found.')
            trace_log.step('post-commit: creating operations')
            counts = create_operations(cam, design, setup, options, run['pending'])
            trace_log.step(f'finished {counts}')

            problems = run['problems']
            message = [
                f'Created {counts["edge"]} Edge and {counts["face"]} Face Trace operation(s).'
            ]
            if counts['drill']:
                message.append(f'Created {counts["drill"]} Drill operation(s).')
            if problems:
                message.append(f'\nSkipped {len(problems)} connector half(s):')
                message.extend(problems[:15])
                if len(problems) > 15:
                    message.append(f'… and {len(problems) - 15} more')
            if not counts['in_setup']:
                message.append(ADD_TO_SETUP_HINT)
            ui.messageBox('\n'.join(message), TITLE)
        except RuntimeError as exc:
            trace_log.step(f'runtime error: {exc}')
            ui.messageBox(str(exc), TITLE)
        except Exception:
            trace_log.step(f'python error: {traceback.format_exc()}')
            ui.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


def _register_create_ops_event(handlers):
    """(Re-)register the post-commit custom event; survives add-in reloads."""
    global _create_ops_event
    app = adsk.core.Application.get()
    try:
        app.unregisterCustomEvent(CREATE_OPS_EVENT_ID)
    except Exception:
        pass
    _create_ops_event = app.registerCustomEvent(CREATE_OPS_EVENT_ID)
    handler = _CreateOpsHandler()
    _create_ops_event.add(handler)
    handlers.append(handler)

