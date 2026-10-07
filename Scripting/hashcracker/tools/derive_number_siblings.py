#!/usr/bin/env python3
"""
Number siblings of every name we hold.

Two passes, both over everything we have:

  * REPLACE - names that already carry an index get their neighbours tried:
    `arena01` -> `arena02`, `hit_offset1` -> `hit_offset2`, `__02_s_mixed` ->
    `__01_`/`__03_`, `skinned_3weights` -> `2weights`, `spider_02_1` ->
    `spider_02_2`.
  * APPEND  - names with *no* index get one: `decals/moss` -> `decals/moss_01`
    ..`decals/moss_10` and `caves_arena` -> `caves_arena01`..`arena10`
    (the concatenated form is how `caves_arena01` is spelled).

`hashcracker mutate` has a numeric step, but it replaces a whole numeric
*token* (`__02_` -> `__03_`); it cannot rewrite digits *inside* a token
(`hit_offset1` -> `hit_offset2`), which is where most indices live.

The index range is a knob (`--range`, default `1-10`) and each value is emitted
unpadded, two-digit padded and padded to the original run's width, so both
spellings are covered.

    python3 tools/derive_number_siblings.py [--range 1-10] [--out FILE]

Digits are taken from the *leaf* only: the `d01_<env>` module prefix is fixed,
so varying it would only generate noise.
"""
import argparse
import csv
import itertools
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

RUN = re.compile(r"\d+")


def parse_range(spec: str) -> list:
    lo, _, hi = spec.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def known_names() -> set:
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return {n for n in names if n}


def reps(value: int, width: int) -> set:
    """All spellings of one index: unpadded, 2-digit, and the run's own width."""
    return {str(value), f"{value:02d}", str(value).zfill(width)}


def replace_variants(name: str, values: list) -> set:
    """Every single-index variant of an already-indexed name."""
    directory, _, leaf = name.rpartition("/")
    out = set()
    for m in RUN.finditer(leaf):
        for v in values:
            for rep in reps(v, len(m.group())):
                out.add((directory + "/" if directory else "")
                        + leaf[:m.start()] + rep + leaf[m.end():])
    out.discard(name)
    return out


def append_variants(name: str, values: list) -> set:
    """`<leaf>_<n>` and `<leaf><n>` for a name that has no index yet."""
    directory, _, leaf = name.rpartition("/")
    pre = directory + "/" if directory else ""
    out = set()
    for v in values:
        for rep in reps(v, 2):
            out.add(pre + leaf + "_" + rep)
            out.add(pre + leaf + rep)
    return out


def pair_variants(name: str, values: list) -> set:
    """
    Replace *two* index runs at the same time (`spider_02_1` -> `spider_03_2`).

    Only used with `--pairs`: it is ~10x the work of the single-run pass, and on
    the names we hold it has found nothing, so it is opt-in rather than default.
    """
    directory, _, leaf = name.rpartition("/")
    pre = directory + "/" if directory else ""
    runs = list(RUN.finditer(leaf))
    out = set()
    for m1, m2 in itertools.combinations(runs, 2):
        for v1 in values:
            for r1 in reps(v1, len(m1.group())):
                for v2 in values:
                    for r2 in reps(v2, len(m2.group())):
                        out.add(pre + leaf[:m1.start()] + r1 + leaf[m1.end():m2.start()]
                                + r2 + leaf[m2.end():])
    out.discard(name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=str(HC / "data" / "vocab" / "derived_num.txt"))
    ap.add_argument("--range", default="1-10",
                    help="index range to try, e.g. 1-10 (default) or 0-99")
    ap.add_argument("--pairs", action="store_true",
                    help="also replace two index runs at once (~10x the work, "
                         "nothing found on the current catalogue)")
    args = ap.parse_args()

    values = parse_range(args.range)
    names = sorted(known_names())
    indexed = [n for n in names if RUN.search(n.rpartition("/")[2])]

    cand: set = set()
    for n in indexed:
        cand |= replace_variants(n, values)     # arena01 -> arena02
    for n in names:
        cand |= append_variants(n, values)      # every name: <leaf>_01 .. <leaf>10
    if args.pairs:
        for n in indexed:
            cand |= pair_variants(n, values)    # spider_02_1 -> spider_03_2
    out = pathlib.Path(args.out)
    out.write_text("\n".join(sorted(cand)) + "\n")
    print(f"range       : {args.range}  ({len(values)} values)   pairs {args.pairs}")
    print(f"names       : {len(names)}  ({len(indexed)} of them indexed)")
    print(f"candidates  : {len(cand)}  -> {out}")


if __name__ == "__main__":
    main()
