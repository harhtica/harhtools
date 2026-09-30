"""Small vector-style pink and white icons, generated without image dependencies."""
import math
import bpy.utils.previews

PINK = (1.0, 0.65, 0.78)
WHITE = (1.0, 0.97, 0.99)
_previews = None


def _line(x, y, ax, ay, bx, by, width=0.06):
    dx, dy = bx-ax, by-ay
    t = max(0, min(1, ((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(x-ax-t*dx, y-ay-t*dy) <= width


def _sample(name, x, y):
    r = math.hypot(x, y)
    if name == 'heart':
        yy = y + 0.13
        return PINK if (x*x+yy*yy-0.48)**3-x*x*yy**3 < 0 else None
    if name == 'shape':
        a = math.hypot(x+0.24, y-0.13)
        b = math.hypot(x-0.24, y+0.13)
        if abs(a-0.49)<0.065 or abs(b-0.49)<0.065:return WHITE
        if a<0.49 or b<0.49:return PINK
    elif name == 'bounds':
        if r<0.13:return WHITE
        if 0.53<max(abs(x),abs(y))<0.67:return PINK
        if (abs(x)<0.045 and abs(y)<0.38) or (abs(y)<0.045 and abs(x)<0.38):return WHITE
    elif name == 'origin':
        if r<0.15 or 0.41<r<0.53:return PINK
        if ((abs(x)<0.055 and 0.55<abs(y)<0.8) or
                (abs(y)<0.055 and 0.55<abs(x)<0.8)):return WHITE
    elif name in {'add','remove'}:
        if abs(y)<0.075 and abs(x)<0.55:return WHITE
        if name=='add' and abs(x)<0.075 and abs(y)<0.55:return WHITE
        if 0.66<r<0.78:return PINK
    return None


def register():
    global _previews
    unregister()
    _previews = bpy.utils.previews.new()
    try:
        for name in ('heart','shape','bounds','origin','add','remove'):
            pixels=[]
            for j in range(32):
                for i in range(32):
                    colors=[_sample(name, (i+(sx+.5)/3)/16-1, (j+(sy+.5)/3)/16-1)
                            for sy in range(3) for sx in range(3)]
                    colors=[color for color in colors if color is not None]
                    if colors:
                        pixels.extend([sum(c[k] for c in colors)/len(colors) for k in range(3)])
                        pixels.append(len(colors)/9)
                    else:pixels.extend((0,0,0,0))
            preview=_previews.new(name)
            preview.icon_size=(32,32)
            preview.icon_pixels_float=pixels
    except Exception:
        unregister()
        raise


def icon(name):
    return _previews[name].icon_id if _previews and name in _previews else 0


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews=None
