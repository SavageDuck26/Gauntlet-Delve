#!/usr/bin/env python3
"""
Derive new candidates from names we already have (seed-and-expand).

Families (all bounded, all learned from the corpus rather than guessed):

  tiles    modules/d01_<env>/dungeon_tiles/<style>_<W>c_<H>c_<4 cell letters>_NN
           cell alphabet + style/size set mined from the tile names, then every
           4-letter combination enumerated for each style/size with a few indices
  maps     a block unit implies its map textures and vice versa
           (.../borders/caverock_border_low_2c <-> blocks/d01_caves/caverock_border_low_2c_diff)
           plus _diff/_norm/_spec/_mask/_high swaps and _NN sibling indices
  anims    per unit: clip variants (numbers 1..4, direction words, speed words)
  shaders  <base>:<flag>[:<flag>] permutations - flag vocabulary mined from every
           colon-bearing name (diffuse_map, one_bit_alpha, flipbook_animation, ...)

    python3 generators/seed_derive.py --seeds FILE --out FILE [--cap N]
"""
import argparse
import collections
import csv
import itertools
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
DIG = REPO / "Scripting/GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest/04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

TILE = re.compile(r"^modules/(d01_[a-z_]+)/dungeon_tiles/([a-z0-9]+)_(\d+c)_(\d+c)_"
                  r"([a-z])_([a-z])_([a-z])_([a-z])_(\d+)$")
MAPS = ("_diff", "_norm", "_spec", "_mask", "_high", "_illum", "_alpha", "_glow")
SPEED = ["walk", "run", "jog", "sprint", "fast", "slow", "sneak", "strafe"]
DIRS = ["left", "right", "forward", "backwards", "backward", "in", "out"]


def known_names(seeds_file=None):
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["name"]:
            names.add(r["name"])
    if seeds_file:
        names |= {l.split("\t", 1)[1].strip() for l in
                  Path(seeds_file).read_text().splitlines() if "\t" in l}
    return names


def derive_tiles(names):
    styles, cells = collections.Counter(), collections.Counter()
    for n in names:
        m = TILE.match(n)
        if not m:
            continue
        env, style, w, h, a, b, c, d, _i = m.groups()
        styles[(env, style, w, h)] += 1
        cells.update([a, b, c, d])
    alpha = "".join(sorted(set(cells) | {"g", "u", "x", "e", "i", "o"}))
    out = set()
    for (env, style, w, h), _n in styles.items():
        for combo in itertools.product(alpha, repeat=4):
            for i in range(1, 5):
                out.add(f"modules/{env}/dungeon_tiles/"
                        f"{style}_{w}_{h}_{'_'.join(combo)}_{i:02d}")
    return out


def derive_maps(names):
    out = set()
    for n in names:
        if not n.startswith(("blocks/", "props/")):
            continue
        segs = n.split("/")
        leaf = segs[-1]
        dirs = ["/".join(segs[:-1])] + (["/".join(segs[:2])] if len(segs) >= 3 else [])
        for d in dirs:
            for suf in MAPS:
                out.add(f"{d}/{leaf}{suf}")
        for suf in MAPS:
            if not leaf.endswith(suf):
                continue
            base = leaf[: -len(suf)]
            for d in dirs:
                for s2 in MAPS:
                    out.add(f"{d}/{base}{s2}")
            m = re.search(r"_(\d{1,2})$", base)
            if m:
                stem = base[: m.start()]
                for d in dirs:
                    for i in range(1, 13):
                        out.add(f"{d}/{stem}_{i:02d}")
            break
    return out


def derive_anims(names):
    by_unit = collections.defaultdict(set)
    for n in names:
        if "/animations/" not in n and "/animation/" not in n:
            continue
        d, _, leaf = n.rpartition("/")
        by_unit[d].add(leaf)
    out = set()
    for d, clips in by_unit.items():
        for clip in clips:
            toks = clip.split("_")
            for i, t in enumerate(toks):
                if t.isdigit():
                    pad = len(t) > 1
                    for k in range(1, 5):
                        tok = f"{k:02d}" if pad else str(k)
                        out.add(f"{d}/" + "_".join(toks[:i] + [tok] + toks[i + 1:]))
                if t in SPEED:
                    for s in SPEED:
                        out.add(f"{d}/" + "_".join(toks[:i] + [s] + toks[i + 1:]))
                if t in DIRS:
                    for s in DIRS:
                        out.add(f"{d}/" + "_".join(toks[:i] + [s] + toks[i + 1:]))
            out.add(f"{d}/{clip}_01")
            out.add(f"{d}/{clip}_02")
    return out


def derive_shaders(names, max_len=3):
    """
    `<base>:<flag>[:<flag>...]` permutations.

    The flag list is an ORDERED chain in this engine (e.g.
    `billboard:blend_additive:diffuse_map:soft_particles:vertex_color`), so the
    canonical order is learned from the corpus and then ordered subsets up to
    `max_len` are enumerated for every known base.
    """
    flags, order, bases = collections.Counter(), {}, set()
    for n in names:
        if ":" not in n:
            continue
        parts = n.split(":")
        bases.add(parts[0])
        for i, f in enumerate(parts[1:]):
            flags[f] += 1
            order.setdefault(f, i)
    seq = [f for f in sorted(flags, key=lambda f: (order[f], -flags[f], f))][:40]
    per_base = {}
    for n in names:
        if ":" not in n:
            continue
        parts = n.split(":")
        per_base.setdefault(parts[0], set()).update(parts[1:])
    out = set()
    for b in sorted(bases):
        own = sorted(per_base.get(b, ()), key=lambda f: (order.get(f, 99), f))[:30]
        for L in range(1, min(5, len(own) + 1)):
            for combo in itertools.combinations(own, L):
                out.add(f"{b}:" + ":".join(combo))
    for b in sorted(bases):
        for L in range(1, max_len + 1):
            for combo in itertools.combinations(seq, L):
                out.add(f"{b}:" + ":".join(combo))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", help="TSV of <hash>\\t<name> to include as seeds")
    ap.add_argument("--out", default="/tmp/seed_c.txt")
    ap.add_argument("--cap", type=int, default=30_000_000)
    args = ap.parse_args()

    names = known_names(args.seeds)
    fams = {
        "tiles": derive_tiles(names),
        "maps": derive_maps(names),
        "anims": derive_anims(names),
        "shaders": derive_shaders(names),
    }
    out = set()
    for f, s in fams.items():
        print(f"  {f:8s} {len(s):>9} candidates")
        out |= s
    new = sorted(n for n in out if n not in names)
    if len(new) > args.cap:
        new = new[: args.cap]
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"  {'TOTAL':8s} {len(new):>9} -> {args.out}")


if __name__ == "__main__":
    main()
