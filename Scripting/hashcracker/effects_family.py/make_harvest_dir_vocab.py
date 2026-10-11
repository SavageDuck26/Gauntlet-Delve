#!/usr/bin/env python3
"""
Directories the harvest knows and the resolved names do not (FINDINGS.txt 55).

A name is `<directory><leaf>`, and every sweep so far used the 368 directories
that appear in *resolved* names.  But a directory only enters that set once one of
its resources is named, so a directory whose resources are all still unresolved is
invisible - and every token sweep is blind to it by construction.

The depot harvest does print those directories.  Its runs have no delimiters, so
most of what it yields is glued artefact (`acharacters/avatar_elf/animations/` is
`a` + a real path), but anchoring on a known dir and taking the suffix cleans it:

    characters/hydra/animations/          characters/grunt_wretch/animations/
    characters/dragon/abilities/          characters/grunt_brute/animations/
    characters/ghost_mother/animations/   characters/avatar_elf/elf_itemsets/set01/
    blocks/d01_crypt/corridor/            blocks/d01_hub_room/entrances/

Artefacts that survive the filter are harmless: a sweep over them simply finds
nothing, so the GPU does the final filtering for free.

    python3 tools/make_harvest_dir_vocab.py [--out DIR]
"""
import argparse
import collections
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
COMP = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "hdir"))
    ap.add_argument("--max-parts", type=int, default=4)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw = [l.strip() for l in (HC / "data" / "vocab" / "leaves" /
                               "dirs_harvested.txt").read_text().splitlines()
           if l.strip()]
    rd = set((HC / "work" / "tokcombo" / "dirs.txt").read_text().split())
    tok = set((HC / "work" / "tokcombo" / "tok.txt").read_text().split())
    anchors = sorted({d for d in rd} | {d.split("/")[0] + "/" for d in rd})

    cand = collections.Counter()
    for s in raw:
        if ":" in s:
            continue
        for a in anchors:
            i = s.find(a)
            if i < 0:
                continue
            rest = s[i:]
            parts = [p for p in rest.split("/") if p]
            if not parts or len(parts) > args.max_parts:
                continue
            if not all(COMP.match(p) for p in parts):
                continue
            if parts[-1] not in tok:          # the parent must be a word the game uses
                continue
            cand[rest.rstrip("/") + "/"] += 1

    new = sorted(d for d in cand if d not in rd)
    (out / "dirs.txt").write_text("\n".join(new) + ("\n" if new else ""))
    (out / "patterns_d1.txt").write_text("\n".join(f"{d}%m" for d in new) + "\n")
    (out / "patterns_d2.txt").write_text("\n".join(f"{d}%a_%b" for d in new) + "\n")
    (out / "patterns_d3.txt").write_text("\n".join(f"{d}%a_%b_%c" for d in new) + "\n")
    (out / "patterns_d4.txt").write_text("\n".join(f"{d}%a_%b_%c_%d" for d in new) + "\n")
    tops = collections.Counter(d.split("/")[0] for d in new)
    print(f"harvest dirs {len(raw):,}  known {len(rd):,}  NEW {len(new):,}")
    print("  by top level:", tops.most_common(10))
    for d in new[:12]:
        print("   ", d)
    print(f"  d2 <dir>%a_%b           {len(new) * len(tok) ** 2:,}")
    print(f"  d3 <dir>%a_%b_%c        {len(new) * len(tok) ** 3:,}")


if __name__ == "__main__":
    main()
