#!/usr/bin/env python3
"""
Answer "was this name ever a live resource, and in which build?" (FINDINGS.txt 60.7).

A harvest is only evidence of a *string*, not of a live resource (FINDINGS 60.4), so
a name that looks recoverable often has no row anywhere.  This walks the actual
resource entries inside each depot snapshot and tests the hash of each name against
them, so the question gets a straight yes/no per build:

    python3 check_build_liveness.py characters/demon_imp/demon_imp
    python3 check_build_liveness.py --file candidates.txt
    python3 check_build_liveness.py --snap 2014 --snap 2015-08 --file candidates.txt

For each name it prints the hash, a column per snapshot, and the status in the
shipped catalogue (named / UNRESOLVED / no row).  Note the snapshot dirs are partial
downloads, so *absence* from a snapshot is weaker evidence than presence; absence
from the shipped catalogue is conclusive, because that is the build we are naming.

Controls worth keeping in any batch: a name known to have been renamed away
(`characters/gator_brute/gator_brute`) should read live in 2014 and 2015-01 and
absent in 2015-08, and `characters/lizard_base` should read live in 2015-08.
"""
import argparse
import csv
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hunt_build_diff as H                                          # noqa: E402
from hunt_unit_textures import murmur                                # noqa: E402

MANIFEST = HERE / "bundle_manifest"
CACHE = HERE / ".liveness_cache"


def hashes_of(snap):
    """Every name hash that is a real resource entry in one snapshot."""
    cache = CACHE / f"{snap}.txt"
    if cache.exists():
        return {int(x, 16) for x in cache.read_text().split() if x}
    out = set()
    for bid, path in sorted(H.bundles_of(snap).items()):
        for _i, h, _t, _b in H.entries_of(path):
            if h:
                out.add(int(h))
    CACHE.mkdir(exist_ok=True)
    cache.write_text("\n".join(f"{h:016x}" for h in sorted(out)))
    return out


def catalogue():
    """The shipped build, as (hash -> name or None)."""
    import json
    overlay = json.loads((HERE / "resource_name_overlay.json").read_text())
    out = {}
    with (MANIFEST / "04_bundle_resources.csv").open(newline="",
                                                     encoding="utf-8",
                                                     errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = r["name_hash"].lower()
            out[h] = r.get("name") or overlay.get(h) or None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="resource names to test")
    ap.add_argument("--file", help="read more names from this file, one per line")
    ap.add_argument("--snap", action="append", default=[],
                    help="snapshot key (default: all in hunt_build_diff.SNAPS)")
    ap.add_argument("--no-cache", action="store_true",
                    help="re-walk the bundles instead of reusing .liveness_cache")
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        names += [l.strip() for l in pathlib.Path(args.file).read_text().splitlines()
                  if l.strip() and not l.startswith("#")]
    if not names:
        ap.error("give at least one name, or --file")

    snaps = args.snap or list(H.SNAPS)
    if args.no_cache:
        for s in snaps:
            (CACHE / f"{s}.txt").unlink(missing_ok=True)
    live = {}
    for s in snaps:
        live[s] = hashes_of(s)
        print(f"  {s}: {len(live[s]):,} live resource hashes", file=sys.stderr)

    cat = catalogue()
    width = max(len(n) for n in names + ["name"])
    print()
    print(f"{'name':{width}s}  {'hash':16s}  " +
          "  ".join(f"{s:>9s}" for s in snaps) + "   shipped catalogue")
    print("-" * (width + 20 + 11 * len(snaps) + 20))
    for n in names:
        h = f"{murmur(n):016x}"
        cols = "  ".join(f"{'LIVE':>9s}" if int(h, 16) in live[s] else f"{'-':>9s}"
                         for s in snaps)
        if h in cat:
            status = f"named: {cat[h]}" if cat[h] else "UNRESOLVED"
        else:
            status = "no row"
        print(f"{n:{width}s}  {h}  {cols}   {status}")


if __name__ == "__main__":
    main()
