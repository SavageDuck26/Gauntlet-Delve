#!/usr/bin/env python3
"""
Mine resource names straight out of the shipped Lua source (section 43).

The `lua/dungeon/layouts/*.lua` files are *level layouts*: each one opens with

    fillers = {
        path = "modules/d01_crypt/quilts/base/",
        ...
        straight_vert_short = {
            crypt_quilt_straight__e_x_e_x__01_slaves = {},
            crypt_quilt_straight__e_x_e_x__04_sarcophagus_slaves = {},
            ...

i.e. they contain the *literal quilt / tile / room identifiers*, with the
directory they live in.  Hashing `<path>..<identifier>` resolves them exactly -
no guessing, no GPU.  We also try every plausible sub-directory for identifiers
that appear without a nearby `path =` (the identifier itself starts with its
environment, so the only unknown is the sub-directory).

    python3 tools/mine_source_names.py [--source DIR] [--write] [-v]

Without --write it only reports; with --write the new names are appended to
matches.tsv so that `merge_matches.py ..` folds them into the overlay.
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent.parent
DIG = HC.parent / "GauntletGameDigging"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64  # noqa: E402

CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
SOURCE = REPO / "game-source" / "Gauntlet-SourceCode-LUA"

PATH_RE = re.compile(r'path\s*=\s*"([^"]+)"')
STR_RE = re.compile(r'"([^"]{3,120})"')
KEY_RE = re.compile(r'^\s*([a-zA-Z][\w]*)\s*=\s*\{')
QUILT_RE = re.compile(r'^([a-z]+)_quilt_')
TILE_RE = re.compile(r'_8c_8c|_4c_4c|_16c_16c')
SUBS = ["base", "encounters", "entrances", "exits", "saferooms", "rooms"]
ENVS = ["caves", "crypt", "lava", "hub_room", "all", "common"]


def unresolved():
    un = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        h = r["name_hash"]
        if not r["name"] and h not in (json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}):
            un[h.lower()] = r["type"]
    return un


def candidates(text):
    """Every (full_name, evidence) we can derive from one Lua file's text."""
    out = []
    last_path = None
    for line in text.splitlines():
        m = PATH_RE.search(line)
        if m and "/" in m.group(1):
            last_path = m.group(1)
            if not last_path.endswith("/"):
                last_path += "/"
        for s in STR_RE.findall(line):
            if "/" in s and re.fullmatch(r"[a-zA-Z0-9_./]+", s):
                out.append((s, "string"))
        m = KEY_RE.match(line)
        if m:
            ident = m.group(1)
            if last_path and re.fullmatch(r"[a-zA-Z0-9_]+", ident):
                out.append((last_path + ident, "path+key"))
            # identifiers that already name their own environment
            mq = QUILT_RE.match(ident)
            if mq:
                env = mq.group(1)
                for sub in SUBS:
                    out.append((f"modules/d01_{env}/quilts/{sub}/{ident}", "quilt"))
                out.append((f"modules/d01_{env}/{ident}", "quilt-bare"))
            if TILE_RE.search(ident):
                for env in ENVS:
                    out.append((f"modules/d01_{env}/dungeon_tiles/{ident}", "tile"))
                    out.append((f"modules/d01_{env}/resources/{ident}", "tile"))
            if ident.startswith("room_"):
                for env in ENVS:
                    out.append((f"modules/d01_{env}/{ident}", "room"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(SOURCE))
    ap.add_argument("--write", action="store_true",
                    help="append the new names to matches.tsv")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    src = pathlib.Path(args.source)
    un = unresolved()
    print(f"source {src}  unresolved hashes {len(un)}")

    cands = {}
    files = sorted(src.rglob("*.lua")) if src.exists() else []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, how in candidates(text):
            cands.setdefault(name, (how, f.relative_to(src)))
    print(f"lua files {len(files)}  distinct candidate names {len(cands):,}")

    hit = []
    for name, (how, f) in cands.items():
        h = f"{murmur_hash64(name):016x}"
        if h in un:
            hit.append((h, name, how, str(f)))
    hit.sort()
    print(f"MATCHES {len(hit)} / {len(un)} unresolved\n")
    by_type = collections.Counter(un[h] for h, _, _, _ in hit)
    for h, name, how, f in hit:
        print(f"  {h}  {un[h]:<10} {name}   [{how} {f}]")
    if hit:
        print("\nby type:", dict(by_type))
    if args.write and hit:
        mf = HC / "matches.tsv"
        with mf.open("a") as fh:
            for h, name, _, _ in hit:
                fh.write(f"{h}\t{name}\n")
        print(f"appended {len(hit)} to {mf}")


if __name__ == "__main__":
    main()
