# harhtools 1.15.0

Shape Builder, reusable shapes, arrays, and alignment for Blender 4.2 or newer.

## Install

In Blender, open **Edit > Preferences > Get Extensions**, open its menu, and choose
**Install from Disk**. Select `harhtools-1.15.0.zip` and enable harhtools. Press **N**
in the 3D View and open the **harhtools** sidebar tab.

If an older standalone script or legacy add-on is running, disable it and restart
Blender before installing. Keep one copy enabled. Installing from disk does not
subscribe to the optional public update repository.

## Selected Arc (mesh Edit Mode)

Select the vertices of one continuous outline section, or use **Edge Select**
to select open edge sections on a filled plane. A single straight edge works;
several disconnected selected ends round separately in the active mesh. Choose
**Selected Arc > Adjust Selected Arc** at the top of the harhtools tab.
**Arc Amount** sets the angle and **Roundness** blends each section toward an arc.
**Reverse Bend** flips the arc to the other side. Changes appear in the workspace.
Press **Enter** or **Ctrl+A** with the pointer over the viewport to keep the result, or **Esc**
to undo slider changes since your last manual mesh edit.

**Arc Plane: Shape** uses the connected unselected geometry to keep the bend in
its plane, including straight sections made by subdividing an edge. If the
section was previously bent out of that plane, adjusting it at full Roundness
returns only that section to the shape plane. Unselected vertices stay fixed.
For isolated straight lines, choose **Object XY**, **Object XZ**, or **Object YZ**;
these axes are local to the object, so they follow its rotation. An incompatible
plane is rejected if it would require moving the fixed endpoints.

Only the selected sections change. In Edge Select mode, each section's two end
corners stay fixed. Vertex Select mode also preserves adjacent unselected joins,
so selecting a lower tip leaves an upper tip unchanged.
**Match Nearby Spacing** is on by default for wire arcs and selected face edges. It measures up to three
untouched edges adjoining each end, takes their median world-space length, and
chooses the closest vertex count for the new arc (3â€“2048 vertices). Switch it off
for a manual **Vertices** count. Without usable adjoining edges, the manual count
is used. Selected face edges gain points by splitting those edges in place;
neighboring faces remain attached and retain their materials and custom data.
Existing face-connected vertices are never removed, so their count is the lower
limit. Subdivision can leave a face with more than four corners; it does not
rebuild the entire plane into quads. Vertex Select mode retains the original
face-connected vertex count. Each selected edge section must be flat and
unbranched. Unselected diagonals and cross edges do not become part of the arc.
A complete closed wire loop is
also supported. Open sections stop at 359 degrees because their ends stay apart.

You can move, rotate or scale vertices, or select another section, with the
controls still open. They refresh after a native transform ends; an invalid
selection pauses them until a continuous section is selected again. Starting
the tool leaves the mesh unchanged until a control is adjusted. Unselected
joining vertices remain unselected when a wire section is resampled.

Undo or Redo ends the active arc session before Blender restores history. Click
**Adjust Selected Arc** again to continue with the resulting selection. Expired
arc controls recover automatically instead of hiding the remainder of the sidebar.

## Readable distances

The **Distances** selector at the top of Harhtools defaults to **Roblox Studs**.
Thickness, bevel depth/width, array gap/radius and their workspace readouts use
studs with compact decimals. The Transform tab shows the selected object's size
in the chosen units. **Scene Units** restores native distance fields.

The conversion respects scene Unit Scale and uses
[Roblox's standard 1 stud = 0.28 metres](https://create.roblox.com/docs/physics/units).
This changes display/input only, not geometry, transforms or scene units.
Blender's own panels keep their native labels. Match your Roblox import scale
settings to the source units when exporting.

## Apply an active tool

With the pointer over the viewport, **Ctrl+A** applies the active Shape Builder,
Make Outline, Selected Arc, Array or shape-placement operation. **Enter** remains
available. Sidebar fields retain their normal text-editing controls, and the
shortcut does not replace Blender's normal Ctrl+A when no Harhtools operation is
active. Tools such as Fit Selected already apply immediately when clicked.

## Fit / Align

Open the **Fit / Align** tab (the second sidebar icon). This replaces the old
Transform page and keeps these controls separate from Shape Builder.

In Object Mode, select the shapes to fit, then select the surrounding frame
last so it is active. Click **Fit Selected into Active**. All selected source
objects move and scale as one arrangement; disconnected shapes within one mesh
work the same way. The active frame stays fixed, and Ctrl+Z undoes the fit.

- **Proportional Scale** starts on and preserves proportions, including depth.
  Turn it off to fit width and height separately along the target's plane axes.
- **Equal Boundary Spacing** starts on. It balances the closest outer-edge gaps
  by maximizing minimum clearance to a convex frame, such as a circle, rectangle
  or pointed arch. This centers a three-circle arrangement using its outer
  contacts, rather than its bounding-box center. It does not make unlike shapes
  parallel at every point or rearrange the individual circles.
- **Gap** sets minimum clearance from the outer geometry to the frame, in studs
  or scene units. **Fill** below 100 percent leaves additional room.
- **Frame Opening** uses the largest inner opening when the target has one;
  otherwise it uses the largest outer boundary. **Outer Boundary** explicitly
  fits to the frame's outside contour instead.

The target must have a closed planar mesh or Bezier/Poly boundary. Target base
boundaries define the frame; selected sources are measured from their evaluated
mesh geometry, including modifiers. The solver encloses all source geometry in
one convex envelope and checks entire edges against the target, not just object
boxes or origins. Concave targets use a conservative centered fit with Equal
Boundary Spacing off. Selected sources are centered onto the target plane.

Fitting does not remesh or change vertex counts. A rotated, non-proportional fit
may need a private transformed mesh/curve data copy because Blender object
channels cannot represent shear. Linked copies remain unchanged. Constraints,
drivers or modifiers that prevent a verified fit cancel the operation and restore
the original state. Fitting does not save Shape Library entries.

## Editable bevel profiles

**Make Outline** is above the bevel section so it stays reachable. **Add Bevel**
is off initially; enable it to reveal profiles and Blender's editable point graph.
Every preset opens directly in this editor without an extra edit click. Editor
data is prepared outside sidebar drawing, which also works in Edit Mode.

Each preset uses a private working copy. Drag/add/delete points and use the native
handle and sampling controls. Selecting a point alone does not create a profile. The first shape
edit creates **<preset> - Edited**, changes the preset selector to **My Profile**,
and refreshes an active Make Outline workspace preview.
Built-in presets remain unchanged and can be chosen again at any time.

Rename the edited profile with **Name**, or choose another saved one with **My
Profile**. **New Profile Copy** protects the current user profile while creating
another variation. Edited profiles are retained as Blender curve datablocks
without scene objects and persist when you save the blend file. They do not
create Shape Library entries. **Update Selected Border** applies the current
settings to an existing border; finished borders do not change until updated.

## Circle / Arc (Object Mode)

Select a complete mesh or Bezier/Poly circle and click **Edit Circle / Arc**.
**Sides / Segments** sets full-circle resolution: 3 makes a triangle, while higher
values approach a smooth circle. **Arc Amount** opens the circle, and **Start
Angle** chooses the cut. **Fill** closes a partial arc with a straight chord.
The panel displays the mesh's base vertex and triangle counts. Wire outlines
have zero faces/triangles; these counts exclude modifiers.

At the original resolution, the original sampling points remain in place for
snapping; cuts add exact-angle endpoints. Center, radius and object transforms
stay unchanged. **Restore Original Circle** restores the original datablock,
including Bezier handles. Controlled curve output uses Poly splines after editing
the sliders. Linked copies keep their original data. No shape preset is saved.

## Shape Builder

Select mesh or curve outlines, then press **Shift+Q** or **On** under Shape Builder.
In mesh Edit Mode, only selected visible edges are used. Curve Edit Mode uses segments
whose two control points are selected. Outlines must share a plane.

- **Regions**: each click creates a separate fill. One continuous drag merges only
  the regions/fills it crosses; untouched fills stay separate. Crossing an existing
  fill preserves your earlier joins. **Alt + click/drag** or **Remove** subtracts
  only the original regions you touch, even inside a merged fill. Removing a
  bridge separates the remaining pieces; you can refill the gap without undo.
  Starting with Alt on an unfilled region does nothing. Hover shows the original
  region boundaries for both Add and Remove.
- **Edge Trim**: start with all source fragments retained; **Alt + drag** removes
  the fragments between intersections or pronounced corners; click/drag restores
  them. Corners with a turn greater than 45 degrees stop a trim run. Smooth curve
  joins and fine circular tessellation stay continuous.
- **Enter / Ctrl+A** creates one object per fill; **Esc / right-click** cancels; **Ctrl+Z** undoes a stroke.
- Hover gives a faint preview. Larger dots mark intersections and a trail follows dragging.
- **Gap Snap** bridges small gaps. Set it to zero to use the outlines exactly.
- **Editable Curve** is the default result. Original cubic Bezier handles are retained
  through intersection splitting and reconstructed as editable spline boundaries.
  Disconnected shapes and holes become separate cyclic splines; trimmed paths can be open.
  Edge Trim always produces editable curves. Optional **Planar Mesh** keeps the older output.
- **Cut Selected Guides** cuts actual intersections into the selected mesh guides when
  you confirm, including selected coplanar faces. It is off by default; cancelling
  changes nothing. This option is disabled for curve guides, which remain unchanged.
  Gap Snap connectors remain preview/output geometry and are not added to guides.

**Shape Library saves only when you click its + button.** Confirming fills does not
create presets or write preview files. Existing presets remain available in the
library box beneath Shape Builder. Drag a preset's large preview or thumbnail/name row into the viewport and release
to place a copy at the preview. **Esc / right-click** cancels placement.
The hand on the thumbnail marks the draggable preview. **Place at 3D Cursor**
below it is a placement toggle; when lit, dropping places the shape at the cursor.
**Lock to Object** picks a target; **Align Rotation** matches its orientation.
**Surface Magnet** follows surfaces under the mouse. During a drag, press
**X / Y / Z** and move the mouse to rotate; press the same axis again to resume
placement. Hold **Shift** for fine rotation. Search sits above the list;
save, rename, delete and refresh actions sit on the right.
Double-click a preset's name to rename it. Use **+** to save the last selected
mesh or curve. Thumbnails have true transparency, including holes; the preview
does not retain a gray selection highlight or a baked checker pattern.
Presets are independent snapshots; deleting one does not delete scene objects.
Curve presets preserve Bezier coordinates, handle coordinates and types, spline closure,
tilt/radius and curve settings. Existing mesh presets continue to work.
Drag either box's grip to reorder Shape Builder and Shape Library.

Fills appear immediately. Region boundaries, screen outlines and feedback buffers
are cached until their inputs change; navigation refreshes screen projections.
The visual drag trail is bounded without dropping the regions crossed by the stroke.
On confirmation, the tool checks Blender's actual curve fill against the preview.
A missing or substantially different fill cancels the entire commit before guide
cutting or selection changes, so it cannot silently leave a broken result.

### Curve behavior and limits

Preview and hit testing use sampled paths, while saved Bezier spans come from the original
control polygons. At nearly coincident joins, numerical detours smaller than the source's
coordinate precision are welded between substantial spans; endpoint and adjacent handle
adjustments are bounded and recorded on the output data. Original source curves are unchanged,
and complete tiny regions are kept. This prevents missing native fills after confirmation.
Mesh wires remain straight pen segments; workshop circle meshes carrying
`harh_circle` metadata can instead be reconstructed as cubic circular arcs. Standard cubic
Bezier circles approximate circles; they are not mathematically exact rational circles.
Use native Bezier guides when you want a small, editable set of pen handles.

Planar Bezier and Poly inputs are supported. NURBS Shape Builder input is rejected with an
explanation rather than silently flattened. The library can still preserve NURBS presets.
Complete and partially shared straight/Bezier paths are supported, including
reversed directions. The shared interval uses one original source in the preview
and output; overlapping baselines are not stacked or turned into sliver regions.
All original source objects remain unchanged. A straight Bezier that doubles back
over itself must be split at its turning point before overlapping-edge trimming.

This provides Illustrator-style merge/erase and editable paths, but is not a full Illustrator
clone: Enter commits a new result, source guides remain unchanged, and Shift marquee is not
implemented. It does not add Illustrator's pen-drawing tool. Blender's native curve handles
remain editable. Tested headlessly in Blender 5.2; live mouse/GPU interaction has not been
verified in the user's desktop session. Minimum-version metadata is retained from 1.4.0,
but this local update's validation was performed on 5.2 only.

## Make Outline

Select closed curves or flat mesh shapes in **Object Mode**, then click
**Make Outline** beneath Shape Builder. Set **Thickness** numerically or drag
inside the shape to preview an inset. Choose **Outside** to drag an outward border.
**Enter** creates the result; **Esc / right-click** cancels without changing geometry.
Flat boundaries can be rotated or placed away from the world origin. Plane
validation uses double-precision calculations and does not flatten source data.

**Corners: Sharp** is the default. Adjacent parallel offset edges meet at a sharp
point, keeping Gothic tips pointed. Acute tips extend to their proper intersection.
With Safe Inset enabled, thickness narrows locally where a full-width sharp offset
would cross or collapse. Choose **Round** for circular opening-corner joins.

**Result: Mesh Border** is the default. It creates connected border faces with
consistent normals and aspect-preserving planar UVs, ready for mesh editing or
extrusion. Sharp Safe Inset keeps one matching offset vertex per source vertex,
forming an ordinary quad strip through every corner. Use **Ctrl+R** across the
strip for a closed loop cut around the whole border. The source perimeter and
sharp points stay fixed; the border gets thinner where space is limited. The
center remains hollow. **Curve Outline** retains the
previous filled POLY-curve output when a curve result is wanted. Sharp corner
seams remain explicit even when cleanup changes the number of offset points.
Existing results are not rewritten: regenerate an older border for this topology.

### Optional bevel profiles

With **Result: Mesh Border**, enable **Add Bevel** and choose **Depth**, **Bevel
Width**, **Profile**, and **Segments**. Profiles are **Rounded**, **Chamfer**,
**Concave**, **Soft Square**, and **Custom** (an adjustable native bevel Shape
value). Chamfer uses one segment. The editable point graph displays the native
profile controls for every preset. During Make Outline, shaded depth and bevel geometry
appear in the workspace before **Enter**, using the same native modifiers as
the final border. Changes are coalesced and unchanged geometry is cached.
Escape removes the preview without creating an output object.

The Profile menu also includes 14 architectural mouldings: **Fillet**, **Fascia**,
**Cavetto**, **Scotia**, **Conge**, **Ovolo**, **Echinus**, **Torus**, **Astragal Bead**,
**Thumb**, **Three-quarter Bead**, **Cyma Recta**, **Cyma Reversa**, and **Beak**.
These are distinct native custom-profile paths, including flat lips and undercuts.
The sections are normalized presets inspired by traditional mouldings; use Width
to size them. Choosing one starts with at least 32 segments; the Segments control
then allows 1Ã¢â‚¬â€œ128. Low counts simplify the section and may lose small details.
After creating a border, its custom profile can also be edited in the native
Bevel modifier. **Update Selected Border** reapplies the selected preset.

To change an existing flat mesh border, select it in Object Mode, choose settings
here, then click **Update Selected Border**. This updates the two existing
Harhtools modifiers rather than adding duplicates. The base vertices, faces and
UVs remain editable. You can also edit **Harhtools Border Depth** and **Harhtools
Border Bevel** directly in Blender's modifier panel, or remove them to return to
the flat border. Depth extends behind the original face.

Only perimeter edges get bevel weight. Internal strip seams and the vertical
edges at sharp silhouette corners remain unweighted. Native overlap clamping
limits the bevel where necessary; a very large requested width may therefore
be reduced locally. These are native Blender
[bevel profiles](https://docs.blender.org/manual/en/5.2/modeling/modifiers/generate/bevel.html),
not subdivision or a change to the original outline. Bevel depth/width use the
mesh's local units; newly generated borders have unit scale. Apply object scale
first if an older border has been scaled and you need predictable world widths.

### Snapping and output

Enable **Snap to Geometry**, or press **S** while the preview is active. Drag near
an unselected visible curve or mesh edge on the same plane; the target determines
the even border thickness. A target on the wrong side of a shape cannot set that
shape's inset/outset. Hidden or locked guides and out-of-plane geometry are excluded.
Finish and restart the tool after editing snap-target geometry.

A green highlighted edge, diamond contact marker, white measurement line and
width label show exactly which target will be used. Hover reveals the target;
drag to set its thickness. The capture radius is 22 pixels at normal UI scale.

**Copy Thickness** below the thickness field (or **C** during Make Outline) lets
you click a mesh edge or straight Poly segment to use its world-space length.
Pick an edge running across an existing border, not along its perimeter. Object
scale is included; the display respects your scene units or Roblox Studs setting.
The selected edge stays unchanged. **Esc** cancels the picker, and an active
outline preview resumes. Curved Bezier segments have no straight edge length;
use a mesh edge or Poly segment to measure a width.

Dragging and snap hover process the latest pointer position at most 30 times per
second; hover never rebuilds the border. Numeric edits coalesce
the same way, and releasing the mouse or pressing Enter uses the final value.
The first snap query can briefly pause while a large scene's guide cache is built;
that scan is skipped entirely while snapping remains off.

Each selected object receives an independent outline. Original shapes are kept
and hidden by default so their filled centers do not obscure the new border.
Uncheck **Hide Original Shapes** to keep them visible. Outputs stay in the sources'
collections and inherit their materials. No library preset is saved automatically.

Bezier inputs are adaptively sampled with a recorded world-space error bound;
the new offset is not an exact Bezier curve. Dense mesh/poly boundaries are simplified
within the same recorded tolerance while preserving corners. Original source
data stays intact. The preview uses lighter sampling; confirmation rebuilds at
final precision. **Safe Inset** is on by default. With **Corners: Sharp**, it narrows
thickness locally before corners or nearby boundaries collide. Matching inner and
outer rows remain connected by quads; no triangle fans or interior junction poles
are added. Full-width areas use the ordinary miter offset. Every preview starts
from the original source, so reducing thickness restores its detail automatically.
The preview status says when thickness narrows at tight corners. With **Corners:
Round**, crowded sections can still close, split or merge, and resolved junctions
can contain poles. Originals remain recoverable after confirmation; the finished
mesh itself is not a procedural inset modifier. Turn Safe Inset off to reject
widths that change the boundary topology. NURBS, open paths,
nonplanar shapes and ambiguous intersecting source loops are not supported.

## Shader Editor: Connect Textures

Drop Image Texture nodes into the material Shader Editor, select the maps you
want, and click **Connect Textures** in its top header. The button arranges the
textures in Base Color, Metallic, Roughness, Normal order and connects them in a
short, smooth sequence. It uses the active/selected Principled BSDF, or the one
feeding the material output. If none exists, it creates one.

Names such as `ColorMap`, `BaseColor`, `Albedo`, `MetalnessMap`, `Metallic`,
`RoughnessMap`, `NormalMap`, and `nor_gl` identify the maps. An explicit Image
Texture node label can override a file name. Unconnected recognized maps are
picked automatically if no selected map exists for their role; multiple candidates
ask you to select the one to use. Unknown maps and packed ORM/metallic-roughness
maps are skipped rather than assigned to an incorrect input.

- Base Color: Color output to Principled Base Color; transparent RGBA also
  connects its Alpha output to Principled Alpha. Opaque, ignored or channel-packed
  alpha does not enable transparency. UDIM alpha is not automatically detected.
- Metallic/Roughness: Non-Color, Color output to the corresponding shader input.
- Normal: Non-Color, Color output to Normal Map Color; Normal output to Principled
  Normal. Existing converters are reused when possible.

The shader and its directly connected output stay beside the ordered texture
column, and the finished setup is framed in the editor. Images shared elsewhere are isolated when their color space must change,
so another material's use of that image keeps its interpretation. **Esc** cancels
and restores the graph during the animation; **Enter / Ctrl+A** finishes it at
once. The completed action supports ordinary Undo. The button operates on the
currently edited shader tree, including material node groups, and is hidden in
World, Geometry Nodes and Compositor editors.

## Reload installed updates without reverting the file

From 1.6.0 onward, **Settings > Reload Installed Updates** watches the local extension
version. After a newer version is installed and its files settle, Harhtools reloads
only its own code when Blender is idle in Object Mode. Current geometry, selection,
the open file and compatible tool settings remain in place. Active tools, animation,
rendering and editing postpone the reload. Failed updates restore the previous code.
The loaded version and pending/error status appear in Harhtools Settings.

An already running older version needs one initial activation. Open the repository's
`tools/reload_harhtools.py` in Blender's Scripting Text Editor and run it after installing
1.6.0, or restart Blender once. The helper targets only the enabled Harhtools extension.
It does not save or revert the blend file or reload other add-ons. Older Blender versions
without the active-modal inspection API safely request a restart instead.
The updated helper also recovers the 1.6.0 Preferences enable failure: it finds one
installed Harhtools copy, discards that package's stale modules, and enables the
corrected code. Finish active tools and enter Object Mode before recovery. Open
the updated helper from disk if an older copy is already in your Text Editor.

## Transform / Align

Select the objects to move, then Shift-select the target **last**.

- **Center Shapes to Last** matches their visible world-space bounding-box centers,
  including evaluated modifiers and independent of each object's local axes.
- **Match Origins to Last** matches their object origin positions.

The last selected object stays in place. A brief label reports the result; Ctrl+Z
undoes the move. Detailed movement distances are available in Blender's Info log.

## Array

Open the Array tab with meshes or curves selected in Object Mode. The preview
starts automatically and follows selection changes. **Generate / Enter** creates
copies; **Cancel / Esc** discards the preview. Leaving the Array tab clears it.
Undo and redo rebuild the preview while the Array tab is active.
Switching to another Blender sidebar category, or hiding the sidebar, pauses
the preview and restores faded guides. Returning to harhtools refreshes it.

- **Auto Axis** suggests an axis. Click **X / Y / Z** beneath it, or hold **Shift + scroll wheel**
  over the viewport, to choose one manually. **Global / Last** uses scene axes or
  the last selected object's local orientation.
- **Linear** repeats the selected group in one direction. Count includes the
  original group; Gap is measured between neighboring group bounds.
- **Fit Length** uses two objects. Select the endpoint first and the piece to
  repeat last. Whole copies fill the gap between them without resizing either
  original. Remaining space is distributed evenly while respecting Min Gap.
- **Circular** keeps the original at the first position. Count is the number
  of new groups: five copies plus the original make six positions. Sweep sets
  the arc. From Source uses Radius; Last Origin and 3D Cursor calculate it.
- **Rotate Copies** turns each group with the ring. **Fit Ring** calculates a
  matching radius in From Source mode. With **3D Cursor** or **Last Origin**, it
  measures the section's angular span and calculates how many whole copies fit.
  A 60-degree section gives five copies plus the original. Any remainder stays
  open instead of stretching or overlapping the pieces. Keep the pivot at the
  section's construction center. Align modular outlines before adding bevels.
  **Linked Copies** shares mesh/curve data.
- **Hide Inactive** fades unselected mesh/curve guides. **Inactive Opacity**
  controls their visibility from 0Ã¢â‚¬â€œ100% (15% by default); 100% uses normal native
  display. Sidebar sliders do not interrupt this control. Original visibility is
  restored when the tool closes, before saving, and through undo/redo.

## Settings

Each tab has collapsible sections. Use the arrow beside a section title to fold
it; Shape Builder/Library and the two Settings sections retain their reorder grips.

The gear sits below the tool tabs. **Shape Builder Shortcuts** has two buttons
per row: the undo-shaped icon resets that binding, and the key button captures
a replacement. Toggle on uses one binding in Object and Edit Mode.

**Color Theme** includes Pink, Lavender, Blue, Mint, Royal Purple, Peach, Ocean,
Gold, Rose, and Monochrome. Changing a color switches to **Custom**. Give it a
name and click **Save Theme**; later use **Save Changes** to rename/update it.
Colors and opacity update an unconfirmed Shape Builder preview immediately.
Selected-fill opacity defaults to 50%; hover previews are much fainter.

Theme changes are saved automatically. Named presets and the current custom
colors survive restarts and extension updates. **Save Settings** saves shortcut
bindings and box order in Blender preferences. Button rounding follows Blender's
global theme; the extension does not change it automatically.

## Where your presets are saved

Presets live outside the installed extension, so replacing its ZIP does not
overwrite them. They are local to your computer, not included in a shared ZIP or
automatically shared with your friend.

- Color themes: Blender's configuration folder, `harhtools/color_themes.json`.
  On a standard Windows Blender 5.2 installation this is
  `%APPDATA%/Blender Foundation/Blender/5.2/config/harhtools/color_themes.json`.
- Shapes and square PNG previews: the shared Blender user folder,
  `%APPDATA%/Blender Foundation/Blender/harhtools/shapes` on Windows.
- Shortcuts and box order: Blender's saved user preferences.

Blender profiles can override these paths. When moving to a different computer
or Blender configuration, copy the theme file and shapes folder too. Shape
storage is shared across Blender versions; theme settings use that version's
configuration folder and should be copied when migrating to a new one.
