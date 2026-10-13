#!/usr/bin/env python3
"""Shared clips, spelled the way *this* entity spells them (FINDINGS 64.7).

Every entity should hold the common clips - walk, run, hit, offset, die, stagger, idle,
spawn - because they are the same animation replayed by a different body.  The corpus
proves the sharing exists and also why a plain cross-entity search misses it: the
*concept* is shared, the *spelling* is not.  `hit_offset` alone appears as `hit_offset`,
`hit_offset1`, `hit_offset2`, `hit_offset_01`, `hit_offset_02`, `offset_hit_01`, ... -
11 forms - and 62 of the corpus's 452 concepts are spelled more than one way.

So: take the concepts the corpus uses, generate every spelling convention we observe
(underscored number, glued number, `_default`/`_normal`/`_light`/`_heavy`, direction
tokens with and without numbers, reversed token order), and test them under the
directories of the entities that still have unresolved clips.  Every candidate is a
clip name a human would have written, so this is not a word-combination brute force.

It found, in one run, `characters/cultist_novice/animation/{die_headshot01, die_left01,
die_right01, die_slump01}` - the glued-number form, which `mutate` structurally cannot
reach (it substitutes a *token*, so the separator before the number is always kept) and
which `%p_%t` misses (it always joins prefix and tail with `_`).

    python3 tools/anim_shared_vocab.py [--out FILE] [--write-units FILE]

Writes the candidate list (one full resource name per line) and prints the counts.  Feed
it to the engine:

    ./target/release/hashcracker crack --cpu --targets data/vocab/unresolved_targets.txt \
        --candidates /tmp/anim_shared.txt --matches matches.tsv
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
REFS = HC / "work" / "refs_animation.json"

# number forms: the corpus uses `_01`, `_1`, `01`, `1` and (rarely) two digits glued to a
# word, so all four go in, 1..20.
NUMS = [str(i) for i in range(1, 21)] + [f"{i:02d}" for i in range(1, 21)]
DIRS = ["left", "right", "back", "front", "forward", "fwd", "up", "down",
        "strafe_left", "strafe_right", "left_back", "right_back"]
SUFS = ["default", "normal", "loop", "start", "init", "end", "exit", "windup",
        "winddown", "heavy", "light", "fast", "slow", "short", "long", "special",
        "normal_01", "left_01", "right_01", "back_01", "front_01", "idle", "b", "c"]


def unit_of(path: str) -> str:
    """`characters/x/anything` -> `x`; `gameobjects/spawners/y` -> `gameobjects/spawners`."""
    p = path.split("/")
    return p[1] if p and p[0] == "characters" else "/".join(p[:-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/anim_shared.txt")
    ap.add_argument("--write-units", help="also write the entity list here")
    args = ap.parse_args()

    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace")))
    named = [r["name"] for r in rows if r["type"] == "animation" and r["name"]]
    unresolved = [r["name_hash"] for r in rows if r["type"] == "animation" and not r["name"]]
    refs = json.loads(REFS.read_text()) if REFS.exists() else {}

    leaves = sorted({n.rsplit("/", 1)[1] for n in named})
    concepts = collections.defaultdict(set)
    for leaf in leaves:
        m = re.match(r"^(.*?)_?(\d+)$", leaf)
        concepts[m.group(1) if m else leaf].add(leaf)

    variants = set(leaves)
    for concept in concepts:
        v = {concept}
        v |= {f"{concept}_{s}" for s in SUFS}
        for n in NUMS:
            v |= {f"{concept}_{n}", f"{concept}{n}"}
        for d in DIRS:
            v.add(f"{concept}_{d}")
            v |= {f"{concept}_{d}_{n}" for n in NUMS}
            v |= {f"{concept}_{d}{n}" for n in NUMS}
        parts = concept.split("_")
        if len(parts) == 2:  # `offset_hit_01` beside `hit_offset_01`
            rev = f"{parts[1]}_{parts[0]}"
            v.add(rev)
            v |= {f"{rev}_{n}" for n in NUMS} | {f"{rev}{n}" for n in NUMS}
        variants |= v

    units = sorted({unit_of(r) for h in set(unresolved) for r in refs.get(h, [])})
    out = set()
    for u in units:
        base = f"characters/{u}" if not u.startswith("gameobjects") else u
        for tail in ("animations", "animation"):
            out |= {f"{base}/{tail}/{v}" for v in variants}

    pathlib.Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    if args.write_units:
        pathlib.Path(args.write_units).write_text("\n".join(units) + "\n")
    print(f"leaves {len(leaves)}  concepts {len(concepts)}  spelling variants {len(variants)}")
    print(f"entities with unresolved clips {len(units)}")
    print(f"candidates {len(out):,} -> {args.out}")


if __name__ == "__main__":
    main()
