#!/usr/bin/env python3
"""
Join the engine's runtime unit list to a .level file's 72-byte records.

Why this exists: the offline decode of a .level cannot tell a correct rotation
read from a plausible one - about half the records do not form a unit quaternion
in any order of f0/f15/f16/f17.  The running engine knows the real transforms, so
capturing them (GauntletModLoader: mods/functions/LevelProbe) gives ground truth.

The join key is the TEMPLATE HASH: Unit.debug_name(unit) returns the unit's
resource-name hash, which is the same MurmurHash64A value the .level record
carries at offset 32.

Record layout (72 bytes at 128 + i*72), all CONFIRMED against the engine:
   0   float    quaternion component (w)     60,64,68  float  x, y, z
  32   uint64   template hash (the join key)  48,52,56  float  position x,y,z

Usage:
  python3 compare_runtime_units.py <level file> <runtime_units.tsv>
"""
import math, re, struct, sys

REC = 72
TABLE = 128
OFF_TEMPLATE = 32
OFF_POS = 48
OFF_ROT = (0, 60, 64, 68)


def read_records(path):
    blob = open(path, 'rb').read()
    count = struct.unpack_from('<I', blob, 4)[0]
    out = []
    for i in range(count):
        base = TABLE + i * REC
        out.append({
            'index': i,
            'template': struct.unpack_from('<Q', blob, base + OFF_TEMPLATE)[0],
            'pos': struct.unpack_from('<3f', blob, base + OFF_POS),
            'rot': tuple(struct.unpack_from('<f', blob, base + o)[0] for o in OFF_ROT),
        })
    return out


def read_engine(path):
    out = []
    for line in open(path).read().splitlines()[1:]:
        f = line.rstrip('\r').split('\t')
        if len(f) < 12 or not f[1]:
            continue
        m = re.search(r'([0-9a-fA-F]{16})', f[11])
        if not m:
            continue
        rot = [float(v) for v in f[4:8]] if f[4] else None
        out.append({'template': int(m.group(1), 16),
                    'pos': (float(f[1]), float(f[2]), float(f[3])),
                    'rot': rot, 'engine_index': int(f[0])})
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    recs = read_records(sys.argv[1])
    eng = read_engine(sys.argv[2])
    print('file records: %d   engine units: %d' % (len(recs), len(eng)))

    # Match by hash, consuming each file record once so repeated hashes pair in order.
    used, pairs = set(), []
    for e in eng:
        for r in recs:
            if r['index'] in used or r['template'] != e['template']:
                continue
            used.add(r['index'])
            pairs.append((e, r))
            break

    print('joined pairs: %d' % len(pairs))
    if not pairs:
        return 1

    worst = 0.0
    for e, r in pairs:
        worst = max(worst, math.dist(e['pos'], r['pos']))
    print('worst position disagreement: %.4f' % worst)

    matched = [p for p in pairs if p[0]['rot']]
    if matched:
        print('\nengine rotation vs record (f0,f15,f16,f17)  [the comparison that settles it]')
        for e, r in matched[:10]:
            print('  eng=(%8.4f,%8.4f,%8.4f,%8.4f)  rec=(%8.4f,%8.4f,%8.4f,%8.4f)  |rec|=%.4f'
                  % (e['rot'][0], e['rot'][1], e['rot'][2], e['rot'][3],
                     r['rot'][0], r['rot'][1], r['rot'][2], r['rot'][3],
                     math.sqrt(sum(v * v for v in r['rot']))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
