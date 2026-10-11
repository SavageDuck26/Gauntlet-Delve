#!/usr/bin/env python3
"""Wall/brick cross for the level block textures.

    python3 wallgen.py | python3 tools/check_names.py [--write]

Shape comes straight from the names we hold:

    blocks/<dir>/<family>_<part>[_<map>]          blocks/d01_crypt/crypt_wall_01_diff
    blocks/<dir>/walls/<family>_<part>[_<map>]    blocks/d01_caves/walls/caverock_wall_2c

so the cross is level dirs x families x parts x map suffix, in both shapes.  The
families include the masonry words the held names do NOT use as families yet
(swampstruct, masonry, cobble, marble, basalt ...) - that is where a brick wall
that is not `cavestruct_bricks` would hide.
"""
import pathlib

V = pathlib.Path(__file__).resolve().parent.parent / "data" / "vocab"
read = lambda n: [l.strip() for l in (V / n).read_text().splitlines() if l.strip()]

DIRS = read("level_dirs_all.txt")
FAMS = read("level_fams.txt") + [
    "swampstruct", "struct", "structs", "masonry", "cobble", "cobbles", "cobblestone",
    "rock", "rocks", "cliff", "cliffs", "cavewall", "ruins", "ruin", "bricks", "brick",
    "block", "blocks", "stone", "stones", "stonewall", "stoneswall", "marble", "granite",
    "sandstone", "basalt", "obsidian", "plaster", "stucco", "concrete", "tiles", "tile",
    "floor", "floors", "ground", "grounds", "terrain", "dirt", "gravel", "moss", "mossy",
    "ivy", "vines", "roots", "mud", "slime", "wood", "planks", "beams", "metal", "iron",
    "gold", "bone", "bones", "skull", "skulls", "crystal", "crystals", "ice", "lava",
]
PARTS = read("level_parts.txt")
MAPS = ["", "_diff", "_norm"]

seen = set()
for d in DIRS:
    walls = d + "walls/"
    for f in FAMS:
        for p in PARTS:
            for m in MAPS:
                for base in (d, walls):
                    n = f"{base}{f}_{p}{m}"
                    if n not in seen:
                        seen.add(n)
                        print(n)
            for m in MAPS:
                for base in (d, walls):
                    n = f"{base}{p}{m}"
                    if n not in seen:
                        seen.add(n)
                        print(n)
