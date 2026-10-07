#!/usr/bin/env python3
"""
Reference graph between *resolved* resources (FINDINGS.txt §49).

`hunt_texture_refs.py` records who references each *unnamed* resource.  This
records the same edges between resources that all have names - decompress each
bundle once and match every 8-byte window of every named body against the named
resources of the same bundle.

That graph is a fingerprint: a resource's set of referrers is nearly unique, so
for an unnamed resource we can find its nearest *resolved* twin by referrer-set
similarity and then treat the twin's name as the thing to edit (the "derived
names similar to others" case).

    python3 hunt_ref_graph.py [--limit N] [--out FILE]
"""
import argparse
import collections
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import list_game_bundles as L                                      # noqa: E402
from hunt_texture_refs import load, windows                        # noqa: E402

DEPOT = REPO / "Gauntlet-PreSlayer-2015-08-11" / "depot_258972" / "contents"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(HERE.parent / "hashcracker" / "work" /
                                         "ref_graph.json"))
    args = ap.parse_args()

    rows = load()
    per_bundle = collections.defaultdict(dict)
    for r in rows:
        if r.get("bundle"):
            per_bundle[r["bundle"]][int(r["name_hash"], 16)] = r["_name"]

    bundles = sorted(per_bundle)
    if args.limit:
        bundles = bundles[:args.limit]
    graph = collections.defaultdict(set)
    for b in bundles:
        path = DEPOT / b
        if not path.exists():
            continue
        names = per_bundle[b]
        named = {h: n for h, n in names.items() if n}
        if not named:
            continue
        _sig, _uz, data = L.decompress_bundle(path.read_bytes())
        _count, toc = L.parse_toc(data)
        entries, _end, _ok = L.parse_resources(data, toc)
        want = np.array(sorted(named), dtype=np.uint64)
        n_edges = 0
        for e in entries:
            src = named.get(e.get("name_hash"))
            if not src:
                continue
            start = e["body_start"]
            body = data[start:start + e.get("body_size", 0)]
            if len(body) < 8:
                continue
            hits = np.intersect1d(np.unique(windows(body)), want)
            for h in hits.tolist():
                dst = named[int(h)]
                if dst != src:
                    graph[src].add(dst)
                    n_edges += 1
        print(f"  {b}: {len(named)} named, {n_edges} edges")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({k: sorted(v) for k, v in graph.items()},
                              indent=1, sort_keys=True))
    print(f"referrers {len(graph):,}  -> {out}")


if __name__ == "__main__":
    main()
