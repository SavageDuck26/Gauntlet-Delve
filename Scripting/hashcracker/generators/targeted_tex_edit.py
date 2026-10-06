#!/usr/bin/env python3
"""
Edit-distance-1 texture leaves, scoped to the bundle that owns them.

Texture rows are concentrated in a handful of bundles (menu, the d01 module
bundles, all_effects), and within a bundle the leaves are near-neighbours:
`crypt_wall_4c_diff` implies `crypt_wall_4c_norm`, `crypt_wall_2c_diff`,
`cryptsmooth_wall_4c_diff`, ...  So for every resolved texture in a bundle emit
the token-level edits (replace / insert / delete / append) of its leaf into the
same directories, with the usual map suffixes.

    python3 targeted_tex_edit.py [--out FILE]
"""
import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
DIG = REPO / "Scripting/GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest/04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

SUFFIX = ["", "_diff", "_norm", "_spec", "_nrm", "_mask", "_glow", "_locked",
          "_high", "_illum", "_alpha", "_icon", "_01", "_02", "_var01"]
STEMS = ("_diffgloss", "_specgloss", "_nrmgloss", "_glowmask", "_diff", "_norm",
         "_spec", "_nrm", "_mask", "_alpha", "_high", "_illum", "_locked", "_icon")
EXTRA = """2c 4c 1c 8c wall floor ceiling pillar column border door blackbox rock
rocks stairs step floor_drain drain straight turn_left turn_right end left right
corner inner outer crypt cryptsmooth cryptbroken caverock cavestruct cavesmooth
lavastruct lavarock arcade swamp set high illum var01 var02 var03 01 02 03 04
button icon frame background glow hover disabled selected highlight plate
over pressed normal empty locked""".split()


def unstem(leaf):
    for s in sorted(STEMS, key=len, reverse=True):
        if leaf.endswith(s) and len(leaf) > len(s):
            return leaf[: -len(s)]
    return leaf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/texedit_c.txt")
    ap.add_argument("--max-dirs", type=int, default=4)
    ap.add_argument("--max-leaves", type=int, default=80)
    ap.add_argument("--tokens", type=int, default=220)
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text())
    rows = list(csv.DictReader(CATALOGUE.open()))
    known = set(ov.values())

    leaves_by_bundle = collections.defaultdict(set)
    dirs_by_bundle = collections.defaultdict(collections.Counter)
    tokens = collections.Counter()
    for r in rows:
        n = r["name"] or ov.get(r["name_hash"])
        if not n or r["type"] not in ("texture", "material"):
            continue
        leaf = unstem(n.rsplit("/", 1)[-1])
        leaves_by_bundle[r["bundle"]].add(leaf)
        segs = n.split("/")
        if len(segs) > 1:
            dirs_by_bundle[r["bundle"]]["/".join(segs[:-1])] += 1
        for t in leaf.split("_"):
            if t and not t.isdigit():
                tokens[t] += 1
    tok = [t for t, _ in tokens.most_common(args.tokens)] + EXTRA

    out = set()
    for bundle, leaves in leaves_by_bundle.items():
        dirs = [d for d, _ in dirs_by_bundle.get(bundle, {}).most_common(args.max_dirs)]
        if not dirs:
            continue
        for leaf in sorted(leaves)[: args.max_leaves]:
            tl = leaf.split("_")
            variants = set()
            for i in range(len(tl)):
                for t in tok[:60]:
                    variants.add("_".join(tl[:i] + [t] + tl[i + 1:]))
            for i in range(len(tl) + 1):
                for t in tok[:60]:
                    variants.add("_".join(tl[:i] + [t] + tl[i:]))
            for i in range(len(tl)):
                variants.add("_".join(tl[:i] + tl[i + 1:]))
            for v in variants:
                for d in dirs:
                    for s in SUFFIX:
                        out.add(f"{d}/{v}{s}")
    new = sorted(n for n in out if n not in known)
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"bundles {len(leaves_by_bundle)}  tokens {len(tok)}  candidates {len(new)}")


if __name__ == "__main__":
    main()
