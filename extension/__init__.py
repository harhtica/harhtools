"""harhtools: planar Shape Builder, arrays, and object centering for Blender."""

import bpy
from . import icons, shortcuts, shape_library, shape_builder, array_tool, outline_tool, circle_arc, edit_arc, centering, live_reload, display_units, profile_editor


def register():
    try:
        display_units.register()
        icons.register()
        shortcuts.register()
        shortcuts.refresh_theme(shortcuts.settings(),bpy.context)
        shape_library.register()
        shape_builder.register()
        array_tool.register()
        outline_tool.register()
        profile_editor.register()
        circle_arc.register()
        edit_arc.register()
        centering.register()
        live_reload.register()
    except Exception:
        unregister()
        raise


def unregister():
    live_reload.unregister()
    centering.unregister()
    edit_arc.unregister()
    circle_arc.unregister()
    profile_editor.unregister()
    outline_tool.unregister()
    array_tool.unregister()
    shape_builder.unregister()
    shape_library.unregister()
    shortcuts.unregister()
    icons.unregister()
    display_units.unregister()
