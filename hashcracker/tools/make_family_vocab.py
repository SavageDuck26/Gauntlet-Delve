#!/usr/bin/env python3
"""
Vocabularies for every *non-quilt* level family (section 43).

The unresolved `.level` targets turned out not to be quilt-shaped: 27 G quilt
candidates produced nothing.  Body size points elsewhere -

    target  6,720 B   ~  room_crypt_floor_05_adventure     6,688 B
    target 11,952 B   ~  crypt_colosseum_02_mortar        12,032 B
    target  4,880 B   ~  crypt_quilt_turn__*__02           4,880 B

so this builds the vocabularies for the *other* level templates

    modules/d01_<env>/colosseum/<env>_colosseum_<nn>[_<mod>]
    modules/d01_<env>/arena/<env>_arena<nn>
    modules/d01_<env>/room_<env>_floor[3]<nn>[_<mod>][_<wing>]
    modules/d01_<env>/room_dummy
    modules/d01_<env>/prefabs/prefab_<env>_<mod>_<nn>_8c_8c
    modules/menu/<mod>
    modules/d01_hub_room/<mod>[_<nn>]

with the mod vocabulary mined from the game's own prop names (which is where
`chains`, `shield`, `beam`, `mortar`, `dark`, ... live).

    python3 tools/make_family_vocab.py [--out data/vocab/family]
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

# extra words the room/menu families use beyond the prop vocabulary
ROOM_WORDS = ["adventure", "boss", "dark", "template", "felix", "arena",
              "colosseum", "hub", "teleport", "dummy", "sandplane", "walls",
              "hero_portrait_lights", "titlescreen", "loadout", "tutorial"]
WINGS = ["north_wing", "east_wing", "south_wing", "west_wing", "center"]
COLOSSEUM_ROUNDS = [f"{i:02d}" for i in range(1, 13)]
ARENA_ROUNDS = [f"{i:02d}" for i in range(1, 13)]


def known_names():
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return sorted(n for n in names if n)


def prop_phrases(max_len=3, prefixes=("props/", "gameobjects/", "blocks/")):
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


def colosseum_mods():
    """The hazard names the colosseum uses (from resolved colosseum levels)."""
    out = set()
    for n in known_names():
        m = re.search(r"_colosseum_\d+_(.+)$", n)
        if m:
            out.add(m.group(1))
    return out


def layout_rooms():
    """The room/floor identifiers: the 68 `lua/dungeon/layouts/*.lua` names."""
    layouts = (DIG.parent.parent / "game-source" / "Gauntlet-SourceCode-LUA" /
               "lua" / "dungeon" / "layouts")
    out = set()
    if layouts.is_dir():
        for f in sorted(layouts.glob("*.lua")):
            stem = f.stem
            if stem in ("lookup", "room_behavior"):
                continue
            out.add(stem)
            out.add(stem.replace("_floor_", "_floor"))     # crypt_floor3_02 style
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "family"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    names = known_names()
    envs = sorted({m.group(1) for n in names
                   for m in [re.match(r"^modules/d01_([a-z_]+)/", n)] if m})
    nn = [f"{i:02d}" for i in range(1, 25)] + [str(i) for i in range(0, 25)]
    mods = sorted(prop_phrases() | set(ROOM_WORDS) | colosseum_mods())
    wings = sorted(set(WINGS) | {f"{a}_{b}" for n in names
                                 for parts in [n.rsplit("_", 2)]
                                 if len(parts) == 3
                                 for a, b in [(parts[1], parts[2])]
                                 if "wing" in b or "wing" in a})

    def w(name, vals):
        (out / name).write_text("\n".join(vals) + ("\n" if vals else ""))
        print(f"  {name:20s} {len(vals):>7}")

    print("family vocabularies:")
    w("env.txt", envs)
    w("nn.txt", sorted(set(nn)))
    w("mod.txt", mods)
    w("wing.txt", wings)
    w("colosseum_round.txt", COLOSSEUM_ROUNDS)
    w("arena_round.txt", ARENA_ROUNDS)
    rooms = sorted(layout_rooms())
    w("room.txt", rooms)
    print(f"envs {len(envs)} mods {len(mods)} (prop phrases + room words + hazards)")
    print(f"layout rooms {len(rooms)}")


if __name__ == "__main__":
    main()
