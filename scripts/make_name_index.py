#!/usr/bin/env python3
"""
Regenerate the name indexes in `bundle_manifest/` (FINDINGS.txt 59).

The catalogue (`04_bundle_resources.csv`) is keyed by hash, which is the only key
the game uses - so it is the wrong way round for reading.  Two indexes are written
alongside it, regenerated on demand:

    06_names_by_name.txt   every recovered name, ALPHABETICAL BY NAME
    07_names_by_type.txt   the same, grouped by resource type

One row per name: the name, its hash, and every type the name carries (one name
legitimately covers several - a unit, its bones, its material and its lua share a
hash, because the hash *is* the name).

Output is aligned into columns for reading; `--tsv` switches to tab-separated rows
for grep/cut/sort.  The name column is sized to the bulk of the data (90th
percentile, capped) rather than to the longest name, because a single 150-character
shader chain would otherwise leave most of the file blank.

By default only names from the recovery overlay are listed - i.e. names *we*
recovered.  `--all` also merges whatever the catalogue's own `name` column holds;
that normally changes nothing, because `list_game_bundles.py` builds that column
from this same overlay (it matters for a catalogue built without it).

    python3 make_name_index.py                 # -> bundle_manifest/06_, 07_
    python3 make_name_index.py --all           # include the database's own names
    python3 make_name_index.py --mode type     # only the by-type index
    python3 make_name_index.py --tsv           # machine-readable rows
    python3 make_name_index.py --stdout        # print instead of writing
"""
import argparse
import collections
import csv
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE.parent / "Data" / "bundle_manifest"
CATALOGUE = MANIFEST / "04_bundle_resources.csv"
OVERLAY = HERE.parent / "Data" / "resource_name_overlay.json"


def build(include_all):
    """Return sorted [(name, hash, types)] plus the counts to report."""
    overlay = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                             errors="replace")))
    types = collections.defaultdict(set)
    entries = {}
    for r in rows:
        h = r["name_hash"].lower()
        if include_all:
            name = overlay.get(h) or (r.get("name") or "").strip()
        else:
            name = overlay.get(h)          # recovered-only: our names, nothing else
        if not name:
            continue
        entries[h] = name
        types[h].add((r.get("type") or "?").strip())
    out = sorted(((n, h, "+".join(sorted(types.get(h, {"?"}))))
                  for h, n in entries.items()),
                 key=lambda e: e[0].lower())
    return out, len(rows)


def name_width(entries):
    """Column width for the name, sized to the bulk of the data rather than the
    worst case: the longest name here is a 150-character shader chain, and padding
    every row to that would leave most of the file blank."""
    lens = sorted(len(n) for n, _h, _t in entries) or [40]
    cap = lens[min(len(lens) - 1, int(len(lens) * 0.90))] + 2
    return max(40, min(cap, 80))


def fmt(entries, header=True, tsv=False):
    """Readable aligned text by default; --tsv for machines."""
    if tsv:
        lines = [f"{n}\t{h}\t{t}" for n, h, t in entries]
        if header:
            lines = [f"# {len(entries):,} names, alphabetical by name "
                     f"(generated {time.strftime('%Y-%m-%d %H:%M')})",
                     "# name\thash\ttype"] + lines
        return "\n".join(lines) + "\n"

    nw, tw = name_width(entries), max((len(t) for _n, _h, t in entries), default=5)
    lines = []
    if header:
        lines += [f"{'name':<{nw}}  {'hash':<16}  types",
                  f"{'-' * nw}  {'-' * 16}  {'-' * min(tw, 40)}", ""]
    for n, h, t in entries:
        lines.append(f"{n:<{nw}}  {h:<16}  {t}" if len(n) < nw
                     else f"{n}  {h}  {t}")
    if header:
        lines += ["", f"{len(entries):,} names",
                  f"generated {time.strftime('%Y-%m-%d %H:%M')}"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="include names the game's database already carried")
    ap.add_argument("--mode", choices=("both", "name", "type"), default="both")
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--tsv", action="store_true",
                    help="tab-separated instead of aligned columns (for grep/cut)")
    ap.add_argument("--out-dir", default=str(MANIFEST))
    args = ap.parse_args()

    if not CATALOGUE.exists():
        sys.exit(f"catalogue not found: {CATALOGUE}\n"
                 f"(build it with:  python3 list_game_bundles.py --only resources)")
    entries, rowcount = build(args.all)
    out = pathlib.Path(args.out_dir)

    by_type = collections.defaultdict(list)
    for n, h, t in entries:
        by_type[t].append((n, h))

    made = []
    if args.mode in ("both", "name"):
        made.append(("06_names_by_name.txt", fmt(entries, tsv=args.tsv)))
    if args.mode in ("both", "type"):
        nw = name_width(entries)
        body = []
        for t in sorted(by_type):
            body.append(f"{'' if body else ''}### {t}  ({len(by_type[t])} names)")
            body.append("-" * (len(t) + 20))
            for n, h in by_type[t]:
                body.append(f"{n:<{nw}}  {h}" if len(n) < nw else f"{n}  {h}")
            body.append("")
        head = (f"{len(entries):,} names in {len(by_type)} type groups, "
                f"alphabetical within each (generated "
                f"{time.strftime('%Y-%m-%d %H:%M')})\n")
        made.append(("07_names_by_type.txt", (head if not args.stdout else "") +
                     "\n".join(body) + "\n"))

    if args.stdout:
        for name, text in made:
            print(f"===== {name}")
            print(text, end="")
        return

    out.mkdir(parents=True, exist_ok=True)
    for name, text in made:
        (out / name).write_text(text)
        print(f"  wrote {out / name}  ({len(text.splitlines()):,} lines)")

    print(f"\n{len(entries):,} names from {rowcount:,} catalogue rows "
          f"({'all' if args.all else 'recovered-only'})")
    print("by type:")
    for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"  {t:16s} {len(v):>5}")


if __name__ == "__main__":
    main()
