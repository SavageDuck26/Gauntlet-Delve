#!/usr/bin/env python3
"""Name an unresolved *unit* from the asset names inside its own body (FINDINGS 65).

A Stingray unit body embeds the names of its material nodes (`m_crypt_railing_01`), its
sections and walkable zones (`s_crypt_railing_straight_2c`, `z_platform_walkable_01`) as
plain ASCII.  Those are the meshes the level artist built the piece from, so the *unit* is
named after them - the game's own blocks are `blocks/<level>/<family>/<geom>[_2c|_4c]`
(`blocks/d01_caves/floors/caverock_floor_4c_2c`, `blocks/d01_lava/floors/lavarock_floor_01`),
and the `_2c`/`_4c` suffixes are the corner-count variants of the same piece.

So for each unresolved unit: read the body, take the `m_`/`s_`/`z_` strings, strip the
prefix, and cross the stems with the directory families that level really uses (read out of
the catalogue, not guessed), both with and without a corner suffix.  Every candidate is a
piece name a level artist would write; the body tells us which one it is about.

Where the bodies live: `~/Documents/Coding/Gauntlet-Export/unresolved/unit/<hash>.unit`
(`export_all_resources.py`).  Everything else comes from the catalogue and the packages.

    python3 tools/unit_guess_by_body.py [--out FILE] [--limit N]
"""
import argparse
import collections
import csv
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
EXPORT = pathlib.Path.home() / "Documents" / "Coding" / "Gauntlet-Export"

RUN = re.compile(rb"[ -~]{4,80}")
ASSET = re.compile(r"^(?:m|s|z)_([a-z0-9_]+)$")
CORNERS = ["", "_1c", "_2c", "_3c", "_4c", "_2c_2c", "_2c_4c", "_4c_2c", "_4c_4c",
           "_8c", "_2c_1c", "_1c_2c"]
# the family directory names the block tree actually uses (FINDINGS 65); the *level's own*
# dirs are read from the catalogue and used in preference.
FAMILIES = ["floors", "walls", "pillars", "rocks", "borders", "stairs", "railings",
            "water", "lava", "ceilings", "props", "details", "ornaments", "gigameshes",
            "decals", "doors", "templates"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/unit_guess.txt")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace")))
    named = [r["name"] for r in rows if r["name"]]
    # level -> the block directories that level really uses
    lvl_dirs = collections.defaultdict(set)
    for n in named:
        p = n.split("/")
        if len(p) >= 3 and p[0] in ("blocks", "props"):
            lvl_dirs[p[1]].add(p[2])
    # every directory a unit really lives in (the real tree, families included)
    unit_dirs = sorted({r["name"].rsplit("/", 1)[0] for r in rows
                        if r["name"] and r["type"] == "unit"})
    units = [r for r in rows if r["type"] == "unit" and not r["name"]]
    if args.limit:
        units = units[: args.limit]

    out = set()
    report = []
    for r in units:
        body = EXPORT / "unresolved" / "unit" / f"{r['name_hash']}.unit"
        if not body.exists():
            continue
        stems = set()
        for m in RUN.finditer(body.read_bytes()):
            hit = ASSET.match(m.group().decode())
            if hit:
                stems.add(hit.group(1))
        if not stems:
            continue
        level = r["package_path"].split("/")[1] if r["package_path"].startswith("modules/") else ""
        # Families: the union across *all* levels, not this level's own.  `railings` only ever
        # appeared under `blocks/d01_lava`, yet the three units this found are
        # `blocks/d01_crypt/railings/...` - a per-level family list is a trap, and it is what
        # made the first two passes return 0.
        fams = sorted({f for fams_ in lvl_dirs.values() for f in fams_} | set(FAMILIES))
        # The leaf is a *node name out of the body*.  `s_`/`z_` strings (sections and walkable
        # zones) are the piece names - the three finds are all literal `s_crypt_railing_*`
        # strings - while `m_` strings are material names and are usually not the unit name.
        # Both are tried, with the trailing number dropped or renumbered, plus corner/side
        # suffixes, because the game's own pair is `m_lavastruct_railing_01` (material) beside
        # `blocks/d01_lava/railings/lavastruct_railing_2c` (unit).
        leaves = set()
        for stem in stems:
            base = re.sub(r"_?\d+$", "", stem)
            for pre in (stem, base, base + "_01", base + "_1"):
                for corner in CORNERS:
                    leaves.add(pre + corner)
        report.append((r["name_hash"], level, sorted(stems)))
        for leaf in leaves:
            for fam in fams:
                out.add(f"blocks/{level}/{fam}/{leaf}")
                out.add(f"props/{level}/{fam}/{leaf}")
            out.add(f"blocks/{level}/{leaf}")
            out.add(f"props/{level}/{leaf}")
            out.add(f"blocks/common/{leaf}")
        for d in unit_dirs:
            for leaf in leaves:
                out.add(f"{d}/{leaf}")
    pathlib.Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"units with asset strings: {len(report)}  candidates {len(out):,} -> {args.out}")
    for h, level, stems in report[:10]:
        print(f"  {h}  [{level}]  {stems[:4]}")


if __name__ == "__main__":
    main()
