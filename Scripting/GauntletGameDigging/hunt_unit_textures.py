#!/usr/bin/env python3
"""
Hunt the textures a unit actually uses, by following its resource references.

Name-pattern hunting (`derive_tex_siblings.py` and friends) can only find a
texture if it is named after the thing that owns it.  When it is not - a
character that re-uses another character's maps, a prop with an odd stem - the
only reliable route is to read the resource: a `.unit` body carries the hashes
of the materials it draws with, and a `.material` body carries the hashes of its
textures.  Every one of those hashes is a MurmurHash64A of a resource name, so
they can be resolved against the catalogue or flagged as still-missing targets.

    python3 hunt_unit_textures.py --bundle <file> --name characters/demon_overlord_mini/demon_overlord_mini
    python3 hunt_unit_textures.py --bundle <file> --hash e42cccf190760a24 --materials

`--bundle` is an unpacked-or-packed bundle file (a depot `contents/<bundle-id>`
file, the id being murmur64A of the package path).  Materials referenced by the
unit are decoded in place (`resource_tools.material_tools.decode_material`) so
their texture slots come out by name where we have it.
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "resource_tools"))

import list_game_bundles as L      # noqa: E402  (decompress_bundle/parse_toc/...)
from material_tools import decode_material  # noqa: E402

CATALOGUE = HERE / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = HERE / "resource_name_overlay.json"
HASHDB = HERE / "hash_database.json"


def murmur(name: str) -> int:
    return L.murmur_hash64(name)


def known_resources():
    """hash -> (name, type) from the catalogue, our overlay and the hash db."""
    known = {}
    if HASHDB.exists():
        for h, n in json.loads(HASHDB.read_text()).items():
            known[int(h, 16)] = (n, "?")
    if CATALOGUE.exists():
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if r.get("name"):
                known[int(r["name_hash"], 16)] = (r["name"], r["type"])
    if OVERLAY.exists():
        for h, n in json.loads(OVERLAY.read_text()).items():
            known.setdefault(int(h, 16), (n, "overlay"))
    return known


def type_map():
    """type_hash (int) -> type name, from the catalogue."""
    m = {}
    if CATALOGUE.exists():
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if r.get("type_hash") and r.get("type"):
                m[int(r["type_hash"], 16)] = r["type"]
    return m


def find_entries(data: bytes, hash_int: int):
    """Every (index, entry) in the bundle carrying this name hash."""
    _count, toc = L.parse_toc(data)
    entries, _end, _ok = L.parse_resources(data, toc)
    out = []
    for i, e in enumerate(entries):
        if e.get("name_hash") == hash_int:
            start = e["body_start"]
            out.append((i, e, data[start:start + e.get("body_size", 0)]))
    return out


def find_body(data: bytes, hash_int: int, want_type: int = None):
    """Pick the entry for a name hash; `want_type` disambiguates by type hash."""
    cands = find_entries(data, hash_int)
    if not cands:
        return None, None, None
    if want_type is not None:
        for i, e, b in cands:
            if e.get("type_hash") == want_type:
                return i, e, b
    return max(cands, key=lambda t: len(t[2]))


def anchored_candidates(name: str, suffixes: list):
    """
    Names this resource would have by convention, anchored on its own name.

    The one that matters most here is Stingray's `m_<name>` for materials
    (`characters/x/x` -> `characters/x/m_x`), plus the map forms `<name><suffix>`
    and the material forms `<name>_material` / `<name>_mat`.
    """
    d, _, leaf = name.rpartition("/")
    pre = d + "/" if d else ""
    stems = {leaf}
    for p in ("avatar_", "boss_"):
        if leaf.startswith(p):
            stems.add(leaf[len(p):])
    cands = set()
    for s in stems:
        cands.add(pre + "m_" + s)
        cands.add(pre + s + "_material")
        cands.add(pre + s + "_mat")
        for suf in suffixes:
            cands.add(pre + s + suf)
            cands.add(pre + "m_" + s + suf)
    return cands


def files_missing():
    """name hashes the catalogue could not name and our overlay does not cover."""
    missing = set()
    if CATALOGUE.exists():
        ov = set()
        if OVERLAY.exists():
            ov = set(json.loads(OVERLAY.read_text()))
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if not r.get("name") and r.get("name_hash") not in ov:
                missing.add(int(r["name_hash"], 16))
    return missing


def bundle_toc(data: bytes, tmap: dict):
    """name_hash -> (type name, index) for everything the bundle carries."""
    _count, toc = L.parse_toc(data)
    entries, _end, _ok = L.parse_resources(data, toc)
    out = {}
    for i, e in enumerate(entries):
        th = e.get("type_hash", 0)
        out.setdefault(e.get("name_hash"), (tmap.get(th, hex(th)), i, e))
    return out


def scan_references(body: bytes, hashes: set):
    """Every 64-bit little-endian window that names a resource in `hashes`."""
    found = collections.Counter()
    for off in range(0, max(0, len(body) - 7)):
        v = int.from_bytes(body[off:off + 8], "little")
        if v in hashes:
            found[v] += 1
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--name")
    ap.add_argument("--hash")
    ap.add_argument("--type", help="resource type to pick, e.g. unit / material")
    ap.add_argument("--materials", action="store_true",
                    help="also decode referenced materials and list their textures")
    ap.add_argument("--suffixes",
                    default=str(HERE.parent / "hashcracker" / "data" / "suffixes.txt"))
    args = ap.parse_args()

    if not args.name and not args.hash:
        ap.error("give --name or --hash")
    target = int(args.hash, 16) if args.hash else murmur(args.name)
    known = known_resources()
    tmap = type_map()
    sf = pathlib.Path(args.suffixes)
    suffixes = [s.strip() for s in sf.read_text().split() if s.strip()] if sf.exists() else []

    packed = pathlib.Path(args.bundle).read_bytes()
    print(f"bundle      : {args.bundle}  ({len(packed):,} bytes)")
    _sig, _unzipped, data = L.decompress_bundle(packed)

    entries = find_entries(data, target)
    print(f"resource    : {args.name or args.hash}  [{known.get(target, ('<unknown>',))[0]}]")
    for i, e, b in entries:
        th = e.get("type_hash", 0)
        print(f"   entry {i:<5} type {tmap.get(th, hex(th)):<12} body {len(b):>9,}")
    want = None
    if args.type:
        want = next((h for h, n in tmap.items() if n == args.type), None)
    idx, entry, body = find_body(data, target, want)
    if body is None:
        raise SystemExit("resource not found in this bundle")
    toc_by_hash = bundle_toc(data, tmap)

    refs = scan_references(body, set(toc_by_hash))
    known_missing = files_missing()
    print(f"\nreferenced resources ({len(refs)})  [matched against this bundle's TOC]:")
    for h, count in refs.most_common():
        t, i, _e = toc_by_hash[h]
        n = known.get(h, (None,))[0]
        if n:
            tag = f"known: {n}"
        elif h in known_missing:
            tag = "*** UNRESOLVED TARGET ***"
        else:
            tag = "(named elsewhere)"
        print(f"  {t:<12} {h:016x} x{count:<3} {tag}")

    # ---- name the unknown neighbours of this resource ----------------------
    cands = {murmur(c): c for c in anchored_candidates(args.name or "", suffixes)}
    unknown = [h for h in refs if h not in known]
    print(f"\nunknown reference hashes: {len(unknown)}")
    for h in unknown:
        print(f"  {h:016x}  ->  {cands.get(h, '<no convention match>')}")

    if not args.materials:
        return

    # ---- walk the materials (named or just-named) for their texture slots --
    walk = [h for h in refs if known.get(h, ("", ""))[1] == "material"]
    walk += [h for h in unknown if cands.get(h, "").rsplit("/", 1)[-1].startswith("m_")]
    print(f"\nwalking {len(walk)} material(s):")
    for h in walk:
        _i, _e, mb = find_body(data, h)
        if not mb:
            continue
        try:
            dec = decode_material(mb)
        except Exception:
            continue
        label = known.get(h, (cands.get(h, "<unknown>"),))[0]
        for t in dec.get("textures", []):
            th = int(t["texture_hash"], 16)
            n = known.get(th, (None,))[0]
            if n:
                tag = f"known: {n}"
            else:
                tag = cands.get(th, "*** UNRESOLVED TARGET ***")
            print(f"  {label}\n      slot {t['slot_index']:<3} {th:016x}  {tag}")


if __name__ == "__main__":
    main()
