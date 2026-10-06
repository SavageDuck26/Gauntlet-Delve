#!/usr/bin/env python3
"""
Bare Lua table keys as resource candidates.

The generated `unit_paths.lua` style lists only cover script-*referenced*
resources, but the settings/managers/gui files are full of bare identifiers
that are exactly resource names:

    lua/managers/perk_settings.lua
        artful_dodger = { ... }          -> achievement_icons/artful_dodger
                                            achievement_icons/artful_dodger_locked

Same story as the ability keys and the quilt layout keys.  Every key found in
`lua/managers`, `lua/settings` and `gui` is emitted verbatim and against the
icon / hud / decal namespaces, with and without the usual suffixes.

    python3 targeted_lua_keys.py [--out FILE]
"""
import argparse
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUA_ROOT = (Path.home() / ".local/share/Steam/steamapps/common/Gauntlet"
            / "Gauntlet-Source-DO_NOT_EDIT")
SCAN = ("lua/managers", "lua/settings", "gui", "lua/generated", "lua/states",
        "lua/dungeon")
KEY = re.compile(r"^\s*([a-z][a-z0-9_]{3,60})\s*=", re.M)
STR = re.compile(r'["\']([a-z][a-z0-9_]{3,60})["\']')
PREFIX = ["achievement_icons", "cape_icons", "equippables_icons", "hud",
          "menu", "decals", "effects", "particles", "gameobjects", "textures",
          "equipment", "ui", "icons", "money", "loading_screens"]
SUB = ["", "_locked", "_icon", "_bg", "_frame", "_01", "_02", "_glow",
       "_disable", "_highlight", "_selected", "_empty", "_bg_02"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/luakeys_c.txt")
    args = ap.parse_args()

    keys = set()
    for sub in SCAN:
        root = LUA_ROOT / sub
        if not root.exists():
            continue
        for p in root.rglob("*.lua"):
            txt = p.read_text(errors="ignore")
            keys.update(KEY.findall(txt))
            keys.update(STR.findall(txt))
    keys = {k for k in keys if len(k) > 3}

    out = set(keys)
    for k in list(keys):
        for pre in PREFIX:
            for s in SUB:
                out.add(f"{pre}/{k}{s}")
        for cls in ("warrior", "elf", "wizard", "valkyrie", "necromagus"):
            out.add(f"equipment/{cls}/{k}")
            out.add(f"equippables_icons/eq_{cls}_{k}")
    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"lua keys {len(keys)} -> candidates {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
