#!/usr/bin/env python3
"""
Universal directory x vocabulary sweep inputs (FINDINGS.txt §47).

Two observations drive this:

  * every resource name is `<directory><leaf>`, and the *directories* are almost
    all known - 47 animation dirs, 157 unit dirs, 109 texture dirs, ... and the
    harvest prints the rest;
  * the missing part is therefore the *leaf vocabulary*, which is exactly what
    the shipped Lua and the harvest are full of.

So this collects, once, every vocabulary we can lay hands on - harvested leaves
(and their number/suffix siblings), every string and identifier in the Lua
source, and the leaves/tokens of the names we already hold - and pairs each with
every known directory (resolved, per type and overall, plus the harvest's own
15 k path prefixes).

    python3 tools/make_universal_vocab.py [--out DIR]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
LUA = REPO / "game-source" / "Gauntlet-SourceCode-LUA"
HARVEST = HC / "work" / "harvest2" / "raw.txt"

STR = re.compile(r'"([^"\n]{3,120})"')
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,60}")
LEAF = re.compile(r"^[a-z0-9][a-z0-9_]{2,64}$")


def lua_vocab():
    out = set()
    if not LUA.is_dir():
        return out
    for f in LUA.rglob("*.lua"):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for s in STR.findall(text):
            v = s.strip().lower()
            if LEAF.match(v) or "/" in v:
                out.add(v)
                if "/" in v:
                    out.add(v.rsplit("/", 1)[-1])
        for m in IDENT.findall(text):
            v = m.lower()
            if LEAF.match(v) and "_" in v:
                out.add(v)
    return out


def harvest_leaves():
    out = set()
    if not HARVEST.exists():
        return out
    with HARVEST.open(errors="replace") as fh:
        for line in fh:
            for frag in line.strip().split("/"):
                v = frag.strip().lower()
                if LEAF.match(v) and "_" in v:
                    out.add(v)
    return out


def resolved():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    names = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            names.append((r.get("type", "?"), n))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "uni"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    names = resolved()
    vocab = lua_vocab()
    vocab |= harvest_leaves()
    toks = set()
    for _t, n in names:
        vocab.add(n.rsplit("/", 1)[-1])
        for t in re.split(r"[^a-z0-9]+", n.lower()):
            if len(t) > 2:
                toks.add(t)
    vocab |= toks
    vocab = sorted(v for v in vocab if v)
    (out / "vocab.txt").write_text("\n".join(vocab) + "\n")

    dirs = collections.Counter()
    for _t, n in names:
        if "/" in n:
            dirs[n.rsplit("/", 1)[0] + "/"] += 1
    all_dirs = sorted(dirs)
    (out / "dirs_resolved.txt").write_text("\n".join(all_dirs) + "\n")
    (out / "patterns_resolved.txt").write_text(
        "\n".join(f"{d}%m" for d in all_dirs) + "\n")
    print(f"vocab {len(vocab):,}  resolved dirs {len(all_dirs):,}  "
          f"candidates {len(vocab) * len(all_dirs):,}")


if __name__ == "__main__":
    main()
