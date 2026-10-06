#!/usr/bin/env python3
"""
Context-constrained `unit` candidates (blocks, props, passage pieces).

The unresolved units all sit in the module bundles (`modules/d01_*/resources`)
alongside the level quilts, and the generated Lua path lists
(`lua/generated/unit_paths.lua`) only cover script-referenced units - the
stragglers are unreferenced block/passage art such as

    blocks/d01_crypt/walls/crypt_wall_4c, crypt_wall_4c_var01,
    blocks/d01_lava/floors/lavastruct_floor_drain_turn_left_lavaflow

so the lever is the naming habit, not references.  For every resolved unit we
emit, into its own directory and into sibling directories of the same top-level
tree:

    * edit-distance-1 over `_`-tokens (replace / insert / delete / append)
      using a vocabulary of tokens seen anywhere in the unit family plus the
      width/variant/orientation words the family actually uses
      (2c/4c/var01/straight/turn_left/lavaflow/...)
    * the same leaf re-pointed at every other unit directory (cross-dir)

Usage:
    python3 targeted_unit.py [--out FILE] [--max-insert N]
"""
import argparse
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
CATALOGUE = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"

MODS = ("var01 var02 var03 var04 var05 2c 4c 1c 8c 6c straight turn_left turn_right "
        "turn end left right inner outer cross tee corner wall floor ceiling pillar "
        "floor_drain rock rocks stalagmites stalactite border door doorarch arch "
        "plinth block blackbox stairs step platform bridge start mid corner_01 "
        "door_01 door_02 01 02 03 04 05 lavaflow waterflow smooth destroyed "
        "destructible large small tall short open closed").split()


def unit_names():
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["type"] == "unit" and r["name"]:
            names.add(r["name"])
    return {n for n in names if "/" in n and not n.startswith(
        ("characters/", "ability_units/", "equipment/", "gameobjects/", "gui/",
         "lua/", "foundation/", "core/", "effects/", "audio/", "menu/"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/unit_c.txt")
    ap.add_argument("--max-insert", type=int, default=90)
    args = ap.parse_args()

    names = unit_names()
    by_dir = collections.defaultdict(set)
    for n in names:
        d, _, leaf = n.rpartition("/")
        by_dir[d].add(leaf)
    dirs = sorted(by_dir)
    all_leaves = sorted({l for s in by_dir.values() for l in s})

    toks = collections.Counter()
    for leaf in all_leaves:
        toks.update(leaf.split("_"))
    vocab = [t for t, _ in toks.most_common()][: args.max_insert]
    vocab += [m for m in MODS if m not in vocab]

    out = set()
    for d in dirs:
        for leaf in by_dir[d]:
            tl = leaf.split("_")
            for i in range(len(tl)):                    # replace
                for t in vocab:
                    out.add(f"{d}/" + "_".join(tl[:i] + [t] + tl[i + 1:]))
            for i in range(len(tl) + 1):                # insert
                for t in vocab:
                    out.add(f"{d}/" + "_".join(tl[:i] + [t] + tl[i:]))
            for i in range(len(tl)):                    # delete
                out.add(f"{d}/" + "_".join(tl[:i] + tl[i + 1:]))
    # cross-dir: the same leaf in every other directory
    for leaf in all_leaves:
        for d in dirs:
            out.add(f"{d}/{leaf}")

    seen = set(json.loads(OVERLAY.read_text()).values())
    new = sorted(n for n in out if n not in seen)
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"unit dirs {len(dirs)}  leaves {len(all_leaves)}  vocab {len(vocab)}")
    print(f"candidates {len(new)} -> {args.out}")


if __name__ == "__main__":
    main()
