"""harhtools: planar Shape Builder and object centering for Blender."""

from . import shape_builder, centering


def register():
    try:
        shape_builder.register()
        centering.register()
    except Exception:
        unregister()
        raise


def unregister():
    centering.unregister()
    shape_builder.unregister()
