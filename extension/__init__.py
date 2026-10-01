"""harhtools: planar Shape Builder, arrays, and object centering for Blender."""

import bpy
from . import icons, shortcuts, shape_library, shape_builder, array_tool, centering


def register():
    try:
        icons.register()
        shortcuts.register()
        shortcuts.refresh_theme(shortcuts.settings(),bpy.context)
        shape_library.register()
        shape_builder.register()
        array_tool.register()
        centering.register()
    except Exception:
        unregister()
        raise


def unregister():
    centering.unregister()
    array_tool.unregister()
    shape_builder.unregister()
    shape_library.unregister()
    shortcuts.unregister()
    icons.unregister()
