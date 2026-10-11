#!/usr/bin/env python3
"""
Expand the Lua source's bare identifiers into full resource names.

Verbatim Lua literals resolve **nothing** that is still missing (11,799 literals
from 927 files, 0 hits), and that is the useful negative result: the shipped
source names animations, effects, quilts and units *relative to the unit they
belong to*.  `preview_hero.lua` does not say

    characters/avatar_valkyrie/animations/move_jog_look_left

it says

    Unit.animation_event(self.unit, "charselect_turn")

i.e. a leaf in the scope of a unit, and `unit_paths.lua` /
`settings_paths.lua` / `unit_path_to_components.lua` hold the unit directory
itself (they are generated lists of literal paths).  So the resource name is
`<known directory> + <leaf from the source>`, and both halves are in the tree -
we just have to join every leaf to every directory.

This is deliberately cheap: the only thing held in memory is the dict of
unresolved (hash -> type), everything else is streamed.

    python3 tools/mine_lua_expand.py [--source DIR] [--out FILE] [-v]

With no `--out` it only prints; with `--out FILE` each `<hash>\t<name>` line is
appended so that `tools/merge_matches.py ..` folds it into the overlay.
"""
import argparse
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent.parent
DIG = HC.parent / "GauntletGameDigging"
sys.path.insert(0, str(DIG))
sys.path.insert(0, str(HERE))
from bundle_tools import murmur_hash64  # noqa: E402
from named_textures import load_names  # noqa: E402

CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
SOURCE = REPO / "game-source" / "Gauntlet-SourceCode-LUA"

QUOTED = re.compile(r'"([^"\n]{2,160})"')
LEAF = re.compile(r'^[a-z0-9_]{4,60}$')
# Lua config tables name resources as **bare keys** (`special_root_bomb = {`),
# so quoted literals alone miss most of the vocabulary.
KEY = re.compile(r'^\s*([a-z0-9_]{4,60})\s*=\s*[{"]')
PATHISH = re.compile(r'^(?:[a-z0-9_]+/)+[a-z0-9_]+$')
# Leaves are joined to directories that hold resources, so the directory pool is
# the set of directories that *known* names already use plus every directory the
# shipped Lua mentions.
SUFFIXES = ["", "_01", "_1"]


def unresolved() -> dict[str, str]:
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r["name_hash"] or "").lower()
            if h and h not in ov:
                out[h] = r["type"]
    return out


def directories(src: pathlib.Path) -> set[str]:
    """Every directory a resource can live in.

    Two sources, because either one alone is a closed loop:

      * the directories *known* names already use (broad and safe), and
      * every directory the shipped Lua spells out - `unit_paths.lua`,
        `settings_paths.lua` and `unit_path_to_components.lua` are generated
        lists of literal paths, so their `dirname`s are authoritative, and
        `characters/<unit>/` gives the per-unit animation roots (the game joins
        unit-relative leaves itself, which is why verbatim literals resolve
        nothing).
    """
    dirs = set()
    for n in load_names(all_types=True).values():
        d = n.rsplit("/", 1)[0] + "/" if "/" in n else ""
        if d:
            dirs.add(d)
            dirs.add(d.rstrip("/"))
    for p in src.rglob("*.lua"):
        for m in QUOTED.finditer(p.read_text(encoding="utf-8", errors="replace")):
            s = m.group(1).strip().lower()
            if not PATHISH.match(s):
                continue
            parts = s.split("/")
            if parts[0] == "characters" and len(parts) > 1:
                # per-unit animation roots, both directory spellings
                dirs.add(f"characters/{parts[1]}/animations/")
                dirs.add(f"characters/{parts[1]}/animation/")
            cur = ""
            for seg in parts[:-1]:
                cur += seg + "/"
                dirs.add(cur)
    return dirs


def leaves(src: pathlib.Path) -> set[str]:
    out = set()
    for p in src.rglob("*.lua"):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            km = KEY.match(line)
            if km:
                v = km.group(1).strip().lower()
                if LEAF.match(v):
                    out.add(v)
            for m in QUOTED.finditer(line):
                s = m.group(1).strip().lower()
                if LEAF.match(s) and "\\" not in s:
                    out.add(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(SOURCE))
    ap.add_argument("--out")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    src = pathlib.Path(a.source)

    un = unresolved()
    dirs = sorted(directories(src))
    lvs = sorted(leaves(src))
    print(f"unresolved {len(un)}   directories {len(dirs)}   leaves {len(lvs)}",
          file=sys.stderr)
    print(f"candidates {len(dirs) * len(lvs) * (len(SUFFIXES) + 1):,}",
          file=sys.stderr)

    seen_sink: set[tuple[str, str]] = set()
    hits: list[tuple[str, str]] = []
    tested = 0

    def check(name: str) -> None:
        # NB no global de-duplication set here: the candidate stream is tens of
        # millions of names and remembering them all is what OOMs a 24 GB box.
        nonlocal tested
        if not name:
            return
        tested += 1
        h = f"{murmur_hash64(name):016x}"
        if h in un and (h, name) not in seen_sink:
            seen_sink.add((h, name))
            hits.append((h, name))
            print(f"HIT {h} {un[h]:16s} {name}", file=sys.stderr)

    for d in dirs:
        pre = d if d.endswith("/") else d + "/"
        for leaf in lvs:
            check(pre + leaf)
            for suf in SUFFIXES[1:]:
                check(pre + leaf + suf)

    print(f"tested {tested:,}   HITS {len(hits)}", file=sys.stderr)
    if a.out:
        with open(a.out, "a", encoding="utf-8") as fh:
            for h, n in hits:
                fh.write(f"{h}\t{n}\n")
        print(f"appended {len(hits)} to {a.out}", file=sys.stderr)
    for h, n in hits:
        print(h, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
