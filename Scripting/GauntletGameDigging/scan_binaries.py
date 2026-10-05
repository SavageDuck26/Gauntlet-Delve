#!/usr/bin/env python3
"""
Mine resource-path strings out of the game executables / DLLs.

`gauntlet.exe` and its DLLs load/bundle every resource, so they carry many
resource *paths* as plain ASCII. prepare.py only ever kept the last `/`-segment
of such a string; this tool keeps the WHOLE string and expands it the way the
engine's clean_filepath() would (strip every trailing extension, `\\` -> `/`),
then reports any that hash to an unresolved resource name.

Usage:
    python3 scan_binaries.py [--out bin_strings.txt]
"""
import argparse
import csv
import re
from pathlib import Path

import list_game_bundles as L

RUN = re.compile(rb"[A-Za-z0-9_./\\-]{4,160}")
STRIP_EXT = re.compile(r"\.[A-Za-z0-9_]+$")
PLAUSIBLE = re.compile(r"^[a-z0-9][a-z0-9_./-]{2,159}$")

PREFIXES = ["", "characters/", "gameobjects/", "props/", "equipment/",
            "effects/", "effects_ui/", "menu/", "hud/", "decals/", "blocks/",
            "weapons/", "shaders/", "core/rendering/", "modules/", "units/"]


def variants(s):
    """clean_filepath()-like variants of a raw path string."""
    out = {s}
    t = s
    while True:
        t2 = STRIP_EXT.sub("", t)
        if t2 == t:
            break
        t = t2
        out.add(t)
    for v in list(out):
        segs = v.split("/")
        if len(segs) > 2:
            out.add("/".join(segs[1:]))
    return {v for v in out if PLAUSIBLE.match(v)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bin_strings.txt")
    args = ap.parse_args()

    root = L.find_install_root()
    bindir = root / "binaries"
    csvp = Path(__file__).resolve().parent / "bundle_manifest" / "04_bundle_resources.csv"
    targets = set()
    with open(csvp, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["name"] == "":
                targets.add(int(r["name_hash"], 16))
    print(f"unresolved targets: {len(targets)}")

    cands = set()
    for p in sorted(bindir.iterdir()):
        if p.suffix.lower() not in (".exe", ".dll"):
            continue
        raw = 0
        for m in RUN.finditer(p.read_bytes()):
            s = m.group().decode("ascii", "ignore").replace("\\", "/").lower()
            s = re.sub(r"/+", "/", s).strip("/")
            if len(s) < 3:
                continue
            raw += 1
            if "/" in s:
                for v in variants(s):
                    cands.add(v)
                    for pre in PREFIXES[1:]:
                        cands.add(pre + v)
            else:
                # bare identifier: test verbatim and under every known root
                if PLAUSIBLE.match(s):
                    cands.add(s)
                    for pre in PREFIXES[1:]:
                        cands.add(pre + s)
        print(f"  {p.name}: {raw} path-like strings, {len(cands)} candidates so far")

    out = Path(args.out)
    out.write_text("\n".join(sorted(cands)) + "\n")
    hits = []
    for c in cands:
        h = L.murmur_hash64(c)
        if h in targets:
            hits.append(c)
    print(f"\ncandidates: {len(cands)} -> {out}")
    print(f"DIRECT HITS: {len(hits)}")
    for c in sorted(hits)[:60]:
        print("   ", c)


if __name__ == "__main__":
    main()
