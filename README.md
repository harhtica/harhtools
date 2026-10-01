# harhtools

A Blender extension with an editable-curve Shape Builder, reusable shape library,
outlines, arrays, and object alignment tools.
Requires Blender 4.2 or newer; tested on Blender 5.2.

## Version 1.6.3

- Fixes Make Outline incorrectly reporting depth on a flat, translated shape.
  Plane calculations now use double precision; the original shape and the
  threshold for rejecting genuinely nonplanar boundaries remain unchanged.

[Download 1.6.3](https://harhtica.github.io/harhtools/harhtools-1.6.3.zip), or use
the Blender repository below. Reverting a blend file does not reload Python code.
See [tool controls](extension/README.md), [release verification](VERIFICATION.md),
and [regression tests](tests/README.md).

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
- Original shapes remain recoverable. Offset results are filled POLY curves with
  adaptive sampling; invalid or collapsing widths are rejected before committing.
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
2. Increase `version` in `extension/blender_manifest.toml`, for example to `1.6.4`.
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
