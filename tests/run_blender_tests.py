"""Run synthetic regression suites in separate factory-startup Blender processes."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

TESTS = (
    'test_fill_groups.py',
    'test_fill_groups_blender.py',
    'test_manual_library_only.py',
    'test_modal_gesture_regression.py',
    'test_pen_curves.py',
    'test_pen_contacts.py',
    'test_mocked_gpu_caches.py',
    'test_outline_geometry.py',
    'test_outline_snap.py',
    'test_outline_tool.py',
    'test_outline_gpu.py',
    'test_live_reload.py',
    'test_reload_bootstrap.py',
    'test_live_reload_integration.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', default='blender', help='Blender executable path or command name')
    parser.add_argument('tests', nargs='*', choices=TESTS, help='Optional subset; default runs all suites')
    args = parser.parse_args()
    executable = shutil.which(args.blender)
    if executable is None:
        parser.error('Blender was not found; pass --blender /path/to/blender')
    directory = Path(__file__).resolve().parent
    output = directory / '_artifacts'
    output.mkdir(exist_ok=True)
    failed = []
    for name in args.tests or TESTS:
        command = [executable, '--background', '--factory-startup',
                   '--python-exit-code', '1', '--python', str(directory / name)]
        result = subprocess.run(command, cwd=directory.parent, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
        log = output / (Path(name).stem + '.log')
        log.write_text(result.stdout, encoding='utf-8')
        print(('PASS' if result.returncode == 0 else 'FAIL') + ' ' + name, flush=True)
        if result.returncode:
            failed.append(name)
            print(result.stdout[-6000:], flush=True)
    print(f'{len(args.tests or TESTS) - len(failed)}/{len(args.tests or TESTS)} suites passed. Logs: {output}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
