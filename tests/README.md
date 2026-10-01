# Regression tests

Run from the repository root with Python 3 and Blender installed:

```sh
python tests/run_blender_tests.py --blender /path/to/blender
```

If `blender` is on `PATH`, omit `--blender`. On Windows, pass the quoted path to
`blender.exe`. To run one suite directly:

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/test_manual_library_only.py
```

The runner starts a separate Blender process for each suite. Fixtures are
synthetic; no user scene or installed add-on is required. Tests do not install the
extension or save user preferences. Results, logs, and temporary library presets
stay in ignored `tests/_artifacts/`. `--python-exit-code 1` is required when running
a Blender script directly so a failed assertion produces a failing exit code.

| Suite | Coverage |
| --- | --- |
| `test_fill_groups.py` | Separate fill ownership, drag merges, erase, and immutable undo snapshots. Also runs with ordinary Python. |
| `test_fill_groups_blender.py` | Real curve regions, independent output objects, retained shared boundaries, and intentional seam removal. |
| `test_manual_library_only.py` | No automatic preset writes; explicit **+** saves curves; legacy insertion/refresh behavior; batch rollback and guide-cut ordering. |
| `test_modal_gesture_regression.py` | Actual modal/mouse methods with projection and UI hooks replaced: clicks, hover, drag, erase, undo, and failed commits. |
| `test_pen_curves.py` | Editable cubic output, source fidelity, holes, open paths, transformed input, and selected Curve Edit Mode segments. |
| `test_pen_contacts.py` | Interior tangent contacts, neighboring crossings, and partial duplicate curves without false regions. |
| `test_pen_overlaps.py` | Six overlapping semicircles, unique shared baseline, separate baseline trimming, native union fill, reversed/partial cubics, third-guide crossings, nonuniform straight handles and translated tiny guides. |
| `test_builder_curve_output.py` | Native filled area of the Gothic circle construction, both viewing directions, translated coordinates, tiny junction repair, and retained small geometry. |
| `test_builder_planarity.py` | Tiny translated circles, distant rotated coplanar inputs, valid regions, and unchanged rejection of real depth. |
| `test_circle_arc.py` | Exact original sampling, arc cuts, triangle output/counts, transforms, linked data, native Bezier restore, reload persistence and no datablock leaks. |
| `test_edit_arc.py` | Selected bottom rounding, fixed upper geometry/joins, local wire resampling, face topology preservation, exact cancellation/selection, external-edit protection and modal cleanup. |
| `test_edit_arc_plane.py` | Connected shape planes, straight/subdivided selections, tiny/rotated/transformed inputs, fixed joins, reverse bend, off-plane repair, isolated-line overrides and live recapture. |
| `test_edit_arc_live.py` | Normal vertex-edit event pass-through, transform guard, live selection recapture, fixed unselected joins, 64-point-circle density matching, manual counts, world scale, cancellation and bounded 2048-vertex resampling. |
| `test_profile_panel.py` | All 19 automatic native point editors, no thumbnail requests, read-only Object/Edit Mode drawing, canonical architectural samples, preset switching and edit preservation, coalesced drafts, sample updates, failure recovery, visible Make Outline button and cleanup. |
| `test_profile_editor.py` | Native point edits fork defaults, independent user copies, matching thumbnail/modifier output, draft cleanup and custom-profile blend persistence. |
| `test_display_units.py` | Roblox metric conversion, scene scale, editable distance round trips, negative gaps, unchanged geometry/transforms and derived-value reload handling. |
| `test_mocked_gpu_caches.py` | Overlay coverage and cache reuse/invalidation using fake GPU/font APIs and real projection math. |
| `test_outline_geometry.py` | Even-width offsets, exact sharp joins, acute unclamped tips, optional round joins, holes, distant sources, dense plane precision, Gothic curves/mesh, bounded simplification, native hollow fill, and collapse rejection. |
| `test_outline_mesh.py` | Connected quad strips, preserved miter seams through constrained triangulation and quad merging, trimmed junction faces, preserved boundaries, holes/islands, normals, UVs, and watertight frame thickening. |
| `test_outline_bevel.py` | Five distinct native profiles, hollow watertight output, unchanged base mesh/UVs, perimeter-only weights, sharp vertical miters, modifier reuse, batch rollback, and registered update operator. |
| `test_outline_preview.py` | Five native shaded preview surfaces and cached profile thumbnails, isolated evaluation, and scratch cleanup after success/failure. |
| `test_architectural_profiles.py` | Fourteen distinct native moulding sections and thumbnails, exact agreement with evaluated modifier sections, watertight hollow frames, unchanged base vertices, custom-path rollback, detail defaults and no scratch datablocks. |
| `test_outline_snap.py` | Native Bezier/Poly/mesh targets, dense source indexing, ownership, exact closest points, perspective projection, coplanarity, visibility, stale targets, lazy initialization, and cache reuse. |
| `test_outline_tool.py` | Actual operator commits, separate outputs, source preservation, rollback, optional snapping, translated plane selection/ownership, mouse controls, and registration cleanup. |
| `test_outline_interaction.py` | Actual modal/RNA methods: idle hover, coalesced drag/slider updates, timer cadence, final release/Enter values, cached errors, Escape over sidebar, timer cleanup, and dense source ownership indexing. |
| `test_outline_gpu.py` | Actual outline draw callbacks with mocked GPU/BLF: transformed boundaries, cache reuse, measurement feedback, callback guards and state restoration after failures. |
| `test_live_reload.py` | Idle guards, debounce, version changes, settings restoration, and failed-reload rollback. |
| `test_reload_bootstrap.py` | One-time Scripting helper activates an older running package or recovers failed enable with orphaned modules without touching geometry. |
| `test_live_reload_integration.py` | Actual Preferences registration through restricted context, package replacement and failure recovery in isolated temporary installations. |

These tests validate behavior and cache allocation. They do not measure actual
GPU performance or replace a visual check in an interactive Blender viewport.
The suites were verified with Blender 5.2; run them against other supported
Blender versions before claiming equivalent coverage there.
