#!/usr/bin/env python3
"""
Candidates from the LUA ability tables.

Ability tables in the shipped Lua are keyed by *bare identifiers*
(`ability_selection = { ice_field = {...} }`) - exactly the kind of name that
string-literal mining misses (same story as quilt keys and status effects).
Every ability needs animations, so each key is a strong clip candidate.

For each Lua file we take its unit directory (path minus `.lua`) and generate
`<dir>/animations/<form>` and `<dir>/animation/<form>` for every ability key and
every animation string referenced in that file, in the usual shapes
(`<key>`, `ability_<key>`, `attack_<key>`, `spell_<key>`, `<key>_start`, ...).

Usage:
    python3 lua_ability_cands.py [--lua DIR] [--out FILE] [--up]
"""
import argparse
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

KEY = re.compile(r"^\t{1,4}([a-z][a-z0-9_]{1,40})\s*=", re.M)
ANIM = re.compile(r'([a-z_]*anim[a-z_]*)\s*=\s*"([a-z0-9_]{2,60})"')
STR = re.compile(r'"([a-z][a-z0-9_]{2,60})"')
SUF = ("", "_start", "_end", "_loop", "_windup", "_winddown", "_enter", "_exit",
       "_init", "_idle", "_attack", "_hit", "_01", "_02", "_cast", "_fire")
PRE = ("", "ability_", "attack_", "spell_", "cast_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lua", default=str(Path.home() / ".local/share/Steam"
                                        / "steamapps/common/Gauntlet"
                                        / "Gauntlet-Source-DO_NOT_EDIT"))
    ap.add_argument("--out", default="/tmp/lua_cands.txt")
    args = ap.parse_args()

    root = Path(args.lua)
    out = set()
    files = 0
    for p in root.rglob("*.lua"):
        rel = str(p.relative_to(root))[:-4]
        if not (rel.startswith(("characters/", "equipment/", "gameobjects/",
                                "props/", "foundation/", "ability_units/"))):
            continue
        txt = p.read_text(errors="ignore")
        # the unit dir is the file's own directory
        unit = rel.rpartition("/")[0]
        if not unit:
            continue
        if not any(k in txt for k in ("ability", "animation", "spawn_info")):
            continue
        files += 1
        names = set(KEY.findall(txt))
        names.update(m.group(2) for m in ANIM.finditer(txt))
        for n in names:
            if not n or n.isdigit():
                continue
            for pre in PRE:
                stem = f"{pre}{n}"
                for s in SUF:
                    for base in (f"{unit}/animations", f"{unit}/animation"):
                        out.add(f"{base}/{stem}{s}")
    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"lua files scanned : {files}")
    print(f"candidates        : {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
