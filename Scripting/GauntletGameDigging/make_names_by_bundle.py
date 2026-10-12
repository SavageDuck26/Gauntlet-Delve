#!/usr/bin/env python3
"""
Every name we hold, grouped by the bundle it ships in: `bundle_manifest/12_names_by_bundle.txt`.

`06_names_by_name.txt` is names A-Z and `07_names_by_type.txt` is names by type; this is the
third cut of the same set - names by the *bundle* they were shipped in, alphabetical inside
each bundle, names only (no hashes).  A name can appear under more than one bundle: the same
resource is often duplicated across packages, which is exactly what this view makes visible.

    ### 0164ad48615ba9ed   modules/d01_crypt/resources   (1,513 names)
      ability_units/spawners/spawner_exploding_burning
      blocks/d01_caves/borders/caverock_border_low_2c
      ...

    python3 make_names_by_bundle.py            # -> bundle_manifest/12_names_by_bundle.txt
    python3 make_names_by_bundle.py --stdout   # print instead

`make_progress_report.py` calls it too, so every progress run refreshes it next to 08.
"""
import argparse
import csv
import json
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "bundle_manifest"
CATALOGUE = MANIFEST / "04_bundle_resources.csv"
OVERLAY = HERE / "resource_name_overlay.json"
OUT = MANIFEST / "12_names_by_bundle.txt"


def collect():
    """bundle -> (package, set of names)."""
    overlay = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    bundles = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("name") or "").strip() or overlay.get(
                (r.get("name_hash") or "").strip().lower())
            if not name:
                continue
            b = r.get("bundle") or ""
            pkg, names = bundles.setdefault(b, [r.get("package_path") or "", set()])
            names.add(name)
    return bundles


def write(stream=None):
    """Write the listing; returns (bundles, total names shown)."""
    bundles = collect()
    total = sum(len(n) for _, n in bundles.values())
    out = stream or OUT.open("w", encoding="utf-8")
    try:
        ts = time.strftime("%Y-%m-%d %H:%M")
        out.write(f"{total:,} names in {len(bundles)} bundles, alphabetical within each "
                  f"(generated {ts})\n")
        for b in sorted(bundles, key=lambda x: (bundles[x][0], x)):
            pkg, names = bundles[b]
            out.write(f"\n### {b}   {pkg}   ({len(names):,} "
                      f"{'name' if len(names) == 1 else 'names'})\n")
            out.write("-" * 78 + "\n")
            for n in sorted(names):
                out.write(f"  {n}\n")
    finally:
        if stream is None:
            out.close()
    return len(bundles), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    if args.stdout:
        import sys
        b, t = write(stream=sys.stdout)
    else:
        b, t = write()
    print(f"{t:,} names in {b} bundles -> {OUT}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
