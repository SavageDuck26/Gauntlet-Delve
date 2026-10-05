#!/usr/bin/env python3
"""
Build per-family vocabularies from the SOLVED instances of that family.

The lesson from audio/animations: the winning dictionary for a family is not
general English (or the 173k mined corpus) but the tokens the engine actually
uses for that family - i.e. the words in the names we already solved. This
writes, for each resource type, its solved leaf-token list and its directory
list, ready for `crack --list`.

Usage:
    python3 make_family_vocab.py [--csv ...] [--overlay ...] [--out DIR]
"""
import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

TYPES = ("texture", "material", "particles", "level", "unit", "shader_library",
         "shader", "flow", "animation")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(HERE / "bundle_manifest" / "04_bundle_resources.csv"))
    ap.add_argument("--overlay", default=str(HERE / "resource_name_overlay.json"))
    ap.add_argument("--out", default=str(HERE.parent / "hashcracker" / "data" / "vocab"))
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, newline="", encoding="utf-8")))
    ov = json.loads(Path(args.overlay).read_text()) if Path(args.overlay).exists() else {}
    names = collections.defaultdict(set)          # type -> names
    for r in rows:
        n = r["name"] or ov.get(r["name_hash"])
        if n:
            names[r["type"]].add(n)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for t in TYPES:
        toks = collections.Counter()
        dirs = collections.Counter()
        for n in names.get(t, ()):
            d, _, leaf = n.rpartition("/")
            dirs[d] += 1
            for tok in leaf.split("_"):
                toks[tok] += 1
        (out / f"{t}_tok.txt").write_text("\n".join(w for w, _ in toks.most_common()) + "\n")
        (out / f"{t}_dirs.txt").write_text("\n".join(d for d, _ in dirs.most_common()) + "\n")
        print(f"  {t:16s} solved={len(names.get(t, ())):5d} tokens={len(toks):5d} dirs={len(dirs):5d}")


if __name__ == "__main__":
    main()
