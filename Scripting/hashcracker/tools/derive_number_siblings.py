#!/usr/bin/env python3
"""
Number siblings of every name we hold - `arena01` -> `arena02`, `hit_offset1` ->
`hit_offset2`, `__02_s_mixed` -> `__01_s_mixed` / `__03_s_mixed`.

Whenever a name carries an index, the neighbouring indices almost always ship
too (animation hit offsets, arena/colosseum slots, quilt variant numbers,
`floor02` rooms, `spider_02_1` pieces, `skinned_3weights` shader chains).

`hashcracker mutate` handles the *whole-token* case (`__02_`), because its
numeric step replaces one token with a number - but it cannot rewrite the digits
*inside* a token, which is where most of the indices live (`hit_offset1`,
`arena01`, `floor02`, `skinned_3weights`).  This tool covers both, cheaply
(~300k candidates, CPU, ~1 s), so it can run as an always-on phase.

    python3 tools/derive_number_siblings.py [--out data/vocab/derived_num.txt]

Digits are taken from the *leaf* only: the `d01_<env>` module prefix is fixed,
so varying it would only generate noise.
"""
import argparse
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

RUN = re.compile(r"\d+")
MAX_N = 100         # indices 0..99, both unpadded and padded to the run's width


def known_names() -> set:
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return {n for n in names if n}


def siblings(name: str) -> set:
    """Every single-index variant of `name` (all runs replaced one at a time)."""
    directory, _, leaf = name.rpartition("/")
    out = set()
    for m in RUN.finditer(leaf):
        width = len(m.group())
        for v in range(MAX_N):
            for rep in {str(v), str(v).zfill(width)}:
                out.add((directory + "/" if directory else "")
                        + leaf[:m.start()] + rep + leaf[m.end():])
    out.discard(name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=str(HC / "data" / "vocab" / "derived_num.txt"))
    args = ap.parse_args()

    seeds = [n for n in sorted(known_names()) if RUN.search(n.rpartition("/")[2])]
    cand: set = set()
    for n in seeds:
        cand |= siblings(n)
    out = pathlib.Path(args.out)
    out.write_text("\n".join(sorted(cand)) + "\n")
    print(f"seeds       : {len(seeds)}  (resolved names with an index)")
    print(f"candidates  : {len(cand)}  -> {out}")


if __name__ == "__main__":
    main()
