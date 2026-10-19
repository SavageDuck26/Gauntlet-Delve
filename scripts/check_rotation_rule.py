#!/usr/bin/env python3
"""
check_rotation_rule.py - the record-rotation rule, checked without an export file.

WHY THIS EXISTS (FINDINGS 9H.29).  The first un-baked build shipped 12 placements where the
three that carried their own rotation held the INVERSE of it - a crane facing 251.6 degrees
around -Z instead of 108.36 around +Z, two stairs 180 and 120 degrees out - and NOTHING in the
file said so.  The nine identity placements were correct, which is why every earlier check
passed.  The cause was not the rule but its application twice: `to_engine_rotation` put the
result into the engine's branch by negating only xyz, and the record-branch rule applied later
negated all four and put the sign back.

So this check tests no export, no level and no engine.  It re-derives the rule and tests the
properties that together make that bug impossible:

  1. COMPOSITION - to_engine_rotation(q, +90, -90) is F * R_node * F^-1 with F = R_x(+90), the
     file -> engine change of a self-consistent Y-up export; `_orientation_error` (the check the
     build now refuses on) reads 0.
  2. IDEMPOTENCE - `_record_branch` changes nothing when applied to its own output, and the
     engine's reconstruction from the stored xyz, q = (x, y, z, -sqrt(1-|xyz|^2)), is the SAME
     ROTATION as the composed one.  Half the cases here compose to w > 0, which is the half the
     old code got wrong.
  3. TEETH - the old xyz-only branch is reproduced and must be caught on EVERY case whose
     composed w > 0.  It is not wrong on the others (w < 0 needs no branch and w == 0 has
     nothing to flip), which is exactly why the bug hid behind nine identical floors.

Usage:
  python3 check_rotation_rule.py
"""
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from level_from_glb import (                       # noqa: E402
    ORIENT_TOL_DEG, _orientation_error, _qmul, _record_branch, _x_quat, _quat_angle_deg,
    to_engine_rotation,
)

# The node rotations the own-unit arena actually carries (9H.29), plus the identity, plus random
# ones: the cases that were wrong, the case that hid them, and the general case.
CASES = [
    ('identity', (0.0, 0.0, 0.0, 1.0)),
    ('crane 108.36 about Y', (0.0, 0.8108319044113159, 0.0, 0.5852792859077454)),
    ('stair -90 about X', (-0.70710688829422, 0.0, 0.0, 0.7071066498756409)),
    ('stair.001 120 about (-1,1,1)', (-0.5, 0.5, 0.5, 0.5)),
    ('yaw 90', (0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4))),
    ('yaw 180', (0.0, 1.0, 0.0, 0.0)),
    ('roll 30 about Z', (0.0, 0.0, math.sin(math.pi / 12), math.cos(math.pi / 12))),
]
_rng = random.Random(9)
for i in range(8):
    v = [_rng.uniform(-1, 1) for _ in range(4)]
    n = math.sqrt(sum(c * c for c in v))
    CASES.append(('random #%d' % (i + 1), tuple(c / n for c in v)))

# F = R_x(+90) is the file -> engine change for a Y-up export, and a self-consistent export has
# deg_mesh = -deg_pos, which is what makes the rule the conjugation it is.
DEG_POS, DEG_MESH = 90, -90


# Comparing against quaternions that came out of a float32 file can never be exact (the export's
# own stairs are 0.021 degrees from ideal) and acos amplifies that near a zero angle, so the
# "unchanged" tests use the same tolerance the build does rather than an equality.
TOL = ORIENT_TOL_DEG


def composed(q, deg_pos, deg_mesh):
    """R_x(deg_pos) * R_node * R_x(deg_mesh) - the composition, before any branch."""
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n > 0.0:
        x, y, z, w = x / n, y / n, z / n, w / n
    if deg_pos:
        x, y, z, w = _qmul(_x_quat(deg_pos), (x, y, z, w))
    if deg_mesh:
        x, y, z, w = _qmul((x, y, z, w), _x_quat(deg_mesh))
    return [x, y, z, w]


def engine_rebuild(q):
    """What the ENGINE builds from a record: xyz as stored, w derived as -|w| (9H.18, 329/329)."""
    x, y, z = q[0], q[1], q[2]
    return (x, y, z, -math.sqrt(max(0.0, 1.0 - x * x - y * y - z * z)))


def old_branch(q, deg_pos, deg_mesh):
    """The pre-9H.29 to_engine_rotation: the branch negates ONLY xyz, leaving w positive."""
    x, y, z, w = composed(q, deg_pos, deg_mesh)
    if w > 0.0:
        x, y, z = -x, -y, -z
    return [x, y, z, w]


def main() -> int:
    bad = 0
    print('the rule: R_record = F * R_node * F^-1,  F = R_x(%+d), deg_mesh = %+d'
          % (DEG_POS, DEG_MESH))
    # "flip" = the composed quaternion has w > 0 AND an xyz to negate, i.e. the branch has
    # something to do.  The identity composes to w = 1 with xyz all zero, which is the case the
    # nine floors are and the reason the bug was invisible: there is nothing there to negate,
    # so both the old code and the new are right.
    wants = [(name, q, composed(q, DEG_POS, -DEG_POS)) for name, q in CASES]
    flips = [n for n, _q, w in wants if w[3] > 0.0 and max(abs(v) for v in w[:3]) > 1e-6]
    print('%-30s %8s %8s %8s %8s %6s' % ('case', 'orient', 'idem', 'rebuilt', 'old bug', 'flip'))
    uncaught = []
    for name, q, want in wants:
        rec = to_engine_rotation(list(q), DEG_POS, DEG_MESH)
        orient = _orientation_error(q, DEG_POS, rec)            # 1. composition
        idem = _quat_angle_deg(rec, _record_branch(list(rec)))  # 2. idempotence
        rebuilt = _quat_angle_deg(engine_rebuild(rec), want)    # 2b. what the engine constructs
        old = _orientation_error(q, DEG_POS, old_branch(list(q), DEG_POS, DEG_MESH))
        needs_branch = name in flips
        print('%-30s %8.3f %8.3f %8.3f %8.3f %6s'
              % (name, orient, idem, rebuilt, old, 'yes' if needs_branch else 'no'))
        checks = (('the record does not reproduce the authored orientation', orient),
                  ('_record_branch is NOT idempotent - the double branch is back', idem),
                  ("the engine's reconstruction is a different rotation", rebuilt))
        for label, value in checks:
            if value > TOL:
                print('  *** %s (%.3f deg)' % (label, value))
                bad += 1
        if rec[3] > 1e-9:
            print("  *** the record is not in the engine's branch (w must be <= 0)")
            bad += 1
        # 3. TEETH: where the branch has something to flip, the old code is plainly wrong.
        if needs_branch and old <= TOL:
            uncaught.append(name)
    print()
    if uncaught:
        print('  *** the old xyz-only branch is NOT caught on: %s' % ', '.join(uncaught))
        bad += 1
    print('the old branch is caught on every case that needs one: %d of %d cases have a branch'
          ' to apply' % (len(flips), len(CASES)))
    if len(flips) < 4:
        print('  *** too few cases exercise the branch - this check proves nothing')
        bad += 1
    if bad:
        print()
        print('FAILED (%d)' % bad)
        return 1
    print()
    print('all %d cases: the rule holds, the branch is idempotent, the engine rebuilds the'
          ' authored rotation' % len(CASES))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
