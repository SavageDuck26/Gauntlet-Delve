#!/usr/bin/env python3
"""
Purpose-built vocabularies for the dungeon-tile level family.

Tiles are the biggest remaining chunk of the `.level` targets (section 43): the
unresolved levels' nearest resolved neighbours by body size are almost all
`caverock_8c_8c_*` / `lavarock_8c_8c_*` and `quilt blackbox`, i.e. the level set
is missing *tiles*, not rooms.

The shape is fixed and small:

    modules/d01_<env>/dungeon_tiles/<rock>_<dims>_<a>_<b>_<c>_<d>_<nn>[_corridor]

    rock    lavarock 52, caverock 19 resolved - and *nothing* for crypt, which is
            exactly where the crypt level targets are
    dims    always 8c_8c where resolved
    quads   four letters; resolved ones use {u,g,w,c,d} in groups 0/1 and
            {g,u,c} in groups 2/3, i.e. a small directional alphabet
    nn      01, 02 resolved
    tail    `_corridor` on one resolved name

So the whole family is enumerable: rocks x dims x quads x nn x tail is ~1e10 at
worst and ~1e8 for the resolved dims - seconds on the GPU.

    python3 tools/make_tile_vocab.py [--out data/vocab/tile] [--letters x] [--quad-cap N]
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

TILE = re.compile(r"^modules/d01_([a-z_]+)/dungeon_tiles/([a-z0-9_]+)$")
# rock stems: the ones we have plus the obvious siblings (crypt has none resolved)
ROCKS = ["lavarock", "caverock", "cryptrock", "hubrock", "rock", "dungeonrock",
         "levelrock", "crypt_rock", "cave_rock", "lava_rock", "crypttile",
         "crypttiles", "tile", "crypt"]
DIMS = ["8c_8c", "4c_4c", "6c_6c", "10c_10c", "12c_12c", "16c_16c", "2c_2c",
        "8c_4c", "4c_8c", "16c_16c"]
# directional letters: observed set + the plausible remainder of such an alphabet
LETTERS = "ugwcdpsbferniatoylxhvqkjmz"
NN = [f"{i:02d}" for i in range(1, 25)]
TAILS = ["", "_corridor"]


def known_names():
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return sorted(n for n in names if n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "tile"))
    ap.add_argument("--letters", default=LETTERS,
                    help="letter alphabet for the four quad groups")
    ap.add_argument("--quad-cap", type=int, default=400000)
    ap.add_argument("--full", action="store_true",
                    help="every letter in every group (26^4), not just the observed per-group alphabets")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen_quads, seen_rocks, seen_dims, seen_nn = set(), set(), set(), set()
    for n in known_names():
        m = TILE.match(n)
        if not m:
            continue
        p = m.group(2).split("_")
        seen_rocks.add(p[0])
        seen_dims.add(f"{p[1]}_{p[2]}")
        if len(p) >= 7:
            seen_quads.add("_".join(p[3:7]))
        if len(p) >= 8:
            seen_nn.add(p[7])

    alpha = list(args.letters)
    # per-position alphabets, observed letters first: groups 0/1 use the full
    # directional set, groups 2/3 never show `w`/`d` in the resolved tiles
    obs_any = sorted({c for q in seen_quads for c in q.replace("_", "")})
    a0 = [c for c in obs_any + alpha if c in set(obs_any) | set(alpha)]
    a0 = list(dict.fromkeys(obs_any + alpha))
    a2 = [c for c in dict.fromkeys(obs_any + alpha) if c not in "wd"]
    quads = set(seen_quads)
    for combo in itertools.product(a0, a0, a2, a2):      # every plausible quad
        quads.add("_".join(combo))
    if args.full:                                        # every letter anywhere
        for combo in itertools.product(alpha, repeat=4):
            quads.add("_".join(combo))
    if len(quads) > args.quad_cap:
        quads = set(sorted(quads)[:args.quad_cap])

    def w(name, vals):
        vals = sorted(v for v in vals if v != "" or name.endswith("tail.txt"))
        (out / name).write_text("\n".join(vals) + ("\n" if vals else ""))
        print(f"  {name:16s} {len(vals):>7}")

    print("tile vocabularies:")
    w("rock.txt", set(ROCKS) | seen_rocks)
    w("dim.txt", set(DIMS) | seen_dims)
    w("quad.txt", quads)
    w("nn.txt", set(NN) | seen_nn)
    w("tail.txt", TAILS)
    print(f"alphabet {len(alpha)}  quads {len(quads)}  "
          f"space(8c_8c, no tail) {len(set(ROCKS) | seen_rocks) * len(quads) * 24 * 3:,}")


if __name__ == "__main__":
    main()
