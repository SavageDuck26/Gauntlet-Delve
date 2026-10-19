#!/usr/bin/env python3
"""What does a Blender export ACTUALLY resolve to, before anything is built?

Read the GLB the way the build will (base names, the ignore filter, the mod config's own units and
the game's unit corpus) and print one row per base name - because three of the pipeline's rules are
per-base-name, and each of them fails in a way that only shows up in game:

  * ONE BASE NAME IS ONE UNIT, built from the FIRST node's mesh of that name.  If a name covers
    several shapes, every placement renders the first one - the spiral road (9H.40) and the new
    `Road Top` sections both hit this.  Distinct shapes need distinct names, and a purely numeric
    tail (`.001`) is stripped as Blender's duplicate suffix, so letters or words are what works.
  * A NAME NOTHING RESOLVES IS DROPPED.  A node that is neither one of the author's own units nor a
    game unit is reported as unresolved by the build - and simply not placed.
  * A MESH OVER 65,535 VERTS IS REFUSED.  Sixteen-bit indices are what every shipped mesh block
    uses (9H.39), so the build stops rather than writing 32-bit ones.

Everything it prints comes from the numbers the build itself uses: the vertex count the exporter
wrote, the mesh's own bounding-box size (the check that tells "the same tile triangulated
differently" from "a genuinely different piece"), distinct node positions, and how many nodes carry
their own rotation.

usage: report_scene_bases.py <export.glb> [--mod-json <the mod's json>] [--ignore SUBSTR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from check_deployed_placement import read_glb, base_name                # noqa: E402
import level_from_glb as L                                              # noqa: E402

MAX_VERTS_PER_MESH = 65535
BIG_MESH = 15972                 # the largest mesh the game itself ships (9H.39)


def mesh_stats(js: dict, node: dict):
    """(vertex count, local bounding-box size) the way the unit builder sees them."""
    verts = 0
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    for prim in js['meshes'][node['mesh']]['primitives']:
        acc = js['accessors'][prim['attributes']['POSITION']]
        verts += acc['count']
        for k in range(3):
            if 'min' in acc and 'max' in acc:
                lo[k] = min(lo[k], acc['min'][k])
                hi[k] = max(hi[k], acc['max'][k])
    size = tuple(round(hi[k] - lo[k], 3) for k in range(3)) if lo[0] < 1e30 else (0.0, 0.0, 0.0)
    return verts, size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('glb', type=Path)
    ap.add_argument('--mod-json', type=Path, default=None,
                    help='the mod config: its own_units decide which names resolve to the '
                         'author\'s units instead of the game\'s')
    ap.add_argument('--ignore', action='append', default=None, metavar='SUBSTR',
                    help='same filter as the build: a node whose name contains SUBSTR is not part '
                         'of it.  Repeatable; the default list is %r' % L.IGNORE_NAME_SUBSTRINGS)
    a = ap.parse_args()

    for spec in (a.ignore or []):
        if spec.strip() and spec.strip().lower() not in [s.lower() for s in L.IGNORE_NAME_SUBSTRINGS]:
            L.IGNORE_NAME_SUBSTRINGS.append(spec.strip())
    own = {}
    if a.mod_json:
        spec = json.loads(a.mod_json.read_text())
        own = {u['base']: u['unit'] for u in spec['build']['own_units']}
        L.OWN_UNITS = dict(own)
    by_base = L.load_names()

    js, bin0 = read_glb(a.glb)
    groups = {}
    no_mesh = []
    for node in js.get('nodes', []):
        if 'mesh' not in node:
            no_mesh.append(node.get('name', ''))
            continue
        name = node.get('name', '')
        if L.ignored_node(name):
            groups.setdefault((True, base_name(name)), []).append(None)
            continue
        verts, size = mesh_stats(js, node)
        groups.setdefault((False, base_name(name)), []).append(
            (verts, size, tuple(round(v, 3) for v in node.get('translation', [0, 0, 0])),
             'rotation' in node))

    print('%s: %d node(s), %d with a mesh%s'
          % (a.glb.name, len(js.get('nodes', [])), len(js.get('nodes', [])) - len(no_mesh),
             ' (%d without: %s)' % (len(no_mesh), ', '.join(n for n in no_mesh[:6] if n) or 'unnamed')
             if no_mesh else ''))
    print()
    print('%-8s %-28s %5s %-20s %-22s %5s %s'
          % ('status', 'base name', 'nodes', 'exported verts', 'distinct shapes', 'rot',
             'the build'))
    dropped = refused = clashes = placed = 0
    for (is_ignored, base), items in sorted(groups.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        if is_ignored:
            print('%-8s %-28s %5d %-20s %-22s %5s %s'
                  % ('IGNORED', base, len(items), '-', '-', '-', 'not placed, no unit built'))
            continue
        placed += len(items)
        verts = sorted({v[0] for v in items})
        sizes = {v[1] for v in items}
        rot = sum(1 for v in items if v[3])
        if base in own:
            what, status = 'own unit -> %s' % L.OWN_UNITS[base], 'own'
        elif L.resolve(base, by_base):
            what, status = 'a game unit', 'game'
        else:
            what, status = '*** UNRESOLVED: dropped from the level ***', 'NEW'
            dropped += 1
        if max(verts) > MAX_VERTS_PER_MESH:
            what += '  *** OVER 65535: the build REFUSES this kind'
            refused += 1
        elif max(verts) > BIG_MESH:
            what += '  (bigger than any shipped mesh, under the limit)'
        if len(sizes) > 1:
            clashes += 1
        print('%-8s %-28s %5d %-20s %-22s %5d %s'
              % (status, base, len(items),
                 '%d value(s): %s' % (len(verts), ','.join(str(v) for v in verts[:4])),
                 '%d size(s)%s' % (len(sizes), '  <-- different shapes!' if len(sizes) > 1 else ''),
                 rot, what))
    print()
    print('%d node(s) would be placed, in %d kind(s)' % (placed, len(groups)))
    if clashes:
        print('WARNING: %d base name(s) cover more than one shape.  One name is ONE unit, built from'
              % clashes)
        print('         the first node of that name - every other placement of it will render that')
        print('         same mesh.  Give each distinct shape its own name (words or letters: a')
        print('         purely numeric tail like ".001" is stripped as Blender\'s duplicate suffix).')
    if dropped:
        print('WARNING: %d base name(s) resolve to nothing, so those nodes are NOT placed.  Add them'
              % dropped)
        print('         to the config\'s own_units (and its resources), or name them to match a game')
        print('         unit.')
    if refused:
        print('NOTE: %d kind(s) are over the 65,535-vert limit and the build will refuse them; split'
              % refused)
        print('      the object in Blender - each piece becomes its own unit and placement.')
    if not (clashes or dropped or refused):
        print('OK - every node resolves, every name is one shape, and nothing is over the limit.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

