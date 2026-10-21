#!/usr/bin/env python3
"""
check_mod_sources.py - is this mod ACTUALLY shipping a change, or a copy of the original?

A mod.json lists resources and where their bytes come from.  Twice now a bundle has been
built, validated, deployed, loaded in game and shown to change nothing, because the file
listed as the edited one was byte-identical to the pristine export.  Nothing in the
pipeline noticed: the container parsed, the package came online, the room rendered - just
the same as before.

So compare every resource's source against the game's own copy of the same resource,
before building.  A resource that is identical is one that will have no effect, which is
either a mistake or a deliberate no-op.

    check_mod_sources.py room_edit_mod/mod.json
    check_mod_sources.py --export-root /path/to/Gauntlet-Export room_edit_mod/mod.json

Exit status is 1 when the mod overrides shipped resources and NONE of them differ from the
original - i.e. it cannot possibly change anything.  That is the case worth failing a build
on.  A mod built only from new names has no original to compare against, so it is reported
as nothing-to-compare rather than as a failure.

The pristine tree is the `named/` export - one file per resource, named after the resource
path, which is what `level_to_glb.py` writes and `glb_to_level.py` patches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

TOOL_DIR = Path(__file__).resolve().parent
REPO = TOOL_DIR.parent

# The pristine export tree is not written down either.  By convention it is a SIBLING
# checkout of this repo - that is where the level exporter writes its named/ tree, and what
# glb_to_level.py patches against - so it is derived from this file's own location.
# GAUNTLET_EXPORT points at one somewhere else; --export-root overrides either.
EXPORT_CANDIDATES = [
    REPO / 'Gauntlet-Export',
    REPO.parent / 'Gauntlet-Export',
]


def _export_root() -> Path:
    override = os.environ.get('GAUNTLET_EXPORT')
    for c in ([Path(override).expanduser()] if override else []) + EXPORT_CANDIDATES:
        if c.is_dir():
            return c
    return EXPORT_CANDIDATES[1]      # the sibling convention, even before it exists


DEFAULT_EXPORT = _export_root()

# resource type -> file extension in the named/ export tree
EXTENSIONS: Dict[str, str] = {
    'level': '.level',
    'unit': '.unit',
    'material': '.material',
    'texture': '.dds',
    'lua': '.lua',
}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def source_path(spec: dict, moddir: Path) -> Path | None:
    src = spec.get('source')
    if not src:
        return None
    p = Path(src)
    return p if p.is_absolute() else (moddir / p)


def pristine_path(spec: dict, export_root: Path) -> Path | None:
    res = spec.get('path')
    if not res:
        return None
    ext = EXTENSIONS.get(spec.get('type', ''))
    if not ext:
        return None
    return export_root / 'named' / (res + ext)


def check(modjson: Path, export_root: Path) -> Tuple[List[dict], int, int]:
    spec = json.loads(modjson.read_text())
    moddir = modjson.parent
    rows: List[dict] = []

    for r in spec.get('resources', []):
        src = source_path(r, moddir)
        mine = pristine_path(r, export_root)
        row = {'path': r.get('path', '?'), 'type': r.get('type', '?'),
               'comparable': False}

        if src is None or not src.exists():
            row['verdict'] = 'SOURCE MISSING'
        elif mine is None or not mine.exists():
            row['verdict'] = 'new name - no original to compare'
            row['source'] = str(src)
        else:
            row['comparable'] = True
            row['source'] = str(src)
            row['verdict'] = ('IDENTICAL to the original' if md5(src) == md5(mine)
                              else 'differs')
        rows.append(row)

    differing = sum(1 for r in rows if r['verdict'] == 'differs')
    comparable = sum(1 for r in rows if r['comparable'])
    return rows, differing, comparable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mod_json')
    ap.add_argument('--export-root', default=str(DEFAULT_EXPORT))
    a = ap.parse_args()

    modjson = Path(a.mod_json)
    rows, differing, comparable = check(modjson, Path(a.export_root))
    m = json.loads(modjson.read_text())

    print('== %s   mod=%s' % (modjson, m.get('name', '?')))
    for r in rows:
        print('   %-14s %-62s %s' % (r['type'], r['path'][:62], r['verdict']))

    print()
    print('   %d of %d resource(s) differ from the shipped original'
          % (differing, len(rows)))

    if comparable == 0:
        print('   nothing here overrides a shipped resource - new names only, so there is')
        print('   no original to compare against.  Nothing to say; not a failure.')
        return 0

    if differing == 0:
        print('   NONE of the %d overriding resource(s) differ from the original.' % comparable)
        print('   This mod cannot change anything: it will build, load, come online, and')
        print('   render exactly as the game does.  Check the edit actually got applied.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
