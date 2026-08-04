"""
Lamello P-System CNC Toolpath Addin command handlers.

Registers the Manufacture command, wires dialog/preview handlers, and orchestrates
Side/Flat sketch + CAM operation generation on OK.
"""

import os
import traceback

import adsk.core
import adsk.cam
import adsk.fusion

from lib.cam_ops import (
    create_drill_operation,
    create_trace_operation,
    default_tool_preset,
    find_tool_by_description,
    list_milling_setups,
    operation_display_name,
    setup_wcs_z_axis,
)
from lib.path_geometry import (
    create_drill_point_sketch,
    create_feed_path_sketch,
    create_flat_path_sketch,
    geometry_for_assembly,
    get_or_create_clamex_component,
    point_for_assembly,
)
from lib.errors import UserFacingError
from lib.settings import save_settings
from lib.toolpath_def import (
    cross_offset_mm,
    default_flat_op_prefix,
    default_op_prefix,
    feed_point_chain,
    flat_point_chain,
)
from lib.transform import (
    drill_hole_world_point,
    placement_display_name,
    transform_feed_chain,
    transform_flat_chain,
)
from lib.preview import clear_toolpath_preview, draw_toolpath_preview
from lib.placement_sets import MODE_FLAT, MODE_SIDE
from commands.generate_clamex.dialog import (
    build_dialog_inputs,
    handle_input_changed,
    read_dialog_values,
    read_preview_enabled,
    read_preview_values,
    seed_anchor_selection,
)

# CMD_ID is kept stable across releases so existing toolbar customizations keep working.
CMD_ID = 'ClamexGenerateToolpathsCmd'
CMD_NAME = 'Lamello P-System CNC Toolpath Addin'
CMD_DESC = 'Generate Lamello P-System connector toolpaths at selected anchor points'
ADDIN_TITLE = 'Lamello P-System'
_handlers = []


def _addin_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def _resource_folder():
    return './resources'


def _resolve_setup(cam, setup_name):
    for setup in list_milling_setups(cam):
        if setup.name == setup_name:
            return setup
    raise RuntimeError(f'Setup "{setup_name}" was not found.')


def _execute_side_generation(values, setup, setup_z_axis, tool, preset, component, occurrence, cam):
    created_trace_ops = 0
    created_drill_ops = 0
    placement_count = 0
    drill_jobs = []
    local_chain = feed_point_chain()

    for set_data in values.get('sets') or []:
        set_prefix = set_data.get('op_prefix') or default_op_prefix(set_data.get('connector_type'))

        for anchor in set_data['anchor_points']:
            placement_count += 1
            placement_name = placement_display_name(anchor)
            world_points = transform_feed_chain(
                anchor,
                local_chain,
                set_data['reference_axis'],
                setup_z_axis,
                set_data.get('flip_feed', False),
                set_data.get('flip_z', False),
                set_data.get('tool_thickness_offset', True),
                cross_offset_mm(set_data.get('connector_type')),
                values.get('tool_half_thickness_offset_mm'),
            )
            _sketch, sketch_lines = create_feed_path_sketch(component, placement_name, world_points)
            geometry = geometry_for_assembly(sketch_lines, occurrence)

            op_name = operation_display_name(placement_name, set_prefix)
            create_trace_operation(setup, cam, op_name, tool, geometry, preset)
            created_trace_ops += 1

            if set_data.get('drill_holes'):
                drill_jobs.append((set_data, anchor, placement_name, set_prefix))

    drill_tool = None
    drill_preset = None
    if drill_jobs:
        drill_description = values.get('drill_tool_description')
        drill_tool = find_tool_by_description(cam, drill_description)
        if not drill_tool:
            raise RuntimeError(f'Drill tool "{drill_description}" was not found.')
        drill_preset = default_tool_preset(drill_tool)

    for set_data, anchor, placement_name, set_prefix in drill_jobs:
        hole_point = drill_hole_world_point(
            anchor,
            set_data['reference_axis'],
            setup_z_axis,
            set_data.get('flip_feed', False),
            set_data.get('flip_z', False),
            set_data.get('connector_type'),
        )
        _drill_sketch, sketch_point = create_drill_point_sketch(
            component,
            placement_name,
            hole_point,
        )
        point_entity = point_for_assembly(sketch_point, occurrence)
        drill_name = operation_display_name(placement_name, f'{set_prefix} – Drill')
        create_drill_operation(
            setup,
            cam,
            drill_name,
            drill_tool,
            [point_entity],
            set_data.get('drill_clearance_mm', 10.0),
            drill_preset,
        )
        created_drill_ops += 1

    return placement_count, created_trace_ops, created_drill_ops


def _execute_flat_generation(values, setup, setup_z_axis, tool, preset, component, occurrence, cam):
    created_trace_ops = 0
    placement_count = 0

    for set_data in values.get('sets') or []:
        set_prefix = set_data.get('op_prefix') or default_flat_op_prefix(set_data.get('connector_type'))
        local_chain = flat_point_chain(set_data.get('connector_type'))

        for anchor in set_data['anchor_points']:
            placement_count += 1
            placement_name = placement_display_name(anchor)
            world_points = transform_flat_chain(
                anchor,
                local_chain,
                set_data['reference_axis'],
                setup_z_axis,
                set_data.get('flip_feed', False),
                set_data.get('flip_z', False),
            )
            _sketch, sketch_lines = create_flat_path_sketch(component, placement_name, world_points)
            geometry = geometry_for_assembly(sketch_lines, occurrence)

            op_name = operation_display_name(placement_name, set_prefix)
            create_trace_operation(setup, cam, op_name, tool, geometry, preset)
            created_trace_ops += 1

    return placement_count, created_trace_ops


def _execute_generation(values, cam, design):
    if not design:
        raise RuntimeError('Could not access the Design product in this document.')

    setup = _resolve_setup(cam, values['setup_name'])
    setup_z_axis = setup_wcs_z_axis(setup)
    tool = find_tool_by_description(cam, values['tool_description'])
    if not tool:
        raise RuntimeError(f'Tool "{values["tool_description"]}" was not found.')

    preset = default_tool_preset(tool)
    component, occurrence = get_or_create_clamex_component(design)

    if values['mode'] == MODE_SIDE:
        placements, traces, drills = _execute_side_generation(
            values, setup, setup_z_axis, tool, preset, component, occurrence, cam
        )
        return {
            'mode': MODE_SIDE,
            'placements': placements,
            'traces': traces,
            'drills': drills,
        }

    placements, traces = _execute_flat_generation(
        values, setup, setup_z_axis, tool, preset, component, occurrence, cam
    )
    return {
        'mode': MODE_FLAT,
        'placements': placements,
        'traces': traces,
        'drills': 0,
    }


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            event_args = adsk.core.CommandCreatedEventArgs.cast(args)
            cmd = event_args.command
            inputs = cmd.commandInputs

            app = adsk.core.Application.get()
            cam = adsk.cam.CAM.cast(app.activeProduct)
            if not cam:
                raise UserFacingError(
                    'Please switch to the Manufacture workspace with an active CAM document, '
                    'then re-run the add-in.'
                )

            state = build_dialog_inputs(inputs, cam, _addin_dir())

            on_activate = CommandActivateHandler(cmd, state)
            cmd.activate.add(on_activate)
            _handlers.append(on_activate)

            on_input_changed = CommandInputChangedHandler(cmd, state)
            cmd.inputChanged.add(on_input_changed)
            _handlers.append(on_input_changed)

            on_execute_preview = CommandExecutePreviewHandler(state)
            cmd.executePreview.add(on_execute_preview)
            _handlers.append(on_execute_preview)

            on_execute = CommandExecuteHandler(state)
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
        except UserFacingError as exc:
            ui.messageBox(str(exc), ADDIN_TITLE)
        except Exception:
            ui.messageBox(f'{ADDIN_TITLE} dialog failed:\n{traceback.format_exc()}', ADDIN_TITLE)


class CommandActivateHandler(adsk.core.CommandEventHandler):
    def __init__(self, command, state):
        super().__init__()
        self._command = command
        self._state = state

    def notify(self, args):
        try:
            seed_anchor_selection(self._command.commandInputs, self._state)
            _request_toolpath_preview(self._command)
        except Exception:
            app = adsk.core.Application.get()
            app.log(f'Clamex activate failed:\n{traceback.format_exc()}')


def _request_toolpath_preview(command):
    app = adsk.core.Application.get()
    try:
        if not command.doExecutePreview():
            app.log('Clamex preview: doExecutePreview returned False')
    except Exception:
        app.log(f'Clamex preview request failed:\n{traceback.format_exc()}')


def _draw_toolpath_preview(inputs, state):
    app = adsk.core.Application.get()
    if not read_preview_enabled(inputs):
        clear_toolpath_preview(app)
        return
    cam = adsk.cam.CAM.cast(app.activeProduct)
    values = read_preview_values(inputs, state)
    if not values:
        return
    drawn = draw_toolpath_preview(app, values, cam)
    if drawn:
        app.log(f'Clamex preview: drew {drawn} preview sketch(es)')
    viewport = app.activeViewport
    if viewport:
        viewport.refresh()



class CommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, command, state):
        super().__init__()
        self._command = command
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.InputChangedEventArgs.cast(args)
            handle_input_changed(
                event_args.input,
                event_args.inputs,
                self._state,
                self._command,
            )
        except Exception:
            app = adsk.core.Application.get()
            app.log(f'Clamex inputChanged failed:\n{traceback.format_exc()}')


class CommandExecutePreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            _draw_toolpath_preview(event_args.command.commandInputs, self._state)
        except Exception:
            app = adsk.core.Application.get()
            app.log(f'Clamex executePreview failed:\n{traceback.format_exc()}')


def _active_set_or_defaults(state):
    if state.active_index >= 0 and state.sets:
        return state.sets[state.active_index]
    return {}


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        app = adsk.core.Application.get()
        ui = app.userInterface
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            inputs = event_args.command.commandInputs
            values = read_dialog_values(inputs, self._state)

            cam = adsk.cam.CAM.cast(app.activeProduct)
            if not cam:
                raise UserFacingError(
                    'Please switch to the Manufacture workspace with an active CAM document, '
                    'then re-run the add-in.'
                )

            design = adsk.fusion.Design.cast(
                app.activeDocument.products.itemByProductType('DesignProductType')
            )

            results = _execute_generation(values, cam, design)

            active_state = self._state.active_state()
            active_set = _active_set_or_defaults(active_state)

            global_settings = {
                'preview_enabled': read_preview_enabled(inputs),
            }
            if values['mode'] == MODE_SIDE:
                save_settings(
                    _addin_dir(),
                    setup_name=values['setup_name'],
                    side_settings={
                        'tool_description': values['tool_description'],
                        'op_prefix': active_set.get('op_prefix'),
                        'flip_feed': active_set.get('flip_feed', False),
                        'flip_z': active_set.get('flip_z', False),
                        'tool_thickness_offset': active_set.get('tool_thickness_offset', True),
                        'connector_type': active_set.get('connector_type'),
                        'drill_holes': active_set.get('drill_holes', False),
                        'drill_tool_description': values.get('drill_tool_description'),
                        'drill_clearance_mm': active_set.get('drill_clearance_mm'),
                    },
                    global_settings=global_settings,
                )
            else:
                save_settings(
                    _addin_dir(),
                    setup_name=values['setup_name'],
                    flat_settings={
                        'tool_description': values['tool_description'],
                        'op_prefix': active_set.get('op_prefix'),
                        'flip_feed': active_set.get('flip_feed', False),
                        'flip_z': active_set.get('flip_z', False),
                        'connector_type': active_set.get('connector_type'),
                    },
                    global_settings=global_settings,
                )

            if results['mode'] == MODE_SIDE:
                message_parts = [
                    f'Created {results["traces"]} Side Trace operation(s) '
                    f'for {results["placements"]} anchor placement(s).'
                ]
                if results['drills']:
                    message_parts.append(f'Created {results["drills"]} Side Drill operation(s).')
            else:
                message_parts = [
                    f'Created {results["traces"]} Flat Trace operation(s) '
                    f'for {results["placements"]} anchor placement(s).'
                ]
            ui.messageBox('\n'.join(message_parts), ADDIN_TITLE)
        except RuntimeError as exc:
            ui.messageBox(str(exc), ADDIN_TITLE)
        except Exception:
            message = f'Failed:\n{traceback.format_exc()}'
            app.log(f'{ADDIN_TITLE} {message}')
            ui.messageBox(message, ADDIN_TITLE)


def _find_addins_panel(ui):
    panel = ui.allToolbarPanels.itemById('CAMScriptsAddinsPanel')
    if not panel:
        cam_ws = ui.workspaces.itemById('CAMEnvironment')
        if cam_ws:
            panel = cam_ws.toolbarPanels.itemById('CAMScriptsAddinsPanel')
    return panel


def start():
    ui = adsk.core.Application.get().userInterface

    # Recreate the command definition each start so a stale definition (old name,
    # old icon, stacked commandCreated handlers) never survives a reload.
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        panel = _find_addins_panel(ui)
        if panel:
            control = panel.controls.itemById(CMD_ID)
            if control:
                control.deleteMe()
        cmd_def.deleteMe()
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC, _resource_folder())

    on_created = CommandCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)

    panel = _find_addins_panel(ui)
    if panel:
        control = panel.controls.itemById(CMD_ID)
        if not control:
            panel.controls.addCommand(cmd_def)


def stop():
    ui = adsk.core.Application.get().userInterface
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        panel = _find_addins_panel(ui)
        if panel:
            control = panel.controls.itemById(CMD_ID)
            if control:
                control.deleteMe()
        cmd_def.deleteMe()
    _handlers.clear()
