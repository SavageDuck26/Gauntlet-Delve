#!/usr/bin/env python3
"""
Consume a runtime name capture and turn it into recovered resource names.

The companion C++ loader logs every resource name the running
game touches - first through the engine's `can_get_resource` / `resource_package`
call sites, and then, once `HashNameAddress` points at the string hasher (FINDINGS
60.15), through the name->hash function itself, which sees far more names.  The
dump is a TSV of `type<TAB>name`.  This hashes each captured name exactly the way
the engine does (MurmurHash64A, seed 0, lowercased - `hunt_unit_textures.murmur`)
and sorts every capture into the three answers that matter:

    KNOWN      the hash is a row we had already named.  This is the control: a
               capture full of KNOWN rows proves the capture-and-hash chain end to
               end, and any KNOWN row whose catalogue name differs from the
               captured string says the convention (case, separators) is off.
    RECOVERED  the hash is a row we could not name.  This is the payoff: an exact
               name, read out of the engine, for a row that until now was a hash
               and a size.
    NEW        the hash matches no row in the catalogue - new vocabulary, either
               mod-local, generated at runtime, or naming something this build
               never ships.

    python3 hunt_runtime_names.py                    # default capture path
    python3 hunt_runtime_names.py --capture /tmp/runtime_names.tsv
    python3 hunt_runtime_names.py --list recovered
    python3 hunt_runtime_names.py --out /tmp/report.tsv

Nothing is written into the research tree: the catalogue and the reachability
master are read-only inputs here and the report lands next to the capture, so a
session can be gone over before any of it is folded into the overlay or matches.tsv
(that is `merge_matches.py`'s job, and a deliberate second step).
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hunt_unit_textures import murmur                                   # noqa: E402

MANIFEST = HERE.parent / "Data" / "bundle_manifest"
GAME = pathlib.Path.home() / ".local/share/Steam/steamapps/common/Gauntlet"
DEFAULT_CAPTURE = GAME / "binaries" / "runtime_names.tsv"
DEFAULT_REPORT = "runtime_names_classified.tsv"


def catalogue():
    """The shipped build, as (hash -> name or None)."""
    overlay = json.loads((HERE.parent / "Data" / "resource_name_overlay.json").read_text())
    out = {}
    with (MANIFEST / "04_bundle_resources.csv").open(newline="",
                                                     encoding="utf-8",
                                                     errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = r["name_hash"].lower()
            out[h] = r.get("name") or overlay.get(h) or None
    return out


def unresolved_master():
    """The reachability audit's rows, keyed by hash: type/package/size/reason."""
    path = MANIFEST / "10_unresolved_master.tsv"
    out = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            h = (r.get("hash") or "").strip().lower()
            if h:
                out[h] = r
    return out


def read_capture(path):
    """(capture_type, name) pairs, in file order, de-duplicated."""
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2:
            continue
        key = (parts[0], parts[-1])
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def classify(pairs, cat, unresolved):
    rows = []
    for capture_type, name in pairs:
        h = f"{murmur(name):016x}"
        if h in cat:
            rows.append({"status": "KNOWN", "hash": h, "name": name,
                         "capture_type": capture_type, "catalogue": cat[h] or "",
                         "type": "", "package": "", "size": ""})
        elif h in unresolved:
            r = unresolved[h]
            rows.append({"status": "RECOVERED", "hash": h, "name": name,
                         "capture_type": capture_type, "catalogue": "",
                         "type": r.get("type", ""), "package": r.get("package", ""),
                         "size": r.get("size", "")})
        else:
            rows.append({"status": "NEW", "hash": h, "name": name,
                         "capture_type": capture_type, "catalogue": "",
                         "type": "", "package": "", "size": ""})
    return rows


def write_out(rows, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["status", "hash", "name", "capture_type", "type", "package", "size",
            "catalogue"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def report(rows, pair_count):
    by_status = collections.Counter(r["status"] for r in rows)
    print(f"  capture: {pair_count:,} unique (type, name) pairs", file=sys.stderr)
    print(f"    KNOWN     {by_status['KNOWN']:>6,}  catalogue rows we already had",
          file=sys.stderr)
    print(f"    RECOVERED {by_status['RECOVERED']:>6,}  previously unresolved rows",
          file=sys.stderr)
    print(f"    NEW       {by_status['NEW']:>6,}  no catalogue row at all",
          file=sys.stderr)

    strange = [r for r in rows if r["status"] == "KNOWN"
               and r["catalogue"].lower() != r["name"].lower()]
    if strange:
        print(f"\n  KNOWN rows whose captured string differs from the catalogue name "
              f"({len(strange):,}) - check the naming convention:", file=sys.stderr)
        for r in strange[:10]:
            print(f"    {r['hash']}  captured={r['name']!r}  "
                  f"catalogue={r['catalogue']!r}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default=str(DEFAULT_CAPTURE),
                    help=f"runtime_names.tsv to read (default: {DEFAULT_CAPTURE})")
    ap.add_argument("--list", choices=["known", "recovered", "new"],
                    help="print one class in full instead of the summary")
    ap.add_argument("--limit", type=int, default=60,
                    help="rows to print with --list (default 60)")
    ap.add_argument("--out", help=f"report path (default: next to the capture, "
                                  f"i.e. {DEFAULT_REPORT})")
    args = ap.parse_args()

    cap = pathlib.Path(args.capture)
    if not cap.exists():
        ap.error(f"no capture at {cap} - run the game with the loader installed "
                 f"and [NameMining].Enabled=1")

    cat_csv = MANIFEST / "04_bundle_resources.csv"
    if not cat_csv.exists():
        ap.error(f"no catalogue at {cat_csv} - classifying a capture needs the "
                 f"shipped build's resource list")

    out_path = pathlib.Path(args.out) if args.out else cap.parent / DEFAULT_REPORT
    pairs = read_capture(cap)
    rows = classify(pairs, catalogue(), unresolved_master())
    write_out(rows, out_path)
    print(f"  report: {out_path}  (read-only; nothing written into the research tree)",
          file=sys.stderr)

    if not args.list:
        report(rows, len(pairs))
        rec = [r for r in rows if r["status"] == "RECOVERED"]
        if rec:
            print(f"\n  first {min(10, len(rec)):,} recovered names:", file=sys.stderr)
            for r in rec[:10]:
                print(f"    {r['hash']}  {r['name']}   ({r['type']} in "
                      f"{r['package']}, {r['size']} bytes)", file=sys.stderr)
        print(f"\n  written: {out_path}", file=sys.stderr)
        return

    want = {"known": "KNOWN", "recovered": "RECOVERED", "new": "NEW"}[args.list]
    sel = [r for r in rows if r["status"] == want]
    width = max((len(r["name"]) for r in sel), default=4)
    print(f"{'name':{width}s}  {'hash':16s}  {'type':14s}  package")
    print("-" * (width + 20 + 16 + 40))
    for r in sel[:args.limit]:
        extra = f"{r['type']:14s}  {r['package']}" if r["type"] else r["catalogue"]
        print(f"{r['name']:{width}s}  {r['hash']}  {extra}")
    if len(sel) > args.limit:
        print(f"... and {len(sel) - args.limit:,} more "
              f"(see {out_path})")


if __name__ == "__main__":
    main()
