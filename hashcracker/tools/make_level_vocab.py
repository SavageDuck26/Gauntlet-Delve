#!/usr/bin/env python3
"""
Vocabularies for the level pattern sweep.

`lua/dungeon/quilt_builder.lua` gives the exact schema:

    <env>_quilt_<type>__<u>_<r>_<d>_<l>__<variant>

    name:match("^%w+_quilt_(%w+)__([^_]+)_([^_]+)_([^_]+)_([^_]+)__(.*)$")
    local w = #u          -- quilt width  (cells)
    local h = #r          -- quilt height (cells)

so the four `_`-separated groups are the up/right/down/left cell rows, with
`len(u) == len(d) == w` and `len(r) == len(l) == h`.  Each cell is `x` (wall),
`e` (through), `i` (entrance) or `o` (exit); `g` is the normalised walkable
value the builder uses internally and never appears in a name.

Only 38 codes are observed across 425 known pieces, so the sweep enumerates the
alphabet constrained by the width/height rule instead of guessing.

    python3 make_level_vocab.py [--max-len 2]
"""
import csv
import itertools
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOGUE = REPO / "Data/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Data/resource_name_overlay.json"
OUT = HERE.parent / "data/vocab"

QUILT = re.compile(r"^modules/d01_[a-z_]+/quilts/[a-z]+/(crypt|caves|lava)"
                   r"_quilt_([a-z]+)__([a-z_]+)__(\d+)")
CELLS = "xeio"
SHAPES = ["straight", "turn", "mediumroom", "largeroom", "smallroom", "blackbox",
          "entrance", "exit", "saferoom",
          # plausible shapes not yet seen
          "cross", "tee", "junction", "deadend", "corner", "end", "hub",
          "fourway", "start", "finish", "arena"]


def known_level_names():
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["type"] == "level" and r["name"]:
            names.add(r["name"])
    return {n for n in names if n.startswith("modules/")}


def group_sets(observed, restrict3=True):
    """
    Cell-group alphabet per side length.

    Observed side lengths are 1, 2, 3 and 5 cells (never 4).  Lengths 1 and 2
    are enumerated fully; length 3 is trimmed (see `restrict3`); length 5 is
    `xxxxx` plus every single-cell opening, which covers the observed
    `xxxxx`/`xxxxi`/`ixxxx` family without exploding to 4^5 per side.
    """
    g = {1: ["".join(p) for p in itertools.product(CELLS, repeat=1)],
         2: ["".join(p) for p in itertools.product(CELLS, repeat=2)]}
    obs3 = {x for x in observed if len(x) == 3}
    obs5 = {x for x in observed if len(x) == 5}
    if restrict3:
        keep = {"x" + a + "x" for a in CELLS}
        keep |= {a + "x" + b for a in CELLS for b in CELLS}
        keep |= {a + "x" + "x" for a in CELLS} | {"x" + "x" + a for a in CELLS}
        g[3] = sorted(obs3 | keep)
    else:
        g[3] = ["".join(p) for p in itertools.product(CELLS, repeat=3)]
    g[5] = sorted(obs5 | {"x" * 5}
                  | {"x" * i + c + "x" * (4 - i) for i in range(5) for c in "eio"})
    return g


def all_codes(observed, restrict3=True):
    """Every width/height-legal side tuple over the observed side lengths."""
    g = group_sets(observed, restrict3)
    out = []
    for w, gws in g.items():
        for h, ghs in g.items():
            for u in gws:
                for d in gws:
                    for r in ghs:
                        for l in ghs:
                            out.append(f"{u}_{r}_{d}_{l}")
    return out


def main():
    names = known_level_names()
    observed, mods = set(), set()
    for n in names:
        m = QUILT.match(n)
        if not m:
            continue
        observed.add(m.group(3))
        tail = n[len(m.group(0)):]
        for t in tail.split("_")[1:]:
            if t and not t.isdigit():
                mods.add(t)
        # multi-token suffixes too (`keydoorseast_lobbers`, `gold_sand`, ...)
        suf = n.rsplit("__", 1)[-1]
        suf = suf.split("_", 1)[1] if "_" in suf else ""
        if suf and not suf.split("_")[0].isdigit():
            mods.add(suf)

    edges = sorted(set(all_codes(observed)) | observed)
    OUT.mkdir(parents=True, exist_ok=True)

    def dump(name, vals):
        (OUT / name).write_text("\n".join(vals) + "\n")
        print(f"  {name:22s} {len(vals):>8} entries")

    print("level vocabularies (side lengths 1, 2, 3, 5):")
    dump("lvl_env.txt", ["crypt", "caves", "lava"])
    dump("lvl_sub.txt", ["quilts/base", "quilts/encounters", "quilts/entrances",
                         "quilts/exits", "quilts/saferooms"])
    dump("lvl_shape.txt", SHAPES)
    dump("lvl_edge.txt", edges)
    dump("lvl_nn.txt", [f"{i:02d}" for i in range(1, 13)])
    dump("lvl_mod.txt", sorted(mods))
    print(f"observed codes {len(observed)}  -> {len(edges)} candidate codes")


if __name__ == "__main__":
    main()
