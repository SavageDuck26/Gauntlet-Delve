#!/usr/bin/env python3
"""
Shader-chain combination hunt (FINDINGS.txt section 55).

A shader_library name is

    <technique>[:<flag>]*          flags ':'-separated and ALPHABETICALLY SORTED

e.g. `base:blend_normal_world_positive_z:diffuse_map:double_sided:skinned_3weights`
- where the underscores live *inside* a flag name, which is why the flag
vocabulary is small and global while the chains are long.

The existing chain sweep walks the one-flag neighbourhood (insert/drop/swap; +69)
and two-flag variants (+3).  Because the flags are *sorted*, the rest of the
space is **combinations**, not permutations: C(n,k) instead of n^k, which puts
three- and four-flag chains within reach of a plain Python murmur pass - no GPU
needed, so it can run while a sweep holds the lock.

    python3 tools/chain_combo_hunt.py [--max-flags 4] [--matches matches.tsv]
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
sys.path.insert(0, str(DIG))
from hunt_unit_textures import murmur                            # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-flags", type=int, default=4)
    ap.add_argument("--matches", default=str(HC / "matches.tsv"))
    args = ap.parse_args()

    ov = json.loads((DIG / "resource_name_overlay.json").read_text())
    res = set()
    unres = set()
    for r in csv.DictReader((DIG / "bundle_manifest" /
                             "04_bundle_resources.csv").open(
                                 newline="", encoding="utf-8", errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            res.add(n.lower())
        else:
            unres.add(r["name_hash"].lower())

    techs, flags = set(), set()
    for n in res:
        if ":" in n:
            parts = n.split(":")
            techs.add(parts[0])
            flags.update(parts[1:])
    flagl = sorted(flags)
    print(f"techniques {len(techs)}  flags {len(flagl)}  unresolved {len(unres)}",
          flush=True)
    print(f"  flag vocabulary: {flagl}", flush=True)

    found, tested, t0 = [], 0, time.time()
    for t in sorted(techs):
        for k in range(1, args.max_flags + 1):
            for combo in itertools.combinations(flagl, k):
                c = t + ":" + ":".join(combo)
                if c in res:
                    continue
                tested += 1
                if f"{murmur(c):016x}" in unres:
                    found.append(c)
                    print(f"  HIT {c}", flush=True)
    dt = time.time() - t0
    print(f"tested {tested:,} in {dt:.1f}s ({tested / max(dt, 1e-9) / 1e6:.2f} M/s)  "
          f"MATCHES {len(found)}")
    if found:
        with open(args.matches, "a") as fh:
            for c in found:
                fh.write(f"{murmur(c):016x}\t{c}\n")
        print(f"appended {len(found)} to {args.matches}")


if __name__ == "__main__":
    main()
