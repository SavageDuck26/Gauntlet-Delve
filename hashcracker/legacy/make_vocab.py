#!/usr/bin/env python3
"""
Regenerate the derived word lists the cracker's slot patterns use.

These are all derived from the current bundle manifest + overlay, so they must
be rebuilt after every merge (otherwise sweeps run against a stale vocabulary).

Writes to data/vocab/:
    prefixes.txt    first token of every resolved effects/ name  (cha, wep, ...)
    units.txt       unit leaf stems + their tokens               (particle mid slot)
    events.txt      event/suffix tokens from particles + anim events + flow
    top_dirs.txt    most common directories of resolved names
    top_tokens.txt  most common leaf tokens of resolved names
    unit_dirs.txt   full unit paths (animation dir slot)
    clip_words.txt  animation-ish words (clip slot)
    envs.txt        crypt/caves/lava/hub_room/common
    classes.txt     warrior/valkyrie/wizard/elf/necromagus
    known.txt       every resolved name (mutate --names)

Usage:
    python3 make_vocab.py [--csv ...] [--overlay ...] [--lua ...] [--out ...]
"""
import argparse
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(HERE / ".." / ".." / "Data"
                                         / "bundle_manifest" / "04_bundle_resources.csv"))
    ap.add_argument("--overlay", default=str(HERE / ".." / ".." / "Data"
                                             / "resource_name_overlay.json"))
    ap.add_argument("--lua", default=str(Path.home() / ".local/share/Steam"
                                         / "steamapps/common/Gauntlet"
                                         / "Gauntlet-Source-DO_NOT_EDIT"))
    ap.add_argument("--out", default=str(HERE / "data" / "vocab"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(args.csv, newline="", encoding="utf-8")))
    overlay = json.loads(Path(args.overlay).read_text()) if Path(args.overlay).exists() else {}
    names = [r["name"] for r in rows if r["name"]] + list(overlay.values())
    names = sorted(set(names))

    prefixes = collections.Counter()
    units, events = set(), set()
    top_dirs, top_toks = collections.Counter(), collections.Counter()

    for n in names:
        d, _, leaf = n.rpartition("/")
        top_dirs[d] += 1
        top_toks.update(leaf.split("_"))
        if n.startswith(("effects/", "effects_ui/")):
            prefixes[leaf.split("_")[0]] += 1
            events.update(leaf.split("_")[1:])

    unit_dirs, clip = [], set()
    for r in rows:
        if r["type"] == "unit" and r["name"]:
            unit_dirs.append(r["name"])
            units.add(r["name"].rpartition("/")[2])
            units.update(r["name"].rpartition("/")[2].split("_"))
        if r["type"] == "animation" and r["name"]:
            clip.update(r["name"].rpartition("/")[2].split("_"))

    lua = Path(args.lua)
    if lua.is_dir():
        ev = lua / "lua" / "generated" / "animation_events.lua"
        if ev.exists():
            txt = ev.read_text(errors="ignore").lower()
            for s in re.findall(r'"([a-z0-9_]{2,60})"', txt):
                events.add(s)
                events.update(s.split("_"))
                clip.add(s)
                clip.update(s.split("_"))
        for p in lua.rglob("*.lua"):
            for s in re.findall(r'animation[_a-z]*\s*=\s*"([a-z0-9_]{2,60})"',
                                p.read_text(errors="ignore").lower()):
                clip.add(s)
                clip.update(s.split("_"))

    def dump(name, values, cap=None):
        vals = [v for v in values if v and len(v) > 1]
        if cap:
            vals = vals[:cap]
        (out / name).write_text("\n".join(vals) + "\n")
        print(f"  {name:16s} {len(vals)}")

    dump("prefixes.txt", sorted(prefixes))
    dump("units.txt", sorted(units))
    dump("events.txt", sorted(events))
    dump("top_dirs.txt", [d for d, _ in top_dirs.most_common(300)])
    dump("top_tokens.txt", [t for t, _ in top_toks.most_common(500)])
    dump("unit_dirs.txt", sorted(set(unit_dirs)))
    dump("clip_words.txt", [w for w, _ in collections.Counter(clip).most_common(250)])
    dump("envs.txt", ["crypt", "caves", "lava", "hub_room", "common"])
    dump("classes.txt", ["warrior", "valkyrie", "wizard", "elf", "necromagus"])
    dump("known.txt", names, cap=None)
    print(f"written to {out}/")


if __name__ == "__main__":
    main()
