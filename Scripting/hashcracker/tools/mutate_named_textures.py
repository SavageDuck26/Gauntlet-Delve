#!/usr/bin/env python3
"""Spell the missing texture names by mutating every *named* texture name.

The unresolved textures are the last few hundred of ~17.9k.  A missing texture is
almost always a *sibling* of a named one: the other map of a pair (`_diff` ->
`_norm`), another number, another part under the same family, or the same leaf in
a sibling directory.  So instead of inventing vocabulary, mutate the catalogue.

Every candidate is checked with the real murmur64 hash, so a hit is proven, not
guessed.  Nothing here needs GPU or vocabulary.

    python3 tools/mutate_named_textures.py [--json OUT] [--top N] [--write]

--write appends hits to matches.tsv (the overlay is rebuilt by the export).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                              # noqa: E402

NUM_RE = re.compile(r"^\d+$")

MAP_SUF = ["diff", "norm", "n", "normal", "normals", "spec", "mask", "glow",
           "emissive", "illum", "alpha", "atlas", "colour", "color", "tint",
           "detail", "high", "low", "med"]


def load_names():
    """All texture names we know (catalogue + overlay), plus unresolved hashes."""
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    named, unresolved = {}, {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("type") != "texture":
            continue
        h = (r.get("name_hash") or "").strip().lower()
        if not h:
            continue
        n = (r.get("name") or "").strip() or ov.get(h, "").strip()
        if n:
            named[h] = n
        elif h not in ov:
            unresolved.setdefault(h, int(r.get("declared_size") or 0))
    return named, unresolved


def split_name(name: str):
    d, _, leaf = name.rpartition("/")
    return (d + "/" if d else ""), leaf


def variants(name: str, dirs: list[str], suf_vocab: list[str],
             num_vocab: list[str], part_vocab: list[str]):
    """Yield mutated names for one catalogue name."""
    d, leaf = split_name(name)
    toks = leaf.split("_")
    stems = {leaf}
    for k in (1, 2, 3):
        if len(toks) > k:
            stems.add("_".join(toks[:-k]))
    out = set()
    for st in stems:
        for s in suf_vocab:
            out.add(f"{d}{st}_{s}")
            out.add(f"{d}{st}{s}")
        out.add(f"{d}{st}")
        for num in num_vocab:
            out.add(f"{d}{st}_{num}")
            out.add(f"{d}{st}{num}")
    # number permutation on the stem itself: foo_02 -> foo_0k
    if toks and NUM_RE.match(toks[-1]):
        base = "_".join(toks[:-1])
        for num in num_vocab:
            for s in ("", "_diff", "_norm"):
                out.add(f"{d}{base}_{num}{s}")
    # grammar: dir x family x part x number, using this dir's own vocabulary
    if len(toks) >= 2:
        fam = toks[0]
        for p in part_vocab:
            for num in ("01", "02", "03", "04"):
                out.add(f"{d}{fam}_{p}_{num}")
                out.add(f"{d}{fam}_{p}")
    # the same leaf under a sibling directory
    for d2 in dirs:
        if d2 != d:
            out.add(f"{d2}{leaf}")
    out.discard(name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only test first N names")
    args = ap.parse_args()

    named, unresolved = load_names()
    print(f"named textures {len(named):,}   unresolved {len(unresolved):,}")

    # vocabulary harvested from the shipped names
    suf = collections.Counter()
    num = collections.Counter()
    part = collections.Counter()
    dirs = collections.Counter()
    for n in named.values():
        d, leaf = split_name(n)
        if d:
            dirs[d] += 1
        toks = leaf.split("_")
        if len(toks) > 1:
            suf[toks[-1]] += 1
            suf["_".join(toks[-2:])] += 1
        for t in toks:
            if NUM_RE.match(t):
                num[t] += 1
            else:
                part[t] += 1
    for s in MAP_SUF:
        suf[s] += 5
    suf_vocab = [s for s, _c in suf.most_common(120)]
    num_vocab = [n for n, _c in num.most_common(40)]
    part_vocab = [p for p, _c in part.most_common(200)]
    dir_vocab = [d for d, _c in dirs.most_common(200)]
    print(f"vocab: suffix {len(suf_vocab)} number {len(num_vocab)} "
          f"part {len(part_vocab)} dir {len(dir_vocab)}")

    rev = set(unresolved)
    hits = {}
    tested = 0
    names = list(named.items())
    if args.limit:
        names = names[: args.limit]
    for _h, n in names:
        for cand in variants(n, dir_vocab, suf_vocab, num_vocab, part_vocab):
            tested += 1
            ch = f"{murmur_hash64(cand):016x}"
            if ch in rev:
                hits[ch] = cand
    print(f"candidates tested {tested:,}   MATCHES {len(hits)}")
    for h, c in sorted(hits.items()):
        print(f"  {h}  {c}")
    if args.json and hits:
        pathlib.Path(args.json).write_text(json.dumps(hits, indent=2, sort_keys=True))
        print(f"wrote {args.json}")
    if args.write and hits:
        mf = HC / "matches.tsv"
        have = set()
        if mf.exists():
            for line in mf.read_text().splitlines():
                if "\t" in line:
                    have.add(line.split("\t")[0].strip().lower())
        with mf.open("a") as fh:
            added = 0
            for h, c in sorted(hits.items()):
                if h not in have:
                    fh.write(f"{h}\t{c}\n")
                    added += 1
        print(f"appended {added} to {mf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

