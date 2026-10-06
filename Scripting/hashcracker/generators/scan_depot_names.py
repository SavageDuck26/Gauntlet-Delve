#!/usr/bin/env python3
"""
Harvest candidate resource names from a game install / depot.

Compiled bodies are not always opaque: the older (Pre-Slayer) build keeps
~200k name-bearing strings (Lua/config/editor references) that the Slayer build
stripped, and **many of those names contain a colon** - e.g.

    blocks/d01_caves/borders/caverock_border_low_2c
    characters/avatar_elf/animations/bow_attack_fast1
    additive:diffuse_map / ao_integrator:sun_occlusion     (shader permutations)
    modules/d01_caves/dungeon_tiles/caverock_8c_8c_g_g_g_u_01

The colon matters: every earlier corpus scan filtered with
`^[a-z0-9][a-z0-9_./-]{3,110}$`, which silently dropped all of them.  This tool
keeps them, and also handles the Pre-Slayer bundle packing (raw 64 KiB chunks
mixed with zlib chunks - see `decompress_bundle`).

Usage:
    python3 generators/scan_depot_names.py \
        --contents <dir-with-bundles> [--binaries <dir-with-exe-dll>] \
        [--out FILE] [--no-suffixes]

    # then hash them against the outstanding work:
    ./target/release/hashcracker crack --gpu \
        --targets data/vocab/unresolved_targets.txt \
        --candidates FILE --matches matches.tsv
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "GauntletGameDigging"))
from list_game_bundles import decompress_bundle, parse_toc, parse_resources  # noqa

# colon-tolerant on purpose (that is the whole point of the tool)
TOKEN = re.compile(rb"[a-zA-Z][a-zA-Z0-9_:./-]{2,120}")
SUFFIX = ("_diff", "_norm", "_spec", "_01", "_02", "_var01")
DEFAULT_BINARIES = (Path.home() / ".local/share/Steam/steamapps/common/Gauntlet"
                    / "binaries")


def harvest(contents: Path, binaries: Path | None):
    raw = set()
    for p in sorted(contents.iterdir()):
        if not p.is_file() or p.suffix in (".stream", ".ini", ".data"):
            continue
        try:
            _sig, _unz, data = decompress_bundle(p.read_bytes())
            _c, toc = parse_toc(data)
            entries, _end, _ok = parse_resources(data, toc)
        except Exception:                            # noqa: BLE001
            continue
        for e in entries:
            body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]
            if body:
                raw.update(m.decode("latin1") for m in TOKEN.findall(body))
        raw.update(m.decode("latin1") for m in TOKEN.findall(data[:0x10000]))
    if binaries and binaries.is_dir():
        for p in sorted(binaries.iterdir()):
            if p.suffix.lower() in (".exe", ".dll"):
                raw.update(m.decode("latin1") for m in TOKEN.findall(p.read_bytes()))
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contents", required=True,
                    help="directory holding the hash-named bundle files")
    ap.add_argument("--binaries", default=str(DEFAULT_BINARIES))
    ap.add_argument("--out", default="/tmp/depot_names.txt")
    ap.add_argument("--no-suffixes", action="store_true",
                    help="skip the _diff/_norm/_01 expansions")
    args = ap.parse_args()

    raw = harvest(Path(args.contents), Path(args.binaries))
    out = set()
    for s in raw:
        for v in {s, s.lower(), s.strip("_./-")}:
            if len(v) < 3:
                continue
            out.add(v)
            if not args.no_suffixes and len(v) < 110:
                out.update(v + suf for suf in SUFFIX)
    lines = sorted(x for x in out if " " not in x and "\t" not in x)
    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"bundles/files scanned ok, raw strings {len(raw)} "
          f"-> candidates {len(lines)} -> {args.out}")


if __name__ == "__main__":
    main()
