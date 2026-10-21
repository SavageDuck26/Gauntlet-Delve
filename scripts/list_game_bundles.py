#!/usr/bin/env python3
"""
Gauntlet Game Bundle & File Cataloguer
======================================

Produces human-readable AND machine-readable listings of "everything" shipped
with Gauntlet Slayer Edition:

  * every loose file in the install tree (`file_tree`)
  * every bundle file in `contents/` incl. `.stream` companions (`bundles`)
  * every bundle registered in `contents/bundle_database.data` (`database`)
  * every resource packed inside every bundle (`resources`)

Format notes (do NOT extrapolate -- see FINDINGS.txt sections 4-6):

  * Bundle name  = MurmurHash64A(package_path, seed=0) rendered as 16 lowercase
                   hex chars. e.g. b22560b172a4cff8 -> "resource_packages/elias".
  * Packed file  = 12-byte header {u32 sig(0xF0000004), u32 unzipped_size, u32 0}
                   followed by N x {u32 compressed_size, zlib bytes}.
                   Each block decompresses to a padded 64 KiB frame; the true
                   content length is `unzipped_size`.
  * Unpacked body (CORRECTED Oct 2026 - see FINDINGS 9H.12 and SCRIPTS.md
    "Mod bundles: the container format".  This tool's earlier "(N+1) TOC with a
    sentinel" description was WRONG, and so was "resource 0 has a 20-byte header"):
      [0x000] u32   N            resource count
      [0x004] 256 bytes of preamble (opaque for natives, zero for customs)
      [0x104] TOC: EXACTLY N x 16-byte entries {u64 type_hash, u64 name_hash} -
              NO sentinel
      [0x104 + N*16] payloads back to back, NO alignment padding.  EVERY resource,
              resource 0 included, carries the same 36-byte header
              {u64 type, u64 name, u32 flags, u64 stream_size, u32 data_size,
              u32 unknown} followed by data_size bytes

Usage:
    python list_game_bundles.py                      # everything, auto path
    python list_game_bundles.py --contents <dir>
    python list_game_bundles.py --out <dir>
    python list_game_bundles.py --only resources
    python list_game_bundles.py --no-decompress      # TOC only (fast, low RAM)

Conventions follow scripts/ (murmur_hash64, snake_case).
"""

import argparse
import csv
import json
import os
import struct
import sys
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME = os.path.expanduser("~")

# Candidate install roots (Linux/Proton first, then native Windows).
INSTALL_CANDIDATES = [
    os.path.expanduser(
        "~/.local/share/Steam/steamapps/common/Gauntlet"),
    r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet",
    r"C:\Program Files\Steam\steamapps\common\Gauntlet",
]

# Where the reverse-engineering toolchain + hash database live.
TOOL_DIR = Path(__file__).resolve().parent
HASH_DB_CANDIDATES = [
    TOOL_DIR.parent / "Data" / "hash_database.json",
]

BUNDLE_SIG_OLD = 0xF0000004
BUNDLE_SIG_NEW = 0xF0000005
KNOWN_SIGS = (BUNDLE_SIG_OLD, BUNDLE_SIG_NEW)
ZLIB_CHUNK = 0x10000  # 64 KiB uncompressed block size
# first two bytes of a zlib stream; a chunk without one is stored RAW (Pre-Slayer)
ZLIB_MAGIC = (b"\x78\x9c", b"\x78\xda", b"\x78\x01", b"\x78\x5e")


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def murmur_hash64(key: str, seed: int = 0) -> int:
    """MurmurHash64A over lowercase UTF-8 bytes, little-endian (seed 0)."""
    m = 0xC6A4A7935BD1E995
    r = 47
    key_bytes = key.lower().encode("utf-8")
    length = len(key_bytes)
    h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)

    nblocks = length // 8
    for i in range(nblocks):
        k = struct.unpack("<Q", key_bytes[i * 8:(i + 1) * 8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    tail = key_bytes[nblocks * 8:]
    if len(tail) >= 7:
        h ^= tail[6] << 48
    if len(tail) >= 6:
        h ^= tail[5] << 40
    if len(tail) >= 5:
        h ^= tail[4] << 32
    if len(tail) >= 4:
        h ^= tail[3] << 24
    if len(tail) >= 3:
        h ^= tail[2] << 16
    if len(tail) >= 2:
        h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    return h


# Resource type names taken verbatim from the engine's null-separated type-name
# string table inside binaries/gauntlet.exe (region ~0x345380, "config",
# "render_config", "unit", ... "ugg", "adapter_index", ...). This is the
# authoritative list -- the type hash is murmur64A(name, seed=0). It supersedes
# the (partly incorrect) mappings found in older tools such as
# catalog_bundles.py / analyze_bundles.py.
TYPE_NAMES = [
    "config", "render_config", "unit", "shader_library_group",
    "shader_library", "shader", "texture", "material", "animation",
    "animation_curves", "bones", "state_machine", "lua",
    "physics_properties", "package", "particles", "wav", "sound_environment",
    "font", "level", "spu_job", "data", "shading_environment", "strings",
    "network_config", "mouse_cursor", "timpani_bank", "timpani_master",
    "flow", "surface_properties", "baked_lighting", "ivf", "bik",
    "vector_field", "apb", "xml", "ugg", "adapter_index", "boot_package",
]
TYPE_HASH_TO_NAME = {murmur_hash64(t): t for t in TYPE_NAMES}


# ---------------------------------------------------------------------------
# Bundle reading
# ---------------------------------------------------------------------------

def decompress_bundle(packed: bytes, limit: int = None):
    """
    Decompress a packed bundle.

    Returns (signature, unzipped_size, data). `data` is truncated to
    `unzipped_size`. If `limit` is given, stop once `len(data) >= limit`
    (used to grab just the TOC without materialising the whole bundle).
    """
    if len(packed) < 12:
        raise ValueError("file too small for bundle header")
    signature, unzipped_size, _pad = struct.unpack("<III", packed[:12])
    if signature not in KNOWN_SIGS:
        raise ValueError("unknown bundle signature 0x%08X" % signature)

    result = bytearray()
    pos = 12
    while pos + 4 <= len(packed):
        chunk_size = struct.unpack_from("<I", packed, pos)[0]
        pos += 4
        if chunk_size == 0 or pos + chunk_size > len(packed):
            break
        blk = packed[pos:pos + chunk_size]
        # Pre-Slayer era bundles mix RAW 64 KiB chunks in with the zlib ones
        # (the block simply does not start with a zlib magic byte). Same header,
        # same TOC - only the compression of individual chunks differs.
        result.extend(zlib.decompress(blk) if blk[:2] in ZLIB_MAGIC else blk)
        pos += chunk_size
        if limit is not None and len(result) >= limit:
            break

    if unzipped_size and len(result) > unzipped_size:
        del result[unzipped_size:]
    return signature, unzipped_size, bytes(result)


def parse_toc(data: bytes):
    """
    Return (resource_count, toc) where toc is a list of (type_hash, name_hash).

    The on-disk TOC holds exactly N entries at 0x104, with no sentinel.  An (N+1)th
    "sentinel" entry, and a special 20-byte header for resource 0, are the mistakes
    that made a bundle the engine cannot read look structurally fine - see FINDINGS
    9H.12 and SCRIPTS.md "Mod bundles".
    """
    if len(data) < 4:
        raise ValueError("no resource count")
    count = struct.unpack_from("<I", data, 0)[0]
    toc = []
    for i in range(count):
        off = 0x104 + i * 16
        if off + 16 > len(data):
            break
        toc.append(struct.unpack_from("<QQ", data, off))
    return count, toc


def parse_resources(data: bytes, toc):
    """
    Locate every resource in the bundle body and report its on-disk footprint.

    Layout (corrected Oct 2026, verified against native bundles - FINDINGS 9H.12):
      * EVERY resource, resource 0 included, carries the same 36-byte header
        {u64 type, u64 name, u32 flags, u64 stream_size, u32 data_size, u32 unknown}
        at toc_end = 0x104 + N*16, followed by its body. `hdr_size` is NOT always the
        body length:
        banked/streamed resources (e.g. timpani_bank) embed an internal
        sub-stream table, so the real footprint is only known from the gap to
        the next header. We therefore walk forward, matching each TOC entry's
        16-byte (type,name) pattern in file order (the method used by
        replace_textures_v4.py).

    Returns (entries, end_offset, scan_complete):
      * entries[i]  : dict with header_offset, body_start, body_size,
                      hdr_size (declared), stream_size, flags, type/name hash
      * end_offset  : byte position just past the final resource body
      * scan_complete: True if every TOC entry's header was found in order
    """
    toc_end = 0x104 + len(toc) * 16
    entries = []
    scan_complete = True

    if not toc or toc_end + 36 > len(data):
        return entries, toc_end, False

    # ---- resource 0: the same 36-byte header as every other resource -----
    # The fields are read at +16 for the same reason the loop below reads them there
    # (the first 16 bytes are type/name, which the TOC already gave us), so entry 0 is
    # shaped exactly like its siblings.  Every offset and value this function returns
    # is byte-for-byte what the previous arithmetic produced: the old code computed
    # toc_end as 0x104 + (N+1)*16 and then added its "20-byte" header, i.e. it read at
    # 0x104 + N*16 + 16 and stopped at 0x104 + N*16 + 36 - which IS this header's +16
    # and its end.  header_offset is the one improvement: it now points at the real
    # start of the 36-byte header instead of 16 bytes into it.
    flags, _stream_size, hdr_size, stream_sz = struct.unpack_from("<IQII", data, toc_end + 16)
    entries.append({
        "index": 0, "header_offset": toc_end,
        "type_hash": toc[0][0], "name_hash": toc[0][1],
        "flags": flags, "hdr_size": hdr_size, "stream_size": stream_sz,
        "body_start": toc_end + 36, "body_size": None,
    })
    prev = entries[0]
    search = prev["body_start"]

    # ---- resources 1..N-1 (full 36-byte header, in TOC order) ------------
    for i in range(1, len(toc)):
        type_hash, name_hash = toc[i]
        pat = struct.pack("<QQ", type_hash, name_hash)
        j = data.find(pat, search)
        if j < 0:
            scan_complete = False
            break
        prev["body_size"] = j - prev["body_start"]
        flags, _zeros, hdr_size, stream_sz = struct.unpack_from("<IQII", data, j + 16)
        entry = {
            "index": i, "header_offset": j,
            "type_hash": type_hash, "name_hash": name_hash,
            "flags": flags, "hdr_size": hdr_size, "stream_size": stream_sz,
            "body_start": j + 36, "body_size": None,
        }
        entries.append(entry)
        prev = entry
        search = j + 36

    prev["body_size"] = max(0, len(data) - prev["body_start"])
    end_offset = prev["body_start"] + prev["body_size"]
    return entries, end_offset, scan_complete


# ---------------------------------------------------------------------------
# bundle_database.data
# ---------------------------------------------------------------------------

def parse_bundle_database(db_path: Path):
    """
    Parse bundle_database.data -> list of dicts (priority order = file order).

    Header  : {u32 version, u32 entry_count}
    Entry   : {u32 platform, u32 name_len, char[name_len] name,
               u32 stream_len, char[stream_len] stream_name}
    """
    raw = db_path.read_bytes()
    if len(raw) < 8:
        return 0, []
    version, entry_count = struct.unpack_from("<II", raw, 0)
    entries = []
    off = 8
    while off + 8 <= len(raw) and len(entries) < entry_count:
        platform, name_len = struct.unpack_from("<II", raw, off)
        if name_len == 0 or name_len > 100:
            break
        off += 8
        name = raw[off:off + name_len].decode("ascii", "replace")
        off += name_len
        stream_name = None
        if off + 4 <= len(raw):
            stream_len = struct.unpack_from("<I", raw, off)[0]
            off += 4
            if 0 < stream_len < 100 and off + stream_len <= len(raw):
                stream_name = raw[off:off + stream_len].decode("ascii", "replace")
                off += stream_len
                if off < len(raw) and raw[off] == 0:
                    off += 1
        entries.append({
            "platform": platform,
            "name": name,
            "stream_name": stream_name,
        })
    return version, entries


# ---------------------------------------------------------------------------
# Hash database (resource name -> path)
# ---------------------------------------------------------------------------

def load_hash_db():
    """
    Return {lowercase_hex_hash: name} from hash_database.json, merged with any
    brute-forced names: bundle_name_overlay.json (crack_bundle_names.py) and
    resource_name_overlay.json (crack_resource_names.py).
    """
    db = {}
    for path in HASH_DB_CANDIDATES:
        if path.suffix == ".json" and path.exists():
            with open(path, "r", encoding="utf-8") as f:
                db = json.load(f)
            break
    for overlay in (TOOL_DIR.parent / "Data" / "bundle_name_overlay.json",
                    TOOL_DIR.parent / "Data" / "resource_name_overlay.json"):
        if overlay.exists():
            with open(overlay, "r", encoding="utf-8") as f:
                db.update(json.load(f))
    return db


def resolve(hash_db, hash_int):
    """Resolve an integer hash to a path name, or None."""
    if hash_int is None:
        return None
    return hash_db.get("%016x" % (hash_int & 0xFFFFFFFFFFFFFFFF))



# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def type_name(type_hash):
    if type_hash is None:
        return "(res0)"
    return TYPE_HASH_TO_NAME.get(type_hash, "unknown(0x%016X)" % type_hash)


def human(n):
    if n is None:
        return "-"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TiB" % n


def classify_bundle_file(name: str):
    """A bundle file is 16 hex chars with no extension."""
    return len(name) == 16 and all(c in "0123456789abcdefABCDEF" for c in name)


def find_install_root(explicit=None):
    if explicit:
        root = Path(explicit)
        return root.parent if root.name == "contents" else root
    for cand in INSTALL_CANDIDATES:
        if os.path.isdir(cand):
            return Path(cand)
    raise SystemExit("Could not locate Gauntlet install; pass --contents/--root.")


def display_path(path) -> str:
    """Machine-neutral display of an install path (home dir shown as `~`)."""
    p = str(path)
    home = str(Path.home())
    return p.replace(home, "~", 1) if home and home in p else p


def write_file_tree(install_root: Path, out_dir: Path):
    rows = []
    for path in sorted(install_root.rglob("*")):
        if path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rows.append((str(path.relative_to(install_root)), size))

    txt = out_dir / "00_file_tree.txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write("GAUNTLET INSTALL FILE TREE\n")
        f.write("Root: %s\n" % display_path(install_root))
        f.write("Files: %d\n" % len(rows))
        f.write("=" * 100 + "\n\n")
        for rel, size in rows:
            f.write("%12d  %s\n" % (size, rel))
    return rows


def load_bundle_blob(path: Path, full: bool):
    """
    Return (raw_len, sig, unzipped_size, data) reading just enough for the TOC
    when `full` is False.
    """
    raw = path.read_bytes()
    limit = None if full else 0x00400000  # 4 MiB of decompressed body is plenty
    sig, unzipped, data = decompress_bundle(raw, limit=limit)
    return len(raw), sig, unzipped, data



def collect_bundle_inventory(install_root: Path, hash_db, full=False,
                             shipped_only=False, exclude_bundles=()):
    """Walk contents/ and return (bundle_reports, db_version, db_entries)."""
    contents = install_root / "contents"
    db_path = contents / "bundle_database.data"

    db_entries = []
    db_version = None
    if db_path.exists():
        db_version, db_entries = parse_bundle_database(db_path)

    db_order = {}
    for i, e in enumerate(db_entries):
        db_order.setdefault(e["name"], i)
    db_names = set(db_order)

    bundles = []
    for f in sorted(contents.iterdir()):
        if not f.is_file() or not classify_bundle_file(f.name):
            continue
        stream = contents / (f.name + ".stream")
        info = {
            "name": f.name,
            "size": f.stat().st_size,
            "stream_size": stream.stat().st_size if stream.exists() else 0,
            "package_path": resolve(hash_db, int(f.name, 16)),
            "in_db": f.name in db_names,
            "db_index": db_order.get(f.name),
            "resources": None,
            "count": None,
            "unzipped": None,
            "signature": None,
            "scan_complete": None,
            "error": None,
        }
        try:
            raw_len, sig, unzipped, data = load_bundle_blob(f, full)
            count, toc = parse_toc(data)
            info["signature"] = "0x%08X" % sig
            info["count"] = count
            info["unzipped"] = unzipped
            entries, end_pos, complete = parse_resources(data, toc)
            info["scan_complete"] = complete
            by_index = {e["index"]: e for e in entries}
            merged = []
            for i, (t, n) in enumerate(toc):
                e = by_index.get(i, {})
                merged.append({
                    "index": i, "type_hash": t, "name_hash": n,
                    "header_offset": e.get("header_offset"),
                    "body_size": e.get("body_size"),
                    "hdr_size": e.get("hdr_size"),
                    "stream_size": e.get("stream_size"),
                    "flags": e.get("flags"),
                })
            info["resources"] = merged
        except Exception as exc:  # noqa: BLE001 - report, never crash the sweep
            info["error"] = "%s: %s" % (type(exc).__name__, exc)
        bundles.append(info)
    # A mod bundle lives in contents/ but is not registered in the shipped
    # bundle_database.data.  The catalogue is the *shipped* game, so keep it out
    # unless the caller explicitly wants everything.
    if shipped_only:
        bundles = [b for b in bundles if b["in_db"]]
    if exclude_bundles:
        drop = set(exclude_bundles)
        bundles = [b for b in bundles if b["name"] not in drop]
    return bundles, db_version, db_entries



def write_bundle_files(bundles, out_dir: Path):
    txt = out_dir / "01_bundle_files.txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write("BUNDLE FILES IN contents/\n")
        f.write("=" * 100 + "\n\n")
        f.write("%-18s %14s %14s %5s %8s %5s %s\n" % (
            "bundle", "size", ".stream", "inDB", "res#", "layOK", "package_path"))
        f.write("-" * 110 + "\n")
        total = total_stream = 0
        for b in sorted(bundles, key=lambda x: x["name"]):
            total += b["size"]
            total_stream += b["stream_size"]
            lay = ("yes" if b.get("scan_complete") else
                   "no" if b.get("scan_complete") is False else "-")
            f.write("%-18s %14d %14d %5s %8s %5s %s\n" % (
                b["name"], b["size"], b["stream_size"],
                "yes" if b["in_db"] else "no",
                b["count"] if b["count"] is not None else "-",
                lay,
                b["package_path"] or ""))
        f.write("-" * 100 + "\n")
        f.write("Total: %d bundles, %s packed + %s stream = %s\n" % (
            len(bundles), human(total), human(total_stream),
            human(total + total_stream)))


def write_database_report(bundles, db_version, db_entries, out_dir: Path, hash_db=None):
    txt = out_dir / "02_bundle_database.txt"
    present = {b["name"]: b for b in bundles}
    with open(txt, "w", encoding="utf-8") as f:
        f.write("BUNDLE_DATABASE.DATA\n")
        f.write("=" * 100 + "\n")
        f.write("Version: %s   Entries: %d\n" % (db_version, len(db_entries)))
        f.write("Priority: entries LATER in the file take precedence.\n")
        f.write("-" * 100 + "\n\n")

        # --- unique bundles, in priority (first-appearance) order ---------
        order = []
        first_idx = {}
        has_stream = {}
        for i, e in enumerate(db_entries):
            if e["name"] not in first_idx:
                first_idx[e["name"]] = i
                order.append(e["name"])
            if e["stream_name"]:
                has_stream[e["name"]] = True
        f.write("UNIQUE BUNDLES IN PRIORITY ORDER (%d)\n" % len(order))
        f.write("-" * 100 + "\n")
        f.write("%5s %-18s %-9s %-9s %s\n" % (
            "idx", "bundle", "stream", "on-disk", "package_path"))
        f.write("-" * 100 + "\n")
        f.write("# a bundle id IS murmur64A(package_path, seed=0).  A path marked '*'\n"
                "# is not in bundle_database.data (that bundle is absent from this\n"
                "# install) and was recovered by hashing the id against the name\n"
                "# database - e.g. the two debug bundles:\n"
                "#   361ea22c921e9f87 -> resource_packages/debug\n"
                "#   8ad87c351f91fb47 -> modules/debug/resources\n")
        for name in order:
            b = present.get(name)
            path = (b or {}).get("package_path") or ""
            if not path and hash_db is not None:
                recovered = resolve(hash_db, int(name, 16))
                if recovered:
                    path = recovered + " *"
            f.write("%5d %-18s %-9s %-9s %s\n" % (
                first_idx[name], name,
                "yes" if has_stream.get(name) else "no",
                "yes" if b else "MISSING",
                path))
        f.write("\n")

        # --- full per-entry dump ------------------------------------------
        f.write("ALL DATABASE ENTRIES (%d)\n" % len(db_entries))
        f.write("-" * 100 + "\n")
        f.write("%6s %-18s %-12s %-9s\n" % (
            "idx", "bundle", "stream", "on-disk"))
        f.write("-" * 100 + "\n")
        for i, e in enumerate(db_entries):
            b = present.get(e["name"])
            f.write("%6d %-18s %-12s %-9s\n" % (
                i, e["name"],
                "yes" if e["stream_name"] else "no",
                "yes" if b else "MISSING"))
        f.write("\n")

        f.write("ON-DISK BUNDLE NAMES (murmur64A of package path)\n")
        f.write("-" * 100 + "\n")
        for b in sorted(bundles, key=lambda x: x["name"]):
            f.write("%-18s  %s\n" % (b["name"], b["package_path"] or "<unknown>"))



def write_resources(bundles, hash_db, out_dir: Path):
    txt = out_dir / "03_bundle_resources.txt"
    csv_path = out_dir / "04_bundle_resources.csv"
    unresolved = 0
    with open(txt, "w", encoding="utf-8") as f, \
            open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow(["bundle", "package_path", "index", "type",
                         "type_hash", "name_hash", "name", "body_size",
                         "declared_size", "stream_size", "flags"])

        grand = 0
        type_totals = {}
        for b in sorted(bundles, key=lambda x: x["name"]):
            f.write("=" * 100 + "\n")
            f.write("BUNDLE %s   (%s)\n" % (
                b["name"], b["package_path"] or "unresolved package path"))
            f.write("  packed=%s  unzipped=%s  sig=%s  resources=%s\n" % (
                human(b["size"]), human(b["unzipped"]), b["signature"],
                b["count"]))
            f.write("  header scan complete: %s\n" % (
                {True: "yes", False: "NO (partial)", None: "n/a"}
                [b.get("scan_complete")]))
            if b["error"]:
                f.write("  !! ERROR: %s\n" % b["error"])
            f.write("-" * 110 + "\n")
            f.write("%5s %-24s %-18s %-18s %10s %10s %s\n" % (
                "#", "type", "type_hash", "name_hash", "body", "declared", "name"))
            f.write("-" * 110 + "\n")
            for r in (b["resources"] or []):
                tn = type_name(r.get("type_hash"))
                th = ("%016x" % r["type_hash"]) if r.get("type_hash") is not None else "-"
                nh = ("%016x" % r["name_hash"]) if r.get("name_hash") is not None else "-"
                nm = resolve(hash_db, r.get("name_hash"))
                if r.get("name_hash") is not None and nm is None:
                    unresolved += 1
                type_totals[tn] = type_totals.get(tn, 0) + 1
                grand += 1
                body = r.get("body_size")
                decl = r.get("hdr_size")
                f.write("%5d %-24s %-18s %-18s %10s %10s %s\n" % (
                    r["index"], tn, th, nh,
                    body if body is not None else "-",
                    decl if decl is not None else "-",
                    nm or "<unresolved>"))
                writer.writerow([
                    b["name"], b["package_path"] or "", r["index"], tn,
                    th, nh, nm or "", r.get("body_size"), r.get("hdr_size"),
                    r.get("stream_size"), r.get("flags"),
                ])
            f.write("\n")
    return grand, type_totals, unresolved


def write_summary(install_root, file_rows, bundles, grand, type_totals,
                  unresolved, out_dir: Path):
    txt = out_dir / "05_summary.txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write("GAUNTLET CATALOGUE SUMMARY\n")
        f.write("=" * 100 + "\n")
        f.write("Install root : %s\n" % display_path(install_root))
        f.write("Total files  : %d\n" % len(file_rows))
        f.write("Bundle files : %d\n" % len(bundles))
        partial = sum(1 for b in bundles if b.get("scan_complete") is False)
        f.write("Scan check   : %d bundle(s) with incomplete header scan\n" % partial)
        f.write("Resources    : %d\n" % grand)
        f.write("Unresolved   : %d name hashes (not in hash_database.json)\n"
                % unresolved)
        f.write("\nRESOURCES BY TYPE\n" + "-" * 100 + "\n")
        for tn, n in sorted(type_totals.items(), key=lambda x: -x[1]):
            f.write("%8d  %s\n" % (n, tn))



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contents", help="Path to the game 'contents' folder")
    ap.add_argument("--root", help="Path to the Gauntlet install root")
    ap.add_argument("--out", default=str(TOOL_DIR.parent / "Data" / "bundle_manifest"),
                    help="Output directory (default: bundle_manifest/)")
    ap.add_argument("--only", choices=["files", "bundles", "database",
                                       "resources", "all"], default="all")
    ap.add_argument("--no-decompress", action="store_true",
                    help="Read only the TOC (fast, low memory)")
    ap.add_argument("--shipped-only", action="store_true",
                    help="Ignore bundles absent from bundle_database.data "
                         "(installed mods); the catalogue then describes the "
                         "shipped game only")
    ap.add_argument("--exclude-bundle", action="append", default=[],
                    metavar="HASH",
                    help="Skip this bundle id (repeatable)")
    args = ap.parse_args()

    install_root = find_install_root(args.root or args.contents)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    hash_db = load_hash_db()
    print("Install root : %s" % display_path(install_root))
    print("Output dir   : %s" % out_dir)
    print("Hash DB      : %d entries" % len(hash_db))

    file_rows = []
    if args.only in ("files", "all"):
        file_rows = write_file_tree(install_root, out_dir)
        print("File tree    : %d files -> 00_file_tree.txt" % len(file_rows))

    db_version = None
    db_entries = []
    bundles = []
    if args.only in ("bundles", "database", "resources", "all"):
        bundles, db_version, db_entries = collect_bundle_inventory(
            install_root, hash_db, full=not args.no_decompress,
            shipped_only=args.shipped_only,
            exclude_bundles=args.exclude_bundle)
        print("Bundles      : %d parsed" % len(bundles))

    if args.only in ("bundles", "all"):
        write_bundle_files(bundles, out_dir)
        print("   wrote 01_bundle_files.txt")

    if args.only in ("database", "all"):
        write_database_report(bundles, db_version, db_entries, out_dir, hash_db)
        print("   wrote 02_bundle_database.txt")

    grand = unresolved = 0
    type_totals = {}
    if args.only in ("resources", "all"):
        grand, type_totals, unresolved = write_resources(bundles, hash_db, out_dir)
        print("Resources    : %d (%d unresolved)" % (grand, unresolved))

    if args.only == "all":
        write_summary(install_root, file_rows, bundles, grand, type_totals,
                      unresolved, out_dir)
        print("   wrote 05_summary.txt")

    print("\nDone.")


if __name__ == "__main__":
    main()

