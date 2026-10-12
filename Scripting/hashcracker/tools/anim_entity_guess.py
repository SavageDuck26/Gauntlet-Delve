#!/usr/bin/env python3
"""Guess an unresolved animation from its *entity* - every directory context the referrer
implies, crossed with the clips we already know (FINDINGS 64.8).

`extract_anim_refs.py` gives the resource that references each unresolved animation, and
that referrer is a *path* with more context than the unit name:

    gameobjects/spawners/spawner_beam     -> gameobjects/spawners/animations/...
                                          -> gameobjects/spawners/spawner_beam/animations/...
    characters/avatar_valkyrie/valkyrie   -> characters/avatar_valkyrie/{animations,animation}/...

The earlier sweeps derived only the first form (`unit_of`), which is right for characters
but *collapses the spawner's own name* - and the spawner objects own 141 of the 543
unresolved animation rows.  So build every progressive directory context instead, and
cross it with:

  * every leaf of the resolved animation corpus (the shared clip vocabulary),
  * the leaves of the named animations whose `body_size` matches this hash exactly
    (size is nearly a function of the clip, FINDINGS 43 - but it is not transplanted
    verbatim, so the *respellings* of those leaves matter too),
  * each of those respelled the way the corpus respells (`die_headshot_01` ->
    `die_headshot01`, `death` <-> `die`, numbers 1..20 glued or underscored).

    python3 tools/anim_entity_guess.py [--out FILE] [--max-leaves N]
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
REFS = HC / "work" / "refs_animation.json"
NUMS = [str(i) for i in range(1, 13)] + [f"{i:02d}" for i in range(1, 13)]


def contexts(ref: str):
    """Every directory the referrer could be storing its animations in."""
    parts = ref.split("/")
    out = set()
    for i in range(1, len(parts) + 1):
        base = "/".join(parts[:i])
        for tail in ("animations", "animation"):
            out.add(f"{base}/{tail}")
    return out


def respell(leaf: str):
    out = {leaf}
    m = re.match(r"^(.*?)_?(\d+)$", leaf)
    stem = m.group(1) if m else leaf
    for n in NUMS:
        out |= {f"{stem}_{n}", f"{stem}{n}"}
    for a, b in (("die_", "death_"), ("death_", "die_"), ("hit_offset", "offset_hit"),
                 ("offset_hit", "hit_offset"), ("move_", "walk_"), ("walk_", "move_")):
        if a in leaf:
            s = leaf.replace(a, b, 1)
            out.add(s)
            out |= {f"{s}_{n}" for n in NUMS} | {f"{s}{n}" for n in NUMS}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/anim_entity.txt")
    ap.add_argument("--max-leaves", type=int, default=4000)
    args = ap.parse_args()

    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace")))
    leaves = sorted({r["name"].rsplit("/", 1)[1]
                     for r in rows if r["type"] == "animation" and r["name"]})
    by_size = collections.defaultdict(set)
    for r in rows:
        if r["type"] == "animation" and r["name"]:
            by_size[int(r["body_size"])].add(r["name"].rsplit("/", 1)[1])
    refs = json.loads(REFS.read_text()) if REFS.exists() else {}

    out = set()
    for r in rows:
        if r["type"] != "animation" or r["name"]:
            continue
        ctx = {c for ref in refs.get(r["name_hash"], []) for c in contexts(ref)}
        if not ctx:
            continue
        twins = sorted(by_size.get(int(r["body_size"]), ()))
        pool = set(leaves) | set(twins)
        for t in twins:
            pool |= respell(t)
        for t in sorted(twins):
            pool |= respell(t)
        chosen = sorted(pool)
        if len(chosen) > args.max_leaves:  # twins first, then the corpus
            chosen = sorted(set(twins)) + sorted(set(leaves))
            chosen = chosen[:args.max_leaves]
        for c in ctx:
            out |= {f"{c}/{leaf}" for leaf in chosen}
    pathlib.Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"candidates {len(out):,} -> {args.out}")


if __name__ == "__main__":
    main()
