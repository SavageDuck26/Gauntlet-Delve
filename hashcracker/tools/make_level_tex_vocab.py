#!/usr/bin/env python3
"""Level-texture vocabularies: dirs, stems, families, parts, numbers, suffixes.

Read from the catalogue, so it must run *after* `list_game_bundles.py --only
resources` for a round of the level loop to see names found in the previous round.
`tools/make_level_texture_variants.py` uses the same harvest for a candidate file;
this writes the per-position lists that `sweeps/level_tex_hunt.sh` feeds to the
pattern engine instead.

    python3 tools/make_level_tex_vocab.py
"""
import csv
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
V = HC / "data" / "vocab"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"

DIRS = ("blocks/d01_caves/", "blocks/d01_lava/", "blocks/d01_crypt/",
        "blocks/d01_castle/", "blocks/d01_swamp/", "blocks/d01_forest/",
        "props/d01_caves/", "props/d01_lava/", "props/d01_crypt/",
        "props/d01_castle/", "props/d01_swamp/", "props/d01_forest/",
        "props/d01_common/", "props/menu/")
SUF = ["diff", "norm", "normal", "nrm", "spec", "gloss", "glow", "emissive", "mask",
       "ao", "height", "bump", "detail", "cavity", "roughness", "opacity", "alpha",
       "color", "albedo", "basecolor", "diffuse", "d", "n", "nm", "ild", "lava",
       "ice", "moss"]
EXTRA_PARTS = ("wall", "floor", "ceiling", "rock", "rocks", "border", "border_low",
               "border_high", "arch", "doorarch", "pillar", "plinth", "stairs",
               "step", "swatch", "blacktop", "brazier", "bricks", "stonetablet",
               "skulldoor", "stalagmites", "stalactites", "rubble", "debris",
               "edge", "corner", "trim", "cap", "base", "top", "bottom", "small",
               "large", "tall", "short", "wide", "narrow", "broken", "cracked",
               "mossy", "wet", "dry", "stones", "stones_01", "spikes", "vine",
               "vines", "roots", "gravel", "pebbles", "boulder", "crack", "hole")


def main():
    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                              errors="replace")))
    names = [(r["name"].strip(), r["type"]) for r in rows if (r.get("name") or "").strip()]

    stems, fams, parts = set(), set(), set()
    suf_re = re.compile(r"_(" + "|".join(SUF) + r")$")
    for name, typ in names:
        if typ != "texture" or not name.startswith(DIRS):
            continue
        stem = suf_re.sub("", name.split("/")[-1])
        stems.add(stem)
        m = re.match(r"^([a-z]+)_(.*)$", stem)
        if m:
            fams.add(m.group(1))
            parts.add(m.group(2))
    for name, _t in names:
        if name.startswith(DIRS):
            for w in re.split(r"[_/]", name.split("/")[-1]):
                if len(w) >= 4 and not w.isdigit():
                    parts.add(w)
    parts |= set(EXTRA_PARTS)

    nums = [str(i) for i in range(0, 21)] + [f"{i:02d}" for i in range(0, 21)]
    for f, data in (("level_dirs.txt", sorted(DIRS)),
                    ("level_stems.txt", sorted(stems)),
                    ("level_fams.txt", sorted(fams)),
                    ("level_parts.txt", sorted(parts)),
                    ("level_nums.txt", list(dict.fromkeys(nums))),
                    ("level_sufs.txt", SUF)):
        (V / f).write_text("\n".join(data) + "\n")
    print(f"dirs {len(DIRS)}  stems {len(stems)}  fams {len(fams)}  "
          f"parts {len(parts)}  nums {len(set(nums))}  sufs {len(SUF)}")


if __name__ == "__main__":
    main()
