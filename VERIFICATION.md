# Release verification

## Version 1.11.1

- All 29 background Blender suites passed; all three arc suites also passed after
  the final center-precision adjustment.
- Reproduced the axis jump on a temporary copy of the saved Shape Builder.004:
  subdivided its longest edge into an open nine-point section and set a 180-degree
  arc. Published 1.11.0 produced 0.0199604 local units of unwanted depth; the fix
  produced zero local depth. The source and the user's saved blend were not modified.
- New regression coverage includes 32 combinations of plane orientation, scale
  and wire/face topology, additional object rotation/nonuniform scale, fixed joins,
  reverse bend, recovery from an off-plane arc, disconnected geometry, tiny curves,
  previous-plane retention, explicit object-plane overrides and live subdivision.
- Tests use background Blender 5.2 and native mesh APIs. The open desktop session
  is not operated or visually verified; no user file is saved or reverted.

## Version 1.11.0

- All 28 regression suites passed in separate background Blender 5.2 processes.
- Profile-panel tests prohibit native geometry generation and preview allocation
  during drawing. All 14 architectural thumbnails are generated on a coalesced
  timer in Edit Mode, with source coordinates/selection and ID counts unchanged.
  Loading/failure placeholders keep the rest of the panel available. Make Outline
  precedes the bevel section, and the one-time UI migration starts Add Bevel off.
- Native point editing forks a preset on the first shape edit, not on point
  selection. Tests verify unchanged built-ins, independent user copies, actual
  modifier and thumbnail changes, retained custom profiles through blend-library
  serialization and removal of unmodified drafts.
- Selected Arc tests exercise manual vertex-edit event pass-through, native
  transform guards, selection recapture, recovery from invalid selections,
  world-space spacing under nonuniform object scale, local resampling and exact
  preservation of unselected joins. A 64-point-circle fixture produces 24 points
  for a 90-degree arc and 69 for 270 degrees at its untouched neighbors' spacing.
  Escape restores the last manual-edit baseline. A 2048-point slider update took
  about 5 ms on the synthetic fixture; this is not a viewport FPS measurement.
- Stud fields round-trip against the 0.28-metre conversion at three scene scales,
  including negative array gaps. Geometry, transforms and unit scale do not
  change. Reload snapshots exclude derived display fields.
- Validation is headless/native API plus simulated draw/event restrictions.
  The user's desktop was not operated, and the user blend file was not saved or
  reverted. Interactive GPU drawing has not been visually verified here.

## Version 1.10.0

- Reproduced the partial-overlap error on the six selected, closed semicircles
  in the saved scene. The corrected arrangement produces 21 regions and 47 trim
  fragments in about 57 ms. Its 11 shared baseline fragments trim away to six
  open arches. Actual source/trim topology was plotted and visually checked;
  source coordinates, selection and the saved scene remain unchanged.
- Shared straight and cubic intervals retain one original source. Regression
  cases cover nested/partial/reversed duplicates, nonuniform straight handles,
  third-guide crossings, rotated tiny inputs, preserved editable source curves,
  no false sliver regions and native filled union area. Pronounced corners stop
  trim runs; smooth joins and ordinary circle sampling remain continuous.
- All 14 architectural presets produce distinct native sections and watertight
  hollow test frames with unchanged base vertices. Their thumbnails match the
  evaluated modifier's 33 section vertices at 32 segments, including undercuts.
  The thumbnail sheet was visually checked. Native custom path points, handle
  types and selection restore after injected batch failure. Escape and code
  reload preserve a user's segment count below the preset's starting count.
- Profile thumbnail changes took roughly 3ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“6 ms in background tests; unchanged
  profiles reuse the cached image. Native preview evaluation leaves no temporary
  scene, object or mesh IDs. These are CPU measurements, not live viewport FPS.
- All 24 suites passed in isolated background Blender 5.2 processes; affected
  profile, cancellation and reload checks were rerun after the final settings
  restoration correction. Live interaction in the user's desktop was not used
  for testing, and no user blend file was saved or reverted.

## Version 1.9.0

- All 22 suites passed in separate background Blender 5.2 processes.
- Selected Arc reshapes only the chosen mesh chain. The bottom-half fixture
  becomes a semicircle while upper vertices and joining anchors remain exact.
  Tests cover local wire resampling, unchanged face connectivity, slider update
  coalescing, confirmation, exact Escape restoration and external-edit protection.
- Circle / Arc preserves original sampling points when cutting arcs, supports
  64/96-point grids and three-sided output, reports native triangle counts, keeps
  transforms and linked originals, and restores original Bezier data. Repeated
  slider edits leave no obsolete datablocks, and controls survive code reload.
- Shaded bevel previews evaluate native Solidify/Bevel in an isolated temporary
  scene. All five profiles differ and leave no scratch scene/object/mesh IDs,
  including on injected failure. Profile thumbnails use actual native bevel
  sections; the generated pixels were visually checked. Draw/cache/state tests
  use mocked GPU APIs, so this does not claim live viewport or FPS verification.
- Reproduced Shape Builder's false depth error on six small translated circles.
  Double-precision world transforms, centroid accumulation and plane fitting
  fix it while retaining the existing rejection threshold for real nonplanarity.
  The latest saved guides produce 10 regions in about 92 ms with source coordinates
  unchanged. They have since been cut into open/branched guides, so bevel preview
  timing used a separate synthetic 64-vertex circle: about 22 ms / 3,584 triangles.
  These are background CPU measurements, not interactive frame rates.
- Reload recovery removes any package modules loaded during cleanup, and outline
  teardown does not import new modules. Restricted registration, orphaned-module
  recovery, active-tool guards and rollback pass. The user scene was not saved,
  reverted or modified during background verification.

## Version 1.8.0

- Sharp corner correspondence is recovered after offset cleanup, checked against
  both boundaries, inserted as constrained edges, and protected from quad merging.
  Portable six-arc Gothic and concave cusp regressions require direct two-face
  seams at the corner pairs while preserving all source and offset coordinates.
- The latest saved arch read during verification had 490 source boundary points
  and 482 offset points. All six corner pairs have explicit seams. Close-up plots
  of actual mesh edges before/after were visually checked. The scene was not saved
  or reverted, and the source coordinates were verified unchanged.
- Rounded, Chamfer, Concave, Soft Square and Custom use native Solidify and Bevel
  modifiers. Native evaluated synthetic frames are distinct, watertight and hollow.
  The four presets also pass manifold/area/topology checks on the saved arch at
  depth 0.005 m and bevel width 0.0003 m; its evaluated profiles were plotted.
- Only boundary edges receive weight. Native Solidify propagates it to top/bottom
  perimeters while new vertical miter edges and internal face seams remain zero.
  Base mesh coordinates, faces and UVs remain unchanged across profile updates.
- Invalid batches are rejected before edits; injected mid-batch failures restore
  previous modifiers/weights and remove new data. Actual operator creation,
  updating, UI property access and cancellation/settings restoration are covered.
- All 18 suites passed in background Blender 5.2. This does not claim live viewport
  interaction or FPS verification. Native overlap clamping can reduce local bevel
  width where space is limited; source shapes remain recoverable.

## Version 1.7.0

- Sharp miter joins intersect adjacent parallel offset lines without a bevel,
  rounding fallback or miter clamp. Acute analytic tips, Gothic arches, holes,
  concave junction cleanup and genuine collapse rejection are covered.
- Make Outline defaults to a mesh border. Corresponding loops form quad strips;
  changed junctions use constrained triangles merged into valid convex quads.
  The writer checks hollow topology, boundary preservation, used vertices,
  consistent winding and area before creating a Blender mesh with planar UVs.
- The saved 492-point arch at Outside 0.002 m produces 486 convex quads and four
  junction triangles. No duplicate/loose vertices, gaps or overlaps were found;
  all four triangle angles are at least 20 degrees. The sharp outer tips agree
  with analytic offset-line intersections within 2.5e-9 world units.
- Its native mesh matches expected ring area within 8.25e-9 relative error and
  all 32,400 coverage probes, keeping the original interior empty. Rendered
  wireframe strips were visually checked. Original source geometry is unchanged.
- Mesh transaction failures roll back every new object/datablock. Corner changes
  refresh the preview, while cancellation restores corner and result settings.
- Normal extrusion of the saved arch by 0.005 m produces a watertight frame;
  volume matches ring area times depth within 1.68e-8 relative error, and rays
  through its original opening remain clear. All 17 regression suites passed.

## Version 1.6.3

- Reproduced the reported flatness error on the newly saved, translated Gothic
  mesh. Its true plane deviation was about 7.53e-9 world units, but accumulating
  world positions in a float32 Vector produced a false deviation of 1.21e-5,
  exceeding the existing 5.03e-6 threshold.
- World transforms, centroid accumulation, plane construction and source
  projection now use Python double precision. The flatness tolerance is unchanged;
  genuine depth is still rejected, and source geometry is not flattened or moved.
- The current saved shape now creates native hollow borders at Outside 0.05 m
  and 0.14 m. Each passed a 14,400-point fill coverage comparison and source
  preservation checks. Rendered results were visually inspected without saving
  the user's scene.
- Geometry regressions include dense mesh, Poly and Bezier boundaries, rotated
  nonuniform transforms, distant positions, float32 baked transforms and genuinely
  warped vertices or off-plane handles. Selection, ownership and source snapping
  retain the precise plane through the operator instead of casting it too early.
- All 16 regression suites passed in isolated Blender 5.2 processes, including
  28 geometry checks, 15 operator checks and 13 interaction checks.

## Version 1.6.2

- Reproduced Make Outline rejecting the saved Gothic mesh at Outside 0.14 m.
  Offset cleanup now classifies concave junctions against the original source
  distance, removing inverted fragments without dropping valid lobes.
- The saved mesh passes widths 0.12, 0.14 and 0.20 m. Portable regressions cover
  the same construction as native curves and converted meshes, even border
  thickness, cusp preservation, hollow Blender fill and genuine collapse rejection.
- Segment indexes remove repeated full-boundary scans. Dense polyline cleanup
  stays within the sampling tolerance and retains exact source segments for snapping.
- On the saved mesh, a 0.14 m preview rebuild measured about 24 ms and precise
  confirmation about 123 ms. In the workshop's 90,747-segment target set, repeated
  eligible snap queries measured 2.09 ms median and 6.21 ms maximum. Initial target
  collection and projection still take about 1.33 seconds; snapping off skips them.
- Actual modal/RNA method tests cover 500 drag events coalescing to one latest
  pointer update, the 30 Hz timer cap, zero idle hover work, queued final values,
  cached invalid widths, cancellation over the sidebar and timer cleanup.
- Dense ownership indexing agrees with full even-odd tests over 2,340 positions
  on transformed geometry containing holes and separate islands.
- All 16 regression suites passed. A fresh plot of the saved mesh and evaluated
  Blender outline fill was visually checked at identical scale: the 0.14 m result
  is a continuous hollow frame with the original boundary retained as its inner edge.

These are background Blender 5.2 CPU timings and automated interaction tests,
not measurements of live viewport FPS. The user scene was read without saving
or reverting it. Confirmation still validates final geometry before committing.

## Version 1.6.1

- Reproduced a failure after Enter using the workshop's native Bezier guides:
  one viewing direction produced filled area 1.98147 against preview area 11.35621.
- The correction removes precision-scale detours between substantial curve spans
  and uses double-precision subtraction when projecting translated coordinates.
  Original guides remain unchanged; bounded junction adjustments are recorded.
- Both viewing directions now produce the full 32-anchor union. Native filled
  area differs from the preview by 0.01644%, consistent with tessellation.
- Independent checks cover twelve separate major cells, then reuse of the
  generated union and separate outputs as Shape Builder inputs. Coverage sampling
  found no missing lobe, and source controls/transforms remained unchanged.
- A native-fill validation guard runs before guide cutting or selection changes.
  An injected second-result fill failure rolls back all outputs and preserves the
  original selection. The user scene was read in background Blender, never saved.
- Actual `addon_utils.enable()` testing now covers Blender's restricted startup
  context. Window/status access waits until ordinary context is available, fixing
  the `_RestrictData` error that plain `register()` tests did not expose.
- The helper recovery test reproduces failed Preferences enable with stale child
  modules, installs corrected source in the isolated fixture, and recovers the
  extension in that same process while preserving unsaved geometry.

## Version 1.6.0

Validated with Blender 5.2 on Windows in isolated background processes.

- Outline geometry covers even inward/outward widths, holes, disjoint shapes,
  concave corners, arbitrary rotation, nonuniform source transforms and clear
  rejection of crossing or collapsed boundaries.
- A pointed Gothic arch, trefoil and 12-circle cusped quatrefoil produce borders
  at width 0.05. Generated geometry was rendered as a diagnostic sheet and inspected.
  Results are POLY curves; original Bezier sources remain unchanged.
- Real operator commits retain materials and all source collections. Multiple
  selected objects stay independent. Stale-source and batch-failure paths roll
  back without partial results, and commits never write Shape Library presets.
- Snapping tests cover native Bezier, Poly and mesh targets, wrong-side rejection,
  overlapping source ownership, transformed planes, hidden/locked geometry and
  target changes. Cached query timing is a CPU benchmark, not viewport FPS.
- Modal method tests cover numeric/drag width, optional geometry snapping, final
  release position, and the S toggle. These do not replace testing the actual
  mouse in an interactive Blender viewport.
- Outline draw callbacks passed mocked GPU/BLF checks for transformed boundaries,
  cache reuse/invalidation, error feedback and GPU state restoration after failure.
- The one-time reload helper, stable-file checks, busy-mode guards, compatible
  setting preservation, package replacement and failed-registration rollback
  passed. The watcher remains usable after scene loading and Undo.
- Tests also cover extension registration/unregistration, and the existing
  Shape Builder ownership, manual-only library and editable-curve regressions.

The installed user scene was not saved or reverted by this verification. A running
pre-1.6.0 session needs the Scripting-tab helper or one restart to activate the
watcher. New offset splines approximate curves with a recorded sampling bound;
very sharp or narrow features can require a smaller thickness.

## Version 1.5.1

Validated with Blender 5.2 on Windows in separate background processes.

- Separate-click ownership, touched-only drag merging, whole-fill erase, stroke
  undo, and hover behavior passed through the actual modal and mouse methods.
- Independent outputs and shared boundaries survive confirmation and save/reopen.
- Curve and mesh commits make zero Shape Library writes. The explicit **+** action
  saves correctly, and existing presets and files remain unchanged by a commit.
- Output failures roll back generated data; optional guide cutting runs once on
  the original selection. Source curves remain unchanged.
- Curve tests cover original cubic spans, holes, disconnected shapes, tangencies,
  curve Edit Mode, and safe rejection of ambiguous partial overlaps.
- Immediate fill feedback, outline/projection invalidation, and GPU batch reuse
  passed with mocked drawing APIs. These are not live viewport/FPS measurements.
- Extension registration, unregister/re-register, and panel property checks passed.

The release builder validates the ZIP and checks its size/hash in the generated
feed. Portable synthetic regressions and run instructions are in `tests/`.
Blender 4.2 is the declared minimum; this update was tested on 5.2 only.

## Version 1.0.3

- Persistent Add/Remove modes and temporary Alt override passed.
- Sidebar mouse events pass through while the preview remains live.
- Entering the sidebar ends a stroke; returning does not paint unintended regions.
- Add/Alt/remove, stroke undo, clean ring fill, icons, and registration cleanup passed.
- Dark inset and centered mode buttons verified in the live Blender panel.
- Global Blender theme and source geometry are unchanged.

## Version 1.0.2

- Alt-click and Alt-drag remove only selected preview regions.
- Releasing/pressing Alt during a drag switches modes without retracing a previous segment.
- Ordinary clicks keep already-selected regions; removing empty regions adds nothing.
- Ctrl+Z restores a whole stroke, including strokes with modifier changes.
- Clean two-face ring generation and icon register/unregister/re-register tests passed.
- Six custom pink/white icons render in the live Blender panel.
- Scene geometry and any running Shape Builder preview are preserved during the UI update.

## Version 1.0.1

Version 1.0.1, tested with Blender 5.2 on Windows.

- Blender extension build and validation passed.
- Feed ZIP size and SHA-256 match the packaged release.
- Rebuilding the same source preserves the published ZIP and checksum.
- Installed a simulated 1.0.0 extension through a local repository URL.
- Replaced that repository feed with 1.0.1; Blender's update command upgraded it.
- Restarted Blender: extension enabled, harhtools panel loaded, both shortcuts present.
- Shape Builder created a two-face planar ring with its hole preserved.
- Origin centering moved a test object, then detected ALREADY CENTERED on repetition.
- After clearing the runtime namespace (as happens when loading a blend), disabling
  removed the panel, operator, shortcuts, and property; re-enabling succeeded.

Tests used a separate Blender profile and did not change the user's open scene.
The manifest declares Blender 4.2+; only 5.2 has been tested.

## Historical public release verification (1.0.1)

Published at https://harhtica.github.io/harhtools/index.json.

- The HTTPS feed and ZIP downloaded successfully; ZIP size and SHA-256 matched
  the tested local archive byte for byte.
- A separate Blender profile installed and enabled harhtools from that public URL.
- After restart, the panel, shortcuts, clean ring fill, and origin centering passed.
- All 14 uploaded source/release files matched local Git blob hashes. The empty
  `.nojekyll` marker has one harmless newline added by GitHub's editor.
