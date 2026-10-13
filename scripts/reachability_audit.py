#!/usr/bin/env python3
"""
Reachability audit: which of the unresolved resources are referenced by a *named* one?

A name can almost always be *guessed* when something known points at the resource -
a material names its textures, a unit names its material, a level names its props.
When nothing named references it, and no text anywhere spells it, the name is only
reachable by blind enumeration, which is why so many sweeps end at `+0`.

For every resource in the catalogue this walks the bodies of all bundles, collects
the 8-byte-aligned values that are catalogue hashes (Stingray references resources by
hash), and records who references whom.  Then, per unresolved hash:

    named_refs      how many NAMED resources reference it  (>=1 = nameable by inference)
    unres_refs      how many unresolved resources reference it (its own cluster)

    python3 reachability_audit.py            # -> bundle_manifest/09_reachability.tsv
    python3 reachability_audit.py --stdout   # summary only

Costs one pass over the bundles (~2-4 minutes, numpy, read-only).
"""
import argparse
import collections
import csv
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE.parent / "Data" / "bundle_manifest"
sys.path.insert(0, str(HERE))
import list_game_bundles as L                                          # noqa: E402
from hunt_build_diff import entries_of                                 # noqa: E402


def load_catalogue():
    ov = json.loads((HERE.parent / "Data" / "resource_name_overlay.json").read_text())
    rows = list(csv.DictReader((MANIFEST / '04_bundle_resources.csv').open(
        newline='', encoding='utf-8', errors='replace')))
    info = {}
    for r in rows:
        h = int(r['name_hash'], 16)
        n = r.get('name') or ov.get(r['name_hash'].lower())
        if h not in info or n:
            info[h] = {'name': n, 'type': r['type'], 'pkg': r['package_path'],
                       'bundle': r['bundle'], 'size': int(r['body_size'])}
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stdout', action='store_true')
    args = ap.parse_args()

    import numpy as np
    info = load_catalogue()
    cat = np.array(sorted(info), dtype=np.uint64)
    print(f'catalogue hashes: {len(cat):,}  '
          f'(named {sum(1 for v in info.values() if v["name"]):,})', flush=True)

    named_of = {h: v['name'] for h, v in info.items() if v['name']}
    edges = collections.Counter()          # referenced hash -> named references
    edges_unres = collections.Counter()     # referenced hash -> unresolved references
    sample = {}
    root = L.find_install_root()
    bundles = sorted({v['bundle'] for v in info.values()})
    for i, bid in enumerate(bundles, 1):
        p = root / 'contents' / bid
        if not p.exists():
            continue
        for _idx, eh, _t, body in entries_of(p):
            if eh is None or not body:
                continue
            eh = int(eh)
            n = len(body) // 8
            if n == 0:
                continue
            arr = np.frombuffer(body[:n * 8], dtype='<u8')
            hits = arr[np.isin(arr, cat)]
            if hits.size == 0:
                continue
            referrer = named_of.get(eh)
            for ref in {int(x) for x in hits}:
                if ref == eh:
                    continue
                if referrer:
                    edges[ref] += 1
                    sample.setdefault(ref, referrer)
                else:
                    edges_unres[ref] += 1
        print(f'  [{i}/{len(bundles)}] {bid}: named refs so far {len(edges):,}', flush=True)

    unres = [h for h, v in info.items() if not v['name']]
    reach = [h for h in unres if edges[h]]
    unreach = [h for h in unres if not edges[h]]
    print(f'\nunresolved: {len(unres):,}   referenced by a named resource: {len(reach):,}'
          f'   no named reference at all: {len(unreach):,}')

    def bucket(h):
        return info[h]['type'] or '?'

    print('\n=== by type: reachable / unreachable ===')
    for t in sorted({bucket(h) for h in unres}):
        r = sum(1 for h in reach if bucket(h) == t)
        u = sum(1 for h in unreach if bucket(h) == t)
        print(f'  {t:22s} reachable {r:>5,}   unreachable {u:>5,}')

    if not args.stdout:
        out = MANIFEST / '09_reachability.tsv'
        with out.open('w', newline='') as fh:
            w = csv.writer(fh, delimiter='\t')
            w.writerow(['hash', 'type', 'package', 'bundle', 'size',
                        'named_refs', 'unres_refs', 'sample_named_referrer'])
            for h in sorted(unres, key=lambda h: (-edges[h], bucket(h))):
                v = info[h]
                w.writerow([f'{h:016x}', v['type'], v['pkg'], v['bundle'], v['size'],
                            edges[h], edges_unres[h], sample.get(h, '')])
        print(f'\nwrote {out} ({len(unres):,} rows)', flush=True)

        # The master list: every unresolved resource with an explicit status, so the
        # sweeps keep trying them but we know which ones no inference can reach.
        master = MANIFEST / '10_unresolved_master.tsv'
        with master.open('w', newline='') as fh:
            w = csv.writer(fh, delimiter='\t')
            w.writerow(['status', 'hash', 'type', 'package', 'bundle', 'size',
                        'named_refs', 'unres_refs', 'reason', 'sample_named_referrer'])
            def key(h):
                return (0 if not edges[h] else 1, bucket(h), -info[h]['size'])
            for h in sorted(unres, key=key):
                v = info[h]
                status = 'reachable' if edges[h] else 'UNREACHABLE'
                reason = ('no named referrer' if edges_unres[h] else
                          'nothing references it')
                w.writerow([status, f'{h:016x}', v['type'], v['pkg'], v['bundle'],
                            v['size'], edges[h], edges_unres[h], reason,
                            sample.get(h, '')])
        un = sum(1 for h in unres if not edges[h])
        print(f'wrote {master} ({len(unres):,} rows, {un:,} marked UNREACHABLE)', flush=True)
        print('  UNREACHABLE = no NAMED resource references it, so its name cannot be')
        print('  derived by inference.  The engine keeps guessing them anyway: they stay')
        print('  in the sweep targets (data/vocab/unresolved_targets.txt is built from')
        print('  the catalogue, not from this file).')


if __name__ == '__main__':
    t0 = time.time()
    main()
    print(f'done in {time.time() - t0:.0f}s')
