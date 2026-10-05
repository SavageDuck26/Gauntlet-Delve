#!/usr/bin/env python3
"""
rebuild_bundles.py — Rebuild all mod bundles with CORRECTED binary formats.

This script rebuilds CraneTexTest and CustomTexTest using the FIXED 28-byte
package format + corrected bundle layout (N+1 TOC, 20-byte res-0 header).
It then deploys to the game directory and cleans up old broken bundles.

Usage:  cd Scripting/GauntletGameDigging && python3 rebuild_bundles.py
"""

import os, sys, shutil, json, struct, zlib
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).resolve().parent
CRANE_MOD   = SCRIPT_DIR / "crane_mod" / "mod.json"
TEST_MOD    = SCRIPT_DIR / "test_mod" / "mod.json"
BUNDLES_OUT = Path(__file__).resolve().parent.parent.parent / "GauntletModLoader" / "mods" / "bundles"
GAME_DIR    = Path(os.path.expanduser("~/.local/share/Steam/steamapps/common/Gauntlet"))
CONTENTS    = GAME_DIR / "contents"

# Allow override via env var
if "GAUNTLET_CONTENTS" in os.environ:
    CONTENTS = Path(os.environ["GAUNTLET_CONTENTS"])
if "BUNDLES_OUT" in os.environ:
    BUNDLES_OUT = Path(os.environ["BUNDLES_OUT"])

# ---------------------------------------------------------------------------
# MurmurHash64A  (Bitsquid/Stingray engine)
# ---------------------------------------------------------------------------
def murmur64(key: str, seed: int = 0) -> int:
    m  = 0xC6A4A7935BD1E995
    r  = 47
    kb = key.lower().encode("utf-8")
    ln = len(kb)
    h  = (seed ^ ((ln * m) & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
    nblocks = ln // 8
    for i in range(nblocks):
        k = struct.unpack("<Q", kb[i*8:(i+1)*8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    tail = kb[nblocks * 8:]
    if len(tail) >= 7: h ^= tail[6] << 48
    if len(tail) >= 6: h ^= tail[5] << 40
    if len(tail) >= 5: h ^= tail[4] << 32
    if len(tail) >= 4: h ^= tail[3] << 24
    if len(tail) >= 3: h ^= tail[2] << 16
    if len(tail) >= 2: h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    return h

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BUNDLE_SIG       = 0xF0000004
ZLIB_CHUNK       = 0x10000
TYPE_TEXTURE     = 0xCD4238C6A0C69E32
TYPE_UNIT        = 0xE0A48D0BE9A7453F
TYPE_MATERIAL    = 0xEAC0B497876ADEDF
TYPE_LUA         = 0xA14E8DFA2CD117E2
TYPE_PACKAGE     = 0xAD9C6D9ED1E5E77A
SHADER_DIFFUSE   = 0xBA25DE3579DC6624
THINHASH_DIFFUSE = 0x3AA8B87E

TYPE_NAMES = {
    TYPE_TEXTURE: "texture", TYPE_UNIT: "unit",
    TYPE_MATERIAL: "material", TYPE_LUA: "lua",
    TYPE_PACKAGE: "package",
}
TYPE_FROM_NAME = {v: k for k, v in TYPE_NAMES.items()}

# ---------------------------------------------------------------------------
# Resource representation
# ---------------------------------------------------------------------------
class Resource:
    __slots__ = ("type_hash", "name", "name_hash", "data")
    def __init__(self, th, name, nh, data):
        self.type_hash = th
        self.name = name
        self.name_hash = nh
        self.data = data

# ---------------------------------------------------------------------------
# 52-byte material builder (diffuse_map only)
# ---------------------------------------------------------------------------
def build_material_diffuse(texture_hash: int) -> bytes:
    return struct.pack("<II", 0x0A, 1) + \
           struct.pack("<Q", SHADER_DIFFUSE) + \
           struct.pack("<Q", 0) + \
           struct.pack("<I", 1) + \
           struct.pack("<I", THINHASH_DIFFUSE) + \
           struct.pack("<Q", texture_hash) + \
           struct.pack("<III", 0, 0, 0)

# ---------------------------------------------------------------------------
# Package resource builder — CORRECTED 28-byte fixed entries
# ---------------------------------------------------------------------------
def build_package_data(entries: List[Tuple[int, int]]) -> bytes:
    """
    entry = (type_hash, name_hash)
    Format per entry (28 bytes):
      uint64 type_hash  [0:8]
      uint64 name_hash  [8:16]
      uint32 c1=2       [16:20]
      uint32 c2=0       [20:24]
      uint32 name_hi32  [24:28]
    Trailer: 0x01
    """
    buf = struct.pack("<I", len(entries))
    for th, nh in entries:
        hi = (nh >> 32) & 0xFFFFFFFF
        buf += struct.pack("<QQIII", th, nh, 2, 0, hi)
    buf += b"\x01"
    return buf

# ---------------------------------------------------------------------------
# Unpacked bundle builder — CORRECTED layout
# ---------------------------------------------------------------------------
def build_bundle(resources: List[Resource]) -> bytes:
    """
    [0x000] N (uint32)
    [0x004] 84-byte preamble (zeros)
    [0x058] 172-byte padding (zeros)
    [0x104] TOC: (N+1)*16 bytes (entry[N]=sentinel)
    [toc_end] Resource-0: 20-byte header + data
    [after] Resources 1..N-1: 36-byte header + data each
    """
    n = len(resources)
    pkg = [r for r in resources if r.type_hash == TYPE_PACKAGE]
    other = [r for r in resources if r.type_hash != TYPE_PACKAGE]
    ordered = pkg + sorted(other, key=lambda r: r.name_hash)

    parts = [struct.pack("<I", n)]
    parts.append(b"\x00" * 84)   # preamble
    parts.append(b"\x00" * 172)  # padding
    for r in ordered:
        parts.append(struct.pack("<QQ", r.type_hash, r.name_hash))
    parts.append(struct.pack("<QQ", ordered[0].type_hash, ordered[0].name_hash))  # sentinel
    # Resource-0: 20-byte header
    r0 = ordered[0]
    parts.append(struct.pack("<IQII", 1, 0, len(r0.data), 0))
    parts.append(r0.data)
    # Resources 1..N-1: 36-byte header
    for r in ordered[1:]:
        sz = len(r.data)
        parts.append(struct.pack("<QQIQII", r.type_hash, r.name_hash, 1, 0, sz, 0))
        parts.append(r.data)
    raw = b"".join(parts)
    pad = (4 - len(raw) % 4) % 4
    if pad:
        raw += b"\x00" * pad
    return raw

# ---------------------------------------------------------------------------
# zlib chunk compressor
# ---------------------------------------------------------------------------
def compress_bundle(unpacked: bytes) -> bytes:
    parts = [struct.pack("<III", BUNDLE_SIG, len(unpacked), 0)]
    offset = 0
    while offset < len(unpacked):
        chunk = unpacked[offset:offset + ZLIB_CHUNK]
        cdata = zlib.compress(chunk, 6)
        parts.append(struct.pack("<I", len(cdata)))
        parts.append(cdata)
        offset += ZLIB_CHUNK
    return b"".join(parts)

# ---------------------------------------------------------------------------
# Clone a native material and remap texture hashes
# ---------------------------------------------------------------------------
def clone_material(native_path: str, texture_remap: Dict[str, str]) -> bytes:
    """Read a native .material binary and replace texture hashes in-place."""
    with open(native_path, "rb") as f:
        data = bytearray(f.read())
    for old_tex_path, new_tex_path in texture_remap.items():
        old_hash = murmur64(old_tex_path)
        new_hash = murmur64(new_tex_path)
        old_bytes = struct.pack("<Q", old_hash)
        new_bytes = struct.pack("<Q", new_hash)
        idx = 0
        while True:
            idx = data.find(old_bytes, idx)
            if idx == -1:
                break
            data[idx:idx+8] = new_bytes
            idx += 8
    return bytes(data)

# ---------------------------------------------------------------------------
# Build one mod from mod.json
# ---------------------------------------------------------------------------
def build_mod(mod_json_path: Path, out_root: Path):
    mod_dir = mod_json_path.parent
    with open(mod_json_path) as f:
        cfg = json.load(f)

    mod_name     = cfg["name"]
    package_path = cfg["package_path"]
    boot_overlay = cfg.get("boot_overlay")
    specs        = cfg.get("resources", [])

    print(f"\n{'='*60}")
    print(f"  MOD: {mod_name}")
    print(f"  PKG: {package_path}")

    resources: List[Resource] = []
    pkg_entries: List[Tuple[int, int]] = []
    meta: Dict[str, Any] = {}

    for spec in specs:
        rtype = spec["type"]
        path  = spec["path"]
        nhash = murmur64(path)
        thash = TYPE_FROM_NAME.get(rtype)
        if thash is None:
            print(f"    SKIP unknown type: {rtype}")
            continue

        data: Optional[bytes] = None

        if rtype == "texture":
            src = mod_dir / spec["source"]
            data = src.read_bytes()

        elif rtype == "unit":
            src = mod_dir / spec["source"]
            data = src.read_bytes()

        elif rtype == "lua":
            src = mod_dir / spec["source"]
            data = src.read_bytes()

        elif rtype == "material":
            if "texture" in spec:
                tex_hash = murmur64(spec["texture"])
                data = build_material_diffuse(tex_hash)
            elif "clone_from" in spec:
                clone_path = spec["clone_from"]
                if not os.path.isabs(clone_path):
                    candidate = mod_dir / clone_path
                    if not candidate.exists():
                        candidate = SCRIPT_DIR / clone_path
                    if candidate.exists():
                        clone_path = str(candidate)
                data = clone_material(clone_path, spec.get("remap_textures", {}))
            elif "source" in spec:
                src = mod_dir / spec["source"]
                data = src.read_bytes()

        if data is None:
            print(f"    SKIP {rtype} {path}: no source")
            continue

        resources.append(Resource(thash, path, nhash, data))
        pkg_entries.append((thash, nhash))
        meta[path] = {"type": rtype, "type_hash": f"0x{thash:016x}",
                       "name_hash": f"0x{nhash:016x}", "size": len(data)}
        print(f"    {rtype}: {path}  ({len(data):,} bytes)")

    # Build package resource
    pkg_data = build_package_data(pkg_entries)
    pkg_hash = murmur64(package_path)
    resources.insert(0, Resource(TYPE_PACKAGE, package_path, pkg_hash, pkg_data))
    meta[package_path] = {"type": "package", "type_hash": f"0x{TYPE_PACKAGE:016x}",
                           "name_hash": f"0x{pkg_hash:016x}", "size": len(pkg_data)}

    # Build bundle
    bundle_hash_hex = f"{pkg_hash:016x}"
    unpacked = build_bundle(resources)
    compressed = compress_bundle(unpacked)

    print(f"    Bundle hash: {bundle_hash_hex}")
    print(f"    Package blob: {len(pkg_data)} bytes ({len(pkg_entries)} entries × 28 + 5)")
    print(f"    Unpacked: {len(unpacked):,} B  →  Compressed: {len(compressed):,} B")

    # Write output
    out_dir = out_root / mod_name
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / bundle_hash_hex).write_bytes(compressed)
    (out_dir / f"{bundle_hash_hex}.stream").write_bytes(b"")

    # bundle.ini
    ini_lines = ["[Bundle]", f"PackagePath={package_path}",
                 f"ResourceCount={len(resources)}", "HasStream=false"]
    if boot_overlay:
        bo = boot_overlay
        ini_lines += ["", "[BootOverlay]",
                      f"Phase={bo.get('phase','post_splash')}",
                      f"Priority={bo.get('priority',100)}",
                      f"Required={'true' if bo.get('required',False) else 'false'}"]
    (out_dir / "bundle.ini").write_text("\n".join(ini_lines) + "\n")

    # manifest.json
    manifest = {"mod_name": mod_name, "package_path": package_path,
                "bundle_hash": bundle_hash_hex, "resource_count": len(resources),
                "resources": meta,
                "lua_load_code": f'Game:load_package("{package_path}", true)'}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    return out_dir, bundle_hash_hex

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Gauntlet Bundle Rebuilder — Corrected Format")
    print("=" * 60)

    mods_to_build = []
    if CRANE_MOD.exists():
        mods_to_build.append(CRANE_MOD)
    if TEST_MOD.exists():
        mods_to_build.append(TEST_MOD)

    if not mods_to_build:
        print("ERROR: No mod.json files found!")
        sys.exit(1)

    # Step 1: Build all mods
    built: List[Tuple[Path, str]] = []
    for mod_json in mods_to_build:
        try:
            out_dir, bh = build_mod(mod_json, BUNDLES_OUT)
            built.append((out_dir, bh))
        except Exception as e:
            print(f"\n  ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Step 2: Clean old bundle dirs from mods/bundles/
    print(f"\n{'='*60}")
    print("Cleaning old bundles from mods/bundles/...")
    keep = {b[0].name for b in built}
    if BUNDLES_OUT.exists():
        for item in sorted(BUNDLES_OUT.iterdir()):
            if item.is_dir() and item.name not in keep:
                print(f"  REMOVE stale dir: {item.name}")
                shutil.rmtree(item)

    # Step 3: Deploy to game contents/
    known_bad_hashes = {
        "5bfdd50f98f5d0d9",   # old CraneTexTest
        "b4fe67fdbaa47d6e",   # old CustomTexTest
    }
    if CONTENTS.exists():
        print(f"\n{'='*60}")
        print(f"Deploying to: {CONTENTS}")
        # Remove old broken bundle files
        for old_hash in known_bad_hashes:
            for ext in ("", ".stream"):
                fpath = CONTENTS / f"{old_hash}{ext}"
                if fpath.exists():
                    print(f"  REMOVE old: {fpath.name}")
                    fpath.unlink()
        # Copy new bundle files
        for out_dir, bh in built:
            for ext in ("", ".stream"):
                src = out_dir / f"{bh}{ext}"
                dst = CONTENTS / f"{bh}{ext}"
                if src.exists():
                    shutil.copy2(src, dst)
                    print(f"  COPY: {src.name} → {dst}")
    else:
        print(f"\n  WARNING: Game contents not found at {CONTENTS}")
        print("  Copy these bundle files manually to Gauntlet/contents/:")
        for out_dir, _ in built:
            for f in sorted(out_dir.iterdir()):
                if f.is_file():
                    print(f"    {f}")

    print(f"\n{'='*60}")
    print("DONE. Bundles rebuilt with corrected 28-byte package format.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()