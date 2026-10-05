#!/usr/bin/env python3
"""
Rebuild the cracker's target files from the bundle manifest + overlay.

Stale target files silently produce "0 new matches" runs, which is how a whole
family of names (lua paths) stayed unresolved for so long. Always regenerate
before a sweep:

    python3 build_targets.py            # writes data/vocab/targets_<type>.txt
                                        # and data/vocab/unresolved_targets.txt
"""
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MANIFEST = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
OUT = HERE / "data/vocab"


def main():
    ov = json.loads(OVERLAY.read_text())
    rows = list(csv.DictReader(MANIFEST.open()))
    by = collections.defaultdict(set)
    for r in rows:
        by[r["type"]].add(r["name_hash"])

    OUT.mkdir(parents=True, exist_ok=True)
    all_missing = set()
    print(f"{'type':22s} {'resolved':>9s} {'left':>7s}")
    for t, hashes in sorted(by.items(), key=lambda kv: -len(kv[1])):
        miss = sorted(h for h in hashes if h not in ov)
        (OUT / f"targets_{t}.txt").write_text("\n".join(miss) + ("\n" if miss else ""))
        all_missing.update(miss)
        print(f"  {t:20s} {len(hashes) - len(miss):9d} {len(miss):7d}")
    (OUT / "unresolved_targets.txt").write_text(
        "\n".join(sorted(all_missing)) + ("\n" if all_missing else ""))
    print(f"  {'TOTAL':20s} {len(ov):9d} {len(all_missing):7d}")
    print(f"\noverlay names : {len(ov)}")
    print(f"targets written to {OUT}")


if __name__ == "__main__":
    main()
