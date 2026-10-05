#!/usr/bin/env python3
"""
Vocabularies for the block / passage (corridor) pattern sweep.

Observed shapes in the unit family:

    blocks/d01_crypt/walls/crypt_wall_4c[_var01]
    blocks/d01_crypt/walls/cryptsmooth_wall_door_01_4c
    blocks/d01_lava/floors/lavastruct_floor_drain_turn_left[_lavaflow]
    blocks/d01_caves/rocks/caverock_stalagmites_01
    props/d01_caves/borders/border_ornament_01

i.e. `<root>/d01_<env>/<category>/<style>_<part>[_<orientation>][_<width>c][_<variant>]`.
Only the pieces referenced by scripts are named (lua/generated/unit_paths.lua is
exhausted), so the sweep enumerates the habit instead.

    python3 make_unit_vocab.py           # -> data/vocab/unit_*.txt
"""
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOGUE = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
OUT = HERE / "data/vocab"

ROOTS = ["blocks", "props", "gameobjects", "effects", "modules", "hud", "equipment"]
ENVS = ["crypt", "caves", "lava", "arcade", "hub_room", "menu", "common", "debug",
        "d01_crypt", "d01_caves"]
CATS = ["walls", "floors", "rocks", "ceilings", "borders", "props", "pillars",
        "structures", "stairs", "doors", "tunnels", "rooms", "floors_drain", "decals"]
STYLES = ["crypt", "cryptsmooth", "cryptbroken", "cryptwall", "caverock",
          "cavestruct", "cavesmooth", "lavastruct", "lavarock", "arcade", "lava",
          "cave", "rock", "stone", "smooth", "hub", "menu", "struct", "brick",
          "marble", "ice", "sand", "bone", "wood"]
PARTS = ["wall", "floor", "ceiling", "pillar", "column", "rock", "rocks",
         "stalagmites", "stalactite", "border", "door", "doorarch", "arch",
         "plinth", "block", "blackbox", "stairs", "step", "platform", "bridge",
         "floor_drain", "drain", "tunnel", "corridor", "passage", "gate", "beam",
         "ledge", "ramp", "roof", "brazier", "torch", "cobweb", "bones", "skull",
         "cart", "statue", "sarcophagus", "altar", "crystal", "mushroom", "plant",
         "tree", "roots", "water", "pit", "spike", "trapdoor", "ladder", "fence",
         "railing", "window", "opening", "marker", "pillars", "border_corner",
         "wall_end", "wall_corner", "wall_door", "floorpile", "skullpile"]
ORIENT = ["straight", "turn_left", "turn_right", "end", "left", "right", "cross",
          "tee", "corner", "inner", "outer", "start", "mid", "top", "bottom",
          "cap", "base", "middle", "square", "round", "angled", "diagonal",
          "vertical", "horizontal", "wide", "narrow"]
WIDTH = ["1c", "2c", "4c", "6c", "8c", "12c"]
VARIANT = ["var01", "var02", "var03", "var04", "var05", "var06", "01", "02",
           "03", "04", "05", "06", "07", "08", "09", "10", "11", "12",
           "door_01", "door_02", "door_03", "lavaflow", "waterflow",
           "ornament_01", "ornament_02", "broken", "destroyed", "cracked",
           "mossy", "lava", "water"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "unit_root.txt": ROOTS, "unit_env.txt": ENVS, "unit_cat.txt": CATS,
        "unit_style.txt": STYLES, "unit_part.txt": PARTS,
        "unit_orient.txt": ORIENT, "unit_w.txt": WIDTH, "unit_var.txt": VARIANT,
    }

    # also fold in whatever the resolved units actually use
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["type"] == "unit" and r["name"]:
            names.add(r["name"])
    extra = collections.defaultdict(set)
    for n in names:
        leaf = n.rsplit("/", 1)[-1]
        if not n.startswith(("blocks/", "props/")):
            continue
        for m in ("straight", "turn_left", "turn_right", "floor_drain", "wall",
                  "floor", "door", "blackbox", "stalagmites", "stalactite",
                  "border", "ornament", "rocks", "rock"):
            if m in leaf:
                extra["unit_part.txt"].add(m)
        for t in leaf.split("_"):
            if t.endswith("c") and t[:-1].isdigit():
                extra["unit_w.txt"].add(t)
            if t.startswith("var"):
                extra["unit_var.txt"].add(t)

    for fn, vals in files.items():
        vals = sorted(set(vals) | extra.get(fn, set()))
        (OUT / fn).write_text("\n".join(vals) + "\n")
        print(f"  {fn:20s} {len(vals):>5} entries")


if __name__ == "__main__":
    main()
