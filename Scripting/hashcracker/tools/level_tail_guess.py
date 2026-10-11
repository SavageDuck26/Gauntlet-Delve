#!/usr/bin/env python3
"""
Name guesses from exact body-size twins (FINDINGS.txt section 44).

A level body's size is very nearly a function of its name, so two levels with
the *same* size usually differ only in one component (a number, a mod token, a
cell code).  This tool pairs each unresolved level with every resolved level of
the same size (and near sizes), then mutates the twin's *tail* - token
substitutions, insertions, deletions, plural forms, number swaps - hashing each
candidate.  Pure CPU, no GPU needed: ~1e7 candidates.

    python3 tools/level_tail_guess.py [--window 0] [--write] [-v]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
import sys                                                    # noqa: E402
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                        # noqa: E402


def load():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    known, targets = [], {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("type") != "level":
            continue
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            known.append((int(r["body_size"]), n))
        else:
            targets.setdefault(r["name_hash"], int(r["body_size"]))
    return known, targets


def vocab():
    """Tokens that can appear in a level name: names + props + observed mods."""
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    toks = collections.Counter()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if not n:
            continue
        if r.get("type") == "level" or n.startswith(("props/", "gameobjects/",
                                                     "blocks/")):
            for t in re.split(r"[^a-z0-9]+", n):
                if t and not t.isdigit() and len(t) > 1:
                    toks[t] += 1
    return [t for t, _ in toks.most_common(4000)]


def candidates_for(name, vocab, nums):
    """Every near-edit of one resolved level name."""
    d, _, leaf = name.rpartition("/")
    pre = d + "/" if d else ""
    toks = leaf.split("_")
    out = set()
    for i, t in enumerate(toks):
        if not t:
            continue
        for v in vocab:
            if v != t:
                out.add(pre + "_".join(toks[:i] + [v] + toks[i + 1:]))
        out.add(pre + "_".join(toks[:i] + toks[i + 1:]))          # delete
        if re.fullmatch(r"\d+", t):
            for k in nums:
                out.add(pre + "_".join(toks[:i] + [k] + toks[i + 1:]))
        for v in vocab[:600]:
            out.add(pre + "_".join(toks[:i] + [v] + toks[i:]))    # insert
        if not t.endswith("s"):
            out.add(pre + "_".join(toks[:i] + [t + "s"] + toks[i + 1:]))
        elif len(t) > 3:
            out.add(pre + "_".join(toks[:i] + [t[:-1]] + toks[i + 1:]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=0,
                    help="extra bytes of slack when pairing by size")
    ap.add_argument("--max-twins", type=int, default=6)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    known, targets = load()
    bysize = collections.defaultdict(list)
    for s, n in known:
        bysize[s].append(n)
    V = vocab()
    nums = [f"{i:02d}" for i in range(1, 25)] + [str(i) for i in range(1, 13)]
    print(f"resolved levels {len(known)}  targets {len(targets)}  vocab {len(V)}")

    want = {int(h, 16): (h, s) for h, s in targets.items()}
    hits = []
    for h, sz in targets.items():
        seeds = []
        for w in range(args.window + 1):
            seeds += bysize.get(sz + w, [])
            if w:
                seeds += bysize.get(sz - w, [])
        seeds = list(dict.fromkeys(seeds))[:args.max_twins]
        for seed in seeds:
            for c in candidates_for(seed, V, nums):
                if murmur_hash64(c) == int(h, 16):
                    hits.append((h, c, seed))
                    print(f"  *** {h} {sz}B -> {c}   (size twin {seed})")
    print(f"\nverified {len(hits)}")
    if args.write and hits:
        mf = HC / "matches.tsv"
        with mf.open("a") as fh:
            for h, c, _s in hits:
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
