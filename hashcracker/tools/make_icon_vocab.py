#!/usr/bin/env python3
"""
Icon vocabulary for the HUD/item atlases (FINDINGS.txt §48.4).

The atlas rule is `D/L/<icon>` and the icons are the game's own item names.  For
relics and talismans those names are already in the corpus:

    gameobjects/relics/<item>            boots_of_ranadam, eye_of_dur,
                                         crystallized_chaos, golden_feather, ...
    equippables_icons/relic_<item>       the icon spelling of the same items
    equipment/<class>/talisman01..03     talisman names (+ talisman_souleater)

so the icon is `<item>`, `relic_<item>`, `<class>_<item>`, plus the usual
icon/map suffixes.  Patterns are the plausible atlas directories, taken from the
hint (`hud/relics`, `hud/talisman`) and from the resolved atlases.

    python3 tools/make_icon_vocab.py [--out DIR]
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
OVERLAY = DIG / "resource_name_overlay.json"

CLASSES = ["warrior", "wizard", "valkyrie", "elf", "necromagus", "necromancer",
           "common", "d01"]
SUF = ["", "_icon", "_diff", "_norm", "_spec", "icon", "_large", "_small",
       "_locked", "_unlocked", "_hover", "_active", "_empty", "_selected",
       "_off", "_on", "_glow", "_bg", "_frame"]
NUMS = ["", "01", "02", "03", "04", "05", "1", "2", "3"]

ATLAS_DIRS = ["hud/relics", "hud/talisman", "hud/talismans", "hud/relic_icons",
              "hud/talisman_icons", "hud/item_icons", "hud/items", "hud/icons",
              "hud/action_icons", "hud/spells", "hud", "hud/elements",
              "equippables_icons", "equipment", "menu/icons", "menu/shop/icons",
              "items/icons", "icons", "hud/colosseum"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "icon"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    names = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            names.append(n)

    items = set()
    for n in names:
        if n.startswith("gameobjects/relics/"):
            items.add(n.rsplit("/", 1)[-1])
        elif n.startswith("equippables_icons/relic_"):
            items.add(n.rsplit("/", 1)[-1][len("relic_"):])
        elif n.startswith("equipment/") and "talisman" in n:
            items.add(n.rsplit("/", 1)[-1])
        elif n.startswith("equippables_icons/eq_"):
            items.add(n.rsplit("/", 1)[-1])
    items = {i for i in items if i and i != "relics"}
    print(f"item stems {len(items)}: {sorted(items)[:12]} ...")

    vocab = set()
    for it in items:
        stems = {it, f"relic_{it}"}
        for p in ("talisman", "tal"):
            if p in it:
                stems.add(it.replace(p, "").strip("_") or it)
        for c in CLASSES:
            stems.add(f"{c}_{it}")
        for st in stems:
            for s in SUF:
                vocab.add(f"{st}{s}")
            for n2 in NUMS:
                for s in ("", "_icon", "_diff"):
                    vocab.add(f"{st}{n2}{s}")
    vocab = sorted(v for v in vocab if len(v) > 3)

    pats = []
    for d in ATLAS_DIRS:
        pats.append(f"{d}/%m")
        pats.append(f"{d}/%m_%n")
        pats.append(f"{d}/%m/%n")
    (out / "vocab.txt").write_text("\n".join(vocab) + "\n")
    (out / "patterns.txt").write_text("\n".join(pats) + "\n")
    print(f"vocab {len(vocab):,}  patterns {len(pats)}  "
          f"candidates ~{len(vocab) * len(pats):,}")


if __name__ == "__main__":
    main()
