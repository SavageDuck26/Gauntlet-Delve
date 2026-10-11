#!/usr/bin/env python3
"""
Mine harvested *paths* for every resource type (FINDINGS.txt §46).

The raw harvest holds complete paths for the non-level families, not just leaves:

    Acharacters/avatar_warrior/animations/axe_attack_heavy1_sweep
    Dbase:colored_specular:diffuse_map:diffuse_uv_anim:one_bit_alpha
    Hbase:colored_specular:diffuse_map:material_tint_rgb:static_lighting

the leading character being a length/tag byte that happens to be printable, so
each string is tried as-is and with 1-2 leading characters (and, for paths, from
after the first separator) stripped.  Matching is exact so extra variants can
only ever add a true hit, never a false one.

    python3 tools/mine_harvest_paths.py [--raw FILE...] [--write] [-v]
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
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                              # noqa: E402


def unresolved():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("name") or r["name_hash"] in ov:
            continue
        out[r["name_hash"].lower()] = r.get("type", "?")
    return out


ROOT = re.compile(r"(?:modules|characters|props|gameobjects|blocks|effects|"
                  r"materials|core|units|audio|decals|ui|menu|animation|"
                  r"animations|foundation|lua|vehicles)[A-Za-z0-9_/:.]{4,160}")
CHAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+){2,}")


def variants(s):
    """
    Splits of one harvested string that could be a whole resource name.

    The strings are runs of names glued together by the length bytes that
    precede them, which happen to be printable (`..._01chainqmodules/...`), so
    both the leading and the trailing 1-2 characters of each path-shaped
    substring are tried.  Matching is exact, so extra variants can only add a
    true hit.
    """
    out = set()
    for seed in [s] + [m.group(0) for m in ROOT.finditer(s)] \
            + [m.group(0) for m in CHAIN.finditer(s)]:
        for lead in (0, 1, 2):
            if len(seed) <= lead + 5:
                continue
            body = seed[lead:]
            for cut in (0, 1, 2):
                if len(body) > cut + 5:
                    out.add(body[:len(body) - cut] if cut else body)
    if "/" in s:
        out.add(s.split("/", 1)[1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", nargs="*",
                    default=[str(HC / "work" / "harvest2" / "raw.txt")])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    un = unresolved()
    print(f"unresolved hashes {len(un)}")
    hits, tested, seen = [], 0, set()
    for path in args.raw:
        p = pathlib.Path(path)
        if not p.exists():
            print(f"  (missing {p})")
            continue
        with p.open(errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if len(s) < 8:
                    continue
                for c in variants(s):
                    if c in seen:
                        continue
                    seen.add(c)
                    tested += 1
                    h = f"{murmur_hash64(c):016x}"
                    if h in un:
                        hits.append((h, c))
    # hashing is case-insensitive (the engine lowercases), so collapse each hash
    # to its lowercase spelling - that is the form the rest of the corpus uses
    best = {}
    for h, c in hits:
        cur = best.get(h)
        if cur is None or (c.islower() and not cur.islower()):
            best[h] = c
    hits = sorted(best.items())
    print(f"candidates tested {tested:,}  MATCHES {len(hits)}")
    print("by type:", dict(collections.Counter(un[h] for h, _ in hits)))
    for h, c in hits:
        print(f"  {h}  {un[h]:<14} {c}")
    if args.write and hits:
        mf = HC / "matches.tsv"
        with mf.open("a") as fh:
            for h, c in hits:
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
