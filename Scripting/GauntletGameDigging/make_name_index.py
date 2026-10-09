#!/usr/bin/env python3
"""
Regenerate the name indexes in `bundle_manifest/` (FINDINGS.txt 59).

The catalogue (`04_bundle_resources.csv`) is keyed by hash, which is the only key
the game uses - so it is the wrong way round for reading.  Two indexes are written
alongside it, regenerated on demand:

    05_names_by_name.txt   every recovered name, ALPHABETICAL BY NAME
    06_names_by_type.txt   the same, grouped by resource type

One row per name: `name<TAB>hash<TAB>type`, where the type column is every type
the name carries (one name legitimately covers several - a unit, its bones, its
material and its lua share a hash, because the hash *is* the name).

By default only names from the recovery overlay are listed - i.e. names *we*
recovered.  `--all` also includes names the game's own database already carried.

    python3 make_name_index.py                 # -> bundle_manifest/05_, 06_
    python3 make_name_index.py --all           # include the database's own names
    python3 make_name_index.py --mode type     # only the by-type index
    python3 make_name_index.py --stdout       # print instead of writing
"""
import argparse
import collections
import csv
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "bundle_manifest"
CATALOGUE = MANIFEST / "04_bundle_resources.csv"
OVERLAY = HERE / "resource_name_overlay.json"


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


def fmt(entries, header=True):
    lines = []
    if header:
        lines.append(f"# {len(entries):,} names, alphabetical by name "
                     f"(generated {time.strftime('%Y-%m-%d %H:%M')})")
        lines.append("# name\thash\ttype")
    lines += [f"{n}\t{h}\t{t}" for n, h, t in entries]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="include names the game's database already carried")
    ap.add_argument("--mode", choices=("both", "name", "type"), default="both")
    ap.add_argument("--stdout", action="store_true")
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
        made.append(("05_names_by_name.txt", fmt(entries)))
    if args.mode in ("both", "type"):
        body = []
        if not args.stdout:
            body.append(f"# {len(entries):,} names in {len(by_type)} type groups "
                        f"(generated {time.strftime('%Y-%m-%d %H:%M')})")
        for t in sorted(by_type):
            body.append(f"\n### {t}  ({len(by_type[t])} names)")
            body += [f"{n}\t{h}" for n, h in by_type[t]]
        made.append(("06_names_by_type.txt", "\n".join(body) + "\n"))

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
