#!/usr/bin/env python3
"""
Shader chains, scoped by body size (FINDINGS 60.14).

`generators/shader_chains.py` enumerates every sorted flag subset for every
technique, which is now a 3.85 GB candidate file - too big to be useful.  Two facts
make it enumerable again:

  * each technique has its own body-size band (`base` 68k-131k, `billboard` 25k-43k,
    `gui` 5k-7k, `filter` 3.5k-7.5k ...), so an unresolved shader's *size* says which
    technique it almost certainly is;
  * within `base` - the biggest family, 423 samples - mean size rises monotonically
    with the flag count (1:68.6k, 2:71.0k, 3:74.4k ... 9:131.4k), so the size also
    predicts how many flags the chain has.

So for every unresolved shader: take the technique whose size band contains it,
predict the flag count from that technique's own (count -> mean size) table, then
enumerate the sorted subsets of that length drawn from the flags that technique is
most often seen with.  Candidates are hashed in-process and any hit is written to
stdout as `hash<TAB>name`, ready to append to matches.tsv.

    python3 hunt_shader_subsets.py [--top 20] [--tolerance 0.15] [--write]
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hunt_unit_textures import murmur                                # noqa: E402

MANIFEST = HERE / 'bundle_manifest'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=20,
                    help='flags per technique to draw subsets from (default 20)')
    ap.add_argument('--tolerance', type=float, default=0.15,
                    help='allowed size error when matching a flag count')
    ap.add_argument('--write', action='store_true', help='append hits to matches.tsv')
    args = ap.parse_args()

    ov = json.loads((HERE / 'resource_name_overlay.json').read_text())
    rows = list(csv.DictReader((MANIFEST / '04_bundle_resources.csv').open(
        newline='', encoding='utf-8', errors='replace')))

    flags_of = collections.defaultdict(collections.Counter)
    size_of_k = collections.defaultdict(lambda: collections.defaultdict(list))
    bands = collections.defaultdict(list)
    unres = {}
    for r in rows:
        if r['type'] != 'shader_library':
            continue
        n = r.get('name') or ov.get(r['name_hash'].lower())
        size = int(r['body_size'])
        if n and ':' in n:
            tech, flags = n.split(':')[0], n.split(':')[1:]
            flags_of[tech].update(flags)
            size_of_k[tech][len(flags)].append(size)
            bands[tech].append(size)
        elif not n and size > 200:                      # skip 32-byte stub entries
            unres[int(r['name_hash'], 16)] = size

    print(f'techniques {len(bands)}   unresolved shaders {len(unres)}', flush=True)
    table = {}
    for tech, kk in size_of_k.items():
        table[tech] = {k: statistics.mean(v) for k, v in kk.items() if len(v) >= 2}
    for tech in sorted(table, key=lambda t: -len(bands[t]))[:6]:
        band = (min(bands[tech]), max(bands[tech]))
        print(f'  {tech:22s} band {band[0]:>7,}-{band[1]:>7,}  '
              f'{len(table[tech])} flag-count samples')

    tested = 0
    hits = []
    for h, size in sorted(unres.items(), key=lambda kv: kv[1]):
        for tech, band in bands.items():
            lo, hi = min(band), max(band)
            if not (lo * (1 - args.tolerance) <= size <= hi * (1 + args.tolerance)):
                continue
            tab = table.get(tech)
            if not tab:
                continue
            k = min(tab, key=lambda k: abs(tab[k] - size))
            if abs(tab[k] - size) / max(1, size) > args.tolerance:
                continue
            pool = [f for f, _c in flags_of[tech].most_common(args.top)]
            for kk in {k - 1, k, k + 1}:
                if kk < 0 or kk > len(pool):
                    continue
                for combo in itertools.combinations(sorted(pool), kk):
                    name = f'{tech}:' + ':'.join(combo)
                    tested += 1
                    if murmur(name) == h:
                        hits.append((h, name))
                        print(f'  HIT {h:016x}  {name}', flush=True)
    print(f'\ntested {tested:,} candidates -> {len(hits)} hits')
    if hits and args.write:
        with (HERE.parent / 'hashcracker' / 'matches.tsv').open('a') as fh:
            for h, name in hits:
                fh.write(f'{h:016x}\t{name}\n')
        print('appended to matches.tsv')


if __name__ == '__main__':
    main()
