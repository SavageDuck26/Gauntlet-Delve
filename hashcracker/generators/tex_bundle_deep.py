#!/usr/bin/env python3
"""
Per-bundle texture/material deepening.

`targeted_tex_edit.py` uses GLOBAL top-N leaves/dirs for every bundle, which
truncates exactly the vocabulary that matters.  This uses each bundle's OWN
texture vocabulary instead:

  * leaves  = every resolved texture/material leaf in that bundle (unstemmed)
  * dirs    = every texture directory used in that bundle
  * tokens  = tokens from those leaves + the global top-N as a fallback

then, per leaf, edit-distance-1 (replace / insert / delete) plus map-suffix
swaps, `_NN` and `_varNN` siblings - emitted into the bundle's own dirs.  The
work is capped PER BUNDLE so one huge bundle cannot starve the rest.

    python3 generators/tex_bundle_deep.py [--out FILE] [--per-bundle N]
"""
import argparse
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DIG = REPO / "Data"
CATALOGUE = DIG / "bundle_manifest/04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

SUF = ("", "_diff", "_norm", "_spec", "_mask", "_glow", "_high", "_illum",
       "_alpha", "_var01", "_var02", "_01", "_02")
STEMS = ("_diffgloss", "_specgloss", "_nrmgloss", "_glowmask", "_diff", "_norm",
         "_spec", "_nrm", "_mask", "_alpha", "_high", "_illum", "_locked", "_icon")


def unstem(leaf):
    for s in sorted(STEMS, key=len, reverse=True):
        if leaf.endswith(s) and len(leaf) > len(s):
            return leaf[: -len(s)]
    return leaf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/texbundle_c.txt")
    ap.add_argument("--per-bundle", type=int, default=250_000)
    ap.add_argument("--tokens", type=int, default=120)
    args = ap.parse_args()

    known = set(json.loads(OVERLAY.read_text()).values())
    rows = list(csv.DictReader(CATALOGUE.open()))

    leaves_by_bundle = collections.defaultdict(set)
    dirs_by_bundle = collections.defaultdict(collections.Counter)
    glob_tokens = collections.Counter()
    for r in rows:
        n = r["name"]
        if not n or r["type"] not in ("texture", "material"):
            continue
        leaf = unstem(n.rsplit("/", 1)[-1])
        leaves_by_bundle[r["bundle"]].add(leaf)
        segs = n.split("/")
        if len(segs) > 1:
            dirs_by_bundle[r["bundle"]]["/".join(segs[:-1])] += 1
        for t in leaf.split("_"):
            if t and not t.isdigit():
                glob_tokens[t] += 1
    glob = [t for t, _ in glob_tokens.most_common(args.tokens)]

    out = set()
    for bundle, leaves in leaves_by_bundle.items():
        dirs = [d for d, _ in dirs_by_bundle[bundle].most_common(8)]
        if not dirs:
            continue
        toks = collections.Counter()
        for leaf in leaves:
            toks.update(t for t in leaf.split("_") if t and not t.isdigit())
        toks.update(glob)
        tok = [t for t, _ in toks.most_common(args.tokens)]
        made = 0
        for leaf in sorted(leaves):
            tl = leaf.split("_")
            variants = set()
            for i in range(len(tl)):
                for t in tok:
                    variants.add("_".join(tl[:i] + [t] + tl[i + 1:]))
            for i in range(len(tl) + 1):
                for t in tok:
                    variants.add("_".join(tl[:i] + [t] + tl[i:]))
            for i in range(len(tl)):
                variants.add("_".join(tl[:i] + tl[i + 1:]))
            m = re.search(r"_(\d{1,2})$", leaf)
            if m:
                stem = leaf[: m.start()]
                for i in range(1, 13):
                    variants.add(f"{stem}_{i:02d}")
            for v in variants:
                for d in dirs:
                    for s in SUF:
                        out.add(f"{d}/{v}{s}")
                        made += 1
                if made > args.per_bundle:
                    break
            if made > args.per_bundle:
                break
    new = sorted(n for n in out if n not in known)
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"bundles {len(leaves_by_bundle)}  candidates {len(new)} -> {args.out}")


if __name__ == "__main__":
    main()
