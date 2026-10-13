#!/usr/bin/env python3
"""
Gauntlet Bundle Maker & Installer (All-in-One)
===============================================
Creates a Bitsquid bundle from DDS textures, registers it in bundle_database.data,
copies it to the game's contents folder, and generates a Lua loader mod.

USAGE:
    # Replace existing game textures (folder structure must match game paths):
    python make_and_install_bundle.py my_textures my_mod --replace

    # Add new custom textures:
    python make_and_install_bundle.py my_textures my_mod

    # With materials (for GUI bg_img usage):
    python make_and_install_bundle.py my_textures my_mod --with-materials

    # Dry run (preview without writing anything):
    python make_and_install_bundle.py my_textures my_mod --dry-run

WHAT THIS DOES:
    1. Scans your texture folder for .dds files
    2. Builds a compressed Bitsquid bundle (0xF0000004 format)
    3. Backs up and updates bundle_database.data
    4. Copies the bundle to Gauntlet/contents/
    5. Generates a Lua loader mod in Gauntlet/custom/functions/Local Mods/

TEXTURE FOLDER SETUP:
    For --replace mode, mirror the game's folder structure:
        my_textures/
        └── characters/
            └── avatar_warrior/
                ├── warrior_diff.dds
                └── warrior_norm.dds

    For new content mode, just put DDS files in a folder:
        my_textures/
        ├── cool_sword.dds
        └── shield_diff.dds
"""

import struct
import zlib
import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# ============================================================================
# Paths
# ============================================================================

GAME_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet")
CONTENTS_DIR = GAME_DIR / "contents"
BUNDLE_DB = CONTENTS_DIR / "bundle_database.data"
MODS_DIR = GAME_DIR / "custom" / "functions" / "Local Mods"

# ============================================================================
# Constants
# ============================================================================

BUNDLE_SIG = 0xF0000004
ZLIB_CHUNK = 0x10000  # 64KB

TYPE_TEXTURE  = 0xCD4238C6A0C69E32
TYPE_MATERIAL = 0xEAC0B497876ADEDF
TYPE_PACKAGE  = 0xAD9C6D9ED1E5E77A

# 52-byte material format constants
SHADER_DIFFUSE_SIMPLE = 0xBA25DE3579DC6624
THINHASH_DIFFUSE = 0x3AA8B87E

# ============================================================================
# MurmurHash64A (Bitsquid variant, seed 0)
# ============================================================================

def murmur_hash64(key: str, seed: int = 0) -> int:
    m = 0xC6A4A7935BD1E995
    r = 47
    key_bytes = key.lower().encode('utf-8')
    length = len(key_bytes)
    h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)

    nblocks = length // 8
    for i in range(nblocks):
        k = struct.unpack('<Q', key_bytes[i*8:(i+1)*8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    tail = key_bytes[nblocks * 8:]
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

# ============================================================================
# Data classes
# ============================================================================

@dataclass
class Resource:
    type_hash: int
    name: str
    name_hash: int
    data: bytes

@dataclass
class TextureInfo:
    resource: Resource
    width: int
    height: int
    fmt: str
    filepath: str

# ============================================================================
# DDS validation
# ============================================================================

def validate_dds(data: bytes) -> Tuple[bool, int, int, str]:
    if len(data) < 128 or data[:4] != b'DDS ':
        return False, 0, 0, ""
    height = struct.unpack_from('<I', data, 12)[0]
    width  = struct.unpack_from('<I', data, 16)[0]
    fourcc = data[0x54:0x58].decode('ascii', errors='replace')
    return True, width, height, fourcc

# ============================================================================
# Material builder (52-byte minimal format)
# ============================================================================

def build_material_data(texture_hash: int) -> bytes:
    data  = struct.pack('<I', 0x0A)                       # version 10
    data += struct.pack('<I', 1)                           # section count
    data += struct.pack('<Q', SHADER_DIFFUSE_SIMPLE)       # shader hash
    data += struct.pack('<Q', 0)                           # padding
    data += struct.pack('<I', 1)                           # slot index (must be 1)
    data += struct.pack('<I', THINHASH_DIFFUSE)            # diffuse_map thin hash
    data += struct.pack('<Q', texture_hash)                # texture hash
    data += b'\x00' * 12                                   # trailing zeros
    return data  # 52 bytes total

# ============================================================================
# Package resource builder
# ============================================================================

def build_package_data(texture_names: List[str], material_names: List[str] = None) -> bytes:
    entries = []
    for name in texture_names:
        entries.append(struct.pack('<QQI', TYPE_TEXTURE, murmur_hash64(name), 0))
    for name in (material_names or []):
        entries.append(struct.pack('<QQI', TYPE_MATERIAL, murmur_hash64(name), 0))
    data = struct.pack('<I', len(entries)) + b''.join(entries) + b'\x00'
    return data

# ============================================================================
# Bundle builder (0xF0000004 format)
# ============================================================================

def build_bundle(resources: List[Resource]) -> bytes:
    count = len(resources)
    sorted_res = sorted(resources, key=lambda r: r.name_hash)

    parts = []
    # 1. Resource count
    parts.append(struct.pack('<I', count))
    # 2. Name hash table
    for r in sorted_res:
        parts.append(struct.pack('<Q', r.name_hash))
    # 3. Pad to 0x104 if small enough
    current = 4 + count * 8
    if current < 0x104:
        parts.append(b'\x00' * (0x104 - current))
    # 4. Entry table (type_hash, name_hash) per resource
    for r in sorted_res:
        parts.append(struct.pack('<QQ', r.type_hash, r.name_hash))
    # 5. Resource data with 36-byte headers
    for r in sorted_res:
        parts.append(struct.pack('<QQIQII',
            r.type_hash, r.name_hash,
            1,              # flags
            0,              # stream_size
            len(r.data),    # main_size
            0))             # unknown
        parts.append(r.data)

    result = b''.join(parts)
    pad = (4 - len(result) % 4) % 4
    return result + b'\x00' * pad


def compress_bundle(raw: bytes) -> bytes:
    parts = [struct.pack('<III', BUNDLE_SIG, len(raw), 0)]
    offset = 0
    while offset < len(raw):
        chunk = raw[offset:offset + ZLIB_CHUNK]
        compressed = zlib.compress(chunk, 6)
        parts.append(struct.pack('<I', len(compressed)))
        parts.append(compressed)
        offset += ZLIB_CHUNK
    return b''.join(parts)

# ============================================================================
# bundle_database.data handling
# ============================================================================

def parse_bundle_db(data: bytes):
    version, count = struct.unpack('<II', data[:8])
    entries = []
    offset = 8
    for _ in range(count):
        flags = struct.unpack('<I', data[offset:offset+4])[0]; offset += 4
        blen = struct.unpack('<I', data[offset:offset+4])[0]; offset += 4
        bundle = data[offset:offset+blen].decode('utf-8'); offset += blen
        slen = struct.unpack('<I', data[offset:offset+4])[0]; offset += 4
        stream = data[offset:offset+slen].decode('utf-8'); offset += slen
        offset += 1  # null terminator
        entries.append({'flags': flags, 'bundle': bundle, 'stream': stream})
    return version, entries


def build_bundle_db(version: int, entries: list) -> bytes:
    parts = [struct.pack('<II', version, len(entries))]
    for e in entries:
        b = e['bundle'].encode('utf-8')
        s = e['stream'].encode('utf-8')
        parts.append(struct.pack('<I', e['flags']))
        parts.append(struct.pack('<I', len(b)))
        parts.append(b)
        parts.append(struct.pack('<I', len(s)))
        parts.append(s)
        parts.append(b'\x00')
    return b''.join(parts)

# ============================================================================
# Lua mod generator
# ============================================================================

LUA_TEMPLATE = '''\
-- =================================================================================================
-- Auto-generated bundle loader for: {mod_name}
-- Package path: {package_path}
-- Bundle file:  {bundle_name}
-- =================================================================================================

local MOD_NAME = "{mod_name}"

Mods.hook:set(MOD_NAME, "require", function(orig, path, ...)
    local result = orig(path, ...)

    -- Load our custom bundle once the lobby manager is available
    if path == "lua/managers/lobby_manager" then
        local loaded = false

        Mods.hook:set(MOD_NAME, "LobbyManager.update", function(orig_update, self, dt)
            orig_update(self, dt)

            if not loaded then
                loaded = true

                local success, err = pcall(function()
                    Game:load_package("{package_path}", true)
                end)

                if success then
                    print("[" .. MOD_NAME .. "] Bundle loaded: {package_path}")
                else
                    print("[" .. MOD_NAME .. "] ERROR loading bundle: " .. tostring(err))
                end
            end
        end)
    end

    return result
end)
'''

# ============================================================================
# Main pipeline
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Build, register, and install a Gauntlet texture bundle in one step.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Replace warrior textures (folder mirrors game paths):
  python make_and_install_bundle.py warrior_reskin WarriorSkin --replace

  # Add new custom textures:
  python make_and_install_bundle.py my_textures MyPack

  # Preview only:
  python make_and_install_bundle.py my_textures MyPack --dry-run
        """)
    parser.add_argument('texture_folder', help='Folder containing .dds textures')
    parser.add_argument('package_name', help='Name for the package (e.g. MyMod)')
    parser.add_argument('--replace', '-r', action='store_true',
                        help='Replacement mode: folder structure must mirror game paths')
    parser.add_argument('--prefix', default='custom',
                        help='Path prefix for new-content mode (default: custom)')
    parser.add_argument('--with-materials', '-m', action='store_true',
                        help='Create materials for each texture (for GUI usage)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without writing anything')
    parser.add_argument('--no-lua', action='store_true',
                        help='Skip Lua mod generation')
    args = parser.parse_args()

    folder = Path(args.texture_folder)
    if not folder.is_dir():
        print(f"ERROR: Texture folder not found: {folder}")
        sys.exit(1)

    # ── Determine package path and prefix ──
    if args.replace:
        pkg_path = f"resource_packages/replacements/{args.package_name}"
        tex_prefix = ""
    else:
        pkg_path = f"resource_packages/{args.prefix}/{args.package_name}"
        tex_prefix = f"{args.prefix}/{args.package_name}/"

    pkg_hash = murmur_hash64(pkg_path)
    bundle_name = f"{pkg_hash:016x}"

    mode = "REPLACE" if args.replace else "NEW CONTENT"
    print("=" * 70)
    print(f"  Gauntlet Bundle Maker  [{mode}]")
    print("=" * 70)
    print(f"  Package path : {pkg_path}")
    print(f"  Bundle name  : {bundle_name}")
    print(f"  Bundle hash  : 0x{pkg_hash:016X}")
    print()

    # ── Step 1: Collect DDS textures ──
    print("[1/5] Scanning for textures...")
    dds_files = sorted(set(folder.glob('**/*.dds')) | set(folder.glob('**/*.DDS')))
    if not dds_files:
        print("  ERROR: No .dds files found in", folder)
        sys.exit(1)

    textures: List[TextureInfo] = []
    for dds_path in dds_files:
        with open(dds_path, 'rb') as f:
            data = f.read()
        ok, w, h, fmt = validate_dds(data)
        if not ok:
            print(f"  SKIP (invalid DDS): {dds_path.name}")
            continue

        rel = dds_path.relative_to(folder)
        parts = list(rel.parts)
        parts[-1] = rel.stem
        if args.replace:
            res_name = '/'.join(parts)
        else:
            res_name = tex_prefix + '/'.join(parts)
        res_name = res_name.replace('\\', '/')
        name_hash = murmur_hash64(res_name)

        res = Resource(TYPE_TEXTURE, res_name, name_hash, data)
        textures.append(TextureInfo(res, w, h, fmt, str(dds_path)))
        print(f"  {dds_path.name:40s}  {w}x{h} {fmt:5s}  → {res_name}")
        print(f"  {'':40s}  hash 0x{name_hash:016X}")

    print(f"  Found {len(textures)} valid texture(s)")
    if not textures:
        sys.exit(1)

    # ── Step 2: Build resources ──
    print("\n[2/5] Building bundle...")
    all_resources: List[Resource] = []

    # Textures
    tex_names = [t.resource.name for t in textures]
    for t in textures:
        all_resources.append(t.resource)

    # Materials (optional)
    mat_names = []
    if args.with_materials:
        for t in textures:
            mat_name = Path(t.resource.name).name
            mat_hash = murmur_hash64(mat_name)
            mat_data = build_material_data(t.resource.name_hash)
            all_resources.append(Resource(TYPE_MATERIAL, mat_name, mat_hash, mat_data))
            mat_names.append(mat_name)
        print(f"  Created {len(mat_names)} material(s)")

    # Package resource
    pkg_data = build_package_data(tex_names, mat_names)
    all_resources.append(Resource(TYPE_PACKAGE, pkg_path, pkg_hash, pkg_data))

    raw = build_bundle(all_resources)
    compressed = compress_bundle(raw)
    ratio = (1 - len(compressed) / len(raw)) * 100
    print(f"  Resources: {len(all_resources)}  ({len(textures)} tex + {len(mat_names)} mat + 1 pkg)")
    print(f"  Raw size:        {len(raw):>12,} bytes")
    print(f"  Compressed size: {len(compressed):>12,} bytes  ({ratio:.1f}% smaller)")

    if args.dry_run:
        print("\n[DRY RUN] Would perform the following actions:")
        print(f"  • Write bundle to {CONTENTS_DIR / bundle_name}")
        print(f"  • Create empty stream {CONTENTS_DIR / (bundle_name + '.stream')}")
        print(f"  • Register {len(all_resources)} entries in {BUNDLE_DB}")
        if not args.no_lua:
            mod_dir = MODS_DIR / f"{args.package_name}(FF)v1.0"
            print(f"  • Create Lua mod at {mod_dir / 'script_main.lua'}")
        print("\nNo files were written.")
        return

    # ── Step 3: Register in bundle_database.data ──
    print("\n[3/5] Updating bundle_database.data...")
    with open(BUNDLE_DB, 'rb') as f:
        db_data = f.read()
    version, entries = parse_bundle_db(db_data)
    existing_bundles = {e['bundle'] for e in entries}

    if bundle_name in existing_bundles:
        print(f"  Bundle {bundle_name} already in database — skipping registration")
    else:
        backup = BUNDLE_DB.with_suffix('.data.backup')
        if not backup.exists():
            shutil.copy(BUNDLE_DB, backup)
            print(f"  Backup created: {backup.name}")

        stream_name = f"{bundle_name}.stream"
        for _ in range(len(all_resources)):
            entries.append({'flags': 1, 'bundle': bundle_name, 'stream': stream_name})
        new_db = build_bundle_db(version, entries)
        with open(BUNDLE_DB, 'wb') as f:
            f.write(new_db)
        print(f"  Added {len(all_resources)} entries (total now: {len(entries)})")

    # ── Step 4: Install bundle ──
    print("\n[4/5] Installing bundle...")
    bundle_dst = CONTENTS_DIR / bundle_name
    with open(bundle_dst, 'wb') as f:
        f.write(compressed)
    print(f"  Wrote {bundle_dst}")

    stream_dst = CONTENTS_DIR / f"{bundle_name}.stream"
    if not stream_dst.exists():
        stream_dst.touch()
        print(f"  Created empty {stream_dst.name}")

    # ── Step 5: Generate Lua mod ──
    if args.no_lua:
        print("\n[5/5] Lua mod generation skipped (--no-lua)")
    else:
        print("\n[5/5] Generating Lua loader mod...")
        mod_dir = MODS_DIR / f"{args.package_name}(FF)v1.0"
        mod_dir.mkdir(parents=True, exist_ok=True)
        lua_code = LUA_TEMPLATE.format(
            mod_name=args.package_name,
            package_path=pkg_path,
            bundle_name=bundle_name,
        )
        lua_path = mod_dir / "script_main.lua"
        with open(lua_path, 'w', encoding='utf-8') as f:
            f.write(lua_code)
        print(f"  Wrote {lua_path}")

    # ── Save manifest ──
    manifest = {
        "package_name": args.package_name,
        "package_path": pkg_path,
        "package_hash": f"0x{pkg_hash:016X}",
        "bundle_file": bundle_name,
        "mode": "replacement" if args.replace else "new_content",
        "resource_count": len(all_resources),
        "textures": {
            t.resource.name: {
                "hash": f"0x{t.resource.name_hash:016X}",
                "size": f"{t.width}x{t.height}",
                "format": t.fmt,
                "source": Path(t.filepath).name,
            } for t in textures
        },
    }
    if mat_names:
        manifest["materials"] = {
            n: f"0x{murmur_hash64(n):016X}" for n in mat_names
        }

    manifest_path = folder / f"{args.package_name}_manifest.json"
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"\n  Manifest: {manifest_path}")

    # ── Done ──
    print()
    print("=" * 70)
    print("  DONE!  Start the game and your bundle will load automatically.")
    print("=" * 70)
    print()
    print("  Lua loading command (if using manually):")
    print(f'    Game:load_package("{pkg_path}", true)')
    print()
    if args.replace:
        print("  Your textures will override the originals globally once loaded.")
    else:
        print("  Your textures are available by hash after the package loads.")
        print("  Check the manifest for each texture's hash.")
    print()


if __name__ == '__main__':
    main()
