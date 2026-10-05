#!/usr/bin/env python3
"""
Scan every resource body inside every bundle for embedded printable strings.

Some resource types (shaders/DXBC, terrain/level blobs, etc.) may carry their
own name or path as text. This walks all bundles, extracts ASCII runs from each
resource body, and reports any that hash to an *unresolved* resource name —
plus writes the plausible candidates for the Rust hashcracker to expand.

Usage:
    python3 scan_bundle_strings.py [--out candidates.txt]
"""
import argparse
import csv
import re
from pathlib import Path

import list_game_bundles as L

STR = re.compile(rb"[ -~]{4,120}")
PLAUSIBLE = re.compile(r"^[a-z0-9][a-z0-9_./-]{3,110}$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bundle_strings.txt")
    args = ap.parse_args()

    root = L.find_install_root()
    contents = root / "contents"

    # unresolved targets (hash -> type)
    targets = {}
    csvp = Path(__file__).resolve().parent / "bundle_manifest" / "04_bundle_resources.csv"
    with open(csvp, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["name"] == "":
                targets[int(r["name_hash"], 16)] = r["type"]
    print(f"unresolved targets: {len(targets)}")

    strings = set()
    hits = []
    bundles = sorted(p for p in contents.iterdir()
                     if p.is_file() and L.classify_bundle_file(p.name))
    for i, p in enumerate(bundles, 1):
        try:
            _, _, data = L.decompress_bundle(p.read_bytes())
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(bundles)}] {p.name}: {e}")
            continue
        _, toc = L.parse_toc(data)
        entries, _, _ = L.parse_resources(data, toc)
        for e in entries:
            start = e.get("body_start")
            size = e.get("body_size") or 0
            if start is None or size == 0:
                continue
            for m in STR.finditer(data[start:start + size]):
                s = m.group().decode("ascii", "ignore")
                if not PLAUSIBLE.match(s):
                    continue
                strings.add(s)
                h = L.murmur_hash64(s)
                if h in targets:
                    hits.append((s, targets[h]))
        print(f"  [{i}/{len(bundles)}] {p.name}: {len(entries)} res, "
              f"{len(strings)} strings so far")

    Path(args.out).write_text("\n".join(sorted(strings)) + "\n")
    print(f"\ndistinct plausible strings: {len(strings)} -> {args.out}")
    print(f"DIRECT HITS: {len(hits)}")
    for s, t in hits[:40]:
        print(f"  [{t}] {s}")


if __name__ == "__main__":
    main()
