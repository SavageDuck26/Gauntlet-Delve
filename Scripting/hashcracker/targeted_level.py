#!/usr/bin/env python3
"""
Context-constrained level candidates (`modules/<env>/...`).

Levels are template-generated, so the unresolved ones are almost always a
combination the other environments already have.  Grammar mined from the
catalogue:

    modules/<env>/quilts/base|encounters|entrances|exits|saferooms/
        <env>_quilt_<shape>__<edges>__<NN>[_<mod>[_<mod>]]
    modules/<env>/arena/<env>_arena0N
    modules/<env>/colosseum/<env>_colosseum_0N_<hazard>
    modules/<env>/room_<env>_floor_<NN|adventure_N>_<mode>

Generation:
    1. cross-env transfer - every resolved leaf re-prefixed per environment
       (crypt <-> caves <-> lava) and tested in that env's directories
    2. NN x modifier expansion of every resolved quilt leaf
    3. hazard / arena / room-template completion over the observed sets

Usage:
    python3 targeted_level.py [--out FILE] [--max-nn N]
"""
import argparse
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOGUE = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
ENVS = ("crypt", "caves", "lava")
ENV_DIRS = ("quilts/base", "quilts/encounters", "quilts/entrances", "quilts/exits",
            "quilts/saferooms")
QUILT = re.compile(r"^([a-z_]+)_quilt_([a-z]+)__([a-z_]+)__(\d+)((?:_[a-z0-9_]+)*)$")
ROOM = re.compile(r"^room_([a-z_]+)_floor_(.+)$")


def resolved_levels():
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["type"] == "level" and r["name"]:
            names.add(r["name"])
    return {n for n in names if n.startswith("modules/")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/level_c.txt")
    ap.add_argument("--max-nn", type=int, default=12)
    args = ap.parse_args()

    names = resolved_levels()
    leaves = collections.defaultdict(set)
    for n in names:
        d, _, leaf = n.rpartition("/")
        leaves[d].add(leaf)

    shapes, edges, mods, hazards = set(), set(), set(), set()
    modpairs = set()
    for leaf in (l for s in leaves.values() for l in s):
        m = QUILT.match(leaf)
        if m:
            shapes.add(m.group(2)); edges.add(m.group(3))
            toks = [t for t in m.group(5).split("_")[1:] if t and not t.isdigit()]
            mods.update(toks)
            for i in range(len(toks)):
                for j in range(i + 1, len(toks)):
                    modpairs.add(f"{toks[i]}_{toks[j]}")
        mc = re.match(r"^[a-z]+_colosseum_\d+_(.+)$", leaf)
        if mc:
            hazards.add(mc.group(1))
    all_leaves = sorted({l for s in leaves.values() for l in s})
    # shapes not yet seen (the edge code encodes the openings, so straight/turn/
    # cross/tee are the structural set; the room/entrance/exit ones are sizes)
    shapes |= {"cross", "tee", "t_junction", "junction", "deadend", "corner",
               "end", "hub", "fourway", "straight_t", "fourway_room"}

    out = set()
    for env in ENVS:
        dirs = [f"modules/d01_{env}/{d}" for d in ENV_DIRS] + [f"modules/d01_{env}"]
        # every shape x every edge code (the openings the code describes are
        # structural, so combinations the art team never shipped still get tried)
        heads = {f"{env}_quilt_{sh}__{e}" for sh in shapes for e in edges}
        # 1. cross-env transfer + 2. NN x modifier expansion
        for leaf in all_leaves:
            variants = {leaf}
            for e in ENVS + ("hub_room",):
                if leaf.startswith(e + "_"):
                    variants.add(env + leaf[len(e):])
            for v in variants:
                m = QUILT.match(v)
                if not m:
                    continue
                for nn in range(1, args.max_nn + 1):
                    stem = f"{m.group(1)}_quilt_{m.group(2)}__{m.group(3)}__{nn:02d}"
                    out.add(f"modules/d01_{env}/quilts/base/{stem}")
                    for mo in sorted(mods):
                        out.add(f"modules/d01_{env}/quilts/encounters/{stem}_{mo}")
                        out.add(f"modules/d01_{env}/quilts/base/{stem}_{mo}")
                    for mp in sorted(modpairs):
                        out.add(f"modules/d01_{env}/quilts/encounters/{stem}_{mp}")
        # 3. shape x edges across every quilt directory, with mods
        for h in sorted(heads):
            shape = h.split("_quilt_", 1)[1].split("__", 1)[0]
            sub = ("entrances", "exits", "saferooms") if shape in (
                "entrance", "exit", "saferoom") else ("base", "encounters")
            for nn in range(1, args.max_nn + 1):
                for d in sub:
                    stem = f"{h}__{nn:02d}"
                    out.add(f"modules/d01_{env}/quilts/{d}/{stem}")
                    for mo in sorted(mods):
                        out.add(f"modules/d01_{env}/quilts/{d}/{stem}_{mo}")
        # 3. hazards / arenas / rooms
        for nn in range(1, 6):
            out.add(f"modules/d01_{env}/arena/{env}_arena{nn:02d}")
            for hz in sorted(hazards | {"template"}):
                out.add(f"modules/d01_{env}/colosseum/{env}_colosseum_{nn:02d}_{hz}")
        for nn in range(1, args.max_nn + 1):
            for mode in ("adventure", "adventure_template", "boss", "boss_template",
                         "adventure_1", "adventure_1_template", "adventure_2",
                         "adventure_2_template", "adventure_3", "adventure_3_template"):
                out.add(f"modules/d01_{env}/room_{env}_floor_{nn:02d}_{mode}")
            for mode in ("adventure_1", "adventure_2", "adventure_3"):
                out.add(f"modules/d01_{env}/room_{env}_floor_{mode}")
        out.add(f"modules/d01_{env}/room_dummy")

    # menu / hub extras
    for x in ENVS + ("tutorial",):
        out.add(f"modules/menu/loadout_{x}")
    for x in ("teleport", "tutorial_room", "tutorial_room_walls"):
        out.add(f"modules/d01_hub_room/{x}")

    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"resolved level names : {len(names)}")
    print(f"shapes {len(shapes)} edges {len(edges)} mods {len(mods)} "
          f"hazards {len(hazards)}")
    print(f"candidates           : {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
