# Release verification

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

## Public release verification

Published at https://harhtica.github.io/harhtools/index.json.

- The HTTPS feed and ZIP downloaded successfully; ZIP size and SHA-256 matched
  the tested local archive byte for byte.
- A separate Blender profile installed and enabled harhtools from that public URL.
- After restart, the panel, shortcuts, clean ring fill, and origin centering passed.
- All 14 uploaded source/release files matched local Git blob hashes. The empty
  `.nojekyll` marker has one harmless newline added by GitHub's editor.
