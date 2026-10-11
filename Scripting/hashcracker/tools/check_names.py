#!/usr/bin/env python3
"""Check candidate names straight against the unresolved hashes.

The fastest loop in the project: type (or pipe) names, get hits.  No GPU, no
pattern files - just murmur64 and the unresolved set from the catalogue.

    printf 'equipment/capes/cape_s03_r01\n' | python3 tools/check_names.py
    python3 tools/check_names.py --file cands.txt --write

--write appends the hits to matches.tsv.  Exit code 0 always; the hits are what
matters (a control name that is already resolved never prints).
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                              # noqa: E402


def unresolved() -> dict[str, int]:
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        h = (r.get("name_hash") or "").strip().lower()
        if not h or (r.get("name") or "").strip() or h in ov:
            continue
        out.setdefault(h, int(r.get("body_size") or 0))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    un = unresolved()
    if not args.quiet:
        print(f"unresolved hashes: {len(un):,}", file=sys.stderr)

    cands = list(args.names)
    for f in args.file:
        for line in pathlib.Path(f).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                cands.append(line)
    if not sys.stdin.isatty():
        for line in sys.stdin.read().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                cands.append(line)

    hits = []
    for c in cands:
        h = f"{murmur_hash64(c):016x}"
        if h in un:
            hits.append((h, c))
    print(f"tested {len(cands):,}   HITS {len(hits)}")
    for h, c in hits:
        print(f"  {h}  {c}")
    if args.write and hits:
        mf = HC / "matches.tsv"
        have = set()
        if mf.exists():
            for line in mf.read_text().splitlines():
                if "\t" in line:
                    have.add(line.split("\t")[0].strip().lower())
        with mf.open("a") as fh:
            added = 0
            for h, c in hits:
                if h not in have:
                    fh.write(f"{h}\t{c}\n")
                    added += 1
        print(f"appended {added} to {mf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
