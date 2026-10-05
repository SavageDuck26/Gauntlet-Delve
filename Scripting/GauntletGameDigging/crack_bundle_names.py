#!/usr/bin/env python3
"""
Brute-force Gauntlet bundle (package) names.
============================================

A bundle's on-disk filename is MurmurHash64A(package_path, seed=0) rendered as
16 lowercase hex chars. The package path itself is NOT stored anywhere, so we
recover it by generating candidate strings and testing which hash to an
unresolved bundle name.

Candidate sources (best first):
  * the game's own Lua source (package manager + boot scripts name the packages)
  * printable strings inside the game executables/DLLs
  * word lists in the RE toolchain
  * generated templates, e.g. resource_packages/heroes/<avatar>_<suffix>

Usage:
    python crack_bundle_names.py                     # all unresolved bundles
    python crack_bundle_names.py --show-all
    python crack_bundle_names.py --target 0164ad48615ba9ed
    python crack_bundle_names.py --extra-file words.txt
"""

import argparse
import os
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from list_game_bundles import (  # noqa: E402
    murmur_hash64, load_hash_db, find_install_root, classify_bundle_file,
    TOOL_DIR,
)

# --- known scaffolding from the game's Lua (lua/boot/game.lua etc.) ---------
AVATARS = ["warrior", "valkyrie", "wizard", "elf", "necromagus"]

PREFIXES = [
    "", "resource_packages/", "resource_packages/heroes/",
    "resource_packages/custom/", "modules/", "modules/menu/",
    "content/", "foundation/",
]
SUFFIXES = [
    "", "_base", "_equipment", "_capes", "_ability", "_banks", "_units",
    "_effects", "_scripts", "_gui", "_settings", "_boss", "_package",
    "_level", "_menu", "_fx", "_env", "_props",
]

STR_TOKEN_RE = re.compile(rb"[A-Za-z0-9_./%-]{3,80}")


def gather_from_text_file(path: Path, exts, out):
    """Collect path-like tokens from a source file into `out`."""
    if exts is not None and path.suffix.lower() not in exts:
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for m in re.findall(r"[A-Za-z0-9_./%-]{3,80}", text):
        if "/" in m:
            out.add(m.strip("/"))
            # also add every slash-separated segment
            for seg in m.split("/"):
                if 2 <= len(seg) <= 40:
                    out.add(seg)


def gather_from_binary(path: Path, out):
    """Collect printable path-like tokens from a binary file."""
    try:
        data = path.read_bytes()
    except OSError:
        return
    for m in STR_TOKEN_RE.finditer(data):
        s = m.group().decode("ascii", "ignore")
        if "/" in s:
            out.add(s.strip("/"))


def gather_candidate_strings(install_root: Path, extra_files):
    """
    Harvest candidate path strings, split by source so expansion stays bounded.

    Returns (direct, names):
      * direct -- every path-like string found verbatim (used as-is)
      * names  -- short tokens worth expanding via PREFIXES/SUFFIXES
                  (taken ONLY from Lua/tool text, never from raw binaries,
                  otherwise the combinatorics explode)
    """
    direct = set()
    names = set()

    # 1. Lua source shipped with the game (DO_NOT_EDIT) + workspace copy.
    lua_roots = [install_root / "Gauntlet-Source-DO_NOT_EDIT",
                 TOOL_DIR.parents[1] / "game-source" / "Gauntlet-SourceCode-LUA",
                 TOOL_DIR.parents[1] / "Gauntlet-SourceCode-LUA"]
    lua_texts = []
    for root in lua_roots:
        if root.is_dir():
            for p in root.rglob("*.lua"):
                try:
                    lua_texts.append(p.read_text(encoding="utf-8",
                                                 errors="ignore"))
                except OSError:
                    pass
    for text in lua_texts:
        for m in re.findall(r"[A-Za-z0-9_./%-]{3,80}", text):
            if "/" in m:
                direct.add(m.strip("/"))
                for seg in m.split("/"):
                    if 2 <= len(seg) <= 24:
                        names.add(seg)
        # environment / elias / name literals from the dungeon layout table
        for env in re.findall(r'environment\s*=\s*"([a-z0-9_]+)"', text):
            names.add(env)
        for nm in re.findall(r'name\s*=\s*"([a-z0-9_]+)"', text):
            names.add(nm)

    # 2. Game executables / DLLs -- direct candidates only.
    bin_dir = install_root / "binaries"
    if bin_dir.is_dir():
        for p in bin_dir.iterdir():
            if p.suffix.lower() in (".exe", ".dll"):
                gather_from_binary(p, direct)

    # 3. Game config files (settings.ini etc.) + RE toolchain text artefacts.
    config_globs = [(install_root / "contents", "*.ini"),
                    (install_root, "*.ini"), (install_root, "*.txt"),
                    (TOOL_DIR, "*.txt"), (TOOL_DIR, "*.json")]
    for base, glob in config_globs:
        if not base.is_dir():
            continue
        for p in base.glob(glob):
            tmp = set()
            gather_from_text_file(p, None, tmp)
            direct |= tmp
            for s in tmp:
                for seg in s.split("/"):
                    if 2 <= len(seg) <= 24:
                        names.add(seg)

    # 4. User-supplied word lists.
    for ef in (extra_files or []):
        tmp = set()
        gather_from_text_file(Path(ef), None, tmp)
        direct |= tmp
        names |= {s.split("/")[-1] for s in tmp if 2 <= len(s) <= 24}

    names.update(AVATARS)
    names.update(["menu", "base", "debug", "splash", "localization", "morak",
                  "elias", "foundation", "caves", "crypt", "lava", "tutorial",
                  "colosseum", "arcade", "hub_room", "misc_units",
                  "food_units", "relic_units", "gore_effects", "all_effects",
                  "base_effects", "surface_effects", "particle_effects"])
    return direct, names


def build_candidate_set(direct, names):
    """
    Expand harvested strings into a deduplicated candidate package-path set.

      * direct strings are used verbatim
      * <prefix> + <name> and <prefix> + <name> + <suffix> are generated
      * the level tables add:  modules/<env>/resources,
        resource_packages/<env>, resource_packages/elias/<name>
    """
    cands = set()
    for s in direct:
        s = s.strip().strip('"').strip("'").replace("\\", "/").strip("/")
        if s:
            cands.add(s)

    for n in names:
        if not (2 <= len(n) <= 48):
            continue
        cands.add("resource_packages/elias/%s" % n)
        cands.add("modules/%s/resources" % n)
        for pre in PREFIXES:
            cands.add(pre + n)
            for suf in SUFFIXES:
                cands.add("%s%s%s" % (pre, n, suf))
    return cands


def find_unresolved_bundles(install_root: Path, hash_db, only=None):
    """Return {hash_hex: path} for bundle files with no resolved package path."""
    contents = install_root / "contents"
    unresolved = {}
    for f in sorted(contents.iterdir()):
        if not f.is_file() or not classify_bundle_file(f.name):
            continue
        if only and f.name != only:
            continue
        if hash_db.get(f.name.lower()) is None:
            unresolved[f.name] = f
    return unresolved


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="Gauntlet install root")
    ap.add_argument("--contents", help="Path to the game 'contents' folder")
    ap.add_argument("--target", help="Crack a single bundle name (16 hex chars)")
    ap.add_argument("--extra-file", action="append", default=[],
                    help="Extra word list / text file (repeatable)")
    ap.add_argument("--show-all", action="store_true",
                    help="List unresolved bundles even if uncracked")
    args = ap.parse_args()

    install_root = find_install_root(args.root or args.contents)
    hash_db = load_hash_db()
    targets = find_unresolved_bundles(install_root, hash_db, only=args.target)
    if not targets:
        print("No unresolved bundles found (all resolved!).")
        return

    print("Install root : %s" % install_root)
    print("Unresolved   : %d bundle(s)" % len(targets))

    direct, names = gather_candidate_strings(install_root, args.extra_file)
    print("Harvested    : %d direct strings, %d name tokens"
          % (len(direct), len(names)))
    cands = build_candidate_set(direct, names)
    print("Candidates   : %d after expansion" % len(cands))

    rev = {int(name, 16): name for name in targets}  # hash -> bundle name
    solved = {}
    for cand in cands:
        name = rev.get(murmur_hash64(cand))
        if name is not None:
            solved[name] = cand
    print("Cracked      : %d / %d\n" % (len(solved), len(targets)))

    for name in sorted(targets):
        if name in solved:
            print("  %s -> %s" % (name, solved[name]))
        elif args.show_all:
            print("  %s -> <uncracked>" % name)

    if solved and not args.target:
        import json
        overlay = {k: v for k, v in sorted(solved.items())}
        out = TOOL_DIR / "bundle_name_overlay.json"
        out.write_text(json.dumps(overlay, indent=2, sort_keys=True))
        print("\nWrote %d cracked names -> %s" % (len(overlay), out))
        print("list_game_bundles.py merges this automatically.")


if __name__ == "__main__":
    main()

