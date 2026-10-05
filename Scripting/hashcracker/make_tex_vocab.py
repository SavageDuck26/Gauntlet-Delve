#!/usr/bin/env python3
"""
Vocabularies for the texture/material derivation sweep.

Textures and materials share the leaf vocabulary of units and props, in a
flatter namespace:

    unit      blocks/d01_caves/rocks/caverock_rock_01
    texture   blocks/d01_caves/caverock_rock_01_diff
    material  props/d01_common/blackbox_2c_2c
    texture   achievement_icons/<name>[_locked]
    texture   equipment/<class>/<item>_icon

so the sweep is `%d/%l%s`: every directory seen anywhere x every leaf token
seen anywhere x every map suffix.  Generated on the device, so the space can be
hundreds of millions without writing a file.

    python3 make_tex_vocab.py        # -> data/vocab/tex_*.txt
"""
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOGUE = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
OUT = HERE / "data/vocab"
LUA = (Path.home() / ".local/share/Steam/steamapps/common/Gauntlet"
       / "Gauntlet-Source-DO_NOT_EDIT/lua")

STEMS = ("_diffgloss", "_specgloss", "_nrmgloss", "_glowmask", "_diff", "_norm",
         "_spec", "_nrm", "_mask", "_alpha", "_emissive", "_glow", "_high",
         "_illum", "_overlay", "_detail", "_locked", "_icon")
SUFFIXES = ["", "_diff", "_norm", "_spec", "_nrm", "_mask", "_alpha", "_glow",
            "_emissive", "_high", "_illum", "_overlay", "_detail", "_locked",
            "_icon", "_specgloss", "_diffgloss", "_nrmgloss", "_glowmask",
            "_diff_var01", "_diff_var02", "_norm_var01", "_norm_var02",
            "_var01_diff", "_var02_diff", "_diff_01", "_norm_01", "_diff_02",
            "_high_layer", "_high02", "_high03", "_o", "_a", "_add"]
STYLE_EXTRA = ["caverock", "cavestruct", "cavesmooth", "lavarock", "lavastruct",
               "crypt", "cryptsmooth", "cryptbroken", "arcade", "swamp", "stone",
               "rock", "lava", "sand", "bone", "wood", "metal", "marble", "ice",
               "clay", "dirt", "grass", "mud", "crystal", "cloth", "coffin",
               "brazier", "banner", "barrel", "box", "cage", "cart", "pillar",
               "stairs", "wall", "floor", "ceiling", "border", "door", "arch"]
PART_EXTRA = ["wall", "floor", "ceiling", "pillar", "column", "rock", "rocks",
              "floor_01", "floor_02", "floor_03", "wall_2c", "wall_4c",
              "floor_2c", "floor_4c", "border_01", "border_2c", "border_4c",
              "set", "set_b", "set_c", "high", "illum", "diff", "norm",
              "01", "02", "03", "04", "05"]


def unstem(leaf):
    for s in sorted(STEMS, key=len, reverse=True):
        if leaf.endswith(s) and len(leaf) > len(s):
            return leaf[: -len(s)]
    return leaf


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ov = json.loads(OVERLAY.read_text())
    rows = list(csv.DictReader(CATALOGUE.open()))
    type_of = {}
    for r in rows:
        type_of.setdefault(r["name_hash"], r["type"])

    dirs, leaves, toks = collections.Counter(), collections.Counter(), collections.Counter()
    for h, n in ov.items():
        segs = n.split("/")
        for k in (2, 3):
            if len(segs) > k:
                dirs["/".join(segs[:k])] += 1
        leaf = unstem(segs[-1])
        leaves[leaf] += 1
        for t in re.split(r"[_/]", n):
            if t and not t.isdigit() and len(t) > 1:
                toks[t] += 1

    # Lua content tokens (block/prop words live there too)
    for p in LUA.rglob("*.lua"):
        for m in re.findall(r"[a-z][a-z0-9_]{3,60}", p.read_text(errors="ignore")):
            toks[m] += 1

    dirs = [d for d, _ in dirs.most_common(600)]
    base_leaves = [l for l, _ in leaves.most_common(6000)]
    style = [t for t, _ in toks.most_common(90)] + STYLE_EXTRA
    part = [t for t, _ in toks.most_common(200)] + PART_EXTRA
    combos = set()
    for s in dict.fromkeys(style):
        for p in dict.fromkeys(part):
            combos.add(f"{s}_{p}")
    leaves_all = sorted(set(base_leaves) | combos)

    def dump(fn, vals):
        (OUT / fn).write_text("\n".join(sorted(set(vals))) + "\n")
        print(f"  {fn:18s} {len(set(vals)):>6} entries")

    dump("tex_dir.txt", dirs)
    dump("tex_leaf.txt", leaves_all)
    dump("tex_suf.txt", SUFFIXES)
    dump("tex_root.txt", ["blocks", "props", "effects", "menu", "gameobjects",
                          "characters", "equipment", "hud", "textures", "core",
                          "decals", "achievement_icons", "cape_icons",
                          "equippables_icons", "loading_screens", "ui", "money"])


if __name__ == "__main__":
    main()
