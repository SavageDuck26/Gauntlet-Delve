#!/usr/bin/env python3
"""Analyze and compare Gauntlet bundle files - native vs custom."""

import struct
import zlib
import sys
import os

CONTENTS_DIR = os.path.expanduser(
    "~/.local/share/Steam/steamapps/common/Gauntlet/contents"
)

TYPE_HASHES = {
    0xCD4238C6A0C69E32: "texture",
    0xEAC0B497876ADEDF: "material",
    0xA14E8DFA2CD117E2: "lua",
    0xE0A48D0BE9A7453F: "unit",
    0xAD9C6D9ED1E5E77A: "package",
    0x48FF313713A997A1: "mesh",
    0x18DEAD01056B72E9: "bones",
    0xCCE8D5B5F5AE333F: "shader",
    0x931E336D7646CC26: "animation",
    0x2A690FD348FE9AC5: "level",
    0x5F7203C8F280DAB8: "physics",
}


def decompress_bundle(filepath):
    """Decompress a Gauntlet bundle file, return (signature, raw_data)."""
    with open(filepath, "rb") as f:
        data = f.read()

    sig = struct.unpack_from("<I", data, 0)[0]
    uncomp_size = struct.unpack_from("<I", data, 4)[0]
    # padding at offset 8

    chunks = []
    offset = 12
    while offset < len(data):
        if offset + 4 > len(data):
            break
        chunk_size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if chunk_size == 0 or offset + chunk_size > len(data):
            break
        chunk_data = data[offset : offset + chunk_size]
        offset += chunk_size
        try:
            chunks.append(zlib.decompress(chunk_data))
        except zlib.error as e:
            print(f"  WARNING: zlib decompress error at chunk offset {offset - chunk_size}: {e}")
            chunks.append(chunk_data)

    raw = b"".join(chunks)
    return sig, uncomp_size, raw


def analyze_unpacked(raw, label=""):
    """Analyze the unpacked bundle structure and print details."""
    print(f"\n{'='*70}")
    print(f"  BUNDLE: {label}")
    print(f"{'='*70}")
    print(f"  Unpacked size: {len(raw)} bytes (0x{len(raw):X})")

    if len(raw) < 4:
        print("  ERROR: Too small!")
        return

    resource_count = struct.unpack_from("<I", raw, 0)[0]
    print(f"  Resource count: {resource_count}")

    # Hash table (at offset 4, up to 0x100 bytes = 32 entries max)
    max_hashes = min(resource_count, 32)
    print(f"\n  --- Name Hash Table (at 0x04, {max_hashes} entries) ---")
    for i in range(max_hashes):
        off = 4 + i * 8
        if off + 8 > len(raw):
            print(f"    [TRUNCATED at hash {i}]")
            break
        h = struct.unpack_from("<Q", raw, off)[0]
        print(f"    [{i:2d}] 0x{h:016X}")

    # Entry table starts at 0x104
    entry_offset = 0x104
    print(f"\n  --- Resource Entry Table (at 0x{entry_offset:X}, 16 bytes each) ---")
    entries = []
    for i in range(resource_count):
        off = entry_offset + i * 16
        if off + 16 > len(raw):
            print(f"    [TRUNCATED at entry {i}]")
            break
        type_hash, name_hash = struct.unpack_from("<QQ", raw, off)
        type_name = TYPE_HASHES.get(type_hash, f"unknown(0x{type_hash:016X})")
        entries.append((type_hash, name_hash, type_name))
        print(f"    [{i}] type=0x{type_hash:016X} ({type_name:>10s})  name=0x{name_hash:016X}")

    # Resource data section
    data_offset = entry_offset + resource_count * 16
    print(f"\n  --- Resource Data Section (at 0x{data_offset:X}) ---")
    off = data_offset
    for i in range(resource_count):
        if off + 36 > len(raw):
            print(f"    [{i}] TRUNCATED (need 36 header bytes, have {len(raw) - off})")
            break

        r_type, r_name = struct.unpack_from("<QQ", raw, off)
        r_flags = struct.unpack_from("<I", raw, off + 16)[0]
        r_stream_size = struct.unpack_from("<Q", raw, off + 20)[0]
        r_main_size = struct.unpack_from("<I", raw, off + 28)[0]
        r_unknown = struct.unpack_from("<I", raw, off + 32)[0]

        type_name = TYPE_HASHES.get(r_type, f"unknown(0x{r_type:016X})")
        print(f"    [{i}] type=0x{r_type:016X} ({type_name})")
        print(f"         name=0x{r_name:016X}")
        print(f"         flags={r_flags}  stream_size={r_stream_size}  main_size={r_main_size}  unknown={r_unknown}")
        print(f"         data offset: 0x{off+36:X}")

        # Show first 32 bytes of data
        data_start = off + 36
        data_end = min(data_start + r_main_size, len(raw))
        preview = raw[data_start : min(data_start + 64, data_end)]
        hex_preview = " ".join(f"{b:02X}" for b in preview)
        print(f"         data[0:{len(preview)}]: {hex_preview}")

        # Check for DDS magic
        if len(preview) >= 4 and preview[:4] == b"DDS ":
            print(f"         -> DDS texture detected")
        # Check for known patterns
        if type_name == "package" and len(preview) >= 4:
            pkg_count = struct.unpack_from("<I", preview, 0)[0]
            print(f"         -> Package with {pkg_count} entries")
            # Parse package entries
            poff = 4
            pdata = raw[data_start:data_end]
            for j in range(min(pkg_count, 20)):
                if poff + 20 > len(pdata):
                    break
                pt, pn = struct.unpack_from("<QQ", pdata, poff)
                pdeps = struct.unpack_from("<I", pdata, poff + 16)[0]
                pt_name = TYPE_HASHES.get(pt, f"0x{pt:016X}")
                print(f"            pkg[{j}] type={pt_name} name=0x{pn:016X} deps={pdeps}")
                poff += 20 + pdeps * 4

        off = data_start + r_main_size

    # Check remaining bytes
    remaining = len(raw) - off
    if remaining > 0:
        print(f"\n  --- Trailing data: {remaining} bytes at 0x{off:X} ---")
        trail = raw[off : off + min(64, remaining)]
        print(f"      {' '.join(f'{b:02X}' for b in trail)}")
    
    return entries


def analyze_db_entries(bundle_hash_str):
    """Find and show all DB entries for a given bundle hash."""
    db_path = os.path.join(CONTENTS_DIR, "bundle_database.data")
    if not os.path.exists(db_path):
        print(f"\n  DB not found: {db_path}")
        return

    with open(db_path, "rb") as f:
        db = f.read()

    version = struct.unpack_from("<I", db, 0)[0]
    count = struct.unpack_from("<I", db, 4)[0]
    print(f"\n  --- bundle_database.data (version={version}, {count} entries) ---")

    target = bundle_hash_str.lower().encode()
    off = 8
    found = 0
    for i in range(count):
        if off + 4 > len(db):
            break
        platform = struct.unpack_from("<I", db, off)[0]
        off += 4

        name_len = struct.unpack_from("<I", db, off)[0]
        off += 4
        name = db[off : off + name_len]
        off += name_len

        stream_len = struct.unpack_from("<I", db, off)[0]
        off += 4
        stream = db[off : off + stream_len]
        off += stream_len

        # null terminator
        if off < len(db) and db[off] == 0:
            off += 1

        if name == target:
            found += 1
            print(f"    Entry #{i}: platform={platform} name={name.decode()} stream={stream.decode()}")

    print(f"    Found {found} entries for bundle {bundle_hash_str}")


def hexdump(data, max_bytes=256, offset=0):
    """Print a hex dump of data."""
    for i in range(0, min(len(data), max_bytes), 16):
        hex_part = " ".join(f"{data[i+j]:02X}" if i+j < len(data) else "  " for j in range(16))
        ascii_part = "".join(
            chr(data[i+j]) if 32 <= data[i+j] < 127 else "."
            for j in range(16) if i+j < len(data)
        )
        print(f"    {offset+i:08X}: {hex_part}  {ascii_part}")


if __name__ == "__main__":
    # Analyze a known native bundle that has a package resource
    # Pick a small one: 07c9b8511b5aff2e (menu/UI textures)
    native_bundles = []
    custom_bundle = os.path.expanduser(
        "~/.local/share/Steam/steamapps/common/Gauntlet/mods/bundles/Cube_Test/005884553a7b5e6e"
    )

    # Find a few native bundles that are small
    print("Scanning for small native bundles...")
    all_files = []
    for f in os.listdir(CONTENTS_DIR):
        path = os.path.join(CONTENTS_DIR, f)
        if os.path.isfile(path) and not f.endswith(".stream") and f != "bundle_database.data" and "." not in f:
            size = os.path.getsize(path)
            all_files.append((size, f, path))
    
    all_files.sort()
    print(f"Found {len(all_files)} bundle files")
    print(f"Size range: {all_files[0][0]} - {all_files[-1][0]} bytes")
    
    # Analyze the 3 smallest native bundles
    for size, name, path in all_files[:3]:
        print(f"\n>>> Native bundle: {name} ({size} bytes compressed)")
        try:
            sig, uncomp, raw = decompress_bundle(path)
            print(f"  Signature: 0x{sig:08X}")
            print(f"  Declared uncompressed: {uncomp}, actual: {len(raw)}")
            analyze_unpacked(raw, name)
            analyze_db_entries(name)
        except Exception as e:
            print(f"  Error: {e}")

    # Find a native bundle that contains a "package" type resource
    print(f"\n\n{'#'*70}")
    print("# Looking for native bundles with package resources...")
    print(f"{'#'*70}")
    
    for size, name, path in all_files:
        try:
            sig, uncomp, raw = decompress_bundle(path)
            if len(raw) < 4:
                continue
            rc = struct.unpack_from("<I", raw, 0)[0]
            # Check entry table for package type
            for i in range(rc):
                eoff = 0x104 + i * 16
                if eoff + 16 > len(raw):
                    break
                th = struct.unpack_from("<Q", raw, eoff)[0]
                if th == 0xAD9C6D9ED1E5E77A:  # package
                    print(f"\n>>> Found package resource in bundle: {name} ({size} bytes, {rc} resources)")
                    analyze_unpacked(raw, name)
                    analyze_db_entries(name)
                    native_bundles.append((name, raw))
                    break
            if len(native_bundles) >= 2:
                break
        except:
            continue

    # Now analyze the custom bundle
    print(f"\n\n{'#'*70}")
    print("# CUSTOM BUNDLE")
    print(f"{'#'*70}")
    if os.path.exists(custom_bundle):
        sig, uncomp, raw = decompress_bundle(custom_bundle)
        print(f"  Compressed file size: {os.path.getsize(custom_bundle)} bytes")
        print(f"  Signature: 0x{sig:08X}")
        print(f"  Declared uncompressed: {uncomp}, actual: {len(raw)}")
        
        print(f"\n  --- Full hex dump of unpacked data ---")
        hexdump(raw, max_bytes=2048)
        
        analyze_unpacked(raw, "Cube_Test (CUSTOM)")
        analyze_db_entries("005884553a7b5e6e")
    else:
        print(f"  Custom bundle not found: {custom_bundle}")
