#!/usr/bin/env python3
"""
level_set_entities.py - replace a .level's entity table, leaving everything else intact.

A level is [128-byte header][entity table][the rest: shell placement, resource and layer
config, lighting].  The header holds the table's offset and count, and
resource_tools/level_tools.py re-encodes by writing the entities back at that offset and
restoring every other byte - so the table can be replaced wholesale.

That is what keeps the level loadable.  Building one from nothing would mean inventing the
shell placement, the shading environment and the lighting matrices as well; here the donor
level keeps all of it and only its contents change.

The new table must not be LONGER than the original: the encoder restores the preserved gap
section at the original table's end, so extra entities would be overwritten by it.

    level_set_entities.py donor.level out.level --entities spec.json

spec.json: [{"template": "units/custom/test_plane/plane",
             "position": [45, 40, 9], "scale": [1, 1, 1], "rotation": [0, 0, 0, -1]}]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List

PLACEMENT_RECORD_SIZE = 56   # sub-level placement record (FINDINGS 9H.5)

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE / 'resource_tools')):
    if p not in sys.path:
        sys.path.insert(0, p)

from mod_bundle_builder import murmur64                      # noqa: E402
from resource_tools.level_tools import (                      # noqa: E402
    ENTITY_RECORD_SIZE, decode_level, encode_level,
)


def build_entities(spec: List[Dict[str, Any]], donor_entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entity per spec entry, reusing the donor's ids and unused bytes where we can."""
    out: List[Dict[str, Any]] = []
    for i, s in enumerate(spec):
        template = s['template']
        if i < len(donor_entities):
            entity_id = donor_entities[i]['entity_id']
            unused = donor_entities[i].get('_unused', '00' * 8)
        else:
            entity_id = '0x%016x' % (0x1000000000000 + i)
            unused = '00' * 8
        out.append({
            'entity_id': entity_id,
            'template_hash': '0x%016x' % murmur64(template),
            'material_hash': '0x%016x' % int(s.get('material_hash', 0)),
            'position': [float(v) for v in s.get('position', [0, 0, 0])],
            'rotation': [float(v) for v in s.get('rotation', [0, 0, 0, -1])],
            'scale': [float(v) for v in s.get('scale', [1, 1, 1])],
            '_unused': unused,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('donor')
    ap.add_argument('out')
    ap.add_argument('--entities', required=True)
    ap.add_argument('--replace-at', type=int, default=None, metavar='INDEX',
                    help='replace just this entity in the donor table instead of the '
                         'whole table; the spec must then hold exactly one entry.  The '
                         'donor keeps its other entities, which matters in a room whose '
                         'encounter doors and entrance blockers are load-bearing.')
    ap.add_argument('--zero-sublevels', default=None, metavar='PATHS',
                    help='comma-separated resource names whose sub-level PLACEMENT records '
                         'to zero, so the level places nothing but its own entities.  A room '
                         'places its shell as sub-levels, so this is how "just our plane, no '
                         'crypt" is built.  Each name is matched by its murmur64 (56-byte '
                         'records: name_hash, position, rotation, scale, extra - FINDINGS 9H.5).')
    a = ap.parse_args()

    blob = Path(a.donor).read_bytes()
    data = decode_level(blob)
    ent_off, ent_count = data['header'][0]
    original = data['entities']
    print('donor %s: %d bytes, %d entities at 0x%X' % (a.donor, len(blob), ent_count, ent_off))

    spec = json.loads(Path(a.entities).read_text())

    if a.replace_at is not None:
        if len(spec) != 1:
            print('ERROR: --replace-at takes a spec of exactly one entity, got %d' % len(spec))
            return 2
        if not 0 <= a.replace_at < ent_count:
            print('ERROR: --replace-at %d outside 0..%d' % (a.replace_at, ent_count - 1))
            return 2
        entities = list(original)
        entities[a.replace_at] = build_entities(spec, original)[0]
        print('replacing entity %d: %s -> %s'
              % (a.replace_at, original[a.replace_at]['template_hash'],
                 entities[a.replace_at]['template_hash']))
    else:
        if len(spec) > ent_count:
            print('ERROR: %d entities asked for, the donor holds at most %d'
                  % (len(spec), ent_count))
            return 2
        entities = build_entities(spec, original)

    data['entities'] = entities
    data['entity_count'] = len(entities)
    data['header'][0] = [ent_off, len(entities)]

    out = encode_level(data)

    # The whole point: same size, and nothing outside the header's entity-COUNT field and
    # the entity table touched.  That count field is the one thing besides the table this
    # tool owns: header[0] = {entity_table_offset, entity_count}, so the count is the u32
    # at header offset 4.
    if len(out) != len(blob):
        print('ERROR: size changed %d -> %d' % (len(blob), len(out)))
        return 2
    table_end = ent_off + ent_count * ENTITY_RECORD_SIZE
    COUNT_FIELD = 4                      # u32, so 4..7 inclusive
    diff_outside = sum(1 for i in range(len(blob))
                       if not (ent_off <= i < table_end)
                       and not (COUNT_FIELD <= i < COUNT_FIELD + 4)
                       and blob[i] != out[i])
    count_changed = blob[COUNT_FIELD:COUNT_FIELD + 4] != out[COUNT_FIELD:COUNT_FIELD + 4]
    print('size unchanged: %s   entity-count field %s   bytes differing elsewhere: %d'
          % (len(out) == len(blob), 'changed' if count_changed else 'unchanged', diff_outside))
    if diff_outside:
        print('ERROR: the edit reached beyond the entity table and the count field')
        return 2

    if a.zero_sublevels:
        buf = bytearray(out)
        for name in [n.strip() for n in a.zero_sublevels.split(',') if n.strip()]:
            h = murmur64(name)
            needle = struct.pack('<Q', h)
            hits, start = [], 0
            while True:
                i = buf.find(needle, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + 1
            for i in hits:
                buf[i:i + PLACEMENT_RECORD_SIZE] = b'\x00' * PLACEMENT_RECORD_SIZE
            print('  sub-level %-58s hash 0x%016x  placement records zeroed: %d'
                  % (name[:58], h, len(hits)))
        out = bytes(buf)

    Path(a.out).write_bytes(out)

    check = decode_level(out)
    print('wrote %s: %d bytes, %d entities, header[0]=%s'
          % (a.out, len(out), check['entity_count'], check['header'][0]))
    for e in check['entities']:
        print('   template %s  pos %s  scale %s  rot %s'
              % (e['template_hash'], [round(v, 3) for v in e['position']],
                 [round(v, 3) for v in e['scale']], [round(v, 3) for v in e['rotation']]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
