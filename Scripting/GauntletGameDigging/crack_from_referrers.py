#!/usr/bin/env python3
"""Name an unknown from its referrers, by swapping one token of the referrer's name.

A texture's referrer is usually its owner (`equipment/elf/cape_s03`) or the screen that
draws it (`hud/spells`).  So the unknown is a neighbour of that name in token space:
swap one token of the referrer's name for another token its own directory uses, add or
remove a channel suffix, or shift a trailing number.  Much tighter than "every segment
under every directory", which was 63M candidates of mostly noise.
"""
import collections
import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, '/home/<user>/Documents/Coding/Gauntlet-Reverse-Engineering/Scripting/GauntletGameDigging')
from hunt_unit_textures import murmur                                   # noqa: E402

E = pathlib.Path.home() / 'Documents/Coding/Gauntlet-Export'
REFS = pathlib.Path('/tmp/hc/refs_texture.json')

CHANNELS = ['_diff', '_spec', '_norm', '_nrm', '_alpha', '_glow', '_mask', '_emissive',
            '_diffuse', '_normal', '_nm', '_ao', '_ca', '_color', '_icons', '_icon',
            '_diff_01', '_diffuse_map']
NUM = re.compile(r'^(.*?)(\d{1,2})$')


def main():
    refs = json.loads(REFS.read_text())
    rows = list(csv.DictReader((E / 'index.tsv').open(newline=''), delimiter='\t'))
    unres = {r['name_hash'].lower(): r for r in rows if r['status'] == 'unresolved'}
    named = {r['name'] for r in rows if r['status'] == 'named'}

    dir_tokens = collections.defaultdict(set)
    for n in named:
        d = '/'.join(n.split('/')[:-1])
        for t in re.split(r'[_/]', n.split('/')[-1]):
            if t and not t.isdigit():
                dir_tokens[d].add(t)

    cands = {}
    for h, referrers in refs.items():
        if h.lower() not in unres:
            continue
        for r in referrers:
            d = '/'.join(r.split('/')[:-1])
            last = r.split('/')[-1]
            base_stem = r
            cands.setdefault(base_stem, f"referrer {r}")
            for ch in CHANNELS:
                cands.setdefault(base_stem + ch, f"referrer+channel {r}")
            m = NUM.match(last)
            if m:
                head, num = m.group(1), int(m.group(2))
                for k in range(0, 41):
                    for fmt in (str(k), f"{k:02d}"):
                        cands.setdefault('/'.join([d, head + fmt]) if d else head + fmt,
                                         f"number {r}")
            parts = re.split(r'([_/])', r)
            for i, p in enumerate(parts):
                if p in ('_', '/'):
                    continue
                for t in dir_tokens.get(d, ()):
                    if t == p:
                        continue
                    new = '/'.join(parts[:i] + [t] + parts[i + 1:])
                    cands.setdefault(new, f"swap {p}->{t} in {r}")

    print(f"referrer-graph targets: {len([h for h in refs if h.lower() in unres]):,}")
    print(f"candidates: {len(cands):,}", flush=True)
    hits = []
    for c, why in cands.items():
        h = f"{murmur(c):016x}"
        if h in unres:
            hits.append((h, c, why, unres[h]))
    print(f"\nHITS: {len(hits)}")
    for h, c, why, r in sorted(hits, key=lambda x: x[1]):
        print(f"  {h}  {c:52s} ({why})")
        print(f"      {r['type']} {r['package']} {r['size']}B")


if __name__ == '__main__':
    main()
