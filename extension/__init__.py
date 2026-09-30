"""harhtools: planar Shape Builder and object centering for Blender."""

from . import icons, shape_builder, centering


def register():
    try:
        icons.register()
        shape_builder.register()
        centering.register()
    except Exception:
        unregister()
        raise


def unregister():
    centering.unregister()
    shape_builder.unregister()
    icons.unregister()
