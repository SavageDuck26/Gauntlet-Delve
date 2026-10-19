#!/usr/bin/env python3
"""Build the whole custom level mod from the author's Blender scene, in one command.

    python3 scripts/build_level_mod.py scripts/arena_mod/custom_run_mod.json --export

STEPS
  1. EXPORT (with --export): blender --background <build.blend> --python blender_export_glb.py
     -- <build.glb>.  The export settings and the reason for each live in blender_export_glb.py.
  2. UNITS: one build_own_units.py run per own unit, each with the template that decides its
     physics and material binding (FINDINGS 9H.31 - the template's mesh count has to match the
     body's, and the builder keeps that true).
  3. LEVEL: level_from_glb.py --scratch, binding each own unit's node base name to its unit
     resource path, so every placement resolves to OUR hash.
  4. BUNDLE: mod_bundle_builder.py --flat into the game's mods/bundles/<name>.
  5. VERIFY: check_deployed_bundle.py on the deployed bytes - resource count vs manifest AND
     bundle.ini, payloads tight, every unit's mesh_count against the native template it wears,
     every placement hash present as a unit in this package.

STALENESS GUARD.  If the .blend is newer than the .glb and --export was not given, this refuses
(unless --force).  That is not paranoia: it is how a build ends up showing a scene older than the
one the author is looking at (2026-10-18: blend 11:30, glb 09:50).

CONFIG - a "build" block in the mod json (paths may be absolute or relative to the mod dir):
  "build": {
    "blend":  "Base.blend",
    "glb":    "Levels/test_arena_03.glb",
    "skeleton": "assets/exports-samples/samples/level_24abcdf4b1fb4d4a.level",
    "own_units": [
      {"base": "Floor", "unit": "units/custom/duckomp_room/floor",
       "template": ".unit orig/0x6369abda98cf91a5.unit"},
      {"base": "Stair", "unit": "units/custom/duckomp_room/stair",
       "template": ".unit orig/0xc512fd67e8213eec.unit"},
      {"base": "Medieval Crane", "unit": "units/custom/duckomp_room/crane",
       "template": ".unit orig/0x432ffd51ba8d0fc3.unit"}
    ],
    "deploy_dir": "<game>/mods/bundles",
    "mesh_frame": "auto"
  }
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_GAME = Path.home() / '.local/share/Steam/steamapps/common/Gauntlet'


def run(cmd: list, label: str) -> bool:
    print('\n=== %s' % label)
    print('    %s' % ' '.join(str(c) for c in cmd))
    proc = subprocess.run([str(c) for c in cmd], cwd=ROOT, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print((proc.stdout or '').rstrip())
    if proc.returncode != 0:
        print('\n!!! %s FAILED (exit %d) - stopping here' % (label, proc.returncode))
        return False
    return True


def resolve(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def stamp(p: Path) -> str:
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mod_json', type=Path)
    ap.add_argument('--export', action='store_true',
                    help='run Blender headless first, exporting build.glb from build.blend')
    ap.add_argument('--glb', type=Path, default=None,
                    help='override the GLB this build reads (a fresh export, say)')
    ap.add_argument('--blender', default=None,
                    help='Blender binary for --export.  Default: the build.blender in the mod '
                         'json, so the .blend is opened by the version that wrote it')
    ap.add_argument('--no-deploy', action='store_true',
                    help='build and verify, but do not put the bundle in the game folder')
    ap.add_argument('--force', action='store_true',
                    help='build anyway when the .blend is newer than the GLB')
    args = ap.parse_args()

    spec = json.loads(args.mod_json.read_text())
    build = spec.get('build')
    if not build:
        print('%s has no "build" block - see this script\'s docstring for the shape' % args.mod_json)
        return 1
    mod_dir = args.mod_json.resolve().parent
    glb = Path(args.glb).resolve() if args.glb else resolve(mod_dir, build['glb'])
    blend = resolve(mod_dir, build['blend']) if build.get('blend') else None
    skeleton = ROOT / build.get('skeleton',
                                'assets/exports-samples/samples/level_24abcdf4b1fb4d4a.level')
    own = build['own_units']
    blender = args.blender or build.get('blender') or 'blender'
    deploy_dir = Path(build.get('deploy_dir') or (DEFAULT_GAME / 'mods/bundles'))
    frame = build.get('mesh_frame', 'auto')
    name = spec['name']

    level_res = next(r for r in spec['resources'] if r['type'] == 'level')
    level_out = mod_dir / level_res['source']
    unit_dir = mod_dir / next(r['source'] for r in spec['resources']
                              if r['type'] == 'unit').split('/')[0]

    print('mod     : %s  (%s)' % (name, args.mod_json))
    print('blend   : %s' % blend)
    print('glb     : %s' % glb)
    print('level   : %s  -> engine path %s' % (level_out, level_res['path']))
    print('units   : %d own kind(s) into %s' % (len(own), unit_dir))
    print('deploy  : %s' % ('(skipped)' if args.no_deploy else deploy_dir / name))

    # -- staleness guard -------------------------------------------------------
    if (blend and blend.exists() and glb.exists() and not args.export and not args.glb
            and not args.force and blend.stat().st_mtime > glb.stat().st_mtime + 1):
        print('\nREFUSING: the .blend is NEWER than the GLB this build would read.')
        print('          blend  %s' % stamp(blend))
        print('          glb    %s' % stamp(glb))
        print('          What you are looking at in Blender is not what would be built.')
        print('          Re-run with --export, or pass --glb <fresh export>, or --force.')
        return 2

    # -- 1. export ------------------------------------------------------------
    if args.export:
        if not blend or not blend.exists():
            print('--export needs build.blend to exist (%s)' % blend)
            return 1
        if not run([blender, '--background', blend, '--python',
                    HERE / 'blender_export_glb.py', '--', glb], 'export %s' % glb.name):
            return 1

    # -- 2. units -------------------------------------------------------------
    # PHYSICS BY ROLE: the config may name a template per role ("walkable", "collision", "none")
    # and per kind ("physics": {"Floor": "walkable"}); the object's NAME can override both with
    # `_walkable` / `_collision`.  A role selects which native unit the mesh is spliced into,
    # because a unit's collider IS the template's trailer (FINDINGS 9H.19/9H.20/9H.31).
    templates = spec['build'].get('templates') or {}
    physics = spec['build'].get('physics') or {}
    for u in own:
        tpl = Path(u['template'])
        tpl = tpl if tpl.is_absolute() else (HERE / tpl)
        cmd = [sys.executable, HERE / 'build_own_units.py', glb, tpl,
               '%s=%s' % (u['base'], u['unit']), '--out', unit_dir,
               '--mesh-frame=%s' % frame]
        for role, path in templates.items():
            # `strip:PATH` is a template spec, not a path: resolve only the inner path
            if path.startswith('strip:'):
                inner = Path(path.split(':', 1)[1])
                spec = 'strip:%s' % (inner if inner.is_absolute() else (HERE / inner))
            else:
                rp = Path(path)
                spec = str(rp if rp.is_absolute() else (HERE / rp))
            cmd.append('--physics-template=%s=%s' % (role, spec))
        for base, role in physics.items():
            cmd.append('--physics=%s=%s' % (base, role))
        if not run(cmd, 'unit %s  (template %s)' % (u['base'], tpl.name)):
            return 1

    # -- 3. level -------------------------------------------------------------
    cmd = [sys.executable, HERE / 'level_from_glb.py', glb, skeleton, level_out, '--scratch']
    for u in own:
        cmd += ['--own-unit', '%s=%s' % (u['base'], u['unit'])]
    if not run(cmd, 'level %s' % level_out.name):
        return 1

    # -- 4. bundle ------------------------------------------------------------
    out_dir = (mod_dir / 'build' / 'bundles' / name) if args.no_deploy else (deploy_dir / name)
    if not run([sys.executable, HERE / 'mod_bundle_builder.py', args.mod_json, '--flat',
                '-o', out_dir], 'bundle %s' % name):
        return 1

    # -- 5. verify ------------------------------------------------------------
    if not run([sys.executable, HERE / 'check_deployed_bundle.py', out_dir, level_res['path']],
               'verify the deployed bundle'):
        return 1

    print('\nDONE.  %s deployed and verified at %s' % (name, out_dir))
    print('       level  %s (%d bytes)' % (level_out.name, level_out.stat().st_size))
    for f in sorted(unit_dir.glob('*.unit')):
        print('       unit   %s (%d bytes)' % (f.name, f.stat().st_size))
    print('       If something looks different from Blender, check the "glb" line above - the'
          ' export step prints every node it wrote.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
