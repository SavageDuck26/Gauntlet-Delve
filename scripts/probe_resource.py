#!/usr/bin/env python3
"""
Probe one resource: what it says, and what it references (FINDINGS.txt #51).

A body answers two questions and this prints both:

  * **strings** - printable runs, which is how the shipped Lua, the unit-path
    tables and the shader flags were read.  Some resource types are text and name
    their own contents (`.level` and `.particles` are binary; `.lua` is not).
  * **references** - every 8-byte window matched against the bundle's TOC, i.e.
    the resources it points at, with names where we have them.

    python3 probe_resource.py --name characters/mummy_priest/mummy_priest
    python3 probe_resource.py --name <a state_machine> --strings 40
"""
import argparse
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import list_game_bundles as L                                      # noqa: E402
from hunt_texture_refs import load, windows                        # noqa: E402
from hunt_unit_textures import bundle_toc, find_body, murmur       # noqa: E402

DEPOT = REPO / "Gauntlet-PreSlayer-2015-08-11" / "depot_258972" / "contents"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--type", help="restrict to this resource type")
    ap.add_argument("--strings", type=int, default=25)
    ap.add_argument("--refs", type=int, default=40)
    args = ap.parse_args()
    if not args.name:
        ap.error("--name required")

    rows = load()
    row = next((r for r in rows if r["_name"] == args.name
                and (not args.type or r.get("type") == args.type)), None)
    if not row:
        raise SystemExit(f"name not in catalogue: {args.name}")
    b = row["bundle"]
    path = DEPOT / b
    print(f"{args.name}  [{row.get('type')}]  bundle {b}")
    _sig, _uz, data = L.decompress_bundle(path.read_bytes())
    idx, entry, body = find_body(data, murmur(args.name))
    if body is None:
        raise SystemExit("body not found")
    print(f"entry {idx}  body {len(body):,} bytes  type_hash {entry.get('type_hash'):#x}")

    strs = [s.decode("latin1") for s in re.findall(rb"[ -~]{4,}", body)]
    print(f"\nstrings ({len(strs)}):")
    for s in strs[:args.strings]:
        print(f"    {s}")

    toc = bundle_toc(data, {})
    # match against *every* name we hold, not just this bundle's TOC: a state
    # machine referencing animations lives in a different bundle to them
    global_by_hash = {}
    for r in rows:
        if r["_name"]:
            global_by_hash[int(r["name_hash"], 16)] = (r.get("type"), r["_name"])
    hits = np.unique(windows(body))
    named = []
    for h in hits.tolist():
        if h in global_by_hash:
            named.append(global_by_hash[h])
        elif h in toc:
            named.append((toc[h][0], f"<{h:016x}>"))
    print(f"\nreferences ({len(named)}, globally resolved where possible):")
    seen = set()
    for t, n in named:
        if (t, n) in seen:
            continue
        seen.add((t, n))
        print(f"    {t:<14} {n}")


if __name__ == "__main__":
    main()
