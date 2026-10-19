#!/usr/bin/env python3
"""
Check a level's placements for mirror symmetry, and the rotations with them.

Why this exists (FINDINGS 9H.25): an author's test layout is usually built with deliberate
symmetry, and symmetry is a ground truth this side of the fence cannot otherwise get.  If the
layout mirrors in x, then the RECOVERED yaw of a unit and of its partner must mirror too - a
reflection in the x = c plane takes a yaw of t to -t.  Every pair that does not is either a
recovery error or a deliberate asymmetry in the source, and either way it is a named unit to
look at.

This is what validated the baked-export recovery on the 858-node test arena: 51 of 51 real
mirror pairs came back correctly mirrored, so the fit's handedness is right; the one apparent
exception was a rotation-ruler fixture (a diagnostic row, not authored content) pairing with
an unrelated unit.

Usage:
  python3 check_level_symmetry.py <level file> [--skip-last N]
"""
import collections
import math
import struct
import sys

TABLE = 128
REC = 72
OFF_TEMPLATE = 32
OFF_POS = 48
OFF_ROT_XYZ = 60
OFF_ROT_W = 72            # the quaternion's w is the FOURTH consecutive float at 60 (9H.36)


def read_records(path, skip_last=0):
    blob = open(path, 'rb').read()
    count = struct.unpack_from('<I', blob, 4)[0] - skip_last
    out = []
    for i in range(count):
        base = TABLE + i * REC
        x, y, z = struct.unpack_from('<3f', blob, base + OFF_ROT_XYZ)
        w, = struct.unpack_from('<f', blob, base + OFF_ROT_W)
        out.append({'pos': struct.unpack_from('<3f', blob, base + OFF_POS),
                    'yaw': math.degrees(2.0 * math.atan2(z, w)),
                    'template': struct.unpack_from('<Q', blob, base + OFF_TEMPLATE)[0]})
    return out


def mirror_pairs(recs, c, tol=0.05):
    pairs, unpaired = [], []
    for r in recs:
        want = 2.0 * c - r['pos'][0]
        hit = None
        for q in recs:
            if q is r:
                continue
            if (abs(q['pos'][0] - want) < tol and abs(q['pos'][1] - r['pos'][1]) < tol
                    and abs(q['pos'][2] - r['pos'][2]) < tol):
                hit = q
                break
        (pairs.append((r, hit)) if hit else unpaired.append(r))
    return pairs, unpaired


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    skip = 0
    for a in sys.argv[2:]:
        if a.startswith('--skip-last'):
            skip = int(a.split('=', 1)[1]) if '=' in a else 0
    recs = read_records(sys.argv[1], skip)
    print('records: %d  (ruler/diagnostic fixtures skipped: %d)' % (len(recs), skip))

    best = max(((len(mirror_pairs(recs, c)[0]), c)
                for c in [v * 0.05 for v in range(-40, 41)]), key=lambda t: t[0])
    c = best[1]
    pairs, unpaired = mirror_pairs(recs, c)
    print('mirror centre   : x = %.2f  ->  %d mirrored, %d unpaired (of %d)'
          % (c, len(pairs), len(unpaired), len(recs)))

    good = bad = 0
    for a, b in pairs:
        d = b['yaw'] + a['yaw']
        while d > 180.0:
            d -= 360.0
        while d <= -180.0:
            d += 360.0
        if abs(d) < 1.0:
            good += 1
        else:
            bad += 1
            print('   NOT mirrored: pos=%s %s yaw %7.1f  vs partner yaw %7.1f  (off %6.1f)'
                  % (str([round(v, 2) for v in a['pos']]), '%016x' % a['template'],
                     a['yaw'], b['yaw'], d))
    print('yaw mirroring   : %d correct, %d not (a reflection in x negates a yaw)'
          % (good, bad))
    return 0


if __name__ == '__main__':
    sys.exit(main())
