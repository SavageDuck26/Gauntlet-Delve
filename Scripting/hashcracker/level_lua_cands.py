#!/usr/bin/env python3
"""
Level/quilt candidates mined from the dungeon Lua.

`lua/dungeon/layouts/*.lua` enumerate the quilt pieces as *bare table keys*
(not strings), e.g.

    lava_quilt_straight__x_e_x_e__01_rocks = { ... }

so string-literal mining alone never sees them.  This mirrors those keys, all
bare keys and all string literals from the whole dungeon Lua tree against every
level directory (`modules/<env>/{quilts/{base,encounters,entrances,exits,
saferooms},arena,colosseum}` and the module root).

Usage:
    python3 level_lua_cands.py [--lua DIR] [--out FILE]
"""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
LUA = (Path.home() / ".local/share/Steam/steamapps/common/Gauntlet"
       / "Gauntlet-Source-DO_NOT_EDIT/lua")
KEY = re.compile(r"^\s*([a-z][a-z0-9_]{2,80})\s*=", re.M)
QUILT = re.compile(r"[a-z0-9_]*_quilt_[a-z0-9_]+")
LIT = re.compile(r'"([a-z][a-z0-9_/]{2,90})"')
ENVS = ("crypt", "caves", "lava", "hub_room")
SUBS = ("quilts/base", "quilts/encounters", "quilts/entrances", "quilts/exits",
        "quilts/saferooms", "arena", "colosseum", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lua", default=str(LUA))
    ap.add_argument("--out", default="/tmp/level_lua.txt")
    args = ap.parse_args()

    toks = set()
    for p in Path(args.lua).rglob("*.lua"):
        t = p.read_text(errors="ignore")
        toks.update(QUILT.findall(t))
        toks.update(KEY.findall(t))
        toks.update(LIT.findall(t))
    toks = {t for t in toks if 3 <= len(t) <= 90}
    leaf = {t.rsplit("/", 1)[-1] for t in toks}

    ov = json.loads(OVERLAY.read_text())
    known = set(ov.values())
    out = set()
    for env in ENVS:
        for sub in SUBS:
            d = f"modules/d01_{env}" + (f"/{sub}" if sub else "")
            for t in leaf:
                out.add(f"{d}/{t}")
    # also keep the raw tokens in case a name carries its own dir
    out |= toks

    new = sorted(n for n in out if n not in known)
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"lua tokens : {len(toks)} (leaves {len(leaf)})")
    print(f"candidates : {len(new)} unknown of {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
