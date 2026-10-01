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
| `test_pen_contacts.py` | Interior tangent contacts, neighboring crossings, and safe rejection of partial duplicate overlaps. |
| `test_mocked_gpu_caches.py` | Overlay coverage and cache reuse/invalidation using fake GPU/font APIs and real projection math. |

These tests validate behavior and cache allocation. They do not measure actual
GPU performance or replace a visual check in an interactive Blender viewport.
The suites were verified with Blender 5.2; run them against other supported
Blender versions before claiming equivalent coverage there.
