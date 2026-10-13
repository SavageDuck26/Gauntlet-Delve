#!/usr/bin/env python3
"""
Harvest resource paths embedded in bundle resource *bodies*.

Compiled resource bodies are not always opaque: DXBC shader blobs embed the
library they came from, so the renderer bundle yields

    core/rendering/color_grading
    core/rendering/framebuffer_distort
    core/rendering/tone_mapping
    ...

i.e. the resource path itself, for every shader library in the bundle.  This
scans a bundle's bodies for path-like strings and writes them as candidates.

    python3 scan_bundle_paths.py --bundle 1a9c33dcd0301dfd --out /tmp/paths.txt
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
from list_game_bundles import (decompress_bundle, parse_toc, parse_resources,  # noqa
                               find_install_root)

STR = re.compile(rb"[ -~]{5,140}")
PATHY = re.compile(rb"^[a-z][a-z0-9_./-]{4,120}$")
LOOSE = re.compile(rb"^[a-z][a-z0-9_./-]{4,120}$|^[A-Za-z][A-Za-z0-9_./-]{4,120}$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", help="single bundle id (default: every bundle)")
    ap.add_argument("--all", action="store_true", help="scan every bundle")
    ap.add_argument("--out", default="/tmp/paths.txt")
    ap.add_argument("--root-slash", action="store_true", default=True,
                    help="only keep strings that contain a '/'")
    ap.add_argument("--loose", action="store_true",
                    help="keep every identifier-ish string, not just paths")
    args = ap.parse_args()

    root = find_install_root()
    if args.bundle:
        bundles = [args.bundle]
    else:
        csv_path = HERE.parent.parent / "Data/bundle_manifest/04_bundle_resources.csv"
        import csv as _csv
        bundles = sorted({r["bundle"] for r in _csv.DictReader(csv_path.open())})

    out = set()
    for bundle in bundles:
        path = root / "contents" / bundle
        if not path.exists():
            continue
        try:
            _sig, _unz, data = decompress_bundle(path.read_bytes())
            _c, toc = parse_toc(data)
            entries, _e, _ok = parse_resources(data, toc)
        except Exception as e:                      # noqa: BLE001
            print(f"  ! {bundle}: {e}")
            continue
        for e in entries:
            body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]
            for m in STR.findall(body):
                pat = LOOSE if args.loose else PATHY
                if not pat.match(m):
                    continue
                s = m.decode("latin1").strip("/")
                if not args.loose and args.root_slash and "/" not in s:
                    continue
                t = s.lower()
                out.add(t)
                out.add(t.rsplit("/", 1)[-1])
    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"bundles {len(bundles)} -> {len(out)} path candidates -> {args.out}")


if __name__ == "__main__":
    main()
