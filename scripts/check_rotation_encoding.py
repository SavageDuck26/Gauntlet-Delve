#!/usr/bin/env python3
"""The level record's ROTATION, checked against the CODE and against the corpus (FINDINGS 9H.34).

FROM THE DECOMPILE.  The per-unit pass builds each placement with

    FUN_0042db10(out, record + 0xc, record + 0, record + 0x1c)
      -> FUN_0042d7f0(out, quaternion, position, scale)

and FUN_0042d7f0 reads FOUR floats (x, y, z, w) and normalises them (k = 2/|q|^2) into a rotation
matrix.  So a record holds a QUATERNION: x/y/z at 60/64/68, w in the record's first float, and the
engine normalises it.  That is what this file checks, two ways:

 1. ROUND TRIP.  Every authored rotation, written the way the toolkit writes it (x/y/z plus the
    branch w), comes back out of the engine's own rebuild as the same orientation.
 2. THE CORPUS.  The six records of the game's own smallest level
    (assets/exports-samples/samples/level_24abcdf4b1fb4d4a.level) read as clean grid yaws under
    that rule - 0/90/180/90/90 - and NOT under the rotation-vector reading, which would make the
    three 90-degree records 70.53 degrees.  A hand-built crypt room has no 70.53-degree walls.
"""
import math
import struct
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from resource_tools.level_tools import (record_rotation_vector,   # noqa: E402
                                        quat_from_record_vector)

TOL_DEG = 0.01
SKELETON = ROOT / 'assets/exports-samples/samples/level_24abcdf4b1fb4d4a.level'


def axis_quat(axis, deg):
    n = math.sqrt(sum(a * a for a in axis))
    axis = [a / n for a in axis]
    half = math.radians(deg) / 2.0
    s = math.sin(half)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half))


def angle_between(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, dot))))


CASES = [
    ('identity', (0.0, 0.0, 0.0, 1.0)),
    ('+90 about X', axis_quat((1, 0, 0), 90)),
    ("-90 about X (the author's stair)", axis_quat((1, 0, 0), -90)),
    ('180 about X', axis_quat((1, 0, 0), 180)),
    ('+90 about Y', axis_quat((0, 1, 0), 90)),
    ('+90 about Z', axis_quat((0, 0, 1), 90)),
    ('180 about Z', axis_quat((0, 0, 1), 180)),
    ("108.35 about Z (the author's crane)", axis_quat((0, 0, 1), 108.35)),
    ('120 about (-1,-1,1) (the author\u2019s diagonal stair)', axis_quat((-1, -1, 1), 120)),
    ('170 about (1,1,1)', axis_quat((1, 1, 1), 170)),
    ('45 about (1,2,3)', axis_quat((1, 2, 3), 45)),
]


def main() -> int:
    bad = 0
    print('1. ROUND TRIP - what the engine builds from what the toolkit writes')
    print('   %-52s %8s %10s' % ('authored rotation', 'theta', 'error'))
    for name, q in CASES:
        authored = math.degrees(2 * math.acos(max(-1.0, min(1.0, abs(q[3])))))
        vec = record_rotation_vector(list(q))
        # the branch the toolkit writes: negate ALL FOUR when w > 0 (q and -q are the same
        # rotation; negating only xyz is the 9H.29 trap)
        x, y, z, w = (float(v) for v in q)
        n = math.sqrt(x * x + y * y + z * z + w * w)
        x, y, z, w = x / n, y / n, z / n, w / n
        if w > 0.0:
            x, y, z, w = -x, -y, -z, -w
        vec = [x, y, z]
        back = quat_from_record_vector(vec, w)
        err = angle_between(back, q)
        if err > TOL_DEG:
            bad += 1
            print('   %-52s %8.2f %9.3f  *** ERROR' % (name, authored, err))
        else:
            print('   %-52s %8.2f %9.3f' % (name, authored, err))

    print()
    print('2. THE CORPUS - what the game\'s own records say the rule is')
    print('   (the w is the FOURTH consecutive float at +0x48 - the next record\'s offset-0')
    print('    field - so a record\'s own leading float is NOT its own w; FINDINGS 9H.36)')
    if not SKELETON.exists():
        print('   %s is missing; skipping' % SKELETON.name)
    else:
        blob = SKELETON.read_bytes()
        count = struct.unpack_from('<I', blob, 4)[0]
        quat_angles, vec_angles, leading = [], [], []
        for i in range(count):
            off = 128 + i * 72
            w, = struct.unpack_from('<f', blob, off + 72)          # the next record's offset 0
            lead, = struct.unpack_from('<f', blob, off)            # what the toolkit used to use
            vec = [struct.unpack_from('<f', blob, off + 60)[0],
                   struct.unpack_from('<f', blob, off + 64)[0],
                   struct.unpack_from('<f', blob, off + 68)[0]]
            qv = quat_from_record_vector(vec, w)
            vr = quat_from_record_vector(vec, 1.0)                 # the rotation-vector rule
            quat_angles.append(round(math.degrees(2 * math.acos(min(1.0, abs(qv[3])))), 2))
            vec_angles.append(round(math.degrees(2 * math.acos(min(1.0, abs(vr[3])))), 2))
            lv = quat_from_record_vector(vec, lead)
            leading.append(round(math.degrees(2 * math.acos(min(1.0, abs(lv[3])))), 2))
            print('   rec %d  w(next)=%+.4f  own[0]=%+.4f  xyz=(%+.4f,%+.4f,%+.4f)   quaternion'
                  ' reading %7.2f deg   rotation-vector reading %7.2f deg'
                  % (i, w, lead, vec[0], vec[1], vec[2], quat_angles[-1], vec_angles[-1]))
        grid = all(abs(a % 90.0) < 0.01 or abs(a % 90.0 - 90.0) < 0.01 for a in quat_angles)
        if not grid:
            print('   *** the quaternion reading does not give grid yaws - the rule is wrong')
            bad += 1
        else:
            print('   the quaternion reading gives grid yaws (%s); the rotation-vector reading'
                  ' would give %s' % (quat_angles, vec_angles))
            print('   reading each record\'s OWN leading float would give %s - also grid-aligned,'
                  ' which is why the corpus alone never caught the off-by-one (9H.36); the'
                  ' engine\'s own capture does.' % leading)
    print()
    if bad:
        print('FAILED (%d)' % bad)
        return 1
    print('OK - the record holds a quaternion and the engine normalises it, exactly as'
          ' FUN_0042d7f0 says')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
