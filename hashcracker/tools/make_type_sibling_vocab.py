#!/usr/bin/env python3
"""
Per-type sibling vocabularies from the names we hold (FINDINGS.txt #47).

For a type, the leaf vocabulary is not arbitrary: the leaves we already hold for
that type are the game's own vocabulary for it (animation clips are shared
between units on the same rig - `idle`, `walk`, `axe_attack_heavy1_sweep`), and
the remaining names are mostly *variants* of them (the next number of a series,
another modifier).  So per type, cross

    every leaf we hold for that type, plus its number/suffix siblings,
    with every directory we hold for that type, plus the harvested directories
    whose path mentions the type.

    python3 tools/make_type_sibling_vocab.py [--out DIR]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
HARVEST_DIRS = HC / "data" / "vocab" / "leaves" / "dirs_harvested.txt"
HARVEST_LEAVES = HC / "data" / "vocab" / "leaves" / "leaf.txt"

TYPES = ["animation", "unit", "material", "texture", "shader",
         "shader_library", "particles"]
NUMS = [f"{i:02d}" for i in range(1, 13)] + [str(i) for i in range(1, 13)]
SUFS = ["offset", "offset_02", "offset_03", "hit", "hit_02", "01", "02", "03",
        "var01", "var02", "var03", "diff", "norm", "spec", "normal", "glow"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "sib"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    leaves = collections.defaultdict(collections.Counter)
    dirs = collections.defaultdict(collections.Counter)
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if not n or "/" not in n:
            continue
        t = r.get("type", "?")
        leaves[t][n.rsplit("/", 1)[-1]] += 1
        dirs[t][n.rsplit("/", 1)[0] + "/"] += 1

    hdirs = []
    if HARVEST_DIRS.exists():
        hdirs = [d.strip() for d in HARVEST_DIRS.read_text().splitlines() if d]
    hleaves = []
    if HARVEST_LEAVES.exists():
        hleaves = [l.strip() for l in HARVEST_LEAVES.read_text().splitlines() if l]

    for t in TYPES:
        base = set(leaves[t])
        vocab = set(base)
        for l in base:
            m = re.search(r"(\d+)$", l)
            if m:
                vocab |= {l[:m.start()] + n for n in NUMS}
            else:
                vocab |= {f"{l}_{n}" for n in NUMS}
                vocab |= {f"{l}_{s}" for s in SUFS}
        d = sorted(dirs[t])
        # harvested directories that are plausibly this type
        kw = {"animation": ("animation",), "unit": ("characters", "props",
                                                     "gameobjects", "units"),
              "material": ("material",), "texture": ("",), "shader": ("shader",),
              "shader_library": ("",), "particles": ("effect",)}.get(t, ())
        hd = [x for x in hdirs if any(k and k in x for k in kw)] if kw else []
        all_dirs = sorted(set(d) | set(hd))
        # for texture/animation the harvested leaf vocabulary is the useful one
        if t in ("texture", "animation", "unit", "material"):
            vocab |= set(hleaves)
        vocab = sorted(v for v in vocab if v)
        (out / f"vocab_{t}.txt").write_text("\n".join(vocab) + "\n")
        (out / f"patterns_{t}.txt").write_text(
            "\n".join(f"{x}%m" for x in all_dirs) + "\n")
        print(f"  {t:16s} dirs {len(all_dirs):>5}  vocab {len(vocab):>7}  "
              f"cands {len(all_dirs) * len(vocab):,}")


if __name__ == "__main__":
    main()
