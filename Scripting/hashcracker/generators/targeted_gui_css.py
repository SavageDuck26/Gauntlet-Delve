#!/usr/bin/env python3
"""
UI texture names harvested from the gui style sheets.

`gui/*_css.lua` define widget styles that name their images by *leaf*:

    button_friendslist_item = {
        bg_img         = "button_friendslist",
        bg_img_hover   = "button_friendslist_selected",
        bg_img_selected= "button_friendslist_selected",
    }

and the resource is that leaf under the matching UI directory
(`menu/buttons/button_friendslist` is a resolved name).  So every
image-ish property value in the gui Lua is a texture candidate for the menu/hud
directories, with and without the usual state suffixes.

    python3 targeted_gui_css.py [--out FILE]
"""
import argparse
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUA = Path.home() / ".local/share/Steam/steamapps/common/Gauntlet/Gauntlet-Source-DO_NOT_EDIT"

PROP = re.compile(r'(?:bg_?img[a-z_]*|img|image|icon|texture|texture_?name|'
                  r'sprite|atlas|background|frame|glow|normal|hover|selected|'
                  r'disabled|pressed|offline|locked)\s*=\s*"([a-z][a-z0-9_/]{2,70})"')
ANYSTR = re.compile(r'"([a-z][a-z0-9_]{3,70})"')
DIRS = ["menu", "menu/buttons", "menu/icons", "menu/how_to_play",
        "menu/level_select", "menu/shop", "menu/colosseum",
        "menu/colosseum/grades", "menu/hero_coins", "menu/perk_screen",
        "menu/score_screen", "menu/effects", "menu/loadout", "menu/lobby",
        "hud", "hud/cursors", "hud/icons", "ui", "icons"]
SUF = ["", "_selected", "_hover", "_disabled", "_pressed", "_normal", "_empty",
       "_offline", "_locked", "_glow", "_over", "_bg", "_icon", "_01", "_02",
       "_highlight", "_dark", "_light", "_frame", "_background"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/gui_c.txt")
    ap.add_argument("--all-strings", action="store_true", default=True,
                    help="also use every quoted identifier in the gui Lua")
    args = ap.parse_args()

    vals = set()
    for sub in ("gui", "lua/menu", "lua/states", "lua/managers"):
        root = LUA / sub
        if not root.exists():
            continue
        for p in root.rglob("*.lua"):
            txt = p.read_text(errors="ignore")
            vals.update(PROP.findall(txt))
            if args.all_strings:
                vals.update(ANYSTR.findall(txt))
    vals = {v.strip("/") for v in vals if v}
    leaves = {v.rsplit("/", 1)[-1] for v in vals} | set(vals)

    out = set()
    for v in vals:
        if "/" in v:
            out.add(v)                              # already dir-qualified
        leaf = v.rsplit("/", 1)[-1]
        for d in DIRS:
            for l in {v, leaf}:
                out.add(f"{d}/{l}")
                for s in SUF[1:]:
                    out.add(f"{d}/{l}{s}")
    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"gui values {len(vals)}  leaves {len(leaves)}  candidates {len(out)}")


if __name__ == "__main__":
    main()
