#!/usr/bin/env python3
"""
Per-target name templates for the unresolved `.level` resources (section 43).

For every unnamed level we know two things cheaply: its body size (nearly a
function of its name - `room_crypt_floor_05_adventure` is 6,688 B and a 6,720 B
target is next to it) and, from the depot, what it references.  So instead of one
global vocabulary per family, emit a *pattern per target*:

    <size twin's directory>/<size twin's leaf with the last tokens cut>_%n_%m

`modules/d01_crypt/colosseum/crypt_colosseum_02_mortar` therefore yields

    modules/d01_crypt/colosseum/crypt_colosseum_%n_%m
    modules/d01_crypt/colosseum/crypt_colosseum_%n
    modules/d01_crypt/colosseum/crypt_colosseum_%m
    modules/d01_crypt/colosseum/crypt_colosseum_%n_%m_%x        (north_wing)

which the cracker then runs against every mod/number/wing at once.

    python3 tools/make_target_patterns.py [--out FILE] [--seeds N] [--depth N]
"""
import argparse
import bisect
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"


def load_rows():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        out.append((r, n))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "family" /
                                         "target_patterns.txt"))
    ap.add_argument("--seeds", type=int, default=3,
                    help="how many size-neighbours to take per target")
    ap.add_argument("--window", type=int, default=128)
    ap.add_argument("--depth", type=int, default=2,
                    help="how many trailing tokens to cut when templating")
    ap.add_argument("--type", default="level")
    args = ap.parse_args()

    rows = load_rows()
    known = sorted((int(r["body_size"]), n) for r, n in rows
                   if n and r.get("type") == args.type and n.split("/")[0])
    targets = [(r["name_hash"], int(r["body_size"]),
                (r.get("package_path") or "").split("/")[1:2])
               for r, n in rows if not n and r.get("type") == args.type]
    sizes = [s for s, _ in known]

    patterns = set()
    for _h, sz, envl in targets:
        env = envl[0].replace("d01_", "") if envl else None
        i = bisect.bisect_left(sizes, sz)
        picked = []
        for j in range(max(0, i - 12), min(len(sizes), i + 12)):
            if abs(sizes[j] - sz) <= args.window:
                name = known[j][1]
                if env is None or f"d01_{env}" in name:
                    picked.append((abs(sizes[j] - sz), name))
        picked.sort()
        for _d, seed in picked[:args.seeds]:
            d, _, leaf = seed.rpartition("/")
            pre = d + "/" if d else ""
            toks = leaf.split("_")
            for cut in range(1, args.depth + 1):
                if len(toks) <= cut:
                    continue
                stem = "_".join(toks[:-cut])
                patterns.add(f"{pre}{stem}_%n_%m")
                patterns.add(f"{pre}{stem}_%n")
                patterns.add(f"{pre}{stem}_%m")
                patterns.add(f"{pre}{stem}_%n_%m_%x")
                patterns.add(f"{pre}{stem}_%m_%n")
            patterns.add(f"{pre}{leaf}_%m")
            patterns.add(f"{pre}{leaf}_%n_%m")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sorted(patterns)) + "\n")
    print(f"targets {len(targets)}  patterns {len(patterns)}  -> {out}")
    for p in sorted(patterns)[:10]:
        print("   ", p)


if __name__ == "__main__":
    main()
