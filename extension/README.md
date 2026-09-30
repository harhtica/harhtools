# harhtools

Blender extension: Shape Builder and object centering.

## Shape Builder

- Select all mesh/curve outlines that enclose the areas you want to fill.
- Use **Shape Builder** in the panel, or **Shift+M** over the 3D View.
- In Edit Mode, only selected visible mesh edges are used.
- Hover to preview a region. Click or drag to choose adjoining regions.
- Hold Alt and click/drag to remove chosen regions from the preview. A pink
  minus sign and stronger pink hover show removal mode; release Alt to add again.
- Ordinary clicks add regions; clicking a chosen region keeps it selected.
- Ctrl+Z undoes a selection stroke; Backspace clears the chosen regions.
- Enter creates a new Shape Builder object. Esc/right-click cancels.
- Original wire guides remain unchanged.
- Gap Snap can bridge tiny gaps in the preview/new shape; set it to 0 for exact wires.
- Outlines must be coplanar. Output uses clean planar n-gons with only the
  connecting edges needed around holes, rather than an all-quad retopology.

Shift+M invokes Shape Builder in Object Mode and mesh Edit Mode while enabled.

## Centering

Select the objects to move, then Shift-select the target last to make it active.

- **Center Shapes to Active** matches the visible bounding-box centers.
- **Match Origins to Active** matches the object origins.
- The active object stays in place; rotation, scale, and mesh coordinates are preserved.
- Small red ALREADY CENTERED text or purple MOVED text appears at the target for one second.
- The movement distance and world X/Y/Z offsets are recorded in Blender's Info log.
- Ctrl+Z undoes a move.

Disable the add-on in Preferences to remove its panel and shortcuts.

Blender installation reference:
https://docs.blender.org/manual/en/latest/editors/preferences/addons.html
