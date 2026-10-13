#!/usr/bin/env python3
"""
Big-vocabulary counterpart of make_unit_vocab.py for the wide unit sweep.

Everything here is mined from names that are already resolved, so the words are
ones the game actually uses:

  * `style` words  - the head token of every resolved block/prop/texture/
                     material/bone leaf (crypt, cryptsmooth, cavestruct,
                     caverock, lavastruct, lavarock, swamp, ...)
  * `part`  words  - every other non-numeric token from the same families
  * `char`  words  - character names (from units/bones/abilities paths)
  * `gib`   words  - body-part tokens (gib, cape, legs, torso, head, set01..,
                     s01.., r01..)

    python3 make_unit_vocab_big.py        # -> data/vocab/ub_*.txt
"""
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOGUE = REPO / "Data/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Data/resource_name_overlay.json"
OUT = HERE.parent / "data/vocab"

ROOTS = ["blocks", "props", "gameobjects", "effects", "characters", "modules",
         "hud", "equipment", "decals", "ability_units", "gui", "audio"]
ENVS = ["d01_crypt", "d01_caves", "d01_lava", "d01_arcade", "d01_hub_room",
        "d01_menu", "common", "debug"]
CATS = ["walls", "floors", "rocks", "ceilings", "borders", "props", "pillars",
        "structures", "stairs", "doors", "tunnels", "rooms", "decals", "lights",
        "traps", "fx", "bodies", "gib", "gibs", "abilities", "meshes", "beams"]
ORIENT = ["straight", "turn_left", "turn_right", "end", "left", "right", "cross",
          "tee", "corner", "inner", "outer", "start", "mid", "top", "bottom",
          "cap", "base", "middle", "square", "round", "angled", "diagonal",
          "vertical", "horizontal", "wide", "narrow", "forward", "backward",
          "left_back", "right_back"]
WIDTH = ["1c", "2c", "3c", "4c", "6c", "8c", "12c"]
VARIANT = [f"var{i:02d}" for i in range(1, 11)] + [f"{i:02d}" for i in range(1, 21)] \
    + ["door_01", "door_02", "door_03", "lavaflow", "waterflow", "ornament_01",
       "ornament_02", "broken", "destroyed", "cracked", "mossy", "dark", "light"]
DEFAULT_STYLE = ["crypt", "cryptsmooth", "cryptbroken", "caverock", "cavestruct",
                 "cavesmooth", "lavastruct", "lavarock", "arcade", "lava", "cave",
                 "rock", "stone", "smooth", "hub", "menu", "struct", "brick",
                 "marble", "ice", "sand", "bone", "wood", "swamp", "crystal",
                 "metal", "clay", "dirt", "grass", "mud"]
DEFAULT_PART = ["wall", "floor", "ceiling", "pillar", "column", "rock", "rocks",
                "stalagmites", "stalactite", "border", "door", "doorarch", "arch",
                "plinth", "block", "blackbox", "stairs", "step", "platform",
                "bridge", "floor_drain", "drain", "tunnel", "corridor", "passage",
                "gate", "beam", "ledge", "ramp", "roof", "brazier", "torch",
                "cobweb", "bones", "skull", "cart", "statue", "sarcophagus",
                "altar", "crystal", "mushroom", "plant", "tree", "roots", "water",
                "pit", "spike", "trapdoor", "ladder", "fence", "railing", "window",
                "opening", "marker", "floorpile", "skullpile", "wall_end",
                "wall_corner", "wall_door", "border_corner", "blackbox_2c"]
MOD = """low high mid concave convex straight angled split_vertical
split_horizontal froze_base frozen_base no_fade fade nodraw invisible
damaged broken cracked destroyed rubble rubble_small var01 var02 var03 var04
var05 var06 a b c d l r left right inner outer top bottom cap base middle
corner edge side front back narrow wide long short thick thin 01 02 03 04 05""".split()

GIBPART = ["gib", "gibs", "cape", "legs", "torso", "head", "headless", "split",
           "body", "arm", "arms", "hand", "foot", "feet", "shoulder", "hip",
           "neck", "jaw", "skull", "wing", "tail", "horn", "spike", "chain",
           "chains", "cloth", "armour", "armor", "helm", "helmet", "shield",
           "weapon", "set01", "set02", "set03", "set04", "set05", "set06",
           "s01", "s02", "s03", "s04", "s05", "s06", "r01", "r02", "r03"]


def resolved_names():
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["name"]:
            names.add(r["name"])
    return names


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    names = resolved_names()

    styles, parts, chars, gibs = collections.Counter(), collections.Counter(), \
        collections.Counter(), collections.Counter()
    for n in names:
        leaf = n.rsplit("/", 1)[-1]
        toks = [t for t in leaf.split("_") if t and not t.isdigit()]
        if not toks:
            continue
        fam = n.split("/", 1)[0]
        styles[toks[0]] += 1
        for t in toks[1:]:
            parts[t] += 1
        if fam in ("characters", "ability_units"):
            segs = n.split("/")
            if len(segs) > 1:
                chars[segs[1]] += 1
            for t in toks:
                if t in GIBPART:
                    gibs[t] += 1
    for t in DEFAULT_STYLE:
        styles[t] += 1
    for t in DEFAULT_PART:
        parts[t] += 1
    for t in GIBPART:
        gibs[t] += 1

    def dump(fn, vals, cap=None):
        vals = sorted(dict.fromkeys(vals))
        if cap:
            vals = vals[:cap]
        (OUT / fn).write_text("\n".join(vals) + "\n")
        print(f"  {fn:20s} {len(vals):>5} entries")

    dump("ub_root.txt", ROOTS)
    dump("ub_env.txt", ENVS)
    dump("ub_cat.txt", CATS)
    dump("ub_orient.txt", ORIENT)
    dump("ub_w.txt", WIDTH)
    dump("ub_var.txt", VARIANT)
    dump("ub_style.txt", [t for t, _ in styles.most_common(60)])
    dump("ub_part.txt", [t for t, _ in parts.most_common(120)])
    dump("ub_char.txt", [t for t, _ in chars.most_common(80)])
    dump("ub_gib.txt", [t for t, _ in gibs.most_common(60)])
    mods = collections.Counter()
    for n in names:
        if not n.startswith(("blocks/", "props/")):
            continue
        toks = [t for t in n.rsplit("/", 1)[-1].split("_") if t and not t.isdigit()]
        for t in toks[1:-1]:                       # head/tail carry style/width
            mods[t] += 1
    mods.update(MOD)
    dump("ub_mod.txt", [t for t, _ in mods.most_common(120)])
    dump("ub_color.txt", """red blue green gold purple orange yellow white black pink
        cyan teal silver bronze grey gray brown dark light pale bright blood iron
        stone wood bone sand ice fire poison shadow holy""".split())
    dump("ub_num.txt", [f"{i:02d}" for i in range(1, 17)])


if __name__ == "__main__":
    main()
