#!/usr/bin/env python3
"""
Effect-texture candidates from the resolved effect-texture vocabulary (§48.2).

The reference pairs show what `effects/textures/*` names look like - generic
effect textures, not referrer-derived:

    effects/textures/alpha_liquid_01        effects/textures/additive_blob
    effects/textures/alpha_smoke_cloud_01   effects/textures/additive_ember
    effects/textures/alpha_impact_splash_01 effects/textures/additive_candle_flame

i.e. `<kind>_<descriptor...>[_<n>][_norm|_diff]` with a small kind set
(`alpha`, `additive`, ...) and a descriptor vocabulary mined from the 1,103
resolved ones.  Since 398 of the unnamed textures are drawn by `effects/*`
particles, they are almost certainly further members of that family.

    python3 tools/make_fx_texture_vocab.py [--out FILE]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

NUM = ["", "_01", "_02", "_03", "_04", "_05", "_1", "_2", "_3", "_4", "_5"]
SUF = ["", "_norm", "_diff", "_normal"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "fx" / "vocab.txt"))
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    kinds = collections.Counter()
    desc = collections.Counter()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if not n or not n.startswith("effects/textures/"):
            continue
        leaf = n.rsplit("/", 1)[-1]
        toks = leaf.split("_")
        kinds[toks[0]] += 1
        for t in toks[1:]:
            if not t.isdigit():
                desc[t] += 1
    k = [x for x, _ in kinds.most_common(12)]
    d = [x for x, _ in desc.most_common(400)]
    print(f"kinds {len(kinds)} -> {k}")
    print(f"descriptor tokens {len(desc)} (top: {d[:12]})")

    vocab = set()
    for kk in k:
        for t in d:
            for n in NUM:
                for s in SUF:
                    vocab.add(f"{kk}_{t}{n}{s}")
        for a in d:
            for b in d[:60]:
                for n in ("", "_01", "_02"):
                    vocab.add(f"{kk}_{a}_{b}{n}")
    vocab = sorted(vocab)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(vocab) + "\n")
    print(f"candidates {len(vocab):,} -> {out}")


if __name__ == "__main__":
    main()
