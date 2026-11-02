"""
Define tab of the Lamello Joints command (Design workspace).

Pick two touching planar faces on the assembled model: the end face of the panel
that gets the Edge slot and the face of the panel it sits against. Set the
connector type, end offset and count, check the live preview of both halves,
then OK stores the joint on both components (lib/joints.py). The joints follow
the parts through Design-workspace Arrange and are machined by the Manufacture
command "Generate from Joints".

Hosted by commands/joints/command.py, which imports it lazily.
"""

import traceback

import adsk.cam
import adsk.core
import adsk.fusion

from lib import joint_math as jm
from lib import joint_preview
from lib import joints as jt
from lib.cam_ops import find_tool_by_description, tool_diameter_mm
from lib.errors import UserFacingError
from lib.settings import load_settings, save_settings
from lib.toolpath_def import DEFAULT_CONNECTOR_TYPE
from lib.ui_helpers import read_dropdown, select_dropdown

TITLE = 'Lamello P-System – Joints'

INPUT_FACES = 'jointFaces'
INPUT_SWAP = 'jointSwap'
INPUT_TYPE = 'jointConnectorType'
INPUT_END_OFFSET = 'jointEndOffset'
INPUT_COUNT = 'jointCount'
INPUT_DELETE = 'jointDelete'
INPUT_INFO = 'jointInfo'

SETTING_TYPE = 'joints_connector_type'
SETTING_END_OFFSET = 'joints_end_offset_mm'
SETTING_COUNT = 'joints_count'


class _State:
    def __init__(self):
        self.draft = None
        self.error = None
        self.existing_id = None
        self.edge_cutter_diameter_mm = jm.NOMINAL_EDGE_CUTTER_DIAMETER_MM


def _preview_edge_cutter_diameter():
    """Edge tool diameter from the document's CAM library, else nominal."""
    try:
        app = adsk.core.Application.get()
        cam = adsk.cam.CAM.cast(app.activeDocument.products.itemByProductType('CAMProductType'))
        description = load_settings().get('side_tool_description')
        if cam and description:
            diameter = tool_diameter_mm(find_tool_by_description(cam, description))
            if diameter and diameter > 0:
                return diameter
    except Exception:
        pass
    return jm.NOMINAL_EDGE_CUTTER_DIAMETER_MM


def _read_values(inputs):
    end_offset = adsk.core.DistanceValueCommandInput.cast(inputs.itemById(INPUT_END_OFFSET))
    count = adsk.core.IntegerSpinnerCommandInput.cast(inputs.itemById(INPUT_COUNT))
    connector = adsk.core.DropDownCommandInput.cast(inputs.itemById(INPUT_TYPE))
    delete = adsk.core.BoolValueCommandInput.cast(inputs.itemById(INPUT_DELETE))
    return {
        'end_offset_mm': end_offset.value * 10.0 if end_offset else jm.DEFAULT_END_OFFSET_MM,
        'count': count.value if count else jm.DEFAULT_CONNECTOR_COUNT,
        'connector_type': read_dropdown(connector, DEFAULT_CONNECTOR_TYPE),
        'delete': bool(delete and delete.isVisible and delete.value),
    }


def _selected_faces(inputs):
    sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(INPUT_FACES))
    if not sel:
        return []
    return [adsk.fusion.BRepFace.cast(sel.selection(i).entity) for i in range(sel.selectionCount)]


def _recompute(inputs, state):
    """Analyse the selected faces and refresh the info text / manipulator."""
    state.draft = None
    state.error = None
    state.existing_id = None

    faces = _selected_faces(inputs)
    swap = adsk.core.BoolValueCommandInput.cast(inputs.itemById(INPUT_SWAP))
    if len(faces) == 2:
        try:
            state.draft = jt.analyze_face_pair(faces[0], faces[1], bool(swap and swap.value))
            state.existing_id = jt.find_existing_joint_id(state.draft)
        except jm.JointGeometryError as exc:
            state.error = str(exc)
        except Exception:
            state.error = 'Could not analyse these faces.'
            adsk.core.Application.get().log(f'{TITLE}: {traceback.format_exc()}')

    delete = adsk.core.BoolValueCommandInput.cast(inputs.itemById(INPUT_DELETE))
    if delete:
        delete.isVisible = bool(state.existing_id)
        if not state.existing_id:
            delete.value = False

    end_offset = adsk.core.DistanceValueCommandInput.cast(inputs.itemById(INPUT_END_OFFSET))
    if state.draft and end_offset:
        try:
            end_offset.setManipulator(
                jt.point3d(state.draft.frame['start']),
                jt.vector3d(state.draft.frame['u']),
            )
        except Exception:
            pass

    _update_info(inputs, state)


def _update_info(inputs, state):
    info = adsk.core.TextBoxCommandInput.cast(inputs.itemById(INPUT_INFO))
    if not info:
        return
    if state.error:
        info.formattedText = f'<b>Can’t make a joint:</b> {state.error}'
        return
    if not state.draft:
        info.formattedText = (
            'Select two touching faces: the <b>end face</b> of the panel that gets the '
            'Edge slot, and the <b>face</b> of the panel it sits against.'
        )
        return

    values = _read_values(inputs)
    frame = state.draft.frame
    positions, warning = jm.connector_positions(
        frame['length_mm'], values['end_offset_mm'], values['count']
    )
    lines = [
        f'<b>{state.draft.edge_component.name}</b> gets the Edge slot',
        f'<b>{state.draft.face_component.name}</b> gets the Face cavity',
        f'Joint {frame["length_mm"]:.0f} mm long, panel {frame["thickness_mm"]:.1f} mm thick',
        'Connectors at ' + ', '.join(f'{p:.0f}' for p in positions) + ' mm',
    ]
    if state.existing_id:
        lines.append('<i>A joint already exists here. OK replaces it.</i>')
    for message in frame['warnings'] + ([warning] if warning else []):
        lines.append(f'<b>Note:</b> {message}')
    info.formattedText = '<br>'.join(lines)


# --- tab interface (hosted by commands/joints/command.py) ------------------------

LABEL = 'Define'
TOOLTIP = 'Pick two touching faces to place connectors on one joint.'


def new_state():
    state = _State()
    state.edge_cutter_diameter_mm = _preview_edge_cutter_diameter()
    return state


def build(inputs, state):
    """Add the Define tab's inputs to *inputs* (the tab's children)."""
    saved = load_settings()

    faces = inputs.addSelectionInput(
        INPUT_FACES,
        'Touching faces',
        'Select the panel end face and the face it sits against',
    )
    faces.addSelectionFilter('PlanarFaces')
    faces.setSelectionLimits(0, 2)
    faces.tooltip = (
        'Two planar faces that touch on the assembled model. The smaller one is '
        'treated as the edge face (gets the Edge slot); use Swap if that is wrong.'
    )

    swap = inputs.addBoolValueInput(INPUT_SWAP, 'Swap edge / face', True, '', False)
    swap.tooltip = 'Swap which panel gets the Edge slot and which gets the Face cavity.'

    connector = inputs.addDropDownCommandInput(
        INPUT_TYPE, 'Connector type', adsk.core.DropDownStyles.TextListDropDownStyle
    )
    connector.listItems.add('P14', False, '')
    connector.listItems.add('P10', False, '')
    select_dropdown(connector, saved.get(SETTING_TYPE, DEFAULT_CONNECTOR_TYPE))

    end_offset_mm = float(saved.get(SETTING_END_OFFSET, jm.DEFAULT_END_OFFSET_MM))
    end_offset = inputs.addDistanceValueCommandInput(
        INPUT_END_OFFSET, 'End offset', adsk.core.ValueInput.createByReal(end_offset_mm / 10.0)
    )
    try:
        end_offset.minimumValue = 0.0
        end_offset.isMinimumValueInclusive = True
    except Exception:
        pass
    end_offset.tooltip = (
        'Distance from each end of the joint to the first and last connector. '
        'Drag the arrow on the canvas or type a value.'
    )

    count = inputs.addIntegerSpinnerCommandInput(
        INPUT_COUNT,
        'Connectors',
        1,
        jm.MAX_CONNECTOR_COUNT,
        1,
        int(saved.get(SETTING_COUNT, jm.DEFAULT_CONNECTOR_COUNT)),
    )
    count.tooltip = 'Number of connectors, evenly spaced between the end offsets.'

    delete = inputs.addBoolValueInput(INPUT_DELETE, 'Delete this joint', True, '', False)
    delete.tooltip = 'Remove the existing joint between these faces instead of saving.'
    delete.isVisible = False

    inputs.addTextBoxCommandInput(INPUT_INFO, '', '', 6, True)
    _update_info(inputs, state)


def activate(inputs, state, faces):
    """Seed the face selection with up to two pre-selected faces."""
    sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(INPUT_FACES))
    for face in faces[:2]:
        sel.addSelection(face)
    _recompute(inputs, state)


def input_changed(inputs, changed, state):
    if changed.id in (INPUT_FACES, INPUT_SWAP):
        _recompute(inputs, state)
    else:
        _update_info(inputs, state)


def is_valid(inputs, state):
    return state.draft is not None


def preview(inputs, state, design):
    joint_preview.draw_existing(design, skip_joint_id=state.existing_id)
    draft = state.draft
    if draft:
        values = _read_values(inputs)
        if not values['delete']:
            world_points, _warning = jt.layout_world_points(
                draft, values['end_offset_mm'], values['count']
            )
            joint_preview.draw_draft(
                design,
                draft,
                world_points,
                values['connector_type'],
                state.edge_cutter_diameter_mm,
            )


def execute(inputs, state, design):
    """Save (or delete) the joint. Returns a message, or None for no message."""
    _recompute(inputs, state)
    draft = state.draft
    if not draft:
        raise UserFacingError(state.error or 'Select two touching faces.')
    values = _read_values(inputs)
    if values['delete'] and state.existing_id:
        jt.delete_joint(design, state.existing_id)
        return None
    jt.save_joint(
        design, draft, values['connector_type'], values['end_offset_mm'], values['count']
    )
    save_settings(
        global_settings={
            SETTING_TYPE: values['connector_type'],
            SETTING_END_OFFSET: round(values['end_offset_mm'], 3),
            SETTING_COUNT: values['count'],
        }
    )
    return None
