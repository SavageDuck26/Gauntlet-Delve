#!/usr/bin/env python3
"""
Vocabularies for the shader_library chain sweep.

A compiled shader library is `<technique>:[flags...]` with the flags sorted
alphabetically, so the unknown ones are subsets of a flag vocabulary.  Our own
flags (mined from the 346 resolved chains) cover the ones this game uses, but the
engine has more - and another BitSquid-family game ships a name list containing
them (filediver for Helldivers 2, `FINDINGS.txt` section 39: 11 of our 92 flags
appear there, and 2 of our flags + `soft_particles`/`one_bit_alpha`/
`global_uv_scale` style names are in its `hashes.txt`).

So: flags = ours + the *engine-plausible* names from that list (filtered to
feature words by keyword), and the cracker's pattern engine does the
combinations:

    %t:%f            %t:%f:%g            %t:%f:%g:%h

    python3 tools/make_shader_vocab.py [--extra <file>] [--out data/vocab]
"""
import argparse
import collections
import csv
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

# words that mark a flag rather than an asset name
KEYWORDS = ("map", "glow", "decal", "color", "colour", "spec", "light", "particle",
            "vertex", "uv", "alpha", "skin", "tangent", "rotation", "pivot",
            "screen", "distort", "soft", "blur", "fade", "fog", "depth",
            "reflect", "refract", "emissive", "illum", "normal", "diffuse",
            "gloss", "rough", "metal", "tint", "wave", "wobble", "jitter",
            "scroll", "flow", "noise", "dither", "dissolve", "silhouette",
            "billboard", "deferred", "forward", "cube", "planar", "mirror",
            "mask", "blend", "shade", "shadow", "outline", "rim", "one_bit",
            "feature", "quality", "lod", "detail", "parallax", "height",
            "occlusion", "anisotrop", "subsurface", "translucen", "opacity")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", default=str(HC / "data" / "vocab"
                                           / "extra_flags_filediver.txt"))
    ap.add_argument("--out", default=str(HC / "data" / "vocab"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)

    tech = collections.Counter()
    ours = set()
    rows = csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                         errors="replace"))
    for r in rows:
        n = r.get("name")
        if r.get("type") != "shader_library" or not n:
            continue
        t, _, f = n.partition(":")
        tech[t] += 1
        for x in f.split(":"):
            if x:
                ours.add(x)

    extra = set()
    p = pathlib.Path(args.extra)
    if p.exists():
        for tok in p.read_text().split():
            tok = tok.strip().lower()
            if tok in ours or len(tok) < 5 or tok.count("_") > 3:
                continue
            if any(k in tok for k in KEYWORDS):
                extra.add(tok)

    def w(name, vals):
        vals = sorted(vals)
        (out / name).write_text("\n".join(vals) + "\n")
        print(f"  {name:26s} {len(vals):>6}")

    w("shader_tech.txt", tech)
    w("shader_flags.txt", ours)
    w("shader_flags_extra.txt", extra)
    w("shader_flags_all.txt", ours | extra)
    print(f"techniques {len(tech)}  own flags {len(ours)}  extra {len(extra)}")
    print(f"space (1/2/3 flags): "
          f"{len(tech)*len(ours|extra):,} / "
          f"{len(tech)*len(ours|extra)**2:,} / {len(tech)*len(ours|extra)**3:,}")


if __name__ == "__main__":
    main()
