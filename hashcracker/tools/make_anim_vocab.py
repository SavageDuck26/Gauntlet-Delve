#!/usr/bin/env python3
"""
Animation clip candidates from the Lua's event names (FINDINGS.txt #47.9).

An animation clip is named after the ability or state that plays it
(`axe_attack_heavy1_sweep` beside the `axe_attack_heavy1` ability; `beam`,
`buff_windup`), and `lua/generated/animation_events.lua` is the game's own list of
those names - 482 of them.  So: each event name, with and without its `ability_`
prefix, crossed with the clip suffixes the resolved corpus shows
(`_sweep`, `_right`, `_left`, `_back`, `_start`, `_end`, `_windup`, `_loop`,
`_offset`, `_hit`, `_02`..`_05`), against every animation directory.

    python3 tools/make_anim_vocab.py [--out DIR]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
EVENTS = (REPO / "game-source" / "Gauntlet-SourceCode-LUA" / "lua" /
          "generated" / "animation_events.lua")
HARVEST_DIRS = HC / "data" / "vocab" / "leaves" / "dirs_harvested.txt"

SUFS = ["sweep", "right", "left", "back", "start", "end", "windup", "loop",
        "offset", "hit", "idle", "attack", "01", "02", "03", "04", "05"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "anim"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    events = set()
    if EVENTS.exists():
        for m in re.finditer(r'"([a-z0-9_]+)"', EVENTS.read_text(errors="replace")):
            events.add(m.group(1))
    vocab = set(events)
    for e in events:
        stem = e[len("ability_"):] if e.startswith("ability_") else e
        vocab.add(stem)
        vocab |= {f"{stem}_{s}" for s in SUFS}
        vocab |= {f"{e}_{s}" for s in SUFS}
    vocab = sorted(v for v in vocab if v)

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    dirs = collections.Counter()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n and "animation" in n and "/" in n:
            dirs[n.rsplit("/", 1)[0] + "/"] += 1
    if HARVEST_DIRS.exists():
        for d in HARVEST_DIRS.read_text().splitlines():
            if "animation" in d:
                dirs[d.strip()] += 1
    ds = sorted(dirs)

    (out / "vocab.txt").write_text("\n".join(vocab) + "\n")
    (out / "patterns.txt").write_text("\n".join(f"{d}%m" for d in ds) + "\n")
    print(f"events {len(events)}  vocab {len(vocab)}  dirs {len(ds)}  "
          f"candidates {len(vocab) * len(ds):,}")


if __name__ == "__main__":
    main()
