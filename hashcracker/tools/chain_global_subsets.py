#!/usr/bin/env python3
"""Chain subsets over the GLOBAL flag vocabulary (FINDINGS 69).

The per-technique subset sweep came back empty-handed for a reason worth recording: a
technique's *own* flag vocabulary is tiny (`base` has 31 flags, `character` and the filters
7).  But the chains this session found mix vocabularies - `character:double_sided:enemy:
one_bit_alpha:skinned_3weights` uses filters-in-character style flags, and
`base:instanced:diffuse_map` sits in `base`.  So the missing chains are most likely
`<technique>:<sorted subset of the *global* flag vocabulary>`.

    python3 tools/chain_global_subsets.py --tech base --k 4 [--out FILE]

Writes `<tech>:<flag>:...` for every sorted subset, for `tools/chain_walk.sh`-style feeding
into the engine (chunk it by technique and k - C(110,5) is 124 M, which is a 1.2 GB file).
"""
import argparse
import collections
import csv
import itertools
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
CATALOGUE = HC.parent / "Data" / "bundle_manifest" / "04_bundle_resources.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tech", required=True)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace")))
    chains = [r["name"] for r in rows if r["name"] and r["type"] == "shader_library"
              and ":" in r["name"]]
    flags = sorted({f for c in chains for f in c.split(":")})
    n = 0
    with open(args.out, "w") as fh:
        for combo in itertools.combinations(flags, args.k):
            fh.write(args.tech + ":" + ":".join(combo) + "\n")
            n += 1
    print(f"{args.tech} k={args.k}: {n:,} subsets of {len(flags)} global flags -> {args.out}")


if __name__ == "__main__":
    main()
