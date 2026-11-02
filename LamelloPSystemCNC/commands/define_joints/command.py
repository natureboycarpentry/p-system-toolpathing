"""
Define Joints command (Design workspace).

Pick two touching planar faces on the assembled model: the end face of the panel
that gets the Edge slot and the face of the panel it sits against. Set the
connector type, end offset and count, check the live preview of both halves,
then OK stores the joint on both components (lib/joints.py). The joints follow
the parts through Design-workspace Arrange and are machined by the Manufacture
command "Generate from Joints".

Imported lazily from entry.py.
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

TITLE = 'Lamello P-System – Define Joints'

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


def _design():
    return adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)


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


def handle_command_created(args, handlers):
    ui = adsk.core.Application.get().userInterface
    try:
        event_args = adsk.core.CommandCreatedEventArgs.cast(args)
        cmd = event_args.command
        if not _design():
            raise UserFacingError('Switch to the Design workspace to define joints.')

        saved = load_settings()
        inputs = cmd.commandInputs
        cmd.okButtonText = 'Save joint'

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

        state = _State()
        state.edge_cutter_diameter_mm = _preview_edge_cutter_diameter()
        _update_info(inputs, state)

        for event, handler in (
            (cmd.activate, _ActivateHandler(state)),
            (cmd.inputChanged, _InputChangedHandler(state)),
            (cmd.validateInputs, _ValidateHandler(state)),
            (cmd.executePreview, _PreviewHandler(state)),
            (cmd.execute, _ExecuteHandler(state)),
            (cmd.destroy, _DestroyHandler()),
        ):
            event.add(handler)
            handlers.append(handler)
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
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(INPUT_FACES))
            ui = adsk.core.Application.get().userInterface
            picked = []
            for index in range(ui.activeSelections.count):
                face = adsk.fusion.BRepFace.cast(ui.activeSelections.item(index).entity)
                if face and len(picked) < 2:
                    picked.append(face)
            for face in picked:
                sel.addSelection(face)
            _recompute(inputs, self._state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} activate: {traceback.format_exc()}')


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.InputChangedEventArgs.cast(args)
            if event_args.input.id in (INPUT_FACES, INPUT_SWAP):
                _recompute(event_args.inputs, self._state)
            else:
                _update_info(event_args.inputs, self._state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} inputChanged: {traceback.format_exc()}')


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        event_args = adsk.core.ValidateInputsEventArgs.cast(args)
        event_args.areInputsValid = self._state.draft is not None


class _PreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            design = _design()
            joint_preview.clear(design)
            joint_preview.draw_existing(design, skip_joint_id=self._state.existing_id)
            draft = self._state.draft
            if draft:
                values = _read_values(event_args.command.commandInputs)
                if not values['delete']:
                    world_points, _warning = jt.layout_world_points(
                        draft, values['end_offset_mm'], values['count']
                    )
                    joint_preview.draw_draft(
                        design,
                        draft,
                        world_points,
                        values['connector_type'],
                        self._state.edge_cutter_diameter_mm,
                    )
            event_args.isValidResult = False
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} preview: {traceback.format_exc()}')


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            design = _design()
            joint_preview.clear(design)
            _recompute(inputs, self._state)
            draft = self._state.draft
            if not draft:
                raise RuntimeError(self._state.error or 'Select two touching faces.')
            values = _read_values(inputs)
            if values['delete'] and self._state.existing_id:
                jt.delete_joint(design, self._state.existing_id)
                return
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
        except RuntimeError as exc:
            app.userInterface.messageBox(str(exc), TITLE)
        except Exception:
            app.userInterface.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


class _DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            joint_preview.clear(_design())
        except Exception:
            pass
