#!/usr/bin/env python3
"""
Shader-chain candidates: one flag in, out or swapped (FINDINGS.txt §47).

A shader_library name is `<technique>:<flag>:<flag>:...` with the flags
alphabetically sorted (§41).  So from the chains we hold plus the 1,335 the
harvest prints, the whole neighbourhood is:

    insert one vocabulary flag in its sorted position
    drop one flag
    swap one flag for another vocabulary flag (re-sorting)

The names must stay sorted to be legal, which keeps the space small.

    python3 tools/make_chain_candidates.py [--out FILE] [--limit N]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
HARVEST = HC / "work" / "harvest" / "chains.txt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "chains" / "cands.txt"))
    ap.add_argument("--limit", type=int, default=60_000_000)
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    chains = set()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n and r.get("type") in ("shader_library", "shader") and ":" in n:
            chains.add(n.lower())
    if HARVEST.exists():
        for line in HARVEST.read_text(errors="replace").splitlines():
            c = line.strip().lower()
            if c.count(":") >= 2 and re.fullmatch(r"[a-z0-9_:]+", c):
                chains.add(c)
    chains = sorted(chains)

    techs = collections.Counter()
    flags = collections.Counter()
    for c in chains:
        parts = c.split(":")
        techs[parts[0]] += 1
        for p in parts[1:]:
            flags[p] += 1
    fl = sorted(flags)
    print(f"chains {len(chains)}  techniques {len(techs)}  flags {len(fl)}")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w") as fh:
        def emit(parts):
            nonlocal n
            if n >= args.limit:
                return
            fh.write(":".join(parts) + "\n")
            n += 1

        # pairs of flags that co-occur in some chain we hold: a legal two-flag step
        pair_seen = collections.Counter()
        for c in chains:
            fs0 = c.split(":")[1:]
            for i in range(len(fs0)):
                for j in range(i + 1, len(fs0)):
                    pair_seen[(fs0[i], fs0[j])] += 1
        top_pairs = [p2 for p2, _ in pair_seen.most_common(4000)]
        techs_all = sorted(techs)

        for c in chains:
            parts = c.split(":")
            tech, fs = parts[0], parts[1:]
            for a, b in top_pairs:                             # two-flag insert
                if a in fs or b in fs:
                    continue
                i = 0
                while i < len(fs) and fs[i] < a:
                    i += 1
                j = i
                while j < len(fs) and fs[j] < b:
                    j += 1
                new = fs[:i] + [a] + fs[i:j] + [b] + fs[j:]
                emit([tech] + sorted(new))
            if len(fs) > 3:                                    # drop two
                for i in range(len(fs) - 1):
                    emit([tech] + fs[:i] + fs[i + 2:])
            for tech2 in techs_all[:40]:                        # technique swap
                if tech2 != tech:
                    emit([tech2] + fs)
            for f in fl:                                   # insert (sorted)
                if f in fs:
                    continue
                i = 0
                while i < len(fs) and fs[i] < f:
                    i += 1
                emit([tech] + fs[:i] + [f] + fs[i:])
            for i in range(len(fs)):                       # drop
                emit([tech] + fs[:i] + fs[i + 1:])
                for f in fl:                               # swap (re-sort)
                    if f == fs[i]:
                        continue
                    new = fs[:i] + fs[i + 1:] + [f]
                    if fs[i] < f:
                        new = sorted(new)
                    emit([tech] + sorted(new))
    print(f"candidates written {n:,} -> {out}")


if __name__ == "__main__":
    main()
