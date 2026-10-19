#!/usr/bin/env python3
"""Keep a mod config's `own_units` and `resources` in step with the scene.

Two rules make this necessary, and both fail quietly in the author's direction:

  * A KIND THE SCENE HAS BUT THE CONFIG DOES NOT is UNRESOLVED, so the build reports it and drops
    it - the object is simply not in the level.  Every new object in Blender needs a config entry
    (and a `resources` entry, or the bundle cannot ship its unit).
  * A KIND THE CONFIG HAS BUT THE SCENE NO LONGER DOES leaves a stale entry: its unit is built from
    nothing, the file that ships is the one from an earlier build, and the bundle carries the dead
    weight.

So sync after a renaming pass.  A new kind's unit path is its base name slugged
('Road Top Wrap Around' -> road_top_wrap_around) under the same directory the config's other units
use, and it wears the same native template as they do unless `--template` says otherwise - a role
chooses the physics anyway (see the config's "templates" block).

By default this only PRINTS what it would change.  `--write` applies it.

usage: sync_mod_kinds.py <export.glb> <mod json> [--unit-root DIR] [--template PATH] [--write]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check_deployed_placement import read_glb, base_name                # noqa: E402
import level_from_glb as L                                              # noqa: E402


def slug(base: str) -> str:
    """The unit-path segment for a base name: 'Road Top Wrap Around' -> road_top_wrap_around."""
    return re.sub(r'[^a-z0-9]+', '_', base.lower()).strip('_')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('glb', type=Path)
    ap.add_argument('mod_json', type=Path)
    ap.add_argument('--unit-root', default=None, metavar='DIR',
                    help='where a new kind\'s unit path lives (default: the directory the config\'s '
                         'own units already use)')
    ap.add_argument('--template', default=None, metavar='PATH',
                    help='the native template a new kind wears (default: what the config\'s own '
                         'units wear)')
    ap.add_argument('--write', action='store_true', help='apply the diff instead of printing it')
    a = ap.parse_args()

    spec = json.loads(a.mod_json.read_text())
    own = spec.get('build', {}).get('own_units') or []
    if not own:
        raise SystemExit('%s lists no own units, so there is no unit root or template to copy'
                         % a.mod_json)
    L.OWN_UNITS = {u['base']: u['unit'] for u in own}
    by_base = L.load_names()

    js, _ = read_glb(a.glb)
    scene = {base_name(n.get('name', '')) for n in js.get('nodes', [])
             if 'mesh' in n and not L.ignored_node(n.get('name', ''))}
    scene.discard('')

    root = a.unit_root or str(Path(own[0]['unit']).parent)
    template = a.template or own[0]['template']

    own_bases = {u['base'] for u in own}
    gone = [u for u in own if u['base'] not in scene]
    # A scene name a GAME unit already answers to is not ours to add - it resolves, so the build
    # places the game's unit.  Only names that resolve to NOTHING need a config entry.
    new = sorted(b for b in scene if b not in own_bases and L.resolve(b, by_base) is None)

    print('%s: %d kind(s) in the scene, %d in %s' % (a.glb.name, len(scene), len(own), a.mod_json.name))
    for u in gone:
        print('  drop  %-26s %-44s (no such object in the scene)' % (u['base'], u['unit']))
    for b in new:
        print('  add   %-26s %s/%s' % (b, root, slug(b)))
    if not (gone or new):
        print('  in step: nothing to change')
        return 0
    if not a.write:
        print()
        print('DRY RUN - nothing was changed.  Re-run with --write to apply this.')
        return 0

    keep = [u for u in own if u['base'] in scene]
    for b in new:
        keep.append({'base': b, 'unit': '%s/%s' % (root, slug(b)), 'template': template})
    spec['build']['own_units'] = keep
    paths = {u['unit'] for u in keep}
    spec['resources'] = [r for r in spec['resources']
                         if r['type'] != 'unit' or r['path'] in paths]
    have = {r['path'] for r in spec['resources']}
    for u in keep:
        if u['unit'] not in have:
            spec['resources'].append({'type': 'unit', 'path': u['unit'],
                                      'source': 'units/%s.unit' % u['unit'].replace('/', '_')})
    a.mod_json.write_text(json.dumps(spec, indent=2) + '\n')
    print()
    print('wrote %s: %d own kind(s), %d resource(s)'
          % (a.mod_json, len(keep), len(spec['resources'])))
    print('next: build_level_mod.py %s --export' % a.mod_json)
    return 0


if __name__ == '__main__':
    sys.exit(main())

