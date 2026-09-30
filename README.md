# harhtools

A Blender extension with a planar Shape Builder and two object-centering tools.
Requires Blender 4.2 or newer; tested on Blender 5.2.

Version 1.0.3 groups the pink/white controls in a dark inset and adds centered
Add/Remove buttons. The chosen mode and active Shape Builder stay highlighted.
Hold Alt for temporary removal, then release it to return to the chosen mode.
Wire guides stay unchanged.

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
2. Increase `version` in `extension/blender_manifest.toml`, for example to `1.0.4`.
3. Run the builder below using Python 3.11+ (Blender's bundled Python works).
4. Test the resulting ZIP in Blender, then commit and push the source and `docs/`.

```powershell
python build_release.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
```

The builder validates the extension and generates the feed using Blender's own
tools. It refuses to replace an existing version with different contents. Old
ZIPs remain available so cached links keep working; the feed lists only the
current release. GitHub Pages deploys the pushed `docs/` folder.

This source and extension are packaged under GPL-3.0-or-later; see LICENSE.

References: [Blender extension repositories](https://docs.blender.org/manual/en/5.0/advanced/extensions/creating_repository/static_repository.html)
and [GitHub Pages setup](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
