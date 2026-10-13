#!/usr/bin/env python3
"""
Merge hashcracker's matches.tsv into the Python toolchain's overlay.

Usage:
    python3 merge_matches.py [repo_scripting_dir]     # default: ..
"""
import json
import pathlib
import sys

base = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "..").resolve()
overlay = base / "Data" / "resource_name_overlay.json"
# matches.tsv lives in the hashcracker root (this script is in tools/)
matches = pathlib.Path(__file__).resolve().parent.parent.parent / "Data" / "matches.tsv"

ov = json.loads(overlay.read_text()) if overlay.exists() else {}
before = len(ov)
added = []
for line in matches.read_text().splitlines() if matches.exists() else []:
    if "\t" in line:
        h, name = line.split("\t", 1)
        if h not in ov:
            added.append((h, name))
        ov[h] = name
# NB insertion order, never `sort_keys`: a new find has to land at the *end* of the
# overlay so the merge history reads chronologically (FINDINGS 61.14).
overlay.write_text(json.dumps(ov, indent=2))
print(f"overlay: {before} -> {len(ov)} (+{len(ov) - before})")
for h, n in added:
    print(f"   new {h} {n}")
