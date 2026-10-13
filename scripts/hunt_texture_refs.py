#!/usr/bin/env python3
"""
Name a texture from the resource that draws it (FINDINGS.txt §48).

A texture's name is not in the bundle, but its *referrers* are: a unit body and a
material body both carry the 64-bit hashes of the textures they use, matched
against the bundle's own TOC (`hunt_unit_textures.py`'s technique).  So for an
unnamed texture we can at least learn

  * which directory it belongs to, from the referrer's own name, and
  * what the other textures of that same stem are called - the missing one is
    usually the sibling of the ones we hold (`_diff`/`_norm`/`_spec` and then
    `_mask`, `_glow`, `_emissive`, ...).

    python3 hunt_texture_refs.py [--limit N] [--dry-run] [--write]

`--dry-run` prints the referrer histogram instead of generating candidates.
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import list_game_bundles as L                                      # noqa: E402
from bundle_tools import murmur_hash64                             # noqa: E402

CATALOGUE = HERE.parent / "Data" / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = HERE.parent / "Data" / "resource_name_overlay.json"
DEPOT = REPO / "Gauntlet-PreSlayer-2015-08-11" / "depot_258972" / "contents"

REFERRER_TYPES = ("material", "unit", "level", "particles", "decal",
                  "shader_library", "render_config", "strings")


def load():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    rows = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        r["_name"] = r.get("name") or ov.get(r.get("name_hash"))
        rows.append(r)
    return rows


def windows(body):
    """Every 8-byte little-endian window, at any alignment."""
    n = len(body)
    if n < 8:
        return np.empty(0, dtype=np.uint64)
    parts = []
    for off in range(8):
        cnt = (n - off) // 8
        if cnt:
            parts.append(np.frombuffer(memoryview(body)[off:off + cnt * 8],
                                       dtype="<u8"))
    return np.concatenate(parts)


def pairs(bundle_path, prefix, sample=20):
    """Print `<referrer> -> [referenced names]` for resolved pairs, to learn naming."""
    _sig, _uz, data = L.decompress_bundle(pathlib.Path(bundle_path).read_bytes())
    _count, toc = L.parse_toc(data)
    entries, _end, _ok = L.parse_resources(data, toc)
    name = {}
    for r in load():
        if r["_name"]:
            name[int(r["name_hash"], 16)] = (r["_name"], r["type"])
    shown = 0
    for e in entries:
        n = name.get(e.get("name_hash"))
        if not n or not n[0].startswith(prefix):
            continue
        start = e["body_start"]
        body = data[start:start + e.get("body_size", 0)]
        if len(body) < 8:
            continue
        hits = np.unique(windows(body))
        got = [name[int(h)] for h in hits.tolist() if int(h) in name]
        if len(got) < 2:
            continue
        shown += 1
        print(f"\n{n[0]}  [{n[1]}]")
        for nm, ty in sorted(set(got)):
            print(f"    {ty:<10} {nm}")
        if shown >= sample:
            break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--type", default="texture",
                    help="resource type to look for references to")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pairs", help="bundle path, to print referrer->referenced name pairs")
    ap.add_argument("--prefix", default="", help="only referrers whose name starts with this")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if args.pairs:
        pairs(args.pairs, args.prefix)
        return
    rows = load()
    by_bundle = collections.defaultdict(lambda: {"targets": {}, "resolved": []})
    for r in rows:
        b = r["bundle"]
        if not b:
            continue
        if r["_name"]:
            by_bundle[b]["resolved"].append((int(r["name_hash"], 16),
                                             r["_name"], r["type"]))
        else:
            by_bundle[b]["targets"][int(r["name_hash"], 16)] = r["type"]

    bundles = [(b, v) for b, v in by_bundle.items()
               if any(t == args.type for t in v["targets"].values())]
    bundles.sort(key=lambda kv: -sum(1 for t in kv[1]["targets"].values()
                                     if t == args.type))
    if args.limit:
        bundles = bundles[:args.limit]
    print(f"bundles with unresolved {args.type} {len(bundles)}")

    refs = collections.defaultdict(set)          # texture hash -> {referrer name}
    for b, v in bundles:
        path = DEPOT / b
        if not path.exists():
            print(f"  (bundle {b} not in depot)")
            continue
        _sig, _uz, data = L.decompress_bundle(path.read_bytes())
        _count, toc = L.parse_toc(data)
        entries, _end, _ok = L.parse_resources(data, toc)
        todo = {h for h, t in v["targets"].items() if t == args.type}
        if not todo:
            continue
        want = np.array(sorted(todo), dtype=np.uint64)
        for i, e in enumerate(entries):
            th = e.get("type_hash", 0)
            name = next((n for h, n, t in v["resolved"]
                         if h == e.get("name_hash")), None)
            if not name or name.rsplit("/", 1)[-1].count("/"):
                continue
            if not any(name for h, n, t in v["resolved"] if h == e.get("name_hash")):
                continue
            start = e["body_start"]
            body = data[start:start + e.get("body_size", 0)]
            if len(body) < 8:
                continue
            hits = np.intersect1d(np.unique(windows(body)), want)
            for h in hits:
                refs[int(h)].add(name)
        print(f"  {b}: {len(todo)} textures, {sum(1 for h in todo if h in refs)} referenced")

    print(f"\nreferenced {len(refs)} of the unresolved textures")
    hist = collections.Counter()
    for h, names in refs.items():
        for n in names:
            hist[n.rsplit("/", 1)[0] + "/"] += 1
    print("top referrer dirs:", hist.most_common(10))
    if args.dry_run:
        for h, names in list(refs.items())[:12]:
            print(f"  {h:016x}  <- {sorted(names)[:3]}")
        return
    if args.write:
        out = (HERE.parent / "hashcracker" / "work" /
               f"refs_{args.type}.json")
        out.write_text(json.dumps({f"{h:016x}": sorted(n) for h, n in refs.items()},
                                  indent=1, sort_keys=True))
        print(f"wrote {out}")
    return refs


if __name__ == "__main__":
    main()
