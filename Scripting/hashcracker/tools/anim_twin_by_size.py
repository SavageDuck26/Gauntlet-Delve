#!/usr/bin/env python3
"""Identify an unresolved animation from a named one of the same body size (FINDINGS 64.8).

The shared-clip work (`tools/anim_shared_vocab.py`) settles the *spelling*; this settles
*which clip it is*.  Animations are rigged per entity, so the same clip played by another
body has different bytes (0 of 307 unresolved animation bodies are byte-identical to a
named one), but the body *size* is nearly a function of the clip - a measured, documented
fingerprint of this project (FINDINGS section 43) - and it survives the re-rig.

So: for every unresolved animation, every named animation of the same `body_size` is a
candidate leaf, and the entity comes from the referrer graph (`refs_animation.json`), so
the candidate is `<that entity>/an{imation,imations}/<that leaf>` - in both directory
spellings, because the shipped data uses both (`characters/cultist_novice/animation`,
`characters/mummy_risen/animations`).

The same-size leaf is then respelled the way the corpus respells things (`die_headshot_01`
-> `die_headshot01`, `death` <-> `die`, numbers 1..20 glued or underscored), because
size-twinning says *which* clip it is and the spelling is the only other unknown.

    python3 tools/anim_twin_by_size.py [--out FILE] [--delta N] [--matches FILE]

`--delta` widens the size match to +/- N bytes; 0 (exact) is the default and is by far the
strongest signal.
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

NUMS = [str(i) for i in range(1, 21)] + [f"{i:02d}" for i in range(1, 21)]


def unit_of(path: str) -> str:
    p = path.split("/")
    return p[1] if p and p[0] == "characters" else "/".join(p[:-1])


def respell(leaf: str):
    """The same clip in every spelling convention the corpus shows."""
    out = {leaf}
    m = re.match(r"^(.*?)_?(\\d+)$", leaf)
    stem, num = (m.group(1), m.group(2)) if m else (leaf, None)
    for n in NUMS:
        out |= {f"{stem}_{n}", f"{stem}{n}"}
    if num:
        out |= {f"{stem}_{num}", f"{stem}{num}"}
    for a, b in (("die_", "death_"), ("death_", "die_"), ("_offset", "_hit"),
                 ("hit_offset", "offset_hit"), ("move_", "walk_"), ("walk_", "move_")):
        if a in leaf:
            swapped = leaf.replace(a, b, 1)
            out.add(swapped)
            out |= {swapped + "_" + n for n in NUMS} | {swapped + n for n in NUMS}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/anim_twin.txt")
    ap.add_argument("--delta", type=int, default=0)
    args = ap.parse_args()

    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace")))
    by_size = collections.defaultdict(set)
    for r in rows:
        if r["type"] == "animation" and r["name"]:
            by_size[int(r["body_size"])].add(r["name"].rsplit("/", 1)[1])
    refs = json.loads(REFS.read_text()) if REFS.exists() else {}
    sizes = sorted(by_size)
    out = set()
    pairs = 0
    for r in rows:
        if r["type"] != "animation" or r["name"]:
            continue
        h = r["name_hash"]
        units = {unit_of(x) for x in refs.get(h, [])}
        if not units:
            continue
        size = int(r["body_size"])
        near = []
        for s in sizes:
            if abs(s - size) <= args.delta:
                near += list(by_size[s])
        if not near:
            continue
        pairs += 1
        for u in units:
            base = f"characters/{u}" if not u.startswith("gameobjects") else u
            for tail in ("animations", "animation"):
                for leaf in near:
                    out |= {f"{base}/{tail}/{v}" for v in respell(leaf)}
    pathlib.Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"unresolved animations with a size twin: {pairs}")
    print(f"candidates {len(out):,} -> {args.out}")


if __name__ == "__main__":
    main()
