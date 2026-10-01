# Release verification

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
