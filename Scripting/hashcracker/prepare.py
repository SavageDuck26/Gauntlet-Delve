#!/usr/bin/env python3
"""
Prepare inputs for the Rust `hashcracker`.

Reads the Python toolchain's catalogue CSV (+ optionally the game Lua source)
and writes, into --out:

    targets.txt   unique unresolved resource-name hashes (hex, one per line)
    dirs.txt      directory fragments seen in resolved names
    names.txt     leaf stems + tokens mined from Lua + game binaries
    prefixes.txt  top-level roots
    suffixes.txt  texture/material map suffixes

Usage:
    python3 prepare.py --csv ../../.../bundle_manifest/04_bundle_resources.csv \
        --lua /path/to/Gauntlet-Source-DO_NOT_EDIT \
        --binaries /path/to/Gauntlet/binaries \
        --out data
"""
import argparse
import csv
import re
from pathlib import Path

SUFFIXES = [
    "_diff", "_diffuse", "_spec", "_specular", "_norm", "_normal", "_nrm",
    "_gloss", "_glossy", "_mask", "_opacity", "_alpha", "_emissive", "_emit",
    "_glow", "_color", "_col", "_bump", "_height", "_overlay", "_blend",
    "_ao", "_det", "_detail", "_roughness", "_mat", "_material", "_specgloss",
    "_nrmgloss", "_diffgloss", "_glowmask", "_translucent", "_glowmaskcolor",
]
# Targeted vocabularies observed in resolved names (levels / animations).
ENVS = ["d01_crypt", "d01_caves", "d01_lava", "d01_hub_room", "d01_arcade",
        "d01_crypt_boss", "d01_caves_boss", "d01_lava_boss"]
ENVNAMES = ["crypt", "caves", "lava", "hub_room", "hubroom", "arcade",
            "crypt_boss", "caves_boss", "lava_boss", "tutorial"]
KINDS = ["adventure", "boss", "arena", "colosseum", "labyrinth", "endless",
         "procedural", "dummy", "tutorial", "survival", "wave", "gauntlet",
         "room", "trap", "puzzle", "treasure", "shop", "hub", "safe", "saferoom",
         "start", "end", "intro", "outro", "transition", "corridor", "secret"]
ANIM = ["idle", "run", "walk", "sprint", "attack", "death", "die", "hit", "cast",
        "reload", "jump", "land", "taunt", "dodge", "block", "stagger", "stun",
        "knockdown", "revive", "celebrate", "victory", "intro", "outro", "spawn",
        "special", "dormant", "execute", "entrance", "exit", "start", "end",
        "loop", "turn", "strafe", "aim", "shoot", "swing", "charge", "leap",
        "slam", "stomp", "roar", "spit", "summon", "teleport", "morph", "laugh",
        "cheer", "panic", "flee", "guard", "parry", "throw", "pickup", "point",
        "wave", "gesture", "emote", "spawn_special", "hit_react", "death_react"]
ROOTS = [
    "resource_packages", "modules", "characters", "props", "gameobjects",
    "equipment", "effects", "decals", "gui", "hud", "lua", "foundation",
    "core", "shaders", "audio", "sound", "textures", "material", "materials",
    "units", "levels", "particles", "timpani", "weapons", "abilities",
    "items", "enemies", "menu", "weapons_pack", "enemy_units", "fx",
]


VALID = re.compile(r"^[a-z0-9][a-z0-9_./-]{1,63}$")


def valid(s):
    """Keep only identifier-ish tokens (no bare punctuation like '-')."""
    return bool(VALID.match(s)) and any(c.isalnum() for c in s)


def strip_suffix(leaf):
    for s in sorted(SUFFIXES, key=len, reverse=True):
        if s and leaf.endswith(s):
            return leaf[: -len(s)]
    return leaf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="bundle_manifest/04_bundle_resources.csv")
    ap.add_argument("--lua", help="game Lua source dir (Gauntlet-Source-DO_NOT_EDIT)")
    ap.add_argument("--binaries", help="game binaries dir (for string mining)")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    targets, dirs, names, prefixes = set(), set(), set(), set(ROOTS)
    resolved = set()
    events = set()

    with open(args.csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["name"] == "":
                targets.add(r["name_hash"])
            else:
                n = r["name"]
                resolved.add(n)
                names.add(n.rsplit("/", 1)[-1])
                names.add(strip_suffix(n).rsplit("/", 1)[-1])
                if "/" in n:
                    d = n.rsplit("/", 1)[0]
                    dirs.add(d)
                    prefixes.add(n.split("/", 1)[0])
                    names.add(d.rsplit("/", 1)[-1])

    # mine tokens from the Lua source
    if args.lua:
        lua = Path(args.lua)
        for p in lua.rglob("*.lua"):
            t = p.read_text(encoding="utf-8", errors="ignore").lower()
            for w in re.findall(r"[a-z][a-z0-9_]{2,31}", t):
                names.add(w)
            for m in re.findall(r"[a-z0-9_./-]{4,80}", t):
                if "/" in m:
                    # keep the FULL directory path (not just single segments),
                    # e.g. "characters/skeleton_warrior" -> dirs
                    if 2 <= len(m) <= 90:
                        dirs.add(m.rsplit("/", 1)[0])
                    for seg in m.split("/"):
                        if 2 <= len(seg) <= 32:
                            names.add(seg)
                            dirs.add(seg)

    # animation / flow event names (these double as animation clip names)
    if args.lua:
        gen = Path(args.lua) / "lua" / "generated"
        for fn in ("animation_events.lua", "flow_events.lua"):
            p = gen / fn
            if p.exists():
                txt = p.read_text(encoding="utf-8", errors="ignore")
                for m in re.findall(r'"([a-z0-9_]+)"', txt):
                    if 2 <= len(m) <= 48:
                        events.add(m)

    # quilt level pieces: names are literal keys in lua/dungeon/layouts/*.lua,
    # e.g. lava_quilt_blackbox__x_x_x_x__01_rocks  (dirs come from the path mining)
    quilts = set()
    if args.lua:
        lay = Path(args.lua) / "lua" / "dungeon" / "layouts"
        if lay.is_dir():
            for p in lay.rglob("*.lua"):
                txt = p.read_text(encoding="utf-8", errors="ignore").lower()
                for m in re.findall(r"[a-z0-9]+_quilt_[a-z0-9_]+", txt):
                    quilts.add(m)

    # mine path-like strings from binaries
    if args.binaries:
        pat = re.compile(rb"[A-Za-z0-9_./-]{4,120}")
        for p in Path(args.binaries).iterdir():
            if p.suffix.lower() in (".exe", ".dll"):
                for m in pat.finditer(p.read_bytes()):
                    s = m.group().decode("ascii", "ignore").strip("/").lower()
                    if "/" in s:
                        names.add(s.rsplit("/", 1)[-1])
                        for seg in s.split("/"):
                            if 2 <= len(seg) <= 32:
                                dirs.add(seg)
                                names.add(seg)

    def dump(name, values, filt=True):
        vals = sorted(v for v in values if v and (valid(v) if filt else True))
        (out / name).write_text("\n".join(vals) + "\n")
        print(f"{name:16s} {len(vals):>8} entries")

    dump("targets.txt", sorted(targets))
    dump("known.txt", resolved, filt=False)
    dump("dirs.txt", dirs)
    dump("names.txt", names)
    dump("prefixes.txt", prefixes)
    dump("suffixes.txt", SUFFIXES, filt=False)
    dump("env.txt", ENVS, filt=False)
    dump("envname.txt", ENVNAMES, filt=False)
    dump("kind.txt", KINDS, filt=False)
    dump("anim.txt", ANIM, filt=False)
    dump("events.txt", events, filt=False)
    dump("quilts.txt", quilts, filt=False)
    print(f"\nwritten to {out}/")


if __name__ == "__main__":
    main()
