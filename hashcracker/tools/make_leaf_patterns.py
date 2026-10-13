#!/usr/bin/env python3
"""
Directory patterns x harvested leaves for every resource type (FINDINGS.txt #46).

Full harvested paths answered only part of the question.  The rest needs the two
things the harvest *does* give in bulk:

  * the game's real **directory structure** - every path prefix it prints
    (`characters/avatar_warrior/animations/`, `effects_ui/`, ...), which we can
    also take from the resolved names of each type;
  * the game's real **leaf vocabulary** - every last path component it prints.

A resource name is `<directory><leaf>`, so emitting one cracker pattern per
directory and crossing it with the harvested leaf list tests the whole plausible
space on the GPU.  Per type, the directories come from the resolved names of
that type (so a texture directory is tried for textures).

    python3 tools/make_leaf_patterns.py [--out DIR] [--max-leaves N]
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
RAW = HC / "work" / "harvest2" / "raw.txt"

LEAF = re.compile(r"^[a-z0-9][a-z0-9_]{2,64}$")
FRAG = re.compile(r"[A-Za-z0-9_]{3,80}")


def known():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    rows = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            rows.append((r.get("type", "?"), n))
    return rows


def harvested_leaves(max_leaves):
    leaves = collections.Counter()
    with RAW.open(errors="replace") as fh:
        for line in fh:
            for frag in FRAG.findall(line):
                f = frag.lower()
                if LEAF.match(f) and "_" in f:
                    leaves[f] += 1
    top = [l for l, _ in leaves.most_common(max_leaves)]
    return sorted(top)


def harvested_dirs(max_dirs):
    """Every directory prefix the harvest prints (its own directory structure)."""
    dirs = collections.Counter()
    with RAW.open(errors="replace") as fh:
        for line in fh:
            if "/" not in line:
                continue
            low = line.strip().lower()
            parts = [p for p in low.split("/") if p]
            for i in range(1, len(parts)):
                d = "/".join(parts[:i]) + "/"
                if len(d) < 120:
                    dirs[d] += 1
    return sorted(d for d, _ in dirs.most_common(max_dirs))


NUMS = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "1", "2", "3",
        "4", "5", "6"]
SUFS = ["diff", "norm", "spec", "normal", "mask", "glow", "emissive", "tint",
        "color", "alpha", "rough", "metal", "ao", "height", "detail",
        "set01", "set02", "set03", "set04", "set05", "set06", "set07"]


def extend_leaves(leaves):
    """
    Number and suffix siblings of every harvested leaf.

    The first hits (`equippables_icons/<item>_set01` ... `_set07`) show the
    family pattern: one stem, a numbered set suffix.  Harvesting only the exact
    strings misses the *other* numbers of a set and the other map suffixes of a
    stem, so both are generated.
    """
    out = set(leaves)
    for l in leaves:
        m = re.search(r"(\d+)$", l)
        if m:
            out |= {l[:m.start()] + n for n in NUMS}
        else:
            out |= {f"{l}_{n}" for n in NUMS}
            out |= {f"{l}_{s}" for s in SUFS}
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "leaves"))
    ap.add_argument("--max-leaves", type=int, default=300000)
    ap.add_argument("--max-dirs", type=int, default=4000)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = known()
    by_type = collections.defaultdict(collections.Counter)
    for t, n in rows:
        if "/" in n:
            by_type[t][n.rsplit("/", 1)[0] + "/"] += 1
    leaves = harvested_leaves(args.max_leaves)
    (out / "leaf.txt").write_text("\n".join(leaves) + "\n")
    ext = extend_leaves(leaves)
    (out / "leaf_ext.txt").write_text("\n".join(ext) + "\n")
    print(f"harvested leaves {len(leaves):,}  extended {len(ext):,}")

    total = 0
    for t, dirs in sorted(by_type.items()):
        d = [x for x, _ in dirs.most_common(args.max_dirs)]
        if not d:
            continue
        (out / f"dirs_{t}.txt").write_text("\n".join(sorted(d)) + "\n")
        pats = [f"{x}%m" for x in sorted(d)]
        (out / f"patterns_{t}.txt").write_text("\n".join(pats) + "\n")
        print(f"  {t:16s} dirs {len(d):>5}  patterns {len(pats):>5}  "
              f"candidates {len(d) * len(leaves):,}")
        total += len(d) * len(leaves)

    hd = harvested_dirs(20000)
    (out / "dirs_harvested.txt").write_text("\n".join(hd) + "\n")
    (out / "patterns_harvested.txt").write_text(
        "\n".join(f"{x}%m" for x in hd) + "\n")
    (out / "patterns_harvested_small.txt").write_text(
        "\n".join(f"{x}%m" for x in hd[:4000]) + "\n")
    print(f"  harvested dirs   {len(hd):>5}  candidates "
          f"{len(hd) * len(leaves):,}")
    total += len(hd) * len(leaves)
    print(f"total candidates per round {total:,}")


if __name__ == "__main__":
    main()
