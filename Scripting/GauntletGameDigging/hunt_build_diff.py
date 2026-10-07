#!/usr/bin/env python3
"""
Diff one package between two depot snapshots (FINDINGS.txt §50).

Same package name -> same bundle id, so a bundle id that exists in two snapshots
is the same package at two points in time, and its TOC entries line up by name
hash.  Three things come out of that:

  * hashes in both builds        the name did not change
  * hashes only in the old build removed (or renamed)
  * hashes only in the new build added (or renamed)

and - the useful part - *content* matches across builds: a body that is byte
identical in both builds but carries a different name hash is a **rename**, which
is exactly the "these all look like derived names" family.  Where one side of a
rename is a name we already hold, the pair is a rename example; where the new
side is unresolved, it is a rename target.

    python3 hunt_build_diff.py [--old SNAP] [--new SNAP] [--bundle ID] [--list]
"""
import argparse
import collections
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import list_game_bundles as L                                      # noqa: E402
from hunt_texture_refs import load                                 # noqa: E402

SNAPS = {"2014": "Gauntlet-PreSlayer-2014-10-10",
         "2015-01": "Gauntlet-PreSlayer-2015-01-21",
         "2015-08": "Gauntlet-PreSlayer-2015-08-11"}


def bundles_of(snap):
    root = REPO / SNAPS[snap]
    out = {}
    for dep in root.glob("depot_*"):
        for c in dep.glob("contents"):
            for f in c.iterdir():
                if f.is_file() and f.suffix not in (".stream", ".ini", ".data"):
                    out[f.name] = f
    return out


def entries_of(path):
    """(index, name_hash, type_hash, body) for one bundle."""
    try:
        _sig, _uz, data = L.decompress_bundle(path.read_bytes())
    except Exception:                                       # noqa: BLE001
        return []                                           # not a bundle (ini/data)
    if not data:
        return []
    _count, toc = L.parse_toc(data)
    entries, _end, _ok = L.parse_resources(data, toc)
    out = []
    for i, e in enumerate(entries):
        start = e["body_start"]
        out.append((i, e.get("name_hash"), e.get("type_hash"),
                    data[start:start + e.get("body_size", 0)]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="2015-01")
    ap.add_argument("--new", default="2015-08")
    ap.add_argument("--bundle")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dump-renames",
                    help="write clean 1:1 content moves (old hash -> new hash) here")
    args = ap.parse_args()

    old_b, new_b = bundles_of(args.old), bundles_of(args.new)
    shared = sorted(set(old_b) & set(new_b))
    print(f"{args.old}: {len(old_b)} bundles   {args.new}: {len(new_b)} bundles   "
          f"shared {len(shared)}")
    if args.list:
        named = 0
        for r in load():
            if r["_name"]:
                named += 1
        print(f"names we hold: {named}")
        return
    todo = [args.bundle] if args.bundle else shared
    totals = collections.Counter()
    all_examples = []
    for b in todo:
        if b not in old_b or b not in new_b:
            continue
        oe, ne = entries_of(old_b[b]), entries_of(new_b[b])
        oh = {h for _i, h, _t, _b in oe if h}
        nh = {h for _i, h, _t, _b in ne if h}
        only_old, only_new = oh - nh, nh - oh
        old_by_key = collections.defaultdict(list)
        new_by_key = collections.defaultdict(list)
        for i, h, t, body in oe:
            if body:
                old_by_key[(len(body), hashlib.md5(body).hexdigest())].append((h, i))
        for i, h, t, body in ne:
            if body:
                new_by_key[(len(body), hashlib.md5(body).hexdigest())].append((h, i))
        moved = 0
        examples = []
        name_of = {int(r["name_hash"], 16): r["_name"] for r in load() if r["_name"]}
        for k in set(old_by_key) & set(new_by_key):
            old_h = {h for h, _ in old_by_key[k]}
            new_h = {h for h, _ in new_by_key[k]}
            if old_h == new_h:
                continue
            moved += 1
            # only a *clean* bucket (one old hash, one new hash, differing) is a
            # rename; many-to-many buckets are just resources that share a body
            if len(old_h) == 1 and len(new_h) == 1:
                examples.append((old_h.pop(), new_h.pop()))
        named_pairs = [(name_of[oh], name_of[nh]) for oh, nh in examples
                       if oh in name_of and nh in name_of]
        named_new = [name_of[nh] for oh, nh in examples if nh in name_of]
        named_old = [name_of[oh] for oh, nh in examples if oh in name_of]
        totals["bundles"] += 1
        totals["old_only"] += len(only_old)
        totals["new_only"] += len(only_new)
        totals["content_moved"] += moved
        totals["renames_both_named"] += len(named_pairs)
        totals["renames_new_named"] += len(named_new)
        totals["renames_old_named"] += len(named_old)
        print(f"  {b}: {len(oe)} old / {len(ne)} new entries | "
              f"old-only {len(only_old):>5} new-only {len(only_new):>5} | "
              f"same-content-different-hash {moved:>5} "
              f"(both-named {len(named_pairs)}, new-named {len(named_new)}, "
              f"old-named {len(named_old)})")
        for a, c in named_pairs[:6]:
            print(f"        RENAME  {a}   ->   {c}")
        all_examples.extend(examples)
    if args.dump_renames:
        import json
        out = pathlib.Path(args.dump_renames)
        out.write_text(json.dumps([[f"{o:016x}", f"{n:016x}"]
                                   for o, n in all_examples], indent=0))
        print(f"wrote {len(all_examples)} clean content moves -> {out}")
    print("TOTALS:", dict(totals))


if __name__ == "__main__":
    main()
