"""harhtools: planar Shape Builder, arrays, and object centering for Blender."""

import bpy
from . import icons, shortcuts, shape_library, shape_builder, array_tool, outline_tool, centering, live_reload


def register():
    try:
        icons.register()
        shortcuts.register()
        shortcuts.refresh_theme(shortcuts.settings(),bpy.context)
        shape_library.register()
        shape_builder.register()
        array_tool.register()
        outline_tool.register()
        centering.register()
        live_reload.register()
    except Exception:
        unregister()
        raise


def unregister():
    live_reload.unregister()
    centering.unregister()
    outline_tool.unregister()
    array_tool.unregister()
    shape_builder.unregister()
    shape_library.unregister()
    shortcuts.unregister()
    icons.unregister()
