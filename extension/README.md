# harhtools 1.6.1

Shape Builder, reusable shapes, arrays, and alignment for Blender 4.2 or newer.

## Install

In Blender, open **Edit > Preferences > Get Extensions**, open its menu, and choose
**Install from Disk**. Select `harhtools-1.6.1.zip` and enable harhtools. Press **N**
in the 3D View and open the **harhtools** sidebar tab.

If an older standalone script or legacy add-on is running, disable it and restart
Blender before installing. Keep one copy enabled. Installing from disk does not
subscribe to the optional public update repository.

## Shape Builder

Select mesh or curve outlines, then press **Shift+Q** or **On** under Shape Builder.
In mesh Edit Mode, only selected visible edges are used. Curve Edit Mode uses segments
whose two control points are selected. Outlines must share a plane.

- **Regions**: each click creates a separate fill. One continuous drag merges only
  the regions/fills it crosses; untouched fills stay separate. Crossing an existing
  fill includes that whole fill. **Alt + click/drag** removes touched fills only.
  Starting with Alt on an unfilled region does nothing.
- **Edge Trim**: start with all source fragments retained; **Alt + drag** removes
  the fragments between intersections; click/drag restores them.
- **Enter** creates one object per fill; **Esc / right-click** cancels; **Ctrl+Z** undoes a stroke.
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
Partially coincident duplicate cubic intervals are rejected before producing false slivers;
remove the overlapping duplicate guide and retry. Complete duplicates are supported.

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

Enable **Snap to Geometry**, or press **S** while the preview is active. Drag near
an unselected visible curve or mesh edge on the same plane; the target determines
the even border thickness. A target on the wrong side of a shape cannot set that
shape's inset/outset. Hidden or locked guides and out-of-plane geometry are excluded.
Finish and restart the tool after editing snap-target geometry.

Each selected object receives an independent outline. Original shapes are kept
and hidden by default so their filled centers do not obscure the new border.
Uncheck **Hide Original Shapes** to keep them visible. Outputs stay in the sources'
collections and inherit their materials. No library preset is saved automatically.

The result is a filled, editable **POLY Curve** with closed border splines. Bezier
inputs are adaptively sampled with a recorded world-space error bound; the new
offset is not an exact Bezier curve. Original Bezier data stays intact. The preview
uses lighter sampling; confirmation rebuilds at final precision. Opening corners
use circular joins to avoid long spikes. Widths that collapse tips, cross boundaries,
or merge holes are rejected, with the original shape preserved. NURBS, open paths,
nonplanar shapes and ambiguous intersecting source loops are not supported.

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
  controls their visibility from 0–100% (15% by default); 100% uses normal native
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
