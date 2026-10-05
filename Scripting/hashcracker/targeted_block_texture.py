#!/usr/bin/env python3
"""
Derive texture/material candidates from the block (unit) vocabulary.

Resolved names show the two namespaces share their leaves:

    unit      blocks/d01_caves/rocks/caverock_rock_01
    texture   blocks/d01_caves/caverock_rock_01_diff
    texture   blocks/d01_lava/lavarock_floor_01_norm
    material  props/d01_common/blackbox_2c_2c
    material  blocks/d01_caves/caverock_set

i.e. textures and materials are `<root>/<env>/<leaf><suffix>` while units are
`<root>/<env>/<cat>/<leaf>`.  So every unit leaf that is recovered immediately
produces texture/material candidates - which is why units are the lever for the
rest of the catalogue.

    python3 targeted_block_texture.py [--out FILE]
"""
import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOGUE = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"

SUFFIX = ["", "_diff", "_norm", "_spec", "_specgloss", "_glowmask", "_nrmgloss",
          "_diffgloss", "_mask", "_alpha", "_emissive", "_high", "_illum",
          "_nrm", "_glow", "_overlay", "_detail", "_var01", "_var02", "_var03",
          "_var01_diff", "_var02_diff", "_diff_var02", "_norm_var02",
          "_diff_01", "_diff_02"]
STEMS = ("_diff", "_norm", "_spec", "_specgloss", "_glowmask", "_nrmgloss",
         "_diffgloss", "_mask", "_high", "_illum", "_nrm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/blocks_c.txt")
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text())
    rows = list(csv.DictReader(CATALOGUE.open()))
    type_of = {}
    for r in rows:
        type_of.setdefault(r["name_hash"], r["type"])

    known = set(ov.values())

    def unstem(leaf):
        for s in sorted(STEMS, key=len, reverse=True):
            if leaf.endswith(s) and len(leaf) > len(s):
                return leaf[: -len(s)]
        return leaf

    leaves, dirs, tokens = collections.Counter(), collections.Counter(), collections.Counter()
    for h, n in ov.items():
        root = n.split("/", 1)[0]
        if root not in ("blocks", "props", "effects", "gameobjects", "characters",
                        "menu", "textures", "decals"):
            continue
        leaf = unstem(n.rsplit("/", 1)[-1])
        leaves[leaf] += 1
        segs = n.split("/")
        if len(segs) >= 3:                     # <root>/<env> namespace
            dirs["/".join(segs[:2])] += 1
        for t in leaf.split("_"):
            if t and not t.isdigit():
                tokens[t] += 1

    dirs = [d for d, _ in dirs.most_common(120)]
    leaves = [l for l, _ in leaves.most_common(4000)]
    toks = [t for t, _ in tokens.most_common(400)]

    out = set()
    for d in dirs:
        for leaf in leaves:
            for suf in SUFFIX:
                out.add(f"{d}/{leaf}{suf}")
        # style_part_NN shapes built from the token vocabulary
        for a in toks[:150]:
            for b in toks[:150]:
                out.add(f"{d}/{a}_{b}")
                for i in range(1, 5):
                    out.add(f"{d}/{a}_{b}_{i:02d}")
    new = sorted(n for n in out if n not in known)
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"dirs {len(dirs)}  leaves {len(leaves)}  tokens {len(toks)}")
    print(f"candidates {len(new)} -> {args.out}")


if __name__ == "__main__":
    main()
