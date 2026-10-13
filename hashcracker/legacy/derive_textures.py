#!/usr/bin/env python3
"""
Derive texture-name candidates from the material -> texture reference graph.

We have, for every material, the exact list of texture hashes it references
(tools/materials_database.json). Textures of a material are usually named
<material dir>/<material stem><map suffix>, and cross-asset within the same
directory. This produces a targeted candidate list (much smaller than the
global dir x name x suffix sweep) which `hashcracker crack --candidates` tests.

Usage:
    python3 derive_textures.py [--materials FILE] [--csv FILE] [--overlay FILE]
                               [--suffixes FILE] [--out FILE]
"""
import argparse
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def strip_suffix(leaf, suffixes):
    for s in sorted(suffixes, key=len, reverse=True):
        if s and leaf.endswith(s):
            return leaf[: -len(s)]
    return leaf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--materials", default=str(HERE / ".." / ".." / "scripts"
                                               / "Exports" / "extracted_materials"
                                               / "materials_database.json"))
    ap.add_argument("--csv", default=str(HERE / ".." / ".." / "Data"
                                         / "bundle_manifest" / "04_bundle_resources.csv"))
    ap.add_argument("--overlay", default=str(HERE / ".." / ".." / "Data"
                                             / "resource_name_overlay.json"))
    ap.add_argument("--suffixes", default=str(HERE / "data" / "suffixes.txt"))
    ap.add_argument("--out", default=str(HERE / "data" / "derived_tex.txt"))
    args = ap.parse_args()

    suffixes = [l.strip() for l in Path(args.suffixes).read_text().splitlines() if l.strip()]
    names = {}
    with open(args.csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["name"]:
                names[r["name_hash"]] = r["name"]
    if Path(args.overlay).exists():
        names.update(json.loads(Path(args.overlay).read_text()))

    mats = json.loads(Path(args.materials).read_text())

    # directory -> leaf stems seen in resolved names (for cross-asset candidates)
    bydir = {}
    for n in names.values():
        if "/" in n:
            d, leaf = n.rsplit("/", 1)
            bydir.setdefault(d, set()).add(strip_suffix(leaf, suffixes))

    cands = set()
    known_mats = unknown_mats = 0
    for mh, rec in mats.items():
        refs = [h.lower().replace("0x", "") for _, h in rec.get("info", {}).get("texture_refs", [])]
        mname = names.get(mh)
        if mname and "/" in mname:
            known_mats += 1
            d, stem = mname.rsplit("/", 1)
            stem = strip_suffix(stem, suffixes)
            for s in suffixes:                      # material -> its map variants
                cands.add(f"{d}/{stem}{s}")
            for t in bydir.get(d, ()):              # cross-asset within the same dir
                for s in suffixes:
                    cands.add(f"{d}/{t}{s}")
        else:
            # material name unknown: derive it from any of its *known* textures
            for rh in refs:
                rn = names.get(rh)
                if rn and "/" in rn:
                    d, leaf = rn.rsplit("/", 1)
                    cands.add(f"{d}/{strip_suffix(leaf, suffixes)}")
                    unknown_mats += 1
                    break

    cands = {c for c in cands if 3 <= len(c) <= 120}
    Path(args.out).write_text("\n".join(sorted(cands)) + "\n")
    print(f"materials known={known_mats} derived-from-texture={unknown_mats}")
    print(f"candidates: {len(cands)} -> {args.out}")


if __name__ == "__main__":
    main()
