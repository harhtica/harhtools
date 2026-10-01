"""Architectural moulding sections for Blender's native custom bevel profile.

Sections run from the top (0, 1) to the side (1, 0). Circular portions are
sampled analytically; straight lips remain straight, including undercuts.
"""
import math

ITEMS=[
    ('FILLET','Fillet','Narrow stepped band'),
    ('FASCIA','Fascia','Broad flat band with a recessed foot'),
    ('CAVETTO','Cavetto','Concave quarter-circle with fillets'),
    ('SCOTIA','Scotia','Deep hollow between two lips'),
    ('CONGE','Conge','Concave transition into a straight shaft'),
    ('OVOLO','Ovolo','Convex quarter-circle with fillets'),
    ('ECHINUS','Echinus','Sloping convex egg profile'),
    ('TORUS','Torus','Large semicircular roll'),
    ('ASTRAGAL','Astragal Bead','Small bead above a straight shaft'),
    ('THUMB','Thumb','Asymmetric convex roll'),
    ('BEAD_3Q','Three-quarter Bead','Three-quarter circular bead with an undercut'),
    ('CYMA_RECTA','Cyma Recta','Concave upper curve and convex lower curve'),
    ('CYMA_REVERSA','Cyma Reversa','Convex upper curve and concave lower curve'),
    ('BEAK','Beak','Projecting lip and returning bead'),
]
NAMES={key for key,_,_ in ITEMS}

def arc(cx,cy,rx,ry,start,end,n=12):
    return [(cx+rx*math.cos(start+(end-start)*i/n),cy+ry*math.sin(start+(end-start)*i/n)) for i in range(n+1)]

def cubic(a,b,c,d,n=20):
    return [tuple((1-t)**3*a[j]+3*(1-t)**2*t*b[j]+3*(1-t)*t*t*c[j]+t**3*d[j] for j in range(2)) for t in (i/n for i in range(n+1))]

def path(name):
    if name=='FILLET':points=[(0,1),(.22,1),(.22,.83),(.5,.83),(.5,.14),(.72,.14),(.72,0),(1,0)]
    elif name=='FASCIA':points=[(0,1),(.78,1),(.78,.15),(.28,.15),(.28,0),(1,0)]
    elif name=='CAVETTO':points=[(0,1),(.9,1)]+arc(.9,.1,.8,.8,math.pi/2,math.pi)+[(.1,0),(1,0)]
    elif name=='SCOTIA':points=[(0,1),(.82,1)]+arc(.82,.5,.62,.4,math.pi/2,3*math.pi/2,24)+[(.82,0),(1,0)]
    elif name=='CONGE':points=[(0,1),(.8,1)]+arc(.8,.48,.42,.42,math.pi/2,math.pi)+[(.38,.1),(.18,.1),(.18,0),(1,0)]
    elif name=='OVOLO':points=[(0,1),(.9,1)]+arc(.1,.9,.8,.8,0,-math.pi/2)+[(.1,0),(1,0)]
    elif name=='ECHINUS':points=[(0,1),(.95,1)]+cubic((.95,.87),(.95,.52),(.5,.18),(.22,.1))+[(.22,0),(1,0)]
    elif name=='TORUS':points=[(0,1),(.3,1)]+arc(.3,.5,.4,.4,math.pi/2,-math.pi/2,24)+[(.3,0),(1,0)]
    elif name=='ASTRAGAL':points=[(0,1),(.5,1)]+arc(.5,.72,.15,.15,math.pi/2,-math.pi/2,18)+[(.5,.12),(.25,.12),(.25,0),(1,0)]
    elif name=='THUMB':points=[(0,1),(.25,1)]+cubic((.25,.9),(.95,.55),(1.05,.1),(.25,.1))+[(.25,0),(1,0)]
    elif name=='BEAD_3Q':points=[(0,1),(.6,1)]+arc(.6,.55,.35,.35,math.pi/2,-math.pi,30)+[(.2,.55),(.2,0),(1,0)]
    elif name=='CYMA_RECTA':points=[(0,1),(.9,1)]+arc(.9,.5,.4,.4,math.pi/2,math.pi)+arc(.1,.5,.4,.4,0,-math.pi/2)[1:]+[(.1,0),(1,0)]
    elif name=='CYMA_REVERSA':points=[(0,1),(.9,1)]+arc(.5,.9,.4,.4,0,-math.pi/2)+arc(.5,.1,.4,.4,math.pi/2,math.pi)[1:]+[(.1,0),(1,0)]
    elif name=='BEAK':points=[(0,1),(.95,1)]+cubic((.95,.85),(.86,.45),(.64,.12),(.45,.3))+arc(.3,.3,.15,.15,0,-math.pi,16)[1:]+[(.15,.12),(.05,.12),(.05,0),(1,0)]
    else:raise ValueError('Unknown architectural profile: '+name)
    return points

def snapshot(profile):
    return dict(points=[(tuple(p.location),p.handle_type_1,p.handle_type_2,p.select) for p in profile.points],
                clip=profile.use_clip,straight=profile.use_sample_straight_edges,even=profile.use_sample_even_lengths)

def restore(profile,saved,segments):
    while len(profile.points)>2:profile.points.remove(profile.points[1])
    # Insert on a simple diagonal first; assigning coordinates afterwards keeps
    # the ordered path intact even for rolls that turn back under themselves.
    rows=saved['points'];count=len(rows)
    for i in range(1,count-1):profile.points.add(1-i/(count-1),i/(count-1))
    profile.use_clip=saved['clip'];profile.use_sample_straight_edges=saved['straight'];profile.use_sample_even_lengths=saved['even']
    for p,(co,_,_,_) in zip(profile.points,rows):p.location=co;p.select=False
    # Blender's handle RNA setter applies to selected profile points, not just
    # the point used to call it. Isolate each selection to preserve step corners.
    for p,(_,h1,h2,_) in zip(profile.points,rows):
        p.select=True;p.handle_type_1=h1;p.handle_type_2=h2;p.select=False
    for p,(_,_,_,selected) in zip(profile.points,rows):p.select=selected
    profile.update();profile.initialize(segments)

def configure(profile,name,segments):
    restore(profile,dict(points=[(co,'VECTOR','VECTOR',False) for co in reversed(path(name))],clip=True,straight=True,even=False),segments)
