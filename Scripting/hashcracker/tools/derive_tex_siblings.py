#!/usr/bin/env python3
"""
Map siblings of every unit, decal, prop and block we hold.

A unit / prop / block / decal ships its texture maps *next to itself*, named by
appending the map suffix:

    characters/boss_mummy/boss_mummy   -> ..._diff  ..._norm  ..._spec
    props/d01_crypt/commander_chair    -> ..._spec
    decals/crater_01                   -> decals/crater_01_diff
    blocks/d01_caves/caverock_rock_01  -> ..._norm

Catalogue evidence: of the 471 resolved names that end in a map suffix, 192 have
BOTH `_diff` and `_norm`, 80 more have `_diff` + `_spec`, 39 have all three -
siblings are the rule, not the exception.  (`_mat` / `_material` never appear on
the shipped names, so the map suffixes are the whole story.)

`hashcracker mutate` already appends suffixes, but only inside its heavy cycles
(it pays |seeds| x |tokens| for the token edits).  This is the cheap, always-on
version - ~90k candidates in well under a second - so it can fire after *every*
merge and try the siblings of the names we just recovered, in both directions
(unit -> its maps, and map -> its parent).

    python3 tools/derive_tex_siblings.py [--out data/vocab/derived_tex.txt]
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

# namespaces that keep their texture maps next to themselves
NAMESPACES = ("characters/", "decals/", "props/", "blocks/", "gameobjects/",
              "equipment/", "ability_units/", "effects/", "units/", "menu/",
              "gui/")
# fallback map suffixes when data/suffixes.txt is missing (`_nrm` is the
# Stingray spelling, `_norm` the common one)
MAP_SUF = ["_diff", "_diffuse", "_nrm", "_norm", "_normal", "_spec", "_specular",
           "_gloss", "_glossy", "_mask", "_glow", "_height", "_ao", "_emissive",
           "_opacity", "_color", "_col", "_bump", "_detail", "_lightmap",
           "_cavity", "_roughness", "_metalness", "_sss"]
# extras layered on top of the canonical list
MAP_EXTRA = ["_nrm", "_norm", "_diff", "_diffuse"]


def known_names() -> set:
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return {n for n in names if n}


def seed_namespaces(names: set, sufs: list) -> set:
    """
    First path components of the resolved names that carry a map suffix.

    Discovered from the data rather than hard-coded: anything that ships a map
    next to itself belongs in the seed set.  Beyond the obvious ones
    (`characters/`, `blocks/`, `props/`, `decals/`, ...) this picks up the small
    namespaces that a fixed list misses (`hud/`, `effects_ui/`) - validated by
    re-deriving the map names we already hold: 79% recall with a hard-coded
    list, ~100% with the discovered one.
    """
    ns = set(NAMESPACES)
    for n in names:
        if "/" in n and any(n.endswith(s) for s in sufs):
            ns.add(n.split("/", 1)[0] + "/")
    return ns


def seed_numbers(names: set, sufs: list) -> list:
    """
    The tokens the game inserts BETWEEN a stem and its map suffix.

    `_01_diff` (44 names), `_01_norm` (43), `_02_diff`/`_02_norm`, `_03_*`,
    `_01_spec` - the number is *inside* the pair, a shape append/strip/swap
    cannot reach (FINDINGS 60.17: the sweep over those three forms is 594 k
    candidates and returns 0, while this shape names two).  Read from the
    catalogue the same way the namespaces are; the fallback covers a cold start.
    """
    counts = collections.Counter()
    for n in names:
        leaf = n.split("/")[-1]
        for s in sufs:
            if leaf.endswith(s):
                m = re.search(r"[_]?([0-9]{1,3}[a-z]{0,2})$", leaf[: -len(s)])
                if m:
                    counts[m.group(1)] += 1
                break
    got = [k for k, c in counts.most_common() if c >= 2]
    for k in ("01", "02", "1", "2", "03", "3", "0", "04", "4"):
        if k not in got:
            got.append(k)
    return got[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=str(HC / "data" / "vocab" / "derived_tex.txt"))
    ap.add_argument("--suffixes", default=str(HC / "data" / "suffixes.txt"),
                    help="canonical suffix list (data/suffixes.txt)")
    args = ap.parse_args()

    sufs = list(MAP_SUF)
    sf = pathlib.Path(args.suffixes)
    if sf.exists():
        # the canonical list is the one `mutate` uses; union it in so this tool
        # is never narrower than the mutate phase
        sufs = sorted(set(sufs) | {s.strip() for s in sf.read_text().split()
                                   if s.strip()})
        sufs = sorted(set(sufs) | set(MAP_EXTRA))

    allnames = known_names()
    ns = seed_namespaces(allnames, sufs)
    seeds = [n for n in sorted(allnames) if n.startswith(tuple(ns))]
    strip_order = sorted(sufs, key=len, reverse=True)   # most specific first
    nums = seed_numbers(allnames, sufs)
    cand: set = set()
    swaps = 0
    numbered = 0
    for n in seeds:
        base = n
        for s in strip_order:
            if n.endswith(s):
                base = n[: -len(s)]
                break
        cand.update(base + s for s in sufs)
        if base != n:
            cand.add(base)                  # from a map back to its parent
            swaps += 1
        # the number goes INSIDE the pair: <stem>_<NN>_<suffix> (60.17)
        stem = re.sub(r"[_]?[0-9]{1,3}[a-z]{0,2}$", "", base)
        if stem != base:
            numbered += 1
            for k in nums:
                cand.update(f"{stem}_{k}{s}" for s in sufs)
                cand.update(f"{stem}{k}{s}" for s in sufs)
    out = pathlib.Path(args.out)
    out.write_text("\n".join(sorted(cand)) + "\n")
    print(f"namespaces  : {len(ns)}  {sorted(ns)[:12]}")
    print(f"seeds       : {len(seeds)}  ({swaps} already map-suffixed)")
    print(f"numbers     : {len(nums)}  {nums}")
    print(f"numbered    : {numbered} stems carry a number inside the pair")
    print(f"suffixes    : {len(sufs)}")
    print(f"candidates  : {len(cand)}  -> {out}")


if __name__ == "__main__":
    main()
