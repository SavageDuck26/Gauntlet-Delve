#!/usr/bin/env python3
"""Join unknown units to named ones by the material/mesh names inside their bodies.

Unit bodies carry the modeller's names as plain strings - `m_caverock_stalagmites_01`,
`lambert1`, mesh node names - which my earlier name scans discarded as noise.  Two units
sharing those strings are the same asset family (a rock and its variant, a prop and its
broken copy), so: index every string in every *named* unit, then for each *unknown* unit
build candidates from the names of the units it shares strings with, plus the usual
variant suffixes.
"""
import csv
import collections
import pathlib
import re
import sys

sys.path.insert(0, '/home/<user>/Documents/Coding/Gauntlet-Reverse-Engineering/Scripting/GauntletGameDigging')
from hunt_unit_textures import murmur                                   # noqa: E402

E = pathlib.Path.home() / 'Documents/Coding/Gauntlet-Export'
STR = re.compile(rb'[A-Za-z_][A-Za-z0-9_]{3,60}')
VARIANT = ['', '_01', '_02', '_03', '_1', '_2', '_a', '_b', '_c', '_var01', '_var02',
           '_damaged', '_destroyed', '_broken', '_debris', '_fractured', '_chunk',
           '_pieces', '_piece', '_lod', '_lod1', '_lod2', '_low', '_hi', '_open',
           '_closed', '_alt', '_old', '_new', '_no', '_yes', '_static', '_dynamic']


def body_strings(p):
    try:
        raw = p.read_bytes()
    except OSError:
        return set()
    out = set()
    for m in STR.finditer(raw):
        s = m.group().decode('ascii', 'ignore')
        if s.startswith('m_') or (s.islower() and '_' in s):
            out.add(s)
    return out


def main():
    rows = list(csv.DictReader((E / 'index.tsv').open(newline=''), delimiter='\t'))
    unres = {r['name_hash'].lower(): r for r in rows if r['status'] == 'unresolved'}
    named_units = sorted({r['name'] for r in rows
                          if r['status'] == 'named' and r['type'] == 'unit'})
    print(f"named units: {len(named_units):,}", flush=True)

    index = collections.defaultdict(set)
    for i, n in enumerate(named_units, 1):
        p = E / 'named' / (n + '.unit')
        for s in body_strings(p):
            index[s].add(n)
        if i % 300 == 0:
            print(f"  indexed {i:,}/{len(named_units):,}  strings {len(index):,}",
                  flush=True)

    unknown = sorted(p for p in (E / 'unresolved/unit').glob('*.unit'))
    print(f"\nunknown units: {len(unknown)}", flush=True)
    total = 0
    for p in unknown:
        strings = body_strings(p)
        fam = collections.Counter()
        for s in strings:
            if s == 'lambert1':
                continue
            for n in index.get(s, ()):
                fam[n] += 1
        cands = set()
        for n in fam:
            for v in VARIANT:
                cands.add(n + v)
            d = '/'.join(n.split('/')[:-1])
            for s in strings:
                cands.add(f"{d}/{s}")
                cands.add(f"{d}/{s[2:]}" if s.startswith('m_') else f"{d}/{s}")
        total += len(cands)
        hits = [c for c in cands if f"{murmur(c):016x}" == p.stem]
        top = ', '.join(n for n, _ in fam.most_common(3))
        print(f"\n{p.stem}  ({len(strings)} strings, {len(fam)} known relatives)")
        print(f"   relatives: {top}")
        if hits:
            print(f"   *** MATCH: {hits} ***")
    print(f"\ntotal candidates tested: {total:,}", flush=True)


if __name__ == '__main__':
    main()
