#!/usr/bin/env python3
"""
level_decode.py - read a .level structurally and print what is in it.

This is the *map* tool: it writes nothing, it names every section, and it says which of
them are understood and which are not.  resource_tools/level_tools.py still owns
encode/decode for editing (byte-exact on 255/255 real levels); this only reads.

THE HEADER IS NOT 16 OPAQUE PAIRS
---------------------------------
The 128 bytes at the head are 32 uint32 fields: counts interleaved with offsets.  The old
reading ("16 x {field_a, field_b}, where equal values are sentinels") fitted the bytes and
explained nothing.  A sibling Stingray game settles it - filediver's `RawLevel`
(reference/filediver/stingray/level/level.go) is the same struct with 64 slots, and its
loader reads a count, then seeks to an offset and reads that many records.  In Gauntlet:

    u32[0]  = 128            constant in the whole corpus: the unit table starts here
    u32[1]  = unit count     371 / 4247 / 6 in the three levels measured
    u32[2]  = data count     always 1
    u32[3]  = offset         24 bytes past the unit table
    u32[14] = metadata list  verified by decoding it (see METADATA)
    u32[10],[11] = a 12-byte-record array and its count
    u32[15],[16] = a 56-byte-record array and its count
    u32[24] = a per-unit array, EXACTLY 8 bytes per unit (371*8, 4247*8)
    u32[29],[30] = the placement table's count and offset
    u32[28] = file size - 8

Every other field is an offset into the file whose contents are not yet named; those are
printed with their size and content profile rather than guessed at.

UNIT RECORDS (72 bytes, at u32[0], u32[1] of them)
-------------------------------------------------
    0   4   float    -1.0 / 0.0 (a flag; see FINDINGS 9H.6)  [the PREVIOUS unit's w, 9H.36]
    4  12   float[3] scale (1,1,1 on ordinary blocks)        [the PREVIOUS unit's scale, 9H.36]
   16   8   unused
   24   8   entity id       (per instance)
   32   8   template hash   (MurmurHash64A of the unit path, lowercase)
   40   8   material override (0 = none)
   48  12   position xyz
   60  12   rotation xyzw: x/y/z here and w at 72 (the NEXT record's offset 0) - the engine
            reads FOUR consecutive floats at 60 (FINDINGS 9H.36)

METADATA (at u32[14]) - fully decoded
-------------------------------------
    u32 count, then `count` entries:
        u32 hashCount, u32 thinHash[hashCount], u32 type, value
        type 1 = uint32, 2 = float32, 3 = string (u32 length incl. null, then the bytes)
    This is `parseMetadataEntry` from filediver, confirmed on real levels: a room carries
    4 entries, among them 'core/rendering/default_outdoor' and 'default'.

    level_decode.py level.level [--names] [--entities N] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HEADER_FIELDS = 32
UNIT_RECORD_SIZE = 72
PLACEMENT_RECORD_SIZE = 56
HASH_RANGE_RECORD_SIZE = 12
PER_UNIT_ARRAY_STRIDE = 8

# Named from measurement, not inference.  Anything absent from this table is reported as
# an unnamed offset rather than given a plausible-sounding name.
HEADER_NAMES = {
    0: 'unit_table_offset',
    1: 'unit_count',
    2: 'data_count',
    3: 'offset_after_units',
    10: 'record12_offset',
    11: 'record12_count',
    14: 'metadata_offset',
    15: 'record56_count',
    16: 'record56_offset',
    24: 'per_unit_array_offset',
    28: 'file_size_minus_8',
    29: 'placement_count',
    30: 'placement_offset',
}

METADATA_TYPES = {0: 'none', 1: 'uint32', 2: 'float32', 3: 'string'}

HERE = Path(__file__).resolve().parent


def _load_names() -> Dict[str, str]:
    """hash (16 hex) -> name, from whichever name databases the repo has."""
    out: Dict[str, str] = {}
    for name in ('hash_database.json', 'resource_name_overlay.json'):
        path = HERE.parent / 'Data' / name
        if path.exists():
            try:
                out.update(json.loads(path.read_text()))
            except Exception:
                pass
    return out


def _section_bounds(header: List[int], size: int) -> List[tuple]:
    """(start, end) for every distinct offset the header names, in file order."""
    starts = sorted({v for v in header if 128 <= v < size and v % 4 == 0})
    if not starts or starts[0] != 128:
        starts.insert(0, 128)
    starts.append(size)
    return [(starts[i], starts[i + 1]) for i in range(len(starts) - 1)]


def _profile(blob: bytes) -> Dict[str, Any]:
    """What a section looks like, so an unnamed one still says something."""
    n = len(blob)
    if n < 4:
        return {'bytes': n, 'all_zero': True}
    words = struct.unpack_from('<%dI' % (n // 4), blob, 0)
    floats = struct.unpack_from('<%df' % (n // 4), blob, 0)
    nonzero = [w for w in words if w]
    return {
        'bytes': n,
        'zero_pct': round(100.0 * blob.count(0) / n, 1),
        'u32_min': min(nonzero) if nonzero else 0,
        'u32_max': max(nonzero) if nonzero else 0,
        'offset_like_pct': round(100.0 * sum(1 for w in nonzero if w % 4 == 0 and w < n)
                                 / max(1, len(nonzero)), 1),
        'plausible_float_pct': round(100.0 * sum(1 for f in floats if -2000.0 < f < 2000.0)
                                     / max(1, len(floats)), 1),
        'first_u32': list(words[:8]),
    }


def _decode_metadata(blob: bytes, offset: int) -> List[Dict[str, Any]]:
    """The metadata list at `offset`; see parseMetadataEntry in filediver."""
    if not offset or offset >= len(blob):
        return []
    count = struct.unpack_from('<I', blob, offset)[0]
    if count > 512:
        return [{'error': 'implausible entry count %d' % count}]
    pos = offset + 4
    out: List[Dict[str, Any]] = []
    for _ in range(count):
        if pos + 4 > len(blob):
            break
        hash_count = struct.unpack_from('<I', blob, pos)[0]
        pos += 4
        if hash_count > 16:
            out.append({'error': 'implausible key count %d' % hash_count})
            break
        keys = list(struct.unpack_from('<%dI' % hash_count, blob, pos)) if hash_count else []
        pos += 4 * hash_count
        mtype = struct.unpack_from('<I', blob, pos)[0]
        pos += 4
        entry: Dict[str, Any] = {'keys': ['0x%08x' % k for k in keys],
                                 'type': METADATA_TYPES.get(mtype, 'type%d' % mtype)}
        if mtype == 1:
            entry['value'] = struct.unpack_from('<I', blob, pos)[0]
            pos += 4
        elif mtype == 2:
            entry['value'] = struct.unpack_from('<f', blob, pos)[0]
            pos += 4
        elif mtype == 3:
            length = struct.unpack_from('<I', blob, pos)[0]
            pos += 4
            raw = blob[pos:pos + length]
            pos += (length + 3) & ~3          # strings are padded to a 4-byte boundary
            entry['value'] = raw.split(b'\0')[0].decode('ascii', 'replace')
        out.append(entry)
    return out


def _decode_units(blob: bytes, offset: int, count: int, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(min(count, limit)):
        o = offset + i * UNIT_RECORD_SIZE
        if o + UNIT_RECORD_SIZE > len(blob):
            break
        flag = struct.unpack_from('<f', blob, o)[0]
        # The unit's own scale is one record on (o+76 = the next record's offset 4): the 24 bytes
        # at the record's own start are the PREVIOUS unit's w/scale/padding (FINDINGS 9H.36).
        scale = struct.unpack_from('<3f', blob, o + 76) if o + 88 <= len(blob) \
            else struct.unpack_from('<3f', blob, o + 4)
        eid, templ, mat = struct.unpack_from('<3Q', blob, o + 24)
        pos = struct.unpack_from('<3f', blob, o + 48)
        rx, ry, rz = struct.unpack_from('<3f', blob, o + 60)
        # The engine reads the rotation as FOUR CONSECUTIVE floats at 60 (9H.36): x/y/z and the w
        # at 72, i.e. the NEXT record's offset 0 - not this record's own offset 0, which belongs
        # to the previous unit.  The scale is the next record's offset 4 for the same reason.
        rw = struct.unpack_from('<f', blob, o + 72)[0] if o + 76 <= len(blob) else \
            -math.sqrt(max(0.0, 1.0 - rx * rx - ry * ry - rz * rz))
        out.append({'index': i, 'flag': round(flag, 6),
                    'scale': [round(v, 4) for v in scale],
                    'entity_id': '0x%016x' % eid, 'template_hash': '0x%016x' % templ,
                    'material_hash': '0x%016x' % mat,
                    'position': [round(v, 4) for v in pos],
                    'rotation': [round(rx, 6), round(ry, 6), round(rz, 6), round(rw, 6)]})
    return out


def decode(path: Path, name_db: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a level into a plain dict: header, units, metadata, sections, placements."""
    blob = path.read_bytes()
    size = len(blob)
    header = list(struct.unpack_from('<%dI' % HEADER_FIELDS, blob, 0))

    doc: Dict[str, Any] = {'file': path.name, 'size': size,
                           'header': {str(i): v for i, v in enumerate(header)}}

    unit_off, unit_count = header[0], header[1]
    doc['unit_table'] = {'offset': unit_off, 'count': unit_count,
                         'record_size': UNIT_RECORD_SIZE,
                         'ends_at': unit_off + unit_count * UNIT_RECORD_SIZE}
    # The three things that must hold for this reading to be right.
    doc['invariants'] = {
        'unit_table_starts_at_header_end': unit_off == 128,
        'unit_table_fits': unit_off + unit_count * UNIT_RECORD_SIZE <= size,
        'data_count_is_one': header[2] == 1,
    }

    meta = _decode_metadata(blob, header[14])
    if name_db:
        for entry in meta:
            entry['key_names'] = [name_db.get(k[2:], '') for k in entry.get('keys', [])]
    doc['metadata'] = meta

    sections = []
    for start, end in _section_bounds(header, size):
        entry: Dict[str, Any] = {
            'start': start, 'end': end, 'bytes': end - start,
            'profile': _profile(blob[start:end]),
            'named_by': [HEADER_NAMES.get(i, 'u32[%d]' % i)
                         for i, v in enumerate(header) if v == start]}
        span = end - start
        per_unit = span / unit_count if unit_count else 0
        if abs(per_unit - PER_UNIT_ARRAY_STRIDE) < 1e-9:
            entry['shape'] = 'per-unit array, %d B x %d units' % (PER_UNIT_ARRAY_STRIDE, unit_count)
        elif span % PLACEMENT_RECORD_SIZE == 0 and 0 < span // PLACEMENT_RECORD_SIZE <= 64:
            entry['shape'] = '%d x %d-byte placement records' % (span // PLACEMENT_RECORD_SIZE,
                                                                 PLACEMENT_RECORD_SIZE)
        elif span % HASH_RANGE_RECORD_SIZE == 0 and 0 < span // HASH_RANGE_RECORD_SIZE <= 4096:
            entry['shape'] = '%d x %d-byte records' % (span // HASH_RANGE_RECORD_SIZE,
                                                       HASH_RANGE_RECORD_SIZE)
        sections.append(entry)
    doc['sections'] = sections

    place_count, place_off = header[29], header[30]
    placements = []
    for i in range(min(place_count, 64)):
        o = place_off + i * PLACEMENT_RECORD_SIZE
        if o + PLACEMENT_RECORD_SIZE > size:
            break
        raw = blob[o:o + PLACEMENT_RECORD_SIZE]
        # Layout verified against the room's own 7 records: all 7 resolve to real names and
        # the transforms are clean.  The loader (gauntlet.exe FUN_0042b6b0) walks this table
        # with a 0x38 stride, XORs the first 8 bytes with the level's own id to make an
        # instance id, reads the next 8 as the sub-level's resource id, and builds a matrix
        # from +16 (position), +28 (rotation quaternion) and +44 (scale).
        record = {'index': i,
                  'instance_id': '0x%016x' % struct.unpack_from('<Q', raw, 0)[0],
                  'resource_hash': '0x%016x' % struct.unpack_from('<Q', raw, 8)[0],
                  'position': [round(v, 4) for v in struct.unpack_from('<3f', raw, 16)],
                  'rotation': [round(v, 6) for v in struct.unpack_from('<4f', raw, 28)],
                  'scale': [round(v, 4) for v in struct.unpack_from('<3f', raw, 44)]}
        if name_db:
            record['name'] = name_db.get(record['resource_hash'][2:], '')
        placements.append(record)
    doc['placements'] = {'count': place_count, 'offset': place_off, 'records': placements}
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description='read a .level structurally')
    ap.add_argument('level')
    ap.add_argument('--names', action='store_true', help='resolve hashes with the name databases')
    ap.add_argument('--entities', type=int, default=0, help='also list the first N unit records')
    ap.add_argument('--json', help='write the whole reading to this file')
    args = ap.parse_args()

    path = Path(args.level)
    if not path.exists():
        ap.error('no such file: %s' % path)
    name_db = _load_names() if args.names else None
    doc = decode(path, name_db)
    if args.entities:
        doc['units'] = _decode_units(path.read_bytes(), doc['unit_table']['offset'],
                                     doc['unit_table']['count'], args.entities)

    print('%s  %d bytes' % (doc['file'], doc['size']))
    print('  unit table : @%d  %d x %d = %d B'
          % (doc['unit_table']['offset'], doc['unit_table']['count'], UNIT_RECORD_SIZE,
             doc['unit_table']['count'] * UNIT_RECORD_SIZE))
    for key, ok in doc['invariants'].items():
        print('  %-34s %s' % (key, 'ok' if ok else 'FAILED'))
    print('  metadata   : %d entries @%s' % (len(doc['metadata']), doc['header']['14']))
    for entry in doc['metadata'][:8]:
        keys = ','.join(entry.get('key_names') or entry.get('keys', []))
        print('      %-34s %-8s %r' % (keys, entry.get('type'), entry.get('value')))
    print('  placements : %d @%d' % (doc['placements']['count'], doc['placements']['offset']))
    for p in doc['placements']['records'][:12]:
        print('      %-56s pos=%s rot=%s scale=%s'
              % (p.get('name') or p['resource_hash'], p['position'], p['rotation'], p['scale']))
    print('  sections   :')
    for s in doc['sections']:
        prof = s['profile']
        print('      @%-7d %-7d B  %-30s zero=%4.1f%%  off-like=%5.1f%%  float-like=%5.1f%%'
              % (s['start'], s['bytes'], s.get('shape', '?'), prof.get('zero_pct', 0.0),
                 prof.get('offset_like_pct', 0.0), prof.get('plausible_float_pct', 0.0)))
        if s['named_by']:
            print('          named by: %s' % ', '.join(s['named_by']))
        if 'first_u32' in prof:
            print('          first u32: %s' % prof['first_u32'])
    if 'units' in doc:
        print('  first %d units:' % len(doc['units']))
        for u in doc['units']:
            nm = name_db.get(u['template_hash'][2:], '') if name_db else ''
            print('      [%3d] %-46s pos=%s rot=%s'
                  % (u['index'], nm or u['template_hash'], u['position'], u['rotation']))
    if args.json:
        Path(args.json).write_text(json.dumps(doc, indent=1))
        print('wrote %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
