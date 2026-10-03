# harhtools

A Blender extension with an editable-curve Shape Builder, reusable shape library,
outlines, arrays, and object alignment tools.
Requires Blender 4.2 or newer; tested on Blender 5.2.

## Version 1.19.0

- **Array > Deform > Deform Copies** gradually scales each complete copied group.
  **Last Copy Size** is a percentage of the unchanged original: 25% with four
  linear pieces gives 100%, 75%, 50%, 25%. All axes shrink evenly.
- **Keep Edge Gaps** preserves the linear gap as copies change size or rotation.
  Switch it off to retain the original positions. **Progression** controls how
  the change is distributed; **Move / Rotate** adds optional gradual transforms.
- Textured previews smoothly animate the size changes and match generation,
  including **Join Generated**. UV coordinates stay unchanged. Deformation pauses
  during Fit Length or Fit Ring so those existing fits retain their behavior.

## Included from 1.18.2

- Spacing and alignment now always move **whole objects in Object Mode**. Joined
  groups retain their internal arrangement, even with an older saved Disconnected
  Pieces setting. Object Mode measures the outside of each whole group.
- **Edit Mode** still spaces and aligns selected disconnected pieces. The old
  object/piece selector is replaced with a label showing what will move.

## Included from 1.18.1

- **Align to Active** in **Fit / Align > Space / Align Pieces** uses the last-selected
  object as a fixed reference for Center, Min Edge or Max Edge alignment. In Edit
  Mode, the piece containing the active vertex, edge or face is the reference.
  Switch it off to keep using the combined selection bounds.
- Auto preserves the moving row direction while aligning across it. With one
  moving piece, Auto aligns all three axes to the reference. UVs and sizes stay fixed.

## Included from 1.18.0

- **Fit / Align > Space / Align Pieces** works in Object Mode and Mesh Edit Mode.
  **Distribute Even Gaps** spaces disconnected pieces by their outer mesh edges,
  preserving the two end pieces, sizes, UVs and topology. Joined arrays work
  directly; choose **Whole Objects** to keep each object's arrangement together.
- **Align Pieces** aligns centers, minimum edges or maximum edges. Auto detects
  the row direction for spacing and aligns across it; X/Y/Z and Global/Active
  axes provide manual control. Select any vertex, edge or face in an Edit Mode
  island to move that whole island. Other islands stay untouched. Both support Undo.

## Included from 1.17.0

- **Array > Join Generated**, just above Generate, combines the original and all
  circular or linear copies into one mesh. Materials and UVs are preserved, and
  visible modifiers and curves become mesh geometry. Off retains separate copies.
- Joined circular results place their origin at the rotation center, including
  the 3D Cursor. Linear results use the active source origin. Fit Length leaves
  its separate bookend reference untouched. Undo restores the original objects.

## Included from 1.16.2

- Keeps textured array copies visible through ordinary input and source
  transforms. Updated surfaces replace the old surfaces without removing the
  preview objects, and unchanged poses no longer trigger repeated scene updates.

## Included from 1.16.1

- Array previews now show the actual source materials, UV textures and alpha
  cutouts in Material Preview and Rendered view. **Visibility > Show Materials**
  is enabled by default; switch it off for the previous wire preview.
- Preview surfaces share evaluated geometry and reuse their objects while the
  array moves. They cannot be selected, stay out of final renders and saves,
  and are removed on Cancel, Generate, Undo and tool changes.

## Included from 1.16.0

- **Fit / Align > Bake / Match Size > Fit Bake to Active** fits a baked plane
  to the original mesh, including meshes with depth, open edges and modifiers.
  Select the bake first and the original last. No closed boundary is required.
- Width and height match independently by default; **Proportional Scale** keeps
  the aspect ratio. **Use Visible Alpha** ignores transparent padding within the
  plane's own UV crop, including cropped texture atlases.
- **Align Rotation** matches the original plane and compares the alpha silhouette
  to handle rotated geometry. Without a usable alpha silhouette it uses object
  axes. **Facing Surface**, **Center**, **Keep Current**, and **Surface Offset**
  control depth. The original, UVs and mesh topology stay unchanged; Undo works.
- The existing closed-boundary fitting tool remains under **Inside Frame**.

## Included from 1.15.1

- Fixes Connect Textures cancelling with `'Event' object has no attribute 'timer'`
  when its animation starts. The animation now uses Blender's supported event
  type and elapsed time, including when other tools have active timers.

## Included from 1.15.0

- **Connect Textures** in the material Shader Editor header arranges image nodes
  as Base Color, Metallic, Roughness and Normal, then connects them to Principled
  BSDF with a short animated sequence. Select a set to resolve duplicate maps.
- Data maps become Non-Color; normals pass through a Normal Map node. Real
  base-color transparency connects to Alpha. Repeated clicks reuse the converter.
  Esc restores the graph during animation; finished changes support normal Undo.

## Included from 1.14.0

- Sharp **Safe Inset** now works like a normal Make Outline: one matching inner
  vertex per outer vertex, connected by a single quad strip. **Ctrl+R** continues
  around the whole border, including sharp tips.
- Thickness narrows locally before tight corners or nearby boundaries collide.
  The original perimeter stays fixed, full-width areas keep the ordinary offset,
  and reducing thickness restores detail from the original source. The preview
  reports local narrowing. Round joins retain the previous collision behavior.

## Included from 1.13.2

- Safe Inset collision meshes now have all-quad faces and a continuous quad row
  along every boundary. Hover that row with **Ctrl+R** to cut around the border,
  including narrow tips, without stopping at a triangle.
- Original boundaries and sharp corners stay fixed. Some straight edges gain
  midpoint vertices; regular quads are split only when a neighboring patch needs
  the connection. Collapsed junctions retain local poles inside the boundary rows,
  so an arbitrary loop through the middle of a branching junction can still stop.

## Included from 1.13.1

- Fixes long diagonal face fans in collapsed Safe Inset sections. Cross-strip
  edges now follow the original boundary normals and meet at local collision
  junctions. Both topology changes and locally trimmed sharp tips use this flow.
- Preserves the perimeter and normal quad strips. Short triangles remain where
  topology changes; the generated border still supports depth and bevel profiles.

## Included from 1.13.0

- **Safe Inset** is on by default. Tight corners and narrow sections can close,
  split or merge as thickness changes. Lowering the width during preview restores
  detail from the original boundary. Resolved borders remain editable mesh faces.
- Geometry snapping catches within 22 UI pixels and works on hover as well as
  during dragging. A green edge highlight, contact marker, measurement line and
  label identify the target. Pointer checks are coalesced without idle mesh rebuilds.
- **Copy Thickness**, beside the width field, picks the world-space length of a
  mesh edge or straight Poly segment. Press **C** during Make Outline to sample
  an existing border's cross edge, then keep adjusting the same preview.

## Included from 1.12.3

- Fixes the Selected Arc sidebar disappearing after Undo or an interrupted tool.
  Expired Blender operator references are released, and the start button returns.
- Undo/Redo stop arc tracking before Blender replaces the mesh. Native cancel
  and modal errors clean up timers and scratch meshes instead of locking tools.
- The reload helper can repair an already-stuck older session without reopening
  or saving the blend file. A live arc interaction is still allowed to finish.

## Included from 1.12.2

- **Selected Arc** accepts open edge sections on filled meshes. In Edge Select
  mode, select one or more end caps; each rounds separately with fixed corners.
- A single straight edge can gain arc vertices while remaining attached to its
  faces. **Match Nearby Spacing** or a manual **Vertices** count controls detail.
  Existing face vertices and cross edges are retained; extra points subdivide
  the selected edges without cutting unrelated geometry.
- Selection follows the edges actually selected, so unselected diagonals no
  longer create false branches. Preview, manual edits, Escape and Ctrl+A work
  across all selected sections in the active mesh.

## Included from 1.12.1

- Remove cuts only the region under the pointer, including inside a previous
  merged fill. Erasing a bridge separates the surviving pieces so later edits
  do not silently reconnect them. Hover exposes the original region boundaries.
- **Ctrl+A** applies an active Shape Builder, Make Outline, Selected Arc,
  Array or shape-placement operation. Enter still works; native field editing
  and Blender's idle Ctrl+A behavior remain available.

## Included from 1.12.0

- **Fit / Align**, separate from Shape Builder, adds **Fit Selected into Active**.
  Select shapes first and the frame last. One mesh with several disconnected
  shapes and several selected objects are treated as one arrangement.
- **Proportional Scale** preserves proportions; disable it to fit width and
  height separately. Fitting uses visible outer geometry and the actual closed
  target boundary, with the frame opening preferred over its outside edge.
- **Equal Boundary Spacing** balances the closest gaps to a convex frame.
  **Gap** supports Roblox studs; **Fill** leaves additional room. The frame,
  selection and unselected objects stay fixed; Ctrl+Z undoes the operation.

## Included from 1.11.2

- Every bevel preset opens directly in Blender's editable point graph. The
  sidebar no longer uses profile thumbnails or requires an extra edit click.
- Moving, adding or deleting points creates a custom profile. Switching back
  to a preset restores its default shape while preserving your edited copy.
- Editor preparation runs outside panel drawing and reuses unchanged drafts.
  Make Outline remains above the optional bevel controls.

## Included from 1.11.1

- Selected Arc derives its plane from the connected, untouched shape, so straight
  or subdivided sections do not bend out of the surface. Tiny and rotated shapes
  use scale-aware tolerances. Fixed joining points stay in place.
- **Arc Plane: Shape** is automatic; **Object XY/XZ/YZ** provide explicit control
  for isolated straight lines. The previous plane is retained during live edits
  when surrounding geometry cannot determine one.

## Included from 1.11.0

- Fixes missing architectural profile thumbnails by generating outside sidebar
  drawing. The Make Outline button stays above bevel controls; Add Bevel starts off.
- Selected Arc allows normal vertex editing while its controls remain open.
  Unselected joining points stay fixed. Match Nearby Spacing automatically
  resamples wire arcs to match adjoining untouched edges; manual counts remain available.
- Edit Profile Points opens Blender's native point editor on a private copy.
  The first shape edit creates a named custom profile, leaving built-ins intact.
  User profiles drive the thumbnail and active workspace bevel preview.
- Harhtools distances default to Roblox studs, including outline/bevel values and
  array spacing/radius. Scene units remain available, and geometry is not resized.

## Included from 1.10.0

- Adds 14 architectural bevel profiles: Fillet, Fascia, Cavetto, Scotia, Conge,
  Ovolo, Echinus, Torus, Astragal Bead, Thumb, Three-quarter Bead, Cyma Recta,
  Cyma Reversa and Beak. All have matching native section thumbnails and live
  workspace previews. Profiles start at 32 segments, adjustable up to 128.
- Shape Builder accepts partially shared straight and Bezier guides. Shared
  portions appear once, retaining overlap endpoints and crossings. Edge Trim
  stops at pronounced corners so a semicircle's baseline can be erased separately.

## Included from 1.9.0

- **Selected Arc** works on a continuous vertex selection in mesh Edit Mode.
  Round only one section while unselected geometry and its joins stay fixed.
  Adjust the arc angle, roundness and wire vertex count with a live preview;
  Enter keeps it and Escape restores the original geometry and selection.
- **Circle / Arc** controls an existing circle in Object Mode: start angle,
  arc amount, sides/segments down to a triangle, optional fill and triangle count.
  Sampling points remain aligned when cutting an arc at the original resolution.
- **Add Bevel** now shows a native profile cross-section in the sidebar and
  shaded depth/bevel geometry in the workspace before Enter.
- Fixes Shape Builder's false non-flat error on small translated circles using
  double-precision transforms and plane fitting, without flattening geometry.

## Included from 1.8.0

- Mesh borders retain a straight seam between matching sharp corners after
  offset cleanup. Quad merging no longer removes the seam at concave junctions.
- Optional **Add Bevel** adds editable depth and perimeter bevel modifiers.
  Choose **Rounded**, **Chamfer**, **Concave**, **Soft Square**, or **Custom**;
  set depth, width and segments. Internal face-strip seams are not beveled.
- **Update Selected Border** applies those settings to existing flat mesh borders.
  Regenerate older outline results to get the corrected corner topology.

## Included from 1.7.0

- Make Outline now defaults to **Sharp** corners and a **Mesh Border** result.
  Pointed Gothic tips use intersecting parallel offset edges and stay sharp.
- Mesh borders have connected quad strips, with triangles where a junction needs
  them. Hollow centers, consistent normals and planar UVs are validated before
  creation. Original shapes stay recoverable.
- **Round** corners and the previous **Curve Outline** result remain optional.

[Download 1.18.2](https://harhtica.github.io/harhtools/harhtools-1.18.2.zip), or use
the Blender repository below. Reverting a blend file does not reload Python code.
See [tool controls](extension/README.md), [release verification](VERIFICATION.md),
and [regression tests](tests/README.md).

## Included from 1.6.3

- Fixes Make Outline incorrectly reporting depth on a flat, translated shape.
  Plane calculations now use double precision; the original shape and the
  threshold for rejecting genuinely nonplanar boundaries remain unchanged.

## Included from 1.6.2

- Fixes valid outside outlines being rejected at concave Gothic junctions,
  including a 0.14 m border on a Shape Builder result converted to mesh.
- Drag updates process the latest pointer position, with a maximum of 30 preview
  rebuilds per second. Idle hover and unchanged settings do not rebuild geometry.
- Indexed source boundaries speed up geometry snapping on dense shapes. A lighter
  preview keeps final confirmation precise and leaves original geometry intact.

## Included from 1.6.1

- Fixes Shape Builder fills that looked correct in the preview but lost filled
  areas after Enter at closely spaced Gothic curve junctions.
- Confirmation verifies Blender's actual curve fill before changing guides or
  selection. A failed fill rolls back every object in the batch.
- Fixes the `_RestrictData ... window_managers` error when enabling Harhtools
  through Preferences. The reload helper can also recover its failed enable state.

## Included from 1.6.0

- **Make Outline** creates independent, even-width borders around selected closed
  curves and planar meshes. Drag to adjust or enter a thickness, then press Enter.
- Optional **Snap to Geometry** uses nearby coplanar curves or mesh edges to set
  that thickness. Press S to toggle it during the preview.
- Original shapes remain recoverable. Offset results use adaptive sampling;
  invalid or collapsing widths are rejected before committing.
- **Reload Installed Updates** reloads only Harhtools while Blender is idle,
  preserving the current scene and compatible settings. A running older version
  needs the one-time [Scripting-tab helper](tools/reload_harhtools.py) or a restart.

## Included from 1.5.1

- Separate clicks create separate fills. A continuous drag merges only touched
  regions and fills; unrelated fills retain their own boundaries and objects.
- Shape Library saves only when you click **+**. Confirming a fill does not save
  a preset or write a thumbnail.
- Fills appear immediately. Cached outlines and preview buffers reduce repeated
  work while moving the pointer and dragging.
- Shape Builder preserves editable Bezier spans and supports Edge Trim, holes,
  curve Edit Mode, and optional mesh output. Original curve guides remain intact.
- Curve presets retain their handles. Arrays, snapping and alignment controls,
  reusable themes, and optional cutting of mesh guides are also included.

## One-time installation for friends

Repository URL: **https://harhtica.github.io/harhtools/index.json**

1. In Blender, open Edit > Preferences > Get Extensions and allow online access.
2. Open the Repositories menu, click +, and choose Add Remote Repository.
3. Paste `https://harhtica.github.io/harhtools/index.json`.
4. Enable **Check for Updates on Startup** for that repository.
5. Search for **harhtools**, install it, and save preferences if necessary.
6. Press N in the 3D View and open the **harhtools** tab.

Blender checks for published updates; click Update when one is available.
Updates are not silently installed, and editing a local script does not publish it.
The modeling tools themselves work offline.

If the old harhtools.zip add-on is installed, disable and remove that legacy copy
first, then restart Blender before installing this extension. Likewise, restart
if you loaded standalone versions of the scripts in the current session. Only
one copy of the tools should be running. This does not remove scene objects.
Installing this ZIP from disk alone does not subscribe to the public repository.

See [tool controls](extension/README.md).

## Public hosting

[harhtica/harhtools](https://github.com/harhtica/harhtools) publishes its `docs/`
folder through GitHub Pages: **Deploy from a branch**, **main**, **/docs**.
The [download site](https://harhtica.github.io/harhtools/) and its update feed
have been verified, including installation in a separate Blender profile.

Only `docs/` is the published update site. There are no Blender scenes, screenshots,
bridge credentials, or external Python dependencies in the extension package.

## Release your next change

1. Edit the Python files in `extension/`.
2. Increase `version` in `extension/blender_manifest.toml`, for example to `1.8.1`.
3. Run the builder below using Python 3.11+ (Blender's bundled Python works).
4. Test the resulting ZIP in Blender, then commit and push the source and `docs/`.

```powershell
python build_release.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
```

The builder validates the extension and generates the feed using Blender's own
tools. It refuses to replace an existing version with different contents. Old
ZIPs remain available so cached links keep working; the feed lists only the
current release. GitHub Pages deploys the pushed `docs/` folder.

Use this repository's `extension/` as the release source. Copying files only into
Blender's installation folder does not update GitHub or the public repository.
Publish source and generated `docs/` together, verify the deployed feed and ZIP,
then keep local installations on that same release.

This source and extension are packaged under GPL-3.0-or-later; see LICENSE.

References: [Blender extension repositories](https://docs.blender.org/manual/en/5.0/advanced/extensions/creating_repository/static_repository.html)
and [GitHub Pages setup](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
