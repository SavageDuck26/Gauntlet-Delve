#!/usr/bin/env python3
"""
Vocabularies for the particles / effects-name hunt.

`effects/<prefix>_<stem>_<tail>` is the shape of the 828 resolved particles
names (prefixes cha_ 255, wep_ 155, env_ 99, gam_ 70, hit_ 56, relic_ 21,
obj_ 20, statuseffect_ 18, ...), so the unknown ones are enumerable if we cross

    prefixes  x  stems (characters / units)  x  tails (mined from resolved names)

Stems additionally take in the words a character's own Lua uses (a unit's ability
and effect names live there - `orboffire`, `demon_horror`, `barrel_explosion`),
which is where the vocabulary for a one-off boss effect comes from.

    python3 make_effect_vocab.py [--out data/vocab]
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
SOURCE = HC.parent.parent / "game-source" / "Gauntlet-SourceCode-LUA"

PREF = re.compile(r"^effects/([a-z]+_)")
KNOWN_PREFIXES = ["cha_", "wep_", "env_", "gam_", "hit_", "relic_", "obj_",
                  "statuseffect_", "cutscene_", "gib_", "potion_", "trap_",
                  "treasure_", "boss_", "menu_", "unit_", "units_", ""]


def resolved_names():
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return {n for n in names if n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)

    names = resolved_names()
    prefixes = collections.Counter()
    tails = collections.Counter()
    for n in names:
        if n.startswith("effects/"):
            leaf = n.split("/", 1)[1]
            m = PREF.match(n)
            if m:
                prefixes[m.group(1)] += 1
                rest = leaf[len(m.group(1)):]
            else:
                rest = leaf
            toks = rest.split("_")
            for k in (1, 2, 3):
                if len(toks) >= k:
                    tails["_".join(toks[-k:])] += 1

    stems = set()
    for n in names:
        p = n.split("/")
        if p[0] == "characters" and len(p) >= 3:
            stems.add(p[-1])
            stems.add(p[1])
            for t in p[1].split("_") + p[-1].split("_"):
                if len(t) > 2:
                    stems.add(t)
        if p[0] in ("gameobjects", "props", "ability_units") and len(p) >= 2:
            stems.add(p[-1])
            for t in p[-1].split("_"):
                if len(t) > 2:
                    stems.add(t)
    # words a character's own Lua uses: stems AND tails.  A one-off boss effect
    # is named after the ability that spawns it (`ability_orboffire_explode` ->
    # `effects/cha_..._orboffire_explode`), and no *resolved* effect name
    # contains that word, so the tail vocabulary has to come from here.
    lua_words = set()
    for f in list(SOURCE.glob("characters/demon_overlord_mini/*.lua")) + \
             list(SOURCE.glob("characters/demon_heavy/*.lua")) + \
             list(SOURCE.glob("characters/demon_base/*.lua")):
        for m in re.finditer(r'"([a-z0-9_]{4,})"', f.read_text(errors="replace")):
            w = m.group(1)
            lua_words.add(w)
            for t in w.split("_"):
                if len(t) > 3:
                    lua_words.add(t)
    for w in lua_words:
        toks = w.split("_")
        for k in (1, 2, 3):
            if len(toks) >= k:
                tails["_".join(toks[-k:])] += 1
    stems |= {"demon_overlord_mini", "demon_overlord", "demon_horror",
              "overlord_mini", "demon_heavy", "demon_melee", "demon_ranged"}

    def w(name, vals):
        vals = sorted(v for v in vals if v)
        (out / name).write_text("\n".join(vals) + "\n")
        print(f"  {name:24s} {len(vals):>7}")

    w("eff_prefix.txt", {p for p, _ in prefixes.most_common()} | set(KNOWN_PREFIXES))
    w("eff_stem.txt", stems)
    w("eff_tail.txt", {t for t, c in tails.most_common(4000)})
    print(f"prefixes {len(prefixes)}  stems {len(stems)}  tails {len(tails)}")
    print(f"space    : {len(prefixes) * len(stems) * len(tails):,} (prefix x stem x tail)")


if __name__ == "__main__":
    main()
