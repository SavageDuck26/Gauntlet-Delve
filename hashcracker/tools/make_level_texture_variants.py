#!/usr/bin/env python3
"""Level texture variants: the gaps in the `caverock_*` / `cavestruct_*` families.

Each level material draws a whole family of textures (`blocks/d01_caves/caverock_set`
draws 39 named and 6 unnamed).  The named members give the grammar - a dir, a stem
family (`caverock`, `cavestruct`, `caves`), a part (`wall`, `floor`, `brazier_01`,
`stonetablet_2c`), and a map suffix, including compound ones (`caverock_skulldoor_
diff_lava`).  So the unnamed members are the combinations that were never shipped
*under a name we hold*: other numbers, other parts, the other map of a pair.

    python3 tools/make_level_texture_variants.py [--out FILE] [--max-number N]

Writes a candidate file for `crack --candidates`.
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
REFS = HC / "work" / "refs_texture.json"
DIRS = ("blocks/d01_caves/", "blocks/d01_lava/", "blocks/d01_crypt/",
        "blocks/d01_castle/", "props/d01_caves/", "props/d01_lava/",
        "props/d01_crypt/", "props/d01_common/", "props/d01_castle/",
        "blocks/d01_swamp/", "props/d01_swamp/")
MAP_SUF = ["diff", "norm", "normal", "nrm", "spec", "gloss", "glow", "emissive",
           "mask", "ao", "height", "bump", "detail", "ild", "cavity", "roughness",
           "opacity", "alpha", "color", "albedo", "basecolor"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "level_tex_cands.txt"))
    ap.add_argument("--max-number", type=int, default=12)
    args = ap.parse_args()

    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                              errors="replace")))
    named = {}
    for r in rows:
        h = (r.get("name_hash") or "").strip().lower()
        n = (r.get("name") or "").strip()
        if h and n:
            named.setdefault(h, (r.get("type"), n))

    # textures of the level namespaces we hold, as the vocabulary
    fam = collections.defaultdict(set)          # dir -> set of stems
    parts = collections.defaultdict(set)        # stem family -> parts
    suf_seen = collections.Counter()
    for _h, (t, n) in named.items():
        if t != "texture" or not n.startswith(DIRS):
            continue
        d, leaf = n.rsplit("/", 1)
        for s in sorted(MAP_SUF + ["diff_lava", "norm_lava", "diff_ice", "norm_ice"],
                        key=len, reverse=True):
            if leaf.endswith("_" + s):
                stem = leaf[: -len(s) - 1]
                fam[d + "/"].add(stem)
                suf_seen[s] += 1
                m = re.match(r"^([a-z]+)_(.*?)(_?\d+[a-z]{0,2})?$", stem)
                if m:
                    parts[m.group(1)].add(m.group(2) + (m.group(3) or ""))
                break

    print(f"level dirs: {len(fam)}  stems: {sum(len(v) for v in fam.values()):,}  "
          f"families: {sorted(parts)}")
    print(f"suffixes seen: {dict(suf_seen.most_common(8))}")

    allparts = sorted({p for v in parts.values() for p in v})
    famnames = sorted(parts)
    nums = [str(i) for i in range(0, args.max_number + 1)] + \
           [f"{i:02d}" for i in range(0, args.max_number + 1)]

    cands = set()
    for d in sorted(fam):
        stems = fam[d]
        for st in stems:
            # the other map of a pair, and the compound themed forms
            for s in MAP_SUF:
                cands.add(f"{d}{st}_{s}")
            for extra in ("lava", "ice", "moss", "bark", "water"):
                cands.add(f"{d}{st}_diff_{extra}")
                cands.add(f"{d}{st}_norm_{extra}")
                cands.add(f"{d}{st}_{extra}_diff")
            # the neighbouring numbers of a numbered stem
            m = re.match(r"^(.*?)_?(\d+)([a-z]{0,2})$", st)
            if m:
                base, _, tail = m.group(1), m.group(2), m.group(3)
                for n in nums:
                    for sep in ("_", ""):
                        cands.add(f"{d}{base}{sep}{n}{tail}_diff")
                        cands.add(f"{d}{base}{sep}{n}{tail}_norm")
            # other parts under the same family
            for fname in famnames:
                if fname not in st:
                    continue
                for p in allparts:
                    for s in ("diff", "norm"):
                        cands.add(f"{d}{fname}_{p}_{s}")
        # cross-family part combinations
        for fname, p in itertools.product(famnames, allparts[:120]):
            for s in ("diff", "norm", "normal"):
                cands.add(f"{d}{fname}_{p}_{s}")
    out = pathlib.Path(args.out)
    out.write_text("\n".join(sorted(cands)) + "\n")
    print(f"candidates: {len(cands):,} -> {out}")


if __name__ == "__main__":
    main()
