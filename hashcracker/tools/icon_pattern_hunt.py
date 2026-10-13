#!/usr/bin/env python3
"""
Brute-force the *pattern* for the lobby/shop icon names.

The vocabulary was never the problem: `named/localization/game_strings.strings`
holds every English name the icons are built from ("More of Thor", "The Prize",
"Skin of Dariokh", "Wrath of Tesla", "Frozen Dagger", "Dark Fang Knot", ...), and
the two icons we do hold pin the glue rule ("More of Thor" -> `moreofthor`, so
`hud/action_icons/warrior_ultimate_moreofthor`).  What is missing is the *shape* the
15 unresolved icon plates use, so this crosses the glue vocabulary with every
plausible directory x prefix x hero form and streams the lot into
`tools/check_names.py`.

    python3 tools/icon_pattern_hunt.py | python3 -m ... check_names.py --write

Streams; memory flat.
"""
import pathlib
import re
import sys

STRINGS = pathlib.Path.home() / "Documents" / "Coding" / "Gauntlet-Export" / \
    "named" / "localization" / "game_strings.strings"

HERO = ["warrior", "elf", "wizard", "valkyrie", "necromagus", "lizard"]
DIRS = ["equippables_icons/", "hud/action_icons/", "menu/shop/", "hud/", "menu/",
        "equipment/", "cape_icons/", "talisman_icons/", "item_icons/",
        "potion_icons/", "relic_icons/", "shop/", "icons/", ""]
PRE = ["", "talisman_", "item_", "icon_", "relic_", "eq_", "shop_", "potion_",
       "ultimate_", "ability_", "spell_", "cape_", "equip_", "misc_"]
SUF = ["", "_icon", "_illu", "_diff", "_large", "_small", "_ability"]


def glues() -> set:
    raw = STRINGS.read_bytes()
    out = set()
    for v in raw.split(b"\x00"):
        v = v.strip()
        if not v:
            continue
        try:
            t = v.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not (2 <= len(t) <= 60):
            continue
        if any(ch.isdigit() for ch in t) or any(ord(c) > 126 for c in t):
            continue
        toks = re.findall(r"[A-Za-z]+", t)
        if not toks:
            continue
        g = "".join(x.lower() for x in toks)
        u = "_".join(x.lower() for x in toks)
        if 4 <= len(g) <= 40:
            out.add(g)
            out.add(u)
    return out


def main() -> int:
    gl = glues()
    print(f"{len(gl)} glues", file=sys.stderr)
    out = sys.stdout.write
    n = 0
    for g in gl:
        for d in DIRS:
            for p in PRE:
                for s in SUF:
                    out(f"{d}{p}{g}{s}\n")
                    n += 1
                for h in HERO:
                    out(f"{d}{h}_{p}{g}\n")
                    out(f"{d}{p}{g}_{h}\n")
                    n += 2
    print(f"{n} candidates", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
