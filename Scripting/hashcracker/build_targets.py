#!/usr/bin/env python3
"""
Rebuild the cracker's target files from the bundle catalogue + overlay.

IMPORTANT: "unresolved" means *the catalogue shows no name for the row*, not
"the hash is absent from resource_name_overlay.json". The catalogue resolves
names from hash_database.json (142k entries) + both overlays, so measuring
against the overlay alone overstates the unknown set by thousands of entries
and sends sweeps off re-deriving names the catalogue already displays.

    python3 build_targets.py            # writes data/vocab/targets_<type>.txt
                                        # and data/vocab/unresolved_targets.txt
    python3 build_targets.py --strict   # only hashes with NO name anywhere
                                        # (catalogue name empty AND not in
                                        #  hash_database.json values)
"""
import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DIG = REPO / "Scripting/GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest/04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
HASHDB = DIG / "hash_database.json"
OUT = HERE / "data/vocab"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="also require the hash to be unknown to hash_database.json")
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text())
    known_names = set(json.loads(HASHDB.read_text()).values()) if args.strict else set()
    rows = list(csv.DictReader(CATALOGUE.open()))

    by = collections.defaultdict(set)
    for r in rows:
        if r["name"]:
            continue                      # the catalogue already names this row
        if r["name_hash"] in ov:
            continue                      # our overlay names it (catalogue not yet refreshed)
        if args.strict and r["name"] in known_names:
            continue
        by[r["type"]].add(r["name_hash"])

    OUT.mkdir(parents=True, exist_ok=True)
    all_missing = set()
    print(f"{'type':22s} {'left(uniq)':>11s}")
    for t, hashes in sorted(by.items(), key=lambda kv: -len(kv[1])):
        miss = sorted(hashes)
        (OUT / f"targets_{t}.txt").write_text("\n".join(miss) + ("\n" if miss else ""))
        all_missing.update(miss)
        print(f"  {t:20s} {len(miss):11d}")
    (OUT / "unresolved_targets.txt").write_text(
        "\n".join(sorted(all_missing)) + ("\n" if all_missing else ""))
    print(f"  {'TOTAL':20s} {len(all_missing):11d}")
    print(f"\noverlay entries : {len(ov)}")
    print(f"targets written to {OUT}")


if __name__ == "__main__":
    main()

