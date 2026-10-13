#!/usr/bin/env python3
"""
Name the *older* build's resources (FINDINGS.txt §50).

A name hash depends only on the name, so a hash that exists in an old snapshot
but not in the current one is a name that was removed or renamed - and the
current corpus can never name it.  The old build's *own* harvest can: every
snapshot directory carries `_names.txt`, strings harvested from that build's
decompressed bodies, and the names in it are the ones that were in use *then*.

So match that harvest against the old build's TOC instead of the new one, giving
`old_names.json` (old hash -> old name).  Those old names are the anchors for the
rename analysis: an old resource whose body is byte-identical to a resource in
the current build *is* a rename, and knowing both sides - or one - is what turns
that into a name.

    python3 hunt_old_names.py --snap 2015-01 [--raw FILE...] [--write]
"""
import argparse
import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hashcracker" / "tools"))
import list_game_bundles as L                                      # noqa: E402
from mine_harvest_paths import variants                            # noqa: E402
from bundle_tools import murmur_hash64                             # noqa: E402

SNAPS = {"2014": "Gauntlet-PreSlayer-2014-10-10",
         "2015-01": "Gauntlet-PreSlayer-2015-01-21",
         "2015-08": "Gauntlet-PreSlayer-2015-08-11"}


def old_hashes(snap):
    """Every name hash the old build's bundles carry, with its body size."""
    out = {}
    root = REPO / SNAPS[snap]
    for dep in root.glob("depot_*"):
        for c in dep.glob("contents"):
            for f in c.iterdir():
                if not f.is_file() or f.suffix == ".stream":
                    continue
                try:
                    _sig, _uz, data = L.decompress_bundle(f.read_bytes())
                    _count, toc = L.parse_toc(data)
                    entries, _end, _ok = L.parse_resources(data, toc)
                except Exception:                               # noqa: BLE001
                    continue
                for e in entries:
                    h = e.get("name_hash")
                    if h:
                        out.setdefault(int(h), e.get("body_size", 0))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", default="2015-01")
    ap.add_argument("--raw", nargs="*")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    want = old_hashes(args.snap)
    print(f"old build {args.snap}: {len(want):,} name hashes")
    raws = args.raw or [str(REPO / SNAPS[args.snap] / "_names.txt")]
    hits, tested, seen = {}, 0, 0
    for r in raws:
        p = pathlib.Path(r)
        if not p.exists():
            print(f"  (missing {p})")
            continue
        with p.open(errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if len(s) < 6:
                    continue
                seen += 1
                for c in variants(s):
                    tested += 1
                    if murmur_hash64(c) in want:
                        hits.setdefault(c, f"{murmur_hash64(c):016x}")
    print(f"lines {seen:,}  candidates {tested:,}  RESOLVED old names {len(hits):,}")
    for c, h in list(hits.items())[:15]:
        print(f"  {h}  {c}")
    if args.write:
        out = HERE.parent / "hashcracker" / "work" / f"old_names_{args.snap}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({h: c for c, h in hits.items()},
                                  indent=1, sort_keys=True))
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
