#!/usr/bin/env python3
"""Crack unnamed resources by mutating the names of their siblings.

The missing resource is usually a sibling of the ones we hold: this build has
`menu/arrow_left`, `menu/arrow_right`, `menu/arrow_up_down` and one unnamed green
arrow, so `menu/arrow_up` is a one-token mutation of something we have.  Build
candidates by replacing one token of every known name with any token that appears in
the same directory (and, optionally, any frequent token at all), then check the hash.

    python3 crack_siblings.py --hints /tmp/hint_targets.tsv --type texture
"""
import argparse
import collections
import csv
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hunt_unit_textures import murmur                                   # noqa: E402

EXPORT = pathlib.Path.home() / "Documents/Coding/Gauntlet-Export"
SPLIT = re.compile(r"[_/]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hints", help="TSV of hash<TAB>hint; default: all unresolved")
    ap.add_argument("--type", default="texture")
    ap.add_argument("--global-tokens", type=int, default=1200,
                    help="how many frequent tokens from all names to swap in")
    ap.add_argument("--same-dir-only", action="store_true")
    args = ap.parse_args()

    rows = list(csv.DictReader((EXPORT / "index.tsv").open(newline=""), delimiter="\t"))
    named = sorted({r["name"] for r in rows
                    if r["status"] == "named" and r["type"] == args.type})
    print(f"named {args.type} names: {len(named):,}", flush=True)

    targets = {}
    if args.hints:
        for line in pathlib.Path(args.hints).read_text().splitlines():
            if line.strip() and not line.startswith("hash"):
                p = line.split("\t")
                targets[p[0].strip().lower()] = p[1].strip()
    else:
        for r in rows:
            if r["status"] == "unresolved" and r["type"] == args.type:
                targets[r["name_hash"].lower()] = r["name_hash"][:8]
    print(f"targets: {len(targets)}", flush=True)

    # tokens per directory, and the most frequent tokens overall
    dir_tokens = collections.defaultdict(set)
    freq = collections.Counter()
    for n in named:
        d = "/".join(n.split("/")[:-1])
        for t in SPLIT.split(n):
            if t and not t.isdigit():
                dir_tokens[d].add(t)
                freq[t] += 1
    common = [t for t, _ in freq.most_common(args.global_tokens)]
    print(f"directories: {len(dir_tokens):,}  common tokens: {len(common):,}", flush=True)

    hits = []
    tried = 0
    for h, hint in targets.items():
        for n in named:
            d = "/".join(n.split("/")[:-1])
            swaps = dir_tokens.get(d, set())
            if not args.same_dir_only:
                swaps = set(swaps) | set(common)
            parts = n.split("/")
            for i in range(len(parts)):
                for t in swaps:
                    if t == parts[i]:
                        continue
                    cand = "/".join(parts[:i] + [t] + parts[i + 1:])
                    tried += 1
                    if f"{murmur(cand):016x}" == h:
                        hits.append((h, hint, cand, n))
                        print(f"  HIT  {hint}  {h}  -> {cand}   (sibling of {n})",
                              flush=True)
        print(f"  {hint}: done ({tried:,} candidates so far, {len(hits)} hits)",
              flush=True)

    print(f"\ntried {tried:,}, hits {len(hits)}", flush=True)
    if hits:
        with pathlib.Path('/tmp/sibling_hits.tsv').open('w') as fh:
            fh.write("hash\tname\thint\n")
            for h, hint, cand, _n in hits:
                fh.write(f"{h}\t{cand}\t{hint}\n")
        print("wrote /tmp/sibling_hits.tsv", flush=True)


if __name__ == "__main__":
    main()
