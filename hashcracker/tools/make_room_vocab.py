#!/usr/bin/env python3
"""
Room / floor family vocabularies (FINDINGS.txt section 44).

The traversal levels are `room_<env>_floor...`: ten floors per environment, the
tenth being the boss floor, with the wings and sub-numbers lining up across
environments.  The resolved corpus shows every shape that name takes:

    room_caves_floor_10_boss                      floor_%f_boss
    room_lava_floor_10_boss_felix                 floor_%f_boss_%m
    room_crypt_floor_06_boss
    room_crypt_floor_01_adventure                 floor_%f_%m
    room_crypt_floor_02_adventure
    room_crypt_floor_05_adventure
    room_caves_floor_adventure_1                  floor_%m_%k
    room_caves_floor_adventure_1_dark             floor_%m_%k_%m
    room_caves_floor_adventure_1_template
    room_lava_floor_adventure_2
    room_crypt_floor3_02_north_wing               floor%f_%k_%w_wing
    room_crypt_floor3_03_west_wing
    room_crypt_floor3_04_east_wing
    room_crypt_floor3_05_south_wing
    room_lava_floor3                              floor%f

so the sweep crosses floor x sub-number x wing x mod with both padded and
unpadded numbers (floor_01 / floor01 / floor3).

    python3 tools/make_room_vocab.py [--out data/vocab/room]
"""
import argparse
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

ENVS = ["caves", "crypt", "lava"]
FLOORS = [f"{i:02d}" for i in range(1, 11)] + [str(i) for i in range(0, 11)]
NUMS = [f"{i:02d}" for i in range(1, 11)] + [str(i) for i in range(1, 11)]
WINGS = ["north", "east", "south", "west", "center", "up", "down",
         "northeast", "northwest", "southeast", "southwest"]
WINGFULL = [w + "_wing" for w in WINGS] + WINGS
# words a room name uses (from resolved room levels + the layouts)
ROOM_MODS = ["adventure", "boss", "dark", "template", "felix", "endless",
             "tutorial", "arena", "colosseum", "hub", "treasure", "secret",
             "vault", "shop", "boss_arena", "entry", "exit", "start", "end",
             "north", "east", "south", "west", "center"]


def known_names():
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return sorted(n for n in names if n)


def prop_phrases(max_len=2, prefixes=("props/", "gameobjects/", "blocks/")):
    out = set()
    for n in known_names():
        if not n.startswith(prefixes):
            continue
        toks = [t for t in re.split(r"[^a-z0-9]+", n.rsplit("/", 1)[-1]) if t]
        toks = [t for t in toks if t != "var" and not re.fullmatch(r"\d+", t)]
        for i in range(len(toks)):
            for j in range(i + 1, min(len(toks), i + max_len) + 1):
                out.add("_".join(toks[i:j]))
    return out


def layout_words():
    layouts = (DIG.parent.parent / "game-source" / "Gauntlet-SourceCode-LUA" /
               "lua" / "dungeon" / "layouts")
    out = set()
    if layouts.is_dir():
        for f in sorted(layouts.glob("*.lua")):
            out |= {t for t in f.stem.split("_") if not re.fullmatch(r"\d+", t)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "room"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    mods = sorted(set(ROOM_MODS) | prop_phrases() | layout_words())
    room_mods = sorted(set(ROOM_MODS) | layout_words())

    def w(name, vals):
        vals = sorted(set(vals), key=lambda s: (len(s), s))
        (out / name).write_text("\n".join(vals) + ("\n" if vals else ""))
        print(f"  {name:16s} {len(vals):>7}")

    print("room vocabularies:")
    w("env.txt", ENVS)
    w("floor.txt", FLOORS)
    w("num.txt", NUMS)
    w("wing.txt", WINGS)
    w("wingfull.txt", WINGFULL)
    w("mod.txt", mods)
    w("mod_room.txt", room_mods)
    print(f"floors {len(set(FLOORS))} nums {len(set(NUMS))} mods {len(mods)}")


if __name__ == "__main__":
    main()
