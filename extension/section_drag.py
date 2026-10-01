"""A lifted copy of a native sidebar box that follows a section drag."""
from collections import Counter, deque
import math
import bpy


def find_box(pixels,width,height,click_x,click_y,scale=1):
    """Find the connected box background beside its grip, in framebuffer pixels."""
    def rgb(x,y):
        p=(y*width+x)*4
        return tuple(pixels[p:p+3])
    samples=[]
    for y in range(max(0,round(click_y-6*scale)),min(height,round(click_y+6*scale)+1)):
        for x in range(max(0,round(click_x-28*scale)),min(width,round(click_x-14*scale)+1)):
            samples.append((rgb(x,y),x,y))
    if not samples:return None
    color=Counter(item[0] for item in samples).most_common(1)[0][0]
    seed=next((x,y) for value,x,y in samples if value==color)
    seen=set();queue=deque([seed]);left=right=seed[0];bottom=top=seed[1]
    while queue:
        x,y=queue.popleft()
        if not (0<=x<width and 0<=y<height):continue
        key=y*width+x
        if key in seen:continue
        seen.add(key)
        if any(abs(a-b)>1 for a,b in zip(rgb(x,y),color)):continue
        left=min(left,x);right=max(right,x);bottom=min(bottom,y);top=max(top,y)
        queue.extend(((x-1,y),(x+1,y),(x,y-1),(x,y+1)))
    if right-left<60*scale or top-bottom<25*scale:return None
    # Include antialiased box edges, without capturing surrounding controls.
    return (max(0,left-1),max(0,bottom-1),min(width,right+2),min(height,top+2))


class SectionDragPreview:
    def __init__(self,context,event,title,color,first):
        self.area=context.area;self.region=context.region
        self.space_type=type(context.space_data);self.region_type=context.region.type
        self.title=title;self.color=tuple(color);self.first=first
        self.scale=context.preferences.system.ui_scale
        self.start=(event.mouse_x-self.region.x,event.mouse_y-self.region.y)
        self.dy=0;self.moved=False;self.rect=None;self.texture=None;self.drop_edges=None
        self.error=None;self.handler=None;self.attempted=False
        self.handler=self.space_type.draw_handler_add(self.draw,(),self.region_type,'POST_PIXEL')
        self.area.tag_redraw()

    def update(self,mouse_y,moved):
        self.dy=mouse_y-self.region.y-self.start[1]
        self.moved=moved
        self.area.tag_redraw()

    def capture(self):
        import gpu
        vx,vy,width,height=gpu.state.viewport_get()
        framebuffer=gpu.state.active_framebuffer_get()
        data=framebuffer.read_color(vx,vy,width,height,4,0,'UBYTE')
        data.dimensions=width*height*4
        pixels=bytes(data)
        self.rect=find_box(pixels,width,height,*self.start,self.scale)
        if not self.rect:
            raise RuntimeError('Could not locate the section background')
        left,bottom,right,top=self.rect
        # The clear gutter inside each box reveals the sibling's top/bottom
        # without depending on label lengths, panel zoom, or button row counts.
        x=min(right-2,left+max(2,round(3*self.scale)))
        middle=(bottom+top)//2
        color=pixels[(middle*width+x)*4:(middle*width+x)*4+3]
        spans=[];start=None
        for y in range(height+1):
            match=(y<height and all(abs(a-b)<=1 for a,b in zip(
                pixels[(y*width+x)*4:(y*width+x)*4+3],color)))
            if match and start is None:start=y
            if not match and start is not None:
                if y-start>30*self.scale:spans.append((start-2,y+2))
                start=None
        neighbors=[(b,t) for b,t in spans if b<=top+20*self.scale and t>=bottom-20*self.scale]
        self.drop_edges=(min([bottom]+[b for b,t in neighbors]),max([top]+[t for b,t in neighbors]))
        # Capture the actual native controls, preserving their font and pill style.
        rgba=framebuffer.read_color(vx+left,vy+bottom,right-left,top-bottom,4,0,'FLOAT')
        self.texture=gpu.types.GPUTexture((right-left,top-bottom),format='RGBA16F',data=rgba)

    def draw(self):
        context=bpy.context
        if not context.area or context.area.as_pointer()!=self.area.as_pointer():return
        if not context.region or context.region.as_pointer()!=self.region.as_pointer():return
        import gpu,blf
        from gpu_extras.batch import batch_for_shader
        if not self.attempted:
            self.attempted=True
            try:self.capture()
            except Exception as exc:self.error=str(exc)
        shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        old_blend=gpu.state.blend_get();gpu.state.blend_set('ALPHA')
        def polygon(points,color):
            shader.bind();shader.uniform_float('color',color)
            batch_for_shader(shader,'TRIS',{'pos':points},indices=[(0,i,i+1) for i in range(1,len(points)-1)]).draw(shader)
        def rounded(x0,y0,x1,y1,color,r=5):
            r=min(r*self.scale,(x1-x0)/2,(y1-y0)/2)
            points=[]
            for cx,cy,start in ((x1-r,y1-r,0),(x0+r,y1-r,90),(x0+r,y0+r,180),(x1-r,y0+r,270)):
                for i in range(7):
                    angle=math.radians(start+i*15)
                    points.append((cx+r*math.cos(angle),cy+r*math.sin(angle)))
            polygon(points,color)
        def line(x0,y,x1,color,thickness=2):
            polygon([(x0,y),(x1,y),(x1,y+thickness*self.scale),(x0,y+thickness*self.scale)],color)
        try:
            s=self.scale;accent=(*self.color,1)
            if self.rect and self.texture:
                left,bottom,right,top=self.rect
                # Leave a quiet placeholder where the lifted box was.
                rounded(left,bottom,right,top,(.10,.10,.11,.97))
                for x in range(round(left+7*s),round(right-7*s),max(1,round(10*s))):
                    line(x,top-3*s,min(x+5*s,right-7*s),(*self.color,.4),1)
                    line(x,bottom+2*s,min(x+5*s,right-7*s),(*self.color,.4),1)
                x0=left+3*s;x1=right+3*s
                y0=bottom+self.dy;y1=top+self.dy
                rounded(x0-4*s,y0-5*s,x1+4*s,y1+3*s,(0,0,0,.3),7)
                rounded(x0-2*s,y0-2*s,x1+2*s,y1+2*s,accent,6)
                image_shader=gpu.shader.from_builtin('IMAGE')
                image_shader.bind();image_shader.uniform_sampler('image',self.texture)
                batch_for_shader(image_shader,'TRI_FAN',
                    {'pos':[(x0,y0),(x1,y0),(x1,y1),(x0,y1)],'texCoord':[(0,0),(1,0),(1,1),(0,1)]}).draw(image_shader)
                # Mark the actual destination, rather than moving the marker
                # with the floating card and making the drop position ambiguous.
                low,high=self.drop_edges
                target_y=(low-4*s if self.first else high+2*s) if self.moved else top+2*s
                line(left,target_y,right,accent,3)
                message='Release to move '+('below' if self.first else 'above') if self.moved else 'Drag '+('down' if self.first else 'up')+' to reorder'
                label_y=max(6*s,min(self.region.height-18*s,y0-22*s))
                blf.size(0,11*s);blf.position(0,left+4*s,label_y,0);blf.color(0,*accent);blf.draw(0,message)
            else:
                # Still give visible feedback if a third-party theme has no distinct box background.
                x=max(4*s,self.start[0]-180*s);y=self.start[1]+self.dy
                rounded(x,y-14*s,x+175*s,y+14*s,(.12,.12,.13,.98))
                blf.size(0,11*s);blf.position(0,x+8*s,y-4*s,0);blf.color(0,*accent);blf.draw(0,self.title)
        finally:
            blf.color(0,1,1,1,1);gpu.state.blend_set(old_blend)

    def close(self):
        if self.handler is not None:
            self.space_type.draw_handler_remove(self.handler,self.region_type)
            self.handler=None
        self.texture=None
        try:self.area.tag_redraw()
        except ReferenceError:pass
