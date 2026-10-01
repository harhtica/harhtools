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
    x, y = x / 1.08, y / 1.08
    r = math.hypot(x, y)
    if name == 'heart':
        yy = y + 0.13
        return PINK if (x*x+yy*yy-0.48)**3-x*x*yy**3 < 0 else None
    if name == 'shape':
        a = math.hypot(x+0.24, y-0.13)
        b = math.hypot(x-0.24, y+0.13)
        if abs(a-0.49)<0.065 or abs(b-0.49)<0.065:return WHITE
        if a<0.49 or b<0.49:return PINK
    elif name == 'array':
        # Three rounded rectangular ribs along a shallow arc.
        for index,(cx,cy,angle) in enumerate(((-.55,-.15,-.25),(0,.04,0),(.55,-.15,.25))):
            dx,dy=x-cx,y-cy
            xx=abs(dx*math.cos(angle)+dy*math.sin(angle))
            yy=abs(-dx*math.sin(angle)+dy*math.cos(angle))
            qx,qy=max(xx-.075,0),max(yy-.37,0)
            distance=math.hypot(qx,qy)-.085
            if abs(distance)<.045:return WHITE if index==0 else PINK
    elif name == 'align':
        if _line(x,y,0,-.76,0,.76,.055):return WHITE
        if (abs(x)<.64 and .23<y<.50) or (abs(x)<.40 and -.48<y<-.21):return PINK
    elif name == 'library':
        if abs(x)<.71 and abs(y)<.66:
            if abs(x)>.60 or abs(y)>.55:return WHITE
            if any(abs(x-cx)<.19 and abs(y-cy)<.18 for cx in (-.29,.29) for cy in (-.27,.27)):return PINK
    elif name == 'gear':
        tooth=(math.atan2(y,x)*8/math.tau)%1
        outside=.78 if .16<tooth<.84 else .61
        if .25<r<outside:return (.82,.83,.85)
    elif name == 'grab':
        # A curled hand with four knuckles, thumb and cuff; no font dependency.
        palm=(-.39<x<.43 and -.45<y<.28)
        fingers=any(_line(x,y,cx,.12,cx,top,.13)
                    for cx,top in ((-.31,.49),(-.08,.62),(.15,.59),(.36,.42)))
        thumb=_line(x,y,-.46,-.17,-.57,.14,.15)
        cuff=abs(x-.025)<.32 and -.68<y<-.40
        if palm or fingers or thumb or cuff:
            if any(_line(x,y,cx,.17,cx,.34,.025) for cx in (-.19,.035,.265)):
                return (.18,.10,.14)
            if cuff or _line(x,y,-.39,-.12,-.10,-.01,.04):return PINK
            return WHITE
    elif name == 'swap':
        if _line(x,y,-.64,.29,.62,.29,.07) or _line(x,y,.64,-.29,-.62,-.29,.07):return WHITE
        if any(_line(x,y,*line,.07) for line in [(.62,.29,.30,.56),(.62,.29,.30,.02),(-.62,-.29,-.30,-.56),(-.62,-.29,-.30,-.02)]):return PINK
    elif name == 'keycap':
        if abs(x)<.70 and abs(y)<.72:
            if abs(x)>.56 or abs(y)>.56:return PINK
            if abs(x)<.37 and -.24<y<.06:return WHITE
    elif name == 'keyboard':
        if abs(x)<.86 and abs(y)<.58:
            if abs(x)>.74 or abs(y)>.46:return PINK
            if -.33<y<-.20 and abs(x)<.43:return WHITE
            if any(abs(x-cx)<.08 and abs(y-cy)<.07 for cx in (-.51,-.17,.17,.51) for cy in (.02,.28)):return WHITE
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


def register(pink=None,white=None):
    global _previews,PINK,WHITE
    if pink is not None:PINK=pink
    if white is not None:WHITE=white
    unregister()
    _previews = bpy.utils.previews.new()
    try:
        for name in ('heart','shape','align','array','library','gear','grab','bounds','origin','add','remove','keyboard','keycap','swap'):
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
            # Composite a half-display-pixel dark border beneath the antialiased icon.
            base=pixels[:]
            for j in range(32):
                for i in range(32):
                    k=(j*32+i)*4;a=base[k+3]
                    halo=max(base[(y*32+x)*4+3] for y in range(max(0,j-1),min(32,j+2))
                             for x in range(max(0,i-1),min(32,i+2)))*.9
                    alpha=a+(1-a)*halo
                    if alpha:
                        for c in range(3):pixels[k+c]=(base[k+c]*a+.015*(1-a)*halo)/alpha
                        pixels[k+3]=alpha
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
