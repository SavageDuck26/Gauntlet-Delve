#!/usr/bin/env python3
"""
Bundle-scoped candidate generation.

Every unresolved resource already tells us a lot about itself: which *bundle*
it lives in.  A bundle (e.g. `modules/d01_crypt/resources`) only contains
resources from a handful of namespaces, so the directories and leaf tokens seen
among that bundle's *resolved* rows are a strong prior for its unresolved rows.

For each bundle we therefore cross

    (directories used by resolved rows of the same type in this bundle)
  x (leaf tokens/leaves resolved anywhere of that type)
  x (map/name suffixes)

and emit `<dir>/<leaf><suffix>`.  This is the bundle-level analogue of the
animation unit-directory trick.

    python3 bundle_scoped_cands.py [--out FILE] [--types texture,material]
"""
import argparse
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DIG = REPO / "Scripting/GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest/04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

SUFFIX = ["", "_diff", "_norm", "_spec", "_nrm", "_mask", "_alpha", "_glow",
          "_emissive", "_high", "_illum", "_locked", "_icon", "_01", "_02",
          "_var01", "_var02", "_add", "_o", "_bg"]
STEMS = ("_diffgloss", "_specgloss", "_nrmgloss", "_glowmask", "_diff", "_norm",
         "_spec", "_nrm", "_mask", "_alpha", "_high", "_illum", "_locked", "_icon")


def unstem(leaf):
    for s in sorted(STEMS, key=len, reverse=True):
        if leaf.endswith(s) and len(leaf) > len(s):
            return leaf[: -len(s)]
    return leaf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/scoped_c.txt")
    ap.add_argument("--types", default="texture,material,particles,animation,unit,level")
    ap.add_argument("--max-leaves", type=int, default=600)
    ap.add_argument("--max-dirs", type=int, default=10)
    ap.add_argument("--suffixes", type=int, default=8)
    args = ap.parse_args()
    types = {t.strip() for t in args.types.split(",")}

    ov = json.loads(OVERLAY.read_text())
    rows = list(csv.DictReader(CATALOGUE.open()))

    leaves = collections.Counter()
    dirs_by_bundle = collections.defaultdict(collections.Counter)
    for r in rows:
        n = r["name"] or ov.get(r["name_hash"])
        if not n or r["type"] not in types:
            continue
        leaves[unstem(n.rsplit("/", 1)[-1])] += 1
        segs = n.split("/")
        for k in (1, 2, 3):
            if len(segs) > k:
                dirs_by_bundle[(r["bundle"], r["type"])]["/".join(segs[:k])] += 1
    leaves = [l for l, _ in leaves.most_common(args.max_leaves)]

    out = set()
    for _key, dd in dirs_by_bundle.items():
        for d in [x for x, _ in dd.most_common(args.max_dirs)]:
            for l in leaves:
                for s in SUFFIX[: args.suffixes]:
                    out.add(f"{d}/{l}{s}")
    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"bundles with context {len(dirs_by_bundle)}  leaves {len(leaves)}")
    print(f"candidates {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
