#!/usr/bin/env python3
"""
The missing view, grouped by bundle and type: `bundle_manifest/11_missing_by_bundle.tsv`.

`10_unresolved_master.tsv` lists every unresolved resource one row per hash; this is the
same set *grouped*, so the question "which bundle is still carrying holes, of which type,
and which hashes are they" is one grep away:

    package                     bundle            type          rows  hashes  bytes
    modules/d01_crypt/resources 0164ad48615ba9ed  texture         12       9  123456
    ... and the hashes themselves in the last column, space separated.

A row counts as missing exactly the way the sweeps count it - the catalogue's `name`
column is empty *and* `resource_name_overlay.json` has no name for the hash - which is the
same rule as `hashcracker/tools/build_targets.py` and `tools/status.sh`, so the totals here
agree with the score line (2,092 rows / 900 hashes at the time of writing; `08_progress.txt`
carries the live headline).

    python3 make_missing_report.py            # -> bundle_manifest/11_missing_by_bundle.tsv
    python3 make_missing_report.py --stdout   # print instead

`make_progress_report.py` calls `write_missing_by_bundle()` too, so every progress run
refreshes this file alongside `08_progress.txt`.
"""
import argparse
import collections
import csv
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "bundle_manifest"
CATALOGUE = MANIFEST / "04_bundle_resources.csv"
OVERLAY = HERE / "resource_name_overlay.json"
OUT = MANIFEST / "11_missing_by_bundle.tsv"
HEADER = ["package", "bundle", "type", "missing_rows", "missing_hashes", "bytes", "hashes"]


def missing_rows():
    """Every catalogue row with no name, as dicts (catalogue + overlay rule)."""
    overlay = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r.get("name_hash") or "").strip().lower()
            if not h:
                continue
            if (r.get("name") or "").strip() or h in overlay:
                continue
            yield {
                "package": r.get("package_path") or "",
                "bundle": r.get("bundle") or "",
                "type": r.get("type") or "",
                "hash": h,
                "size": int(r.get("body_size") or 0),
            }


def grouped():
    """(package, bundle, type) -> rows, distinct hashes (by size desc), total bytes."""
    out = collections.defaultdict(lambda: {"rows": 0, "hashes": {}, "bytes": 0})
    for r in missing_rows():
        g = out[(r["package"], r["bundle"], r["type"])]
        g["rows"] += 1
        g["bytes"] += r["size"]
        g["hashes"][r["hash"]] = max(g["hashes"].get(r["hash"], 0), r["size"])
    return out


def write_missing_by_bundle(path=OUT, stream=None):
    """Write the grouped view; returns (groups, rows, hashes)."""
    groups = grouped()
    rows = sum(g["rows"] for g in groups.values())
    hashes = len({h for g in groups.values() for h in g["hashes"]})
    out = stream or path.open("w", newline="", encoding="utf-8")
    try:
        w = csv.writer(out, delimiter="\t", lineterminator="\n")
        w.writerow(HEADER)
        for (package, bundle, type_), g in sorted(groups.items()):
            order = sorted(g["hashes"].items(), key=lambda kv: (-kv[1], kv[0]))
            w.writerow([package, bundle, type_, g["rows"], len(g["hashes"]), g["bytes"],
                        " ".join(h for h, _ in order)])
    finally:
        if stream is None:
            out.close()
    return len(groups), rows, hashes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    if args.stdout:
        import sys
        n, rows, hashes = write_missing_by_bundle(stream=sys.stdout)
    else:
        n, rows, hashes = write_missing_by_bundle()
    print(f"{n} (package, bundle, type) groups  {rows} missing rows  {hashes} distinct hashes"
          f"  -> {OUT}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
