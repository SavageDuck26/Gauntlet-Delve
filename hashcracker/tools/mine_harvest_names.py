#!/usr/bin/env python3
"""
Mine the snapshot string harvest for level names (FINDINGS.txt #45).

Each snapshot directory carries `_names.txt`, a previous session's harvest of
every string found in the *decompressed* bundle bodies plus the binaries.  Plain
grep cannot see those strings because the bundles are zlib-blocked, which is why
the depot looked string-free: the harvest proves the data *does* contain
resource names - and, crucially, these are slash-joined runs of them:

    .../caves_quilt_straight__xx_e_xx_e__05_spider/caves_quilt_...__04_spider/...

So this splits every line on `/`, keeps the fragments that look like level
leaves, rebuilds the plausible full package paths around each (the environment is
usually in the fragment's own prefix), hashes them, and matches.

    python3 tools/mine_harvest_names.py [--lines FILE] [--write] [-v]
"""
import argparse
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

ENVS = ["caves", "crypt", "lava", "common", "hub_room", "all"]
SUBS = ["base", "encounters", "entrances", "exits", "saferooms"]
SUFFIXES = ["_diff", "_norm", "_spec", "_var01", "_01", "_02"]
LEAFISH = re.compile(r"^[a-z0-9][a-z0-9_]{5,}$")
LEVELY = re.compile(r"_quilt_|_8c_8c|_4c_4c|^room_|_colosseum|_arena|_floor|"
                    r"^prefab|blackbox|_tile")


def unresolved():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("name") or r["name_hash"] in ov:
            continue
        out[r["name_hash"].lower()] = r.get("type", "?")
    return out


def variants(frag):
    """Full package paths a leaf fragment could live at."""
    out = set()
    stripped = frag
    for s in SUFFIXES:
        if stripped.endswith(s):
            stripped = stripped[:-len(s)]
    for f in {frag, stripped}:
        if not f:
            continue
        if f.startswith("modules/"):
            out.add(f)
        env = f.split("_")[0]
        out.add(f"modules/d01_{env}/{f}")
        for e in ENVS:
            out.add(f"modules/d01_{e}/{f}")
            for sub in SUBS:
                out.add(f"modules/d01_{e}/quilts/{sub}/{f}")
            out.add(f"modules/d01_{e}/dungeon_tiles/{f}")
            out.add(f"modules/d01_{e}/prefabs/{f}")
        out.add(f"modules/{f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default=str(HC / "work" / "harvest" /
                                           "level_lines.txt"))
    ap.add_argument("--all-types", action="store_true",
                    help="match against every unresolved hash, not just levels")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    un = unresolved()
    if not args.all_types:
        un = {h: t for h, t in un.items() if t == "level"}
    print(f"unresolved {len(un)}  source {args.lines}")

    frags = set()
    for line in pathlib.Path(args.lines).read_text(errors="replace").splitlines():
        for frag in line.split("/"):
            frag = frag.strip().lower()
            if LEAFISH.match(frag) and LEVELY.search(frag):
                frags.add(frag)
    print(f"level-ish fragments {len(frags):,}")

    hits = []
    seen = set()
    for frag in sorted(frags):
        for cand in variants(frag):
            if cand in seen:
                continue
            seen.add(cand)
            h = f"{murmur_hash64(cand):016x}"
            if h in un:
                hits.append((h, cand, frag))
    print(f"candidates tested {len(seen):,}  MATCHES {len(hits)}")
    for h, cand, frag in sorted(hits):
        print(f"  {h}  {un[h]:<8} {cand}")
    if args.write and hits:
        mf = HC.parent / "Data" / "matches.tsv"
        with mf.open("a") as fh:
            for h, cand, _f in hits:
                fh.write(f"{h}\t{cand}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
