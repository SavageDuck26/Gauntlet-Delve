#!/usr/bin/env python3
"""
Are a module's level dependencies stored in alphabetical order?

`resource_packages/boot` holds the dependency packages (e.g.
`modules/d01_crypt/resources`).  If the hashes inside follow name order, every
unresolved level hash is bracketed by its known alphabetical neighbours, which
turns name recovery into a fill-in-the-gap problem instead of a sweep.

Usage:
    python3 pkg_order_check.py [--pkg-name modules/d01_crypt/resources]
"""
import argparse
import csv
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
DIG = REPO / "Scripting/GauntletGameDigging"
sys.path.insert(0, str(DIG))
from list_game_bundles import (decompress_bundle, parse_toc, parse_resources,  # noqa
                               find_install_root)

CSV_PATH = DIG / "bundle_manifest/04_bundle_resources.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg-name", default="modules/d01_crypt/resources")
    ap.add_argument("--type", default="level")
    args = ap.parse_args()

    rows = list(csv.DictReader(CSV_PATH.open()))
    pkg = next(r for r in rows if r["type"] == "package" and r["name"] == args.pkg_name)
    print(f"package {args.pkg_name!r}: bundle {pkg['bundle']} index {pkg['index']} "
          f"body {pkg['body_size']}")

    root = find_install_root()
    _sig, _usz, data = decompress_bundle((root / "contents" / pkg["bundle"]).read_bytes())
    _c, toc = parse_toc(data)
    entries, _end, _ok = parse_resources(data, toc)
    e = next(x for x in entries if x["index"] == int(pkg["index"]))
    body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]

    # every 8-byte window as a little-endian hash
    found = {}          # position -> hash
    for i in range(0, len(body) - 8 + 1, 8):
        v = struct.unpack_from("<Q", body, i)[0]
        found[i] = v
    names = {int(r["name_hash"], 16): r["name"] for r in rows
             if r["type"] == args.type and r["name"]}
    hits = [(pos, h) for pos, h in found.items() if h in names]
    print(f"level hashes found inside the package body: {len(hits)}")
    if not hits:
        return
    seq = [names[h] for _p, h in hits]
    ordered = seq == sorted(seq)
    print(f"appear in ALPHABETICAL order? {ordered}")
    print("first 12 in body order:")
    for n in seq[:12]:
        print("   ", n)
    if not ordered:
        # how many adjacent inversions (i.e. how close to sorted)
        inv = sum(1 for i in range(len(seq) - 1) if seq[i] > seq[i + 1])
        print(f"adjacent out-of-order pairs: {inv} / {len(seq) - 1}")


if __name__ == "__main__":
    main()
