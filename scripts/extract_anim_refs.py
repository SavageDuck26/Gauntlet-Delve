#!/usr/bin/env python3
"""
Extract the animation clips each unit actually references.

Every unit ships a `state_machine` sub-resource (type murmur64("state_machine"))
whose body contains the 8-byte Murmur hashes of the animation resources it
plays. The resource shares the unit's name, so a hash found inside it is an
animation of the form `<unit_dir>/<clip>`.

This turns the animation family (1,243 unresolved, previously un-attackable)
into per-unit searches: for unit `characters/necromancer/necromancer` the clip
namespace is the single directory `characters/necromancer/`, so we can brute the
clip with a large vocabulary instead of guessing whole global paths.

Writes:
    data/vocab/anim_dirs.txt     every <unit_dir> that owns animations
    data/vocab/anim_targets.txt  the unresolved animation hashes (crack targets)
    data/vocab/anim_map.json     {unit_dir: [animation hashes]}

Usage:
    python3 extract_anim_refs.py [--csv ...] [--out data/vocab]
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import list_game_bundles as L

STATE_MACHINE = 0xA486D4045106165C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(Path(__file__).resolve().parent
                                         / "bundle_manifest" / "04_bundle_resources.csv"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                         / "hashcracker" / "data" / "vocab"))
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, newline="", encoding="utf-8")))
    anim = {r["name_hash"] for r in rows if r["type"] == "animation"}
    unresolved = {r["name_hash"] for r in rows
                  if r["type"] == "animation" and r["name"] == ""}
    nameof = {}
    for r in rows:
        if r["name"]:
            nameof.setdefault(r["name_hash"], r["name"])

    root = L.find_install_root()
    contents = root / "contents"
    pairs = collections.defaultdict(set)
    sms = 0
    for p in sorted(contents.iterdir()):
        if not (p.is_file() and L.classify_bundle_file(p.name)):
            continue
        _, _, data = L.decompress_bundle(p.read_bytes())
        _, toc = L.parse_toc(data)
        entries, _, _ = L.parse_resources(data, toc)
        for e in entries:
            if e["type_hash"] != STATE_MACHINE:
                continue
            sms += 1
            unit = nameof.get(f'{e["name_hash"]:016x}', f'?{e["name_hash"]:016x}')
            udir = unit.rpartition("/")[0]
            body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]
            for off in range(0, len(body) - 7):
                h = f'{int.from_bytes(body[off:off + 8], "little"):016x}'
                if h in anim:
                    pairs[udir].add(h)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    allh = set().union(*pairs.values()) if pairs else set()
    dirs = sorted(d for d, hs in pairs.items() if hs & unresolved)
    targets = sorted(allh & unresolved)

    (out / "anim_dirs.txt").write_text("\n".join(dirs) + "\n")
    (out / "anim_targets.txt").write_text("\n".join(targets) + "\n")
    (out / "anim_map.json").write_text(json.dumps(
        {d: sorted(hs) for d, hs in sorted(pairs.items())}, indent=2))

    print(f"state_machines scanned : {sms}")
    print(f"units owning anims     : {len(pairs)}")
    print(f"animation refs found   : {len(allh)}")
    print(f"unresolved animations  : {len(unresolved)}")
    print(f"  ...of which referenced: {len(targets)}")
    print(f"unit dirs to search    : {len(dirs)} -> {out}/anim_dirs.txt")


if __name__ == "__main__":
    main()
