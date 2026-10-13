#!/usr/bin/env python3
"""
Test the snapshot harvest's raw strings against every unresolved hash (#45).

`_names.txt` mixes the raw strings with suffix/case mutations of them, so this
strips the generated suffixes back off and treats each surviving string as a
*candidate resource name*: first as-is (the harvest found full paths like
`gameobjects/traps/trap_lava_floor_blades_4c`), then as a leaf under each known
directory and each plausible module path.  Matching is against every unresolved
hash, so it recovers textures/materials/animations/shaders as well as levels.

    python3 tools/mine_harvest_any.py [--names FILE...] [--write] [--max-extra N]
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                              # noqa: E402

SUF = ("_diff", "_norm", "_spec", "_var01", "_01", "_02")
TOP = ("modules", "characters", "props", "gameobjects", "effects",
       "materials", "blocks", "core", "audio", "units", "menu", "ui",
       "decals", "textures")
STR = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_:./-]*$")
LEAF = re.compile(r"^[a-z0-9][a-z0-9_]{2,}$")
KNOWN_LINE = re.compile(r"^[a-zA-Z0-9_:./-]{3,}$")


def unresolved():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("name") or r["name_hash"] in ov:
            continue
        out[r["name_hash"].lower()] = r.get("type", "?")
    return out


def known_dirs():
    """Every directory that appears in a resolved name, plus its leaf forms."""
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    dirs = collections.Counter()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if not n or "/" not in n:
            continue
        d = n.rsplit("/", 1)[0] + "/"
        dirs[d] += 1
    return dirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*",
                    default=[str(HC.parent.parent / d / "_names.txt")
                             for d in ("Gauntlet-PreSlayer-2015-08-11",)])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    un = unresolved()
    print(f"unresolved hashes {len(un)}")

    hits, tested = [], 0
    seen = set()

    def test(cand):
        nonlocal tested
        if cand in seen or not STR.match(cand) or "/" not in cand:
            return
        seen.add(cand)
        tested += 1
        h = f"{murmur_hash64(cand):016x}"
        if h in un:
            hits.append((h, cand))

    for path in args.names:
        p = pathlib.Path(path)
        if not p.exists():
            print(f"  (missing {p})")
            continue
        with p.open(errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if "/" not in line or not KNOWN_LINE.match(line):
                    continue
                parts = [x for x in line.split("/") if x]
                cur = None
                for part in parts:
                    low = part.lower()
                    if low in SUF or len(low) < 3:
                        continue
                    for suf in SUF:                    # harvest also joins
                        if low.endswith(suf) and len(low) > len(suf) + 4:
                            low2 = low[:-len(suf)]
                            if cur:
                                test(cur + low2)
                            break
                    leafish = low.count("_") >= 2 or any(
                        c.isdigit() for c in low)
                    if leafish and cur:
                        test(cur + low)                 # sibling of the dir
                    if not leafish or low.startswith(TOP):
                        cur = low + "/"                 # a directory component
                    test(low)                            # full path as-is
    hits = sorted(set(hits))
    print(f"candidates tested {tested:,}  MATCHES {len(hits)}")
    print("by type:", dict(collections.Counter(un[h] for h, _ in hits)))
    for h, c in hits:
        print(f"  {h}  {un[h]:<10} {c}")
    if args.write and hits:
        mf = HC.parent / "Data" / "matches.tsv"
        with mf.open("a") as fh:
            for h, c in hits:
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
