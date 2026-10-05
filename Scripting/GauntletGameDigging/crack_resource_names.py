#!/usr/bin/env python3
"""
Brute-force Gauntlet resource names (the <unresolved> rows in
bundle_manifest/03_bundle_resources.txt).
================================================================================

A resource name hash is MurmurHash64A(resource_path, seed=0). Names are not
stored in the bundle, so we recover them by generating candidate path strings
and testing which hash to an unresolved resource.

Candidate generators (each is cheap and independent):
  1. lua_file        -- Lua source file paths without ".lua" (fully solves lua)
  2. lua_plus_suffix -- Lua file paths + common asset suffixes
  3. exe_strings     -- verbatim path-like strings inside the game exes/DLLs
  4. ini_paths       -- path-like strings in *.ini config files
  5. name_variants   -- resolved names mutated with numeric / "_varNN" suffixes
  6. per_dir_stems   -- same-directory stems recombined with suffixes
  7. dir_stem_suffix -- every resolved dir x every resolved stem x suffix
  8. dir_token_suffix-- every resolved dir x every Lua-content token x suffix

Results are written to resource_name_overlay.json, which list_game_bundles.py
merges automatically (same mechanism as bundle_name_overlay.json).

Usage:
    python crack_resource_names.py                 # all generators
    python crack_resource_names.py --generators lua_file,exe_strings
    python crack_resource_names.py --only-type texture,material
"""

import argparse
import collections
import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from list_game_bundles import (  # noqa: E402
    murmur_hash64, load_hash_db, find_install_root, classify_bundle_file,
    TOOL_DIR,
)

CSV_PATH = TOOL_DIR / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY_PATH = TOOL_DIR / "resource_name_overlay.json"

# Common texture/material map suffixes (order matters for stripping longest).
SUFFIXES = [
    "", "_diff", "_diffuse", "_spec", "_specular", "_norm", "_normal", "_nrm",
    "_gloss", "_glossy", "_mask", "_opacity", "_alpha", "_emissive", "_emit",
    "_glow", "_color", "_col", "_bump", "_height", "_overlay", "_blend",
    "_ao", "_det", "_detail", "_roughness", "_mat", "_material", "_specgloss",
    "_nrmgloss", "_diffgloss", "_glowmask",
]


def strip_suffix(name):
    leaf = name.rsplit("/", 1)[-1]
    for s in sorted(SUFFIXES, key=len, reverse=True):
        if s and leaf.lower().endswith(s):
            return name[:-len(s)]
    return name


def load_targets_and_resolved(only_types=None):
    """Read the catalogue CSV -> (targets, resolved, type_of)."""
    targets = {}       # hash_int -> set(types)
    resolved = set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["name"] == "":
                targets.setdefault(int(r["name_hash"], 16), set()).add(r["type"])
            else:
                resolved.add(r["name"])
    if only_types:
        targets = {h: t for h, t in targets.items() if t & only_types}
    return targets, resolved


def lua_roots(install_root):
    return [install_root / "Gauntlet-Source-DO_NOT_EDIT",
            TOOL_DIR.parents[1] / "game-source" / "Gauntlet-SourceCode-LUA",
            TOOL_DIR.parents[1] / "Gauntlet-SourceCode-LUA"]


# ---------------------------------------------------------------------------
# Generators -- each yields candidate strings
# ---------------------------------------------------------------------------

def gen_lua_file(install_root, resolved):
    for root in lua_roots(install_root):
        if root.is_dir():
            for p in root.rglob("*.lua"):
                yield str(p.relative_to(root))[:-4].replace("\\", "/")


def gen_lua_plus_suffix(install_root, resolved):
    for base in gen_lua_file(install_root, resolved):
        for s in SUFFIXES:
            if s:
                yield base + s


def gen_exe_strings(install_root, resolved):
    pat = re.compile(rb"[A-Za-z0-9_./-]{3,120}")
    B = install_root / "binaries"
    if not B.is_dir():
        return
    for f in B.iterdir():
        if f.suffix.lower() in (".exe", ".dll"):
            for m in pat.finditer(f.read_bytes()):
                s = m.group().decode("ascii", "ignore")
                if "/" in s:
                    yield s.strip("/")


def gen_ini_paths(install_root, resolved):
    for base, glob in [(install_root / "contents", "*.ini"),
                       (install_root, "*.ini"), (install_root, "*.txt")]:
        if not base.is_dir():
            continue
        for p in base.glob(glob):
            text = p.read_text(encoding="utf-8", errors="ignore")
            for m in re.findall(r"[A-Za-z0-9_./-]{3,80}", text):
                if "/" in m:
                    yield m.strip("/")


def gen_name_variants(install_root, resolved):
    for n in resolved:
        yield n
        base, leaf = (n.rsplit("/", 1) + [""])[:2] if "/" in n else ("", n)
        prefix = base + "/" if base else ""
        for i in range(0, 25):
            yield "%s_%02d" % (n, i)
            yield "%s_var%02d" % (n, i)
            yield "%s%d" % (n, i)
        if leaf.endswith("01"):
            for i in range(0, 25):
                yield prefix + leaf[:-2] + "%02d" % i


def gen_per_dir_stems(install_root, resolved):
    bydir = collections.defaultdict(set)
    for n in resolved:
        d, l = (n.rsplit("/", 1) + [""])[:2] if "/" in n else ("", n)
        bydir[d].add(strip_suffix(l).rsplit("/", 1)[-1])
    for d, stems in bydir.items():
        pfx = d + "/" if d else ""
        for st in stems:
            for s in SUFFIXES:
                yield pfx + st + s


def gen_dir_stem_suffix(install_root, resolved):
    dirs = {n.rsplit("/", 1)[0] for n in resolved if "/" in n}
    stems = {strip_suffix(n).rsplit("/", 1)[-1] for n in resolved}
    for d in dirs:
        for st in stems:
            base = d + "/" + st
            for s in SUFFIXES:
                yield base + s


def gen_dir_token_suffix(install_root, resolved):
    dirs = {n.rsplit("/", 1)[0] for n in resolved if "/" in n}
    toks = set()
    for root in lua_roots(install_root):
        if not root.is_dir():
            continue
        for p in root.rglob("*.lua"):
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for w in re.findall(r"[a-z][a-z0-9_]{4,30}", text):
                toks.add(w)
    for d in dirs:
        for tk in toks:
            base = d + "/" + tk
            for s in SUFFIXES:
                yield base + s


def gen_noop(install_root, resolved):
    return iter(())


GENERATORS = {
    "lua_file": gen_lua_file,
    "lua_plus_suffix": gen_lua_plus_suffix,
    "exe_strings": gen_exe_strings,
    "ini_paths": gen_ini_paths,
    "name_variants": gen_name_variants,
    "per_dir_stems": gen_per_dir_stems,
    "dir_stem_suffix": gen_dir_stem_suffix,
    "dir_token_suffix": gen_dir_token_suffix,
    # handled with scan_parallel in main() (heavy, or fixed root prefixes)
    "root_leaf_suffix": gen_noop,
    "root_token_suffix": gen_noop,
}


# Fixed category roots (observed in resolved names), used by root_* generators.
ROOT_PREFIXES = [
    "", "shaders", "shader_libraries", "shader_library", "core", "core/shaders",
    "core/rendering", "core/units", "effects", "decals", "characters",
    "characters/animations", "props", "gameobjects", "equipment", "gui", "hud",
    "lua", "foundation", "modules", "audio", "sound", "textures", "material",
    "materials", "units", "level", "levels", "animation", "animations",
    "particles", "timpani", "fx", "fgx", "meshes",
]


def _scan_worker(task):
    """Parallel worker: hash dir/vocab/suffix products against targets."""
    dirs, vocab, suffixes, targets = task
    found = {}
    mh = murmur_hash64
    for d in dirs:
        for v in vocab:
            base = (d + "/" + v) if d else v
            for s in suffixes:
                h = mh(base + s)
                if h in targets:
                    found.setdefault(h, base + s)
    return found


def scan_parallel(dirs, vocab, suffixes, targets, jobs):
    """Split `dirs` across a process pool and merge the matches."""
    from multiprocessing import Pool
    dirs = list(dirs)
    jobs = max(1, min(jobs, len(dirs)))
    chunks = [dirs[i::jobs] for i in range(jobs)]
    tasks = [(ch, list(vocab), suffixes, targets) for ch in chunks]
    found = {}
    with Pool(jobs) as pool:
        for part in pool.imap_unordered(_scan_worker, tasks):
            for h, n in part.items():
                found.setdefault(h, n)
    return found


def lua_content_tokens(install_root):
    toks = set()
    for root in lua_roots(install_root):
        if not root.is_dir():
            continue
        for p in root.rglob("*.lua"):
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for w in re.findall(r"[a-z][a-z0-9_]{4,30}", text):
                toks.add(w)
    return toks


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="Gauntlet install root")
    ap.add_argument("--contents", help="Path to the game 'contents' folder")
    ap.add_argument("--generators", default="all",
                    help="Comma list of: " + ",".join(GENERATORS) + " (or 'all')")
    ap.add_argument("--only-type", help="Comma list of resource types to target")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4,
                    help="Worker processes for the heavy generators")
    ap.add_argument("--no-write", action="store_true",
                    help="Do not write resource_name_overlay.json")
    args = ap.parse_args()

    install_root = find_install_root(args.root or args.contents)
    only_types = set(args.only_type.split(",")) if args.only_type else None
    targets, resolved = load_targets_and_resolved(only_types)
    print("Install root : %s" % install_root)
    print("Targets      : %d unresolved hashes" % len(targets))
    print("Resolved     : %d known names (vocabulary)" % len(resolved))

    if args.generators == "all":
        chosen = list(GENERATORS)
    else:
        chosen = [g.strip() for g in args.generators.split(",") if g.strip()]

    # vocabularies for the heavy (parallel) generators
    dirs = {n.rsplit("/", 1)[0] for n in resolved if "/" in n}
    stems = {strip_suffix(n).rsplit("/", 1)[-1] for n in resolved}

    solved = {}          # hash_int -> candidate
    for gname in chosen:
        if gname not in GENERATORS:
            print("  ! unknown generator %r" % gname)
            continue
        if gname == "dir_stem_suffix":
            part = scan_parallel(dirs, stems, SUFFIXES, targets, args.jobs)
        elif gname == "dir_token_suffix":
            toks = lua_content_tokens(install_root)
            print("  %-18s vocab=%d tokens, %d dirs" % (gname, len(toks),
                                                         len(dirs)), flush=True)
            part = scan_parallel(dirs, toks, SUFFIXES, targets, args.jobs)
        elif gname == "root_leaf_suffix":
            leaves = {n.rsplit("/", 1)[-1] for n in resolved}
            part = scan_parallel(ROOT_PREFIXES, leaves, SUFFIXES, targets,
                                 args.jobs)
        elif gname == "root_token_suffix":
            toks = lua_content_tokens(install_root)
            part = scan_parallel(ROOT_PREFIXES, toks, SUFFIXES, targets,
                                 args.jobs)
        else:
            part = {}
            for cand in GENERATORS[gname](install_root, resolved):
                h = murmur_hash64(cand)
                if h in targets:
                    part.setdefault(h, cand)
        added = 0
        for h, n in part.items():
            if h not in solved:
                solved[h] = n
                added += 1
        print("  %-18s solved=+%d (total %d)" % (gname, added, len(solved)),
              flush=True)

    # breakdown
    by_type = collections.Counter()
    for h in solved:
        by_type.update(targets[h])
    print("\nSOLVED %d / %d unresolved hashes" % (len(solved), len(targets)))
    for t, n in by_type.most_common():
        print("  %-22s %d" % (t, n))

    if solved and not args.no_write:
        merged = {}
        if OVERLAY_PATH.exists():
            merged = json.loads(OVERLAY_PATH.read_text())
        for h, name in solved.items():
            merged["%016x" % h] = name
        OVERLAY_PATH.write_text(json.dumps(merged, indent=2, sort_keys=True))
        print("\nWrote %d names -> %s" % (len(merged), OVERLAY_PATH))
        print("Re-run list_game_bundles.py to fold them into the catalogue.")


if __name__ == "__main__":
    main()

