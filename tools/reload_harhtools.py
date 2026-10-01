"""Run once in Blender's Scripting workspace after installing Harhtools updates.

Open this file in the Text Editor and press Run Script. It attaches the new code
watcher even when the running older release did not include one. Finish modal
tools and return to Object Mode; the update then loads after a short idle wait.
The current blend file is neither saved nor reopened. No other add-on is reloaded.
"""
import importlib
from pathlib import Path
import sys
import tomllib

import bpy


def _enabled_harhtools():
    matches = []
    for addon in bpy.context.preferences.addons:
        module = sys.modules.get(addon.module)
        filename = getattr(module, '__file__', None)
        if (not filename or not getattr(module, '__addon_enabled__', True)
                or not callable(getattr(module, 'register', None))):
            continue
        manifest = Path(filename).resolve().parent / 'blender_manifest.toml'
        try:
            data = tomllib.loads(manifest.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        if data.get('id') == 'harhtools':
            matches.append(module)
    if len(matches) != 1:
        raise RuntimeError('Enable exactly one installed Harhtools extension first; found ' + str(len(matches)))
    return matches[0]


def main():
    package = _enabled_harhtools()
    watcher_name = package.__name__ + '.live_reload'
    watcher = sys.modules.get(watcher_name)
    running = watcher is not None and bpy.app.timers.is_registered(watcher._poll)
    if watcher is None:
        try:
            watcher = importlib.import_module(watcher_name)
        except ImportError as exc:
            raise RuntimeError('Install a Harhtools release with live_reload.py before running this script') from exc
    if not running:
        watcher.register()
        version = getattr(package, 'bl_info', {}).get('version')
        watcher._loaded_version = '.'.join(map(str, version)) if version else 'previous session'
    watcher.request_reload()
    print('Harhtools reload queued. Finish active tools and use Object Mode; your current file stays open.')
    return watcher


if __name__ == '__main__':
    main()
