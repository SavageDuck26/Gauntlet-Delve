#!/usr/bin/env python3
"""
Join OUR level's 72-byte records to the engine's own capture of that level.

Why this exists (FINDINGS 9H.24): a capture of the level the engine actually loaded is the
only ground truth for what the engine did with each record.  compare_runtime_units.py did this
for a donor body by TEMPLATE HASH; that join drifts here, because a level of our own has only
a couple of dozen distinct kinds and the engine's unit order is not the file's.  This joins on
(rounded world position, template hash) together, which is unique for 192 of 194 records, and
falls back to nothing rather than to a wrong pair.

It answers three questions, in order:
  1. do the POSITIONS agree            (they do - the layout is right)
  2. how many ROTATIONS agree exactly  (151 of 192 in the hub-room build)
  3. for the ones that do not, is the difference a fixed function of the record?

Reading the answers (measured, 9H.24):
  * the record bytes for a matching and a mismatching unit can be IDENTICAL, so the engine's
    value is not a function of the record's rotation alone - something outside the record
    decides it (the same 21% disagreement appears for a shipped room, so it is the engine's
    own behaviour, not our file's)
  * every identity record survives (75/75), and the deltas come in mirrored pairs:
    +-19.5, +-70.5, +-90 degrees - arccos(1/3) / arcsin(1/3) / 90, the signature of a
    rotation composed through a tilted frame rather than read straight out of the record.

Usage:
  python3 compare_level_capture.py <level file> <capture json> [--offset ox,oy,oz]
"""
import collections
import json
import math
import struct
import sys

REC = 72
TABLE = 128
OFF_ENTITY_ID = 24
OFF_TEMPLATE = 32
OFF_MATERIAL = 40
OFF_POS = 48
OFF_ROT_XYZ = 60
OFF_ROT_W = 72            # the quaternion's w is the FOURTH consecutive float at 60 (9H.36)


def read_records(path):
    blob = open(path, 'rb').read()
    count = struct.unpack_from('<I', blob, 4)[0]
    out = []
    for i in range(count):
        base = TABLE + i * REC
        x, y, z = struct.unpack_from('<3f', blob, base + OFF_ROT_XYZ)
        w, = struct.unpack_from('<f', blob, base + OFF_ROT_W)
        out.append({
            'index': i,
            'entity_id': struct.unpack_from('<Q', blob, base + OFF_ENTITY_ID)[0],
            'template': struct.unpack_from('<Q', blob, base + OFF_TEMPLATE)[0],
            'material': struct.unpack_from('<Q', blob, base + OFF_MATERIAL)[0],
            'pos': struct.unpack_from('<3f', blob, base + OFF_POS),
            'quat': (x, y, z, w),
        })
    return out


def read_capture(path):
    d = json.load(open(path))
    out = []
    for u in d['units']:
        nh = u.get('name_hash', '')
        if '[' not in nh:
            continue
        rot = u.get('rot')
        out.append({
            'index': u.get('index'),
            'template': int(nh[nh.find('[') + 1:nh.find(']')], 16),
            'pos': tuple(u['pos']),
            'quat': (rot[0], rot[1], rot[2], rot[3]),      # the capture is (x, y, z, w)
        })
    return d.get('level', '?'), out


def yaw(q):
    """The rotation's yaw in degrees, from a quaternion given as (x, y, z, w)."""
    return math.degrees(2.0 * math.atan2(q[2], q[3]))


def same_rotation(a, b, tol=2e-3):
    return abs(sum(a[k] * b[k] for k in range(4))) > 1.0 - tol


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    level, cap_path = sys.argv[1], sys.argv[2]
    fixed = None
    for a in sys.argv[3:]:
        if a.startswith('--offset'):
            fixed = tuple(float(v) for v in a.split('=', 1)[1].split(','))
    recs = read_records(level)
    name, cap = read_capture(cap_path)
    print('level   : %s  (%d records)' % (level, len(recs)))
    print('capture : %s  (%d units)' % (name, len(cap)))

    # A sub-level sits at an offset inside its parent; find the one that lines the most
    # (position, hash) pairs up, unless the caller pinned it.
    def joined(offset):
        idx = collections.defaultdict(list)
        for u in cap:
            idx[(tuple(round(v, 1) for v in u['pos']), u['template'])].append(u)
        pairs = []
        for r in recs:
            key = (tuple(round(r['pos'][k] + offset[k], 1) for k in range(3)), r['template'])
            lst = idx.get(key, [])
            if len(lst) == 1:
                pairs.append((lst[0], r))
        return pairs

    offsets = [fixed] if fixed else [(x, y, 0.0) for x in (0.0, 4.0, -4.0, 8.0)
                                     for y in (0.0, 4.0, -4.0, 8.0)]
    best = max(((len(joined(o)), o) for o in offsets), key=lambda t: t[0])
    pairs = joined(best[1])
    print('offset  : %s  ->  %d of %d records joined uniquely'
          % (tuple(best[1]), len(pairs), len(recs)))
    if not pairs:
        return 1

    same = diff = 0
    deltas = collections.Counter()
    per_kind = collections.Counter()
    for u, r in pairs:
        if same_rotation(u['quat'], r['quat']):
            same += 1
            per_kind[('%016x' % r['template'], 'same')] += 1
            continue
        diff += 1
        per_kind[('%016x' % r['template'], 'differ')] += 1
        d = yaw(u['quat']) - yaw(r['quat'])
        while d <= -180.0:
            d += 360.0
        while d > 180.0:
            d -= 360.0
        deltas[round(d, 1)] += 1

    print('rotation: %d exact, %d different' % (same, diff))
    if deltas:
        print('deltas (engine - record), degrees: %s'
              % ', '.join('%+.1f x%d' % (k, v) for k, v in deltas.most_common()))
    kinds = sorted({k for k, _ in per_kind})
    if kinds:
        print('per template hash:')
        for h in kinds:
            print('   %s  %3d exact, %3d different'
                  % (h, per_kind[(h, 'same')], per_kind[(h, 'differ')]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
