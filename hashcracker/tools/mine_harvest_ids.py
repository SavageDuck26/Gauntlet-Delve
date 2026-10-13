#!/usr/bin/env python3
"""
Reconstruct full package paths for level ids harvested from the depot (#45).

`mine_harvest_names.py` works on whole harvest lines; this takes the *clean id
lists* (`work/harvest/{quilt,tile}_ids.txt`, produced with

    grep -hoE '[a-z][a-z0-9]*_quilt_[a-z]+__[a-z0-9_]+' level_lines.txt | sort -u
    grep -hoE '[a-z][a-z0-9]*_8c_8c_[a-z0-9_]+'         level_lines.txt | sort -u

) and hashes each under every plausible package path - both what we knew
(`modules/d01_<env>/quilts/<sub>/`) and what the harvest just taught us
(`lavastruct_*` tiles, `_corridorturn`, `_endless` tails).

    python3 tools/mine_harvest_ids.py [--write] [--all-types]
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

ENVS = ["caves", "crypt", "lava", "hub_room", "common", "all"]
SUBS = ["base", "encounters", "entrances", "exits", "saferooms", "rooms"]


def unresolved(all_types):
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("name") or r["name_hash"] in ov:
            continue
        if not all_types and r.get("type") != "level":
            continue
        out[r["name_hash"].lower()] = r.get("type", "?")
    return out


def path_matrix(ident):
    """Every plausible full package path for one harvested id."""
    out = set()
    env0 = ident.split("_")[0]
    envs = [env0] if env0 in ENVS else []
    envs += [e for e in ENVS if e != env0]
    for e in envs:
        out.add(f"modules/d01_{e}/{ident}")
        out.add(f"modules/d01_{e}/dungeon_tiles/{ident}")
        out.add(f"modules/d01_{e}/prefabs/{ident}")
        for sub in SUBS:
            out.add(f"modules/d01_{e}/quilts/{sub}/{ident}")
    out.add(f"modules/{ident}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*",
                    default=[str(HC / "work" / "harvest" / f)
                             for f in ("quilt_ids.txt", "tile_ids.txt")])
    ap.add_argument("--all-types", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    un = unresolved(args.all_types)
    print(f"unresolved {'all' if args.all_types else 'levels'} {len(un)}  ids {len(args.ids)}")

    tested, hits = 0, []
    seen = set()
    for p in args.ids:
        f = pathlib.Path(p)
        if not f.exists():
            print(f"  (missing {f})")
            continue
        for line in f.read_text(errors="replace").splitlines():
            ident = line.strip().lower()
            if not ident or not re.fullmatch(r"[a-z0-9_]+", ident):
                continue
            for cand in path_matrix(ident):
                if cand in seen:
                    continue
                seen.add(cand)
                tested += 1
                h = f"{murmur_hash64(cand):016x}"
                if h in un:
                    hits.append((h, cand, ident))
    hits = sorted(set(hits))
    print(f"candidates tested {tested:,}  MATCHES {len(hits)}")
    print("by type:", dict(collections.Counter(un[h] for h, _, _ in hits)))
    for h, c, _i in hits:
        print(f"  {h}  {un[h]:<8} {c}")
    if args.write and hits:
        mf = HC.parent / "Data" / "matches.tsv"
        with mf.open("a") as fh:
            for h, c, _i in hits:
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
