#!/usr/bin/env python3
"""
Atlas-subdirectory patterns (FINDINGS.txt #48).

Resolved icons sit in a subdirectory named after their atlas:

    hud/controller_icons            (the atlas material/unit)
    hud/controller_icons/button_y   (its icon textures)
    hud/keyboardmouse_icons/lmb

so a texture referenced by an atlas `D/L` is very likely `D/L/<icon>`.  That
directory appears in **no** resolved name, so no directory sweep could ever
contain it - but the reference edges give us the atlas for every unnamed texture
it draws.

Writes one pattern per referring atlas.

    python3 tools/make_atlas_patterns.py [--refs FILE] [--out FILE]
"""
import argparse
import collections
import csv
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
REFS = HC / "work" / "texture_refs.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", default=str(REFS))
    ap.add_argument("--out", default=str(HC / "work" / "atlas" / "patterns.txt"))
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    unresolved = set()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if not r.get("name") and r.get("name_hash") not in ov:
            unresolved.add(r["name_hash"].lower())
    refs = json.loads(pathlib.Path(args.refs).read_text())

    pats = collections.Counter()
    for h, referrers in refs.items():
        if h not in unresolved:
            continue
        for r in referrers:
            if "/" not in r:
                continue
            pats[f"{r}/%m"] += 1          # the atlas's own subdirectory
            pats[f"{r}_%m"] += 1          # or a suffix of the atlas name
            d, _, leaf = r.rpartition("/")
            pats[f"{d}/{leaf}/%m_%n"] += 1
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sorted(pats)) + "\n")
    print(f"referring atlases {len(pats)}  patterns -> {out}")
    for p in sorted(pats)[:8]:
        print("   ", p)


if __name__ == "__main__":
    main()
