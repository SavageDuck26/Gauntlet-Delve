#!/usr/bin/env python3
"""
Dump printable strings from `level` resource bodies inside a bundle.

Levels are compiled modules; if the body still carries internal names (a debug
name, a quilt token, a spawner id) then an unresolved level's name is readable
straight out of its bytes.  Uses the GauntletGameDigging bundle parsers.

Usage:
    python3 level_body_strings.py --bundle 0164ad48615ba9ed [--indices 14,15,16]
                                  [--grep quilt] [--min 4]
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "GauntletGameDigging"))
from list_game_bundles import (decompress_bundle, parse_toc, parse_resources,  # noqa
                               find_install_root)

STR = re.compile(rb"[ -~]{4,120}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--indices", help="comma list of resource indices (default: all)")
    ap.add_argument("--grep", help="only print strings matching this regex")
    ap.add_argument("--min", type=int, default=4)
    ap.add_argument("--max-per-body", type=int, default=60)
    args = ap.parse_args()

    root = find_install_root()
    blob = (root / "contents" / args.bundle).read_bytes()
    _sig, _usz, data = decompress_bundle(blob)
    count, toc = parse_toc(data)
    entries, _end, ok = parse_resources(data, toc)
    print(f"bundle {args.bundle}: {count} resources, scan_complete={ok}")

    want = {int(x) for x in args.indices.split(",")} if args.indices else None
    pat = re.compile(args.grep.encode()) if args.grep else None
    for e in entries:
        if want is not None and e["index"] not in want:
            continue
        body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]
        got = [s.decode("latin1") for s in STR.findall(body) if len(s) >= args.min]
        if pat:
            got = [s for s in got if pat.search(s.encode())]
        if want is None and not got:
            continue
        print(f"\n--- index {e['index']:5d} name_hash {e['name_hash']:016x} "
              f"body {len(body)}B  ({len(got)} strings)")
        for s in got[:args.max_per_body]:
            print("     ", s)


if __name__ == "__main__":
    main()
