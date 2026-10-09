#!/usr/bin/env python3
"""
Dump every resource in the shipped build as a file, named and with an extension.

The point is to stop needing tools to look at the game: the catalogue knows every
resource's type and (for 17,435 of 20,000 rows) its name, and a resource's body is
just bytes inside a bundle.  So this walks every bundle, cuts each body out, and
writes it to

    <out>/named/<name>.<ext>            name known, extension from the type
    <out>/unresolved/<pkg>/<hash>.<ext> name not known - the gaps, kept visible

plus `index.tsv` (every row: status, type, hash, name, package, size, written path)
and `summary.txt` (per type: named vs unresolved, bytes).

Extensions are the type name itself, which is what Bitsquid uses (`.unit`,
`.material`, `.animation`, ...), with the handful of real-world exceptions mapped.

    python3 export_all_resources.py --out ~/Documents/Coding/Gauntlet-Export
    python3 export_all_resources.py --only texture --limit 20 --out /tmp/probe
    python3 export_all_resources.py --named-only

Bodies are written exactly as they sit in the bundle: this is a faithful dump, not a
conversion.  Some types reference data in the bundle's `.stream` sidecar (large
textures especially) - phase two (`--dds` and friends) is where those get decoded.
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import list_game_bundles as L                                          # noqa: E402

MANIFEST = HERE / "bundle_manifest"
CATALOGUE = MANIFEST / "04_bundle_resources.csv"
DEFAULT_OUT = pathlib.Path.home() / "Documents" / "Coding" / "Gauntlet-Export"

# The type name *is* the extension in this engine.  These are the exceptions, where
# a plain type name would be unhelpful or collide with another type.
EXT_OVERRIDES = {
    "shader_library_group": "shader_library_group",
    "shading_environment": "shading_environment",
    "shader_library": "shader_library",
    "state_machine": "state_machine",
    "render_config": "render_config",
    "mouse_cursor": "mouse_cursor",
    "timpani_bank": "timpani_bank",
    "timpani_master": "timpani_master",
    "network_config": "network_config",
    "surface_properties": "surface_properties",
    "physics_properties": "physics_properties",
    "strings": "strings",
}
UNSAFE = re.compile(r"[^A-Za-z0-9_.:/-]")


def extension_for(type_name):
    t = (type_name or "unknown").strip() or "unknown"
    return EXT_OVERRIDES.get(t, t)


def safe_relpath(name):
    """A resource name as a relative path, without letting it escape the output."""
    parts = [p for p in UNSAFE.sub("_", name).split("/") if p not in ("", ".", "..")]
    return pathlib.Path(*parts) if parts else pathlib.Path("_unnamed")


def catalogue_rows():
    """(bundle, index) -> row, from the hash -> name work (FINDINGS 18-34)."""
    out = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            try:
                key = (r["bundle"], int(r["index"]))
            except (KeyError, ValueError):
                continue
            out[key] = r
    return out


def bundle_files(contents):
    """Only real bundles: their file names are 16 hex digits (the package hash)."""
    out = {}
    for f in contents.iterdir():
        if f.is_file() and re.fullmatch(r"[0-9a-f]{16}", f.name):
            out[f.name] = f
    return out


def bodies_of(path):
    """(index, name_hash, type_hash, body) for one bundle file."""
    try:
        _sig, _uz, data = L.decompress_bundle(path.read_bytes())
    except Exception:                                                  # noqa: BLE001
        return []
    if not data:
        return []
    _count, toc = L.parse_toc(data)
    entries, _end, _ok = L.parse_resources(data, toc)
    out = []
    for i, e in enumerate(entries):
        start = e.get("body_start") or 0
        size = e.get("body_size") or 0
        out.append((i, e.get("name_hash"), e.get("type_hash"), data[start:start + size]))
    return out



def find_contents(root_hint=None):
    """The install's contents/ folder (where the real bundles live)."""
    root = L.find_install_root(root_hint)
    direct = root / "contents"
    if direct.is_dir():
        return direct
    for dep in root.glob("depot_*/contents"):
        return dep
    raise SystemExit(f"no contents/ folder under {root}")


def build_view_tree(out):
    """view/dds/**: a hardlink for every texture body that really is a DDS.

    Bitsquid keeps a DDS blob inside a `.texture` resource, so the bytes are already
    in the right format - only the extension stops a viewer from opening them.  A
    hardlink is the same inode, so this costs no disk at all.
    """
    made = skipped = 0
    named = out / "named"
    for src in named.rglob("*.texture"):
        try:
            if src.read_bytes()[:4] != b"DDS ":
                skipped += 1
                continue
        except OSError:
            skipped += 1
            continue
        dst = out / "view" / "dds" / src.relative_to(named).with_suffix(".dds")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            try:
                dst.hardlink_to(src)
            except OSError:
                shutil.copy2(src, dst)
            made += 1
    print(f"view/dds         : {made:,} hardlinked, {skipped:,} not a DDS", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"output root (default: {DEFAULT_OUT})")
    ap.add_argument("--root", help="game install root (default: auto-detect)")
    ap.add_argument("--only", action="append", metavar="TYPE",
                    help="export only this type (repeatable)")
    ap.add_argument("--limit", type=int, help="stop after N files (smoke testing)")
    ap.add_argument("--named-only", action="store_true",
                    help="skip rows we could not name")
    ap.add_argument("--unresolved-only", action="store_true",
                    help="write only the rows we could not name")
    ap.add_argument("--min-bytes", type=int, default=1,
                    help="skip bodies smaller than this (default 1)")
    ap.add_argument("--dds-view", action="store_true",
                    help="also build view/dds/**: a hardlink per texture whose body "
                         "really is a DDS, so it opens in any image viewer at no cost")
    ap.add_argument("--view-only", action="store_true",
                    help="skip the dump and only (re)build the view tree")
    args = ap.parse_args()

    out = pathlib.Path(args.out).expanduser()
    contents = find_contents(args.root)

    if args.view_only:
        build_view_tree(out)
        return

    cat = catalogue_rows()
    files = bundle_files(contents)
    print(f"install contents : {contents}")
    print(f"bundles          : {len(files)}")
    print(f"catalogue rows   : {len(cat):,}")
    print(f"output           : {out}", flush=True)

    want = set(args.only) if args.only else None
    (out / "named").mkdir(parents=True, exist_ok=True)
    (out / "unresolved").mkdir(parents=True, exist_ok=True)

    stats = collections.Counter()
    by_type = collections.defaultdict(lambda: collections.Counter())
    written = 0
    index = (out / "index.tsv").open("w", newline="", encoding="utf-8")
    idx = csv.writer(index, delimiter="\t")
    idx.writerow(["status", "type", "name", "name_hash", "package", "size",
                  "bundle", "index", "path"])

    for bundle_id in sorted(files):
        entries = bodies_of(files[bundle_id])
        stats["bundles_parsed"] += 1
        for i, name_hash, type_hash, body in entries:
            row = cat.get((bundle_id, i))
            type_name = (row or {}).get("type") or L.type_name(type_hash) or "unknown"
            name = ((row or {}).get("name") or "").strip()
            pkg = (row or {}).get("package_path", "")
            cat_hash = ((row or {}).get("name_hash") or "").strip().lower()
            parsed_hash = f"{name_hash:016x}" if name_hash is not None else ""
            status = "named" if name else "unresolved"

            stats[f"seen_{status}"] += 1
            by_type[type_name][status] += 1
            by_type[type_name]["bytes"] += len(body)

            if row and cat_hash and parsed_hash and cat_hash != parsed_hash:
                stats["hash_mismatch"] += 1
                status = "unresolved"
                name = ""
            if want and type_name not in want:
                stats["skipped_type"] += 1
                continue
            if args.named_only and status != "named":
                continue
            if args.unresolved_only and status != "unresolved":
                continue
            if len(body) < args.min_bytes:
                stats["skipped_empty"] += 1
                continue

            ext = extension_for(type_name)
            if status == "named":
                rel = pathlib.Path("named") / safe_relpath(name).with_suffix("." + ext)
            else:
                # One file per distinct hash, grouped by type: the same unnamed
                # resource often sits in several packages, and 2,565 rows are only
                # 1,096 resources (the index keeps every row's package).
                rel = pathlib.Path("unresolved") / ext / f"{parsed_hash or f'row{i}'}.{ext}"
                if (out / rel).exists():
                    stats["duplicate_hash"] += 1
                    idx.writerow([status, type_name, name, parsed_hash, pkg, len(body),
                                  bundle_id, i, str(rel)])
                    continue
            target = out / rel
            if target.exists():
                stats["duplicate_name"] += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                written += 1

            idx.writerow([status, type_name, name, parsed_hash, pkg, len(body),
                          bundle_id, i, str(rel)])
            if args.limit and written >= args.limit:
                stats["limit_hit"] = 1
                break
        if args.limit and written >= args.limit:
            break
        print(f"  [{stats['bundles_parsed']}/{len(files)}] {bundle_id}: "
              f"written {written:,}", flush=True)

    index.close()

    with (out / "summary.txt").open("w", encoding="utf-8") as fh:
        fh.write(f"{written:,} files written to {out}\n")
        fh.write(f"{stats['seen_named']:,} named, {stats['seen_unresolved']:,} unresolved\n\n")
        fh.write(f"{'type':24s} {'named':>8s} {'unres':>8s} {'MB':>10s}\n")
        for t in sorted(by_type, key=lambda k: -by_type[k]["bytes"]):
            c = by_type[t]
            fh.write(f"{t:24s} {c['named']:8,} {c['unresolved']:8,} "
                     f"{c['bytes']/1048576:10.1f}\n")

    print(f"\nwritten          : {written:,} files", flush=True)
    for k in sorted(stats):
        print(f"  {k:18s} {stats[k]:,}", flush=True)
    print(f"index            : {out / 'index.tsv'}", flush=True)
    print(f"summary          : {out / 'summary.txt'}", flush=True)

    if args.dds_view:
        build_view_tree(out)


if __name__ == "__main__":
    main()
