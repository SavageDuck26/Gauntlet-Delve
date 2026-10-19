#!/usr/bin/env python3
"""Does the FILE's rotation equal the rotation the ENGINE reports for that unit?

THE CHECK THAT WAS MISSING (FINDINGS 9H.36).  Every offline test compared the toolkit's reading
of a record against the toolkit's own writer, so an off-by-one in WHICH record holds a unit's
rotation w - and its scale - was invisible: the round trip stayed byte-exact, the ids, names and
positions all matched, and only the in-game orientation was wrong.  The engine's own per-unit
capture (the loader's LevelResource sweep: `runtime_units.tsv` / the per-level JSONs in
Data/runtime_units/) is the ground truth this check joins to.

The engine reads a unit's transform as FOUR consecutive floats at record+0x3c (FUN_0042d7f0 via
FUN_0042db10, walked by FUN_00430440 from data+0xb0 + i*0x48), so the w is at record+0x48 - the
NEXT record's first float - and the scale is at record+0x4c.  FUN_0042d7f0:
normalize((x, y, z, w)) -> matrix, k = 2/|q|^2.

WHAT IT DOES
  1. reads both readings straight from the bytes and joins each unit to the capture on
     (template hash, world position), then compares rotations;
  2. reports the pre-9H.36 reading - the record's OWN offset-0 float as the w - side by side.  A
     check that cannot fail proves nothing: on the hub the wrong reading is out by up to 168
     degrees on most joined units.

usage: check_level_capture_rotation.py <level file> <capture json> [--offset X,Y,Z] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from resource_tools.level_tools import ENTITY_RECORD_SIZE                        # noqa: E402

TOL_DEG = 1.0


def quat_angle_deg(a, b) -> float:
    """How far apart two quaternions are as an angle, in degrees (q and -q are 0 apart)."""
    d = abs(sum(float(x) * float(y) for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, d)))


def normalise(q):
    n = math.sqrt(sum(float(c) * float(c) for c in q))
    return [float(c) / n for c in q] if n > 0.0 else [0.0, 0.0, 0.0, 1.0]


def read_capture(path: Path):
    """(level name, [{index, template, pos, rot}]) from the loader's per-level JSON."""
    doc = json.loads(path.read_text())
    out = []
    for u in doc.get('units', []):
        nh = u.get('name_hash', '')
        if '[' not in nh:
            continue
        out.append({'index': u.get('index'),
                    'template': int(nh[nh.find('[') + 1:nh.find(']')], 16),
                    'pos': tuple(float(v) for v in u.get('pos', (0, 0, 0))),
                    'rot': tuple(float(v) for v in u.get('rot', (0, 0, 0, 1)))})
    return doc.get('level', '?'), out


def raw_readings(blob: bytes):
    """Both readings of every record, straight from the bytes.

    SHIPPED (9H.36): the w is the next record's offset-0 float.
    OLD     (pre-9H.36): the record's own offset-0 float.
    """
    ent_off, count = struct.unpack_from('<II', blob, 0)
    shipped, old = [], []
    for i in range(count):
        o = ent_off + i * ENTITY_RECORD_SIZE
        vec = struct.unpack_from('<3f', blob, o + 60)
        w_new, = struct.unpack_from('<f', blob, o + 60 + 12)     # the next record's offset 0
        w_old, = struct.unpack_from('<f', blob, o)
        tpl, = struct.unpack_from('<Q', blob, o + 32)
        pos = struct.unpack_from('<3f', blob, o + 48)
        shipped.append({'template': tpl, 'pos': pos,
                        'quat': normalise((vec[0], vec[1], vec[2], w_new))})
        old.append({'template': tpl, 'pos': pos,
                    'quat': normalise((vec[0], vec[1], vec[2], w_old))})
    return shipped, old


def join(records, capture, offset, tol=0.05):
    index = {}
    for u in capture:
        index.setdefault((u['template'],) + tuple(round(v, 2) for v in u['pos']), []).append(u)
    pairs = []
    for r in records:
        key = (r['template'],) + tuple(round(r['pos'][k] + offset[k], 2) for k in range(3))
        hit = index.get(key)
        if hit and len(hit) == 1:
            pairs.append((r, hit[0]))
    return pairs


def index_pairs(records, capture):
    """Capture unit i against FILE RECORD i - the only join that works for dense duplicates.

    The engine reports a level's units in the file's order, so this is valid - but it has to be
    proved rather than assumed, which is why `--by-index` measures every position before trusting
    a rotation.  A (hash, position) join cannot do this level: the author arena chains 968 links
    about 0.08 apart, so every link's key collides and only the 16 isolated units match.
    """
    return [(records[i], capture[i]) for i in range(min(len(records), len(capture)))]


def best_index_offset(records, capture):
    """The offset that lines record i up with capture unit i (for `--by-index` without --offset)."""
    n = min(len(records), len(capture))
    best = None
    for ox in (0.0, 4.0, -4.0, 8.0, -8.0):
        for oy in (0.0, 4.0, -4.0, 8.0, -8.0):
            err = sum(sum(abs(records[i]['pos'][k] + (ox, oy, 0.0)[k] - capture[i]['pos'][k])
                          for k in range(3)) for i in range(n)) / max(n, 1)
            if best is None or err < best[0]:
                best = (err, (ox, oy, 0.0))
    return best[1]


def best_offset(records, capture):
    """The offset that joins the most (hash, position) pairs - the non-index route."""
    best = None
    for ox in (0.0, 4.0, -4.0, 8.0, -8.0):
        for oy in (0.0, 4.0, -4.0, 8.0, -8.0):
            n = len(join(records, capture, (ox, oy, 0.0)))
            if best is None or n > best[0]:
                best = (n, (ox, oy, 0.0))
    return best[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('level')
    ap.add_argument('capture')
    ap.add_argument('--offset', default=None, help='X,Y,Z the capture is offset by')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--max-bad', type=int, default=0,
                    help='mismatches the SHIPPED reading may have and still pass.  Keep it at 0 '
                         'unless you have LOOKED at each one: a mismatch means the file and the '
                         'capture disagree about those bytes (a level this side edited after the '
                         'capture, or a copy that is not the file that was captured), never a '
                         'tolerance to widen.')
    ap.add_argument('--by-index', action='store_true',
                    help='line up capture unit i with FILE RECORD i instead of joining on '
                         '(template hash, position) - the only way to check a level with DENSE '
                         'DUPLICATES.  The author arena chains 968 links about 0.08 apart, so every '
                         'link\'s (hash, position) key collides and only its 16 isolated units can '
                         'be joined (measured: 16 of 986).  The engine reports a level unit by unit '
                         'in the file\'s order, so index alignment is valid - and this mode guards '
                         'it by checking every position first, and picks the offset that lines them '
                         'up when --offset is not given.')
    a = ap.parse_args()

    blob = Path(a.level).read_bytes()
    name, capture = read_capture(Path(a.capture))
    shipped, old = raw_readings(blob)

    if a.by_index:
        offset = tuple(float(v) for v in a.offset.split(',')) if a.offset \
            else best_index_offset(shipped, capture)
        pairs = index_pairs(shipped, capture)
        print('%s' % Path(a.level).name)
        print('  capture : %s (%d units)  [BY INDEX]' % (name, len(capture)))
        print('  aligned : %d record(s) against %d capture unit(s) at offset %s'
              % (len(pairs), len(capture), tuple(round(v, 1) for v in offset)))
        worst_pos = max(max(abs(r['pos'][k] + offset[k] - u['pos'][k]) for k in range(3))
                        for r, u in pairs)
        print('  position: worst error %.5f  (this is what proves the alignment is real)'
              % worst_pos)
        if worst_pos > 0.05:
            print('  *** the positions do not line up by index - the capture is not in the file\'s'
                  ' order, or the offset is wrong; use the (hash, position) join instead')
            return 1
    else:
        offset = tuple(float(v) for v in a.offset.split(',')) if a.offset \
            else best_offset(shipped, capture)
        pairs = join(shipped, capture, offset)
        print('%s' % Path(a.level).name)
        print('  capture : %s (%d units)' % (name, len(capture)))
        print('  joined  : %d of %d record(s) at offset %s'
              % (len(pairs), len(shipped), tuple(round(v, 1) for v in offset)))
        if not pairs:
            print('  *** nothing joined - wrong level/capture pair, or the positions moved')
            return 1

    def score(reading):
        pairs_r = index_pairs(reading, capture) if a.by_index \
            else join(reading, capture, offset)
        worst, bad = 0.0, []
        for r, u in pairs_r:
            err = quat_angle_deg(r['quat'], u['rot'])
            worst = max(worst, err)
            if err > TOL_DEG:
                bad.append((r['template'], err))
        return len(pairs_r), worst, bad

    n_new, worst_new, bad_new = score(shipped)
    n_old, worst_old, bad_old = score(old)
    print("  SHIPPED (w = next record's offset 0): %d/%d within %.1f deg, worst %.3f"
          % (n_new - len(bad_new), n_new, TOL_DEG, worst_new))
    print("  OLD     (w = this record's offset 0): %d/%d within %.1f deg, worst %.3f"
          % (n_old - len(bad_old), n_old, TOL_DEG, worst_old))
    if a.verbose:
        for tpl, err in bad_new[:12]:
            print('      shipped reading off by %7.2f deg on %016x' % (err, tpl))

    failed = 0
    if len(bad_new) > a.max_bad:
        print('  *** the shipped reading does not reproduce the engine on %d unit(s) - e.g. %s'
              % (len(bad_new), ', '.join('%016x by %.2f deg' % t for t in bad_new[:4])))
        failed += 1
    elif bad_new:
        print('  NOTE: %d unit(s) are within --max-bad %d but do NOT match - each one is a file/'
              'capture disagreement, not a tolerance' % (len(bad_new), a.max_bad))
    if len(capture) > 8 and not bad_old:
        print('  *** the OLD reading also fits: this pair cannot tell the two apart')
        failed += 1
    if failed:
        print('FAILED')
        return 1
    print('OK - the file, read the way the code reads it, is the level the engine loaded')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

