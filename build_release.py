"""Build and validate harhtools and its static Blender repository.

Run with Python 3.11+, or Blender's bundled Python. Only docs/ is published.
The extension version is read from extension/blender_manifest.toml.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', default=shutil.which('blender'),
                        help='Path to the Blender executable (4.2 or newer)')
    args = parser.parse_args()
    if not args.blender:
        parser.error('Pass --blender with the path to your Blender executable')
    root = Path(__file__).resolve().parent
    source = root / 'extension'
    docs = root / 'docs'
    docs.mkdir(exist_ok=True)
    manifest = tomllib.loads((source / 'blender_manifest.toml').read_text('utf-8'))
    version = manifest['version']
    filename = f"{manifest['id']}-{version}.zip"
    build_root = root / '.build'
    build_root.mkdir(exist_ok=True)
    # Stage a complete feed before replacing any published files. Old archives
    # stay available for clients that still have the previous index cached.
    with tempfile.TemporaryDirectory(dir=build_root) as temporary:
        stage = Path(temporary)
        env = os.environ.copy()
        for key, folder in [('BLENDER_USER_CONFIG', 'config'),
                            ('BLENDER_USER_SCRIPTS', 'scripts'),
                            ('BLENDER_USER_EXTENSIONS', 'extensions')]:
            directory = stage / folder
            directory.mkdir()
            env[key] = str(directory)
        def blender(*arguments):
            subprocess.run([args.blender, '--background', '--factory-startup',
                            '--command', 'extension', *map(str, arguments)],
                           check=True, env=env)
        blender('build', '--source-dir', source, '--output-dir', stage)
        archive = stage / filename
        blender('validate', archive)
        existing = docs / filename
        if existing.exists():
            def contents(path):
                with zipfile.ZipFile(path) as package:
                    return {name: package.read(name) for name in package.namelist()}
            if contents(existing) != contents(archive):
                raise SystemExit(f'{filename} already exists with different contents. Increase the manifest version before publishing changes.')
            # ZIP timestamps can differ between builds. Preserve the already
            # published bytes and checksum when the actual files are identical.
            shutil.copyfile(existing, archive)
        blender('server-generate', '--repo-dir', stage, '--html')
        feed = json.loads((stage / 'index.json').read_text('utf-8'))
        assert len(feed['data']) == 1
        entry = feed['data'][0]
        assert entry['id'] == 'harhtools' and entry['version'] == version
        assert entry['archive_size'] == archive.stat().st_size
        assert entry['archive_hash'] == 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()
        if not existing.exists():
            shutil.copyfile(archive, existing)
        shutil.copyfile(stage / 'index.html', docs / 'index.html')
        shutil.copyfile(stage / 'index.json', docs / 'index.json')
        (docs / '.nojekyll').touch()
    print(f'Ready: {filename}; commit and push extension/ and docs/ to publish.')


if __name__ == '__main__':
    main()
