#!/usr/bin/env python3
"""
Deep-dive comparison of native Gauntlet bundles vs custom bundles.
Decompresses and dumps full internal structure.
"""

import struct
import zlib
import sys
import os

CONTENTS_DIR = os.path.expanduser("~/.local/share/Steam/steamapps/common/Gauntlet/contents")
MODS_DIR = os.path.expanduser("~/.local/share/Steam/steamapps/common/Gauntlet/mods/bundles")

# Known type hashes
TYPE_NAMES = {
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
    0x169C71E38E8B453B: "state_machine",
    0x786F65C00A816B19: "timpani_master",
    0x99736BE0F6838D39: "timpani_bank",
    0xA486D4045106B5A2: "strings",
    0x5106B81DCD8D6525: "flow",
    0x90641B51C98B7C48: "network_config",
    0x82645835E6B73232: "config",
    0x3ECDFC4F48C8B4C2: "surface_properties",
    0x1E688F426D60010F: "render_config",
    0x27862FE24795319E: "shading_environment",
    0x9831CA893B0D087D: "shading_environment_mapping",
    0x786F65C00A816B19: "timpani_master",
}

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


def decompress_bundle(filepath):
    """Decompress a Gauntlet bundle file, return (signature, uncompressed_size, data)"""
    with open(filepath, 'rb') as f:
        raw = f.read()

    if len(raw) < 12:
        return None, None, None

    sig, uncomp_size, padding = struct.unpack_from('<III', raw, 0)

    if sig not in (0xF0000004, 0xF0000005):
        print(f"  WARNING: Unknown signature 0x{sig:08X}")
        return sig, uncomp_size, None

    offset = 12
    decompressed = bytearray()

    while offset < len(raw):
        if offset + 4 > len(raw):
            break
        chunk_size = struct.unpack_from('<I', raw, offset)[0]
        offset += 4

        if chunk_size == 0 or offset + chunk_size > len(raw):
            break

        chunk_data = raw[offset:offset + chunk_size]
        offset += chunk_size

        try:
            decomp = zlib.decompress(chunk_data)
            decompressed.extend(decomp)
        except zlib.error as e:
            print(f"  WARNING: zlib error at offset {offset - chunk_size}: {e}")
            break

    return sig, uncomp_size, bytes(decompressed)


def parse_bundle(data, label=""):
    """Parse decompressed bundle data and return structured info."""
    if not data or len(data) < 4:
        print(f"  [{label}] No data to parse")
        return None

    resource_count = struct.unpack_from('<I', data, 0)[0]
    print(f"  [{label}] Resource count: {resource_count}")

    # Hash table: starts at offset 4, up to 0x100 bytes (max 32 entries of 8 bytes each)
    hash_table_size = min(resource_count * 8, 0x100)
    print(f"  [{label}] Hash table size: {hash_table_size} bytes ({min(resource_count, 32)} entries)")

    hashes = []
    for i in range(min(resource_count, 32)):
        h = struct.unpack_from('<Q', data, 4 + i * 8)[0]
        hashes.append(h)

    print(f"  [{label}] Hash table entries:")
    for i, h in enumerate(hashes):
        print(f"    [{i}] 0x{h:016X}")

    # Check if hashes are sorted
    sorted_ok = all(hashes[i] <= hashes[i+1] for i in range(len(hashes)-1))
    print(f"  [{label}] Hash table sorted: {sorted_ok}")

    # Padding region: from end of hash table to 0x104
    hash_end = 4 + hash_table_size
    padding_bytes = data[hash_end:0x104]
    non_zero_padding = sum(1 for b in padding_bytes if b != 0)
    print(f"  [{label}] Padding ({hash_end:#x} to 0x104): {len(padding_bytes)} bytes, {non_zero_padding} non-zero")

    # Entry table at 0x104
    entry_offset = 0x104
    print(f"  [{label}] Entry table at offset 0x{entry_offset:X}:")
    entries = []
    for i in range(resource_count):
        off = entry_offset + i * 16
        if off + 16 > len(data):
            print(f"    [{i}] TRUNCATED at offset 0x{off:X}")
            break
        type_hash, name_hash = struct.unpack_from('<QQ', data, off)
        type_name = TYPE_NAMES.get(type_hash, f"unknown(0x{type_hash:016X})")
        entries.append((type_hash, name_hash, type_name))
        print(f"    [{i}] type=0x{type_hash:016X} ({type_name:20s})  name=0x{name_hash:016X}")

    # Resource data section
    data_offset = entry_offset + resource_count * 16
    print(f"\n  [{label}] Resource data section at offset 0x{data_offset:X}:")

    resources = []
    for i in range(resource_count):
        if data_offset + 36 > len(data):
            print(f"    [{i}] TRUNCATED at offset 0x{data_offset:X} (need 36 bytes, have {len(data) - data_offset})")
            break

        r_type, r_name, flags = struct.unpack_from('<QQI', data, data_offset)
        stream_size = struct.unpack_from('<Q', data, data_offset + 20)[0]
        main_size, reserved = struct.unpack_from('<II', data, data_offset + 28)

        type_name = TYPE_NAMES.get(r_type, f"unknown(0x{r_type:016X})")
        print(f"    [{i}] type=0x{r_type:016X} ({type_name})")
        print(f"         name=0x{r_name:016X}")
        print(f"         flags={flags}  stream_size={stream_size}  main_size={main_size}  reserved={reserved}")
        print(f"         data_offset=0x{data_offset + 36:X}")

        # Show first 64 bytes of resource data
        res_data_start = data_offset + 36
        res_data = data[res_data_start:res_data_start + min(main_size, 128)]
        hex_preview = ' '.join(f'{b:02X}' for b in res_data[:64])
        print(f"         data[0:64]: {hex_preview}")

        if type_name == "package" and main_size > 0:
            parse_package_resource(data[res_data_start:res_data_start + main_size], i)

        resources.append({
            'type_hash': r_type,
            'name_hash': r_name,
            'type_name': type_name,
            'flags': flags,
            'stream_size': stream_size,
            'main_size': main_size,
            'reserved': reserved,
            'data_offset': data_offset,
        })

        data_offset = res_data_start + main_size

    # Check trailing bytes
    remaining = len(data) - data_offset
    if remaining > 0:
        trail = data[data_offset:data_offset + min(remaining, 32)]
        hex_trail = ' '.join(f'{b:02X}' for b in trail)
        print(f"\n  [{label}] Trailing {remaining} bytes: {hex_trail}")
    else:
        print(f"\n  [{label}] No trailing bytes (data ends exactly)")

    return {
        'resource_count': resource_count,
        'hashes': hashes,
        'entries': entries,
        'resources': resources,
        'total_size': len(data),
    }


def parse_package_resource(data, idx):
    """Parse a package resource's internal structure."""
    if len(data) < 4:
        print(f"         PACKAGE[{idx}]: too small ({len(data)} bytes)")
        return

    entry_count = struct.unpack_from('<I', data, 0)[0]
    print(f"         PACKAGE[{idx}]: {entry_count} entries")

    off = 4
    for j in range(entry_count):
        if off + 20 > len(data):
            print(f"           [{j}] TRUNCATED")
            break
        p_type, p_name, dep_count = struct.unpack_from('<QQI', data, off)
        type_name = TYPE_NAMES.get(p_type, f"unknown(0x{p_type:016X})")
        print(f"           [{j}] type=0x{p_type:016X} ({type_name})  name=0x{p_name:016X}  deps={dep_count}")
        off += 20 + dep_count * 4


def analyze_db_entries(bundle_hash_str):
    """Find all entries in bundle_database.data for a given bundle hash."""
    db_path = os.path.join(CONTENTS_DIR, "bundle_database.data")
    if not os.path.exists(db_path):
        print(f"  DB not found: {db_path}")
        return

    with open(db_path, 'rb') as f:
        db = f.read()

    version, count = struct.unpack_from('<II', db, 0)
    print(f"\n  DB: version={version}, total_entries={count}")

    target = bundle_hash_str.lower().encode('ascii')
    offset = 8
    matches = 0
    for i in range(count):
        if offset + 8 > len(db):
            break
        platform_id, name_len = struct.unpack_from('<II', db, offset)
        offset += 8
        if offset + name_len > len(db):
            break
        bundle_name = db[offset:offset + name_len]
        offset += name_len

        if offset + 4 > len(db):
            break
        stream_len = struct.unpack_from('<I', db, offset)[0]
        offset += 4
        if offset + stream_len > len(db):
            break
        stream_name = db[offset:offset + stream_len]
        offset += stream_len

        # Skip null terminator
        if offset < len(db) and db[offset] == 0:
            offset += 1

        if bundle_name == target:
            matches += 1
            print(f"  DB match [{matches}]: platform={platform_id} bundle={bundle_name.decode()} stream={stream_name.decode()}")

    if matches == 0:
        print(f"  DB: No entries found for '{bundle_hash_str}'")
    else:
        print(f"  DB: {matches} total entries for '{bundle_hash_str}'")


def analyze_file(filepath, label):
    """Full analysis of a single bundle file."""
    print(f"\n{'='*80}")
    print(f"BUNDLE: {label}")
    print(f"  Path: {filepath}")
    size = os.path.getsize(filepath)
    print(f"  File size: {size} bytes")

    # Show raw header
    with open(filepath, 'rb') as f:
        header = f.read(32)
    hex_header = ' '.join(f'{b:02X}' for b in header)
    print(f"  Raw header (32 bytes): {hex_header}")

    sig, uncomp_size, data = decompress_bundle(filepath)
    if sig is None:
        print(f"  FAILED to read")
        return None

    print(f"  Signature: 0x{sig:08X}")
    print(f"  Declared uncompressed size: {uncomp_size}")
    print(f"  Actual decompressed size: {len(data) if data else 0}")
    if data and uncomp_size != len(data):
        print(f"  *** SIZE MISMATCH: declared={uncomp_size} actual={len(data)} ***")

    if data:
        return parse_bundle(data, label)
    return None


def find_native_bundles_with_packages():
    """Scan all native bundles to find ones containing package resources."""
    print("\n" + "="*80)
    print("SCANNING NATIVE BUNDLES FOR PACKAGE RESOURCES...")
    print("="*80)

    pkg_type_hash = 0xAD9C6D9ED1E5E77A  # "package" type
    found = []

    for fname in sorted(os.listdir(CONTENTS_DIR)):
        fpath = os.path.join(CONTENTS_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        if '.' in fname or fname == 'bundle_database.data':
            continue

        try:
            sig, uncomp_size, data = decompress_bundle(fpath)
            if not data or len(data) < 0x120:
                continue

            rcount = struct.unpack_from('<I', data, 0)[0]
            if rcount == 0 or rcount > 10000:
                continue

            # Check entry table for package type
            for i in range(rcount):
                off = 0x104 + i * 16
                if off + 16 > len(data):
                    break
                type_hash = struct.unpack_from('<Q', data, off)[0]
                if type_hash == pkg_type_hash:
                    found.append((fname, rcount, data))
                    break
        except Exception:
            continue

    print(f"Found {len(found)} native bundles with package resources")
    for fname, rc, _ in found[:5]:
        print(f"  {fname} ({rc} resources)")

    return found


def main():
    print("GAUNTLET BUNDLE DEEP ANALYSIS")
    print("=" * 80)

    # 1. Verify expected hashes
    pkg_path = "resource_packages/custom/Cube_Test"
    expected_hash = murmur_hash64(pkg_path)
    print(f"\nPackage path: '{pkg_path}'")
    print(f"Expected hash: 0x{expected_hash:016X} = {expected_hash:016x}")

    # 2. Analyze custom bundle
    custom_path = os.path.join(MODS_DIR, "Cube_Test", "005884553a7b5e6e")
    if os.path.exists(custom_path):
        custom_info = analyze_file(custom_path, "CUSTOM (Cube_Test)")
    else:
        print(f"\nCustom bundle not found at {custom_path}")
        custom_info = None

    # 2b. Also check if it's been copied to contents/
    contents_custom = os.path.join(CONTENTS_DIR, "005884553a7b5e6e")
    if os.path.exists(contents_custom):
        print(f"\n  Custom bundle exists in contents/: YES")
        if os.path.getsize(contents_custom) == os.path.getsize(custom_path):
            print(f"  Same size as source: YES")
        else:
            print(f"  *** SIZE DIFFERS from source ***")
    else:
        print(f"\n  Custom bundle exists in contents/: NO *** MISSING ***")

    # 3. Check DB entries for custom bundle
    analyze_db_entries("005884553a7b5e6e")

    # 4. Find and analyze a native bundle with package resources for comparison
    native_bundles = find_native_bundles_with_packages()

    if native_bundles:
        # Analyze the first native bundle with packages (pick a small one)
        native_bundles.sort(key=lambda x: x[1])  # sort by resource count
        fname, rc, _ = native_bundles[0]
        native_path = os.path.join(CONTENTS_DIR, fname)
        native_info = analyze_file(native_path, f"NATIVE ({fname}, {rc} resources)")

        # Also analyze a medium-sized one for comparison
        if len(native_bundles) > 1:
            fname2, rc2, _ = native_bundles[len(native_bundles)//2]
            native_path2 = os.path.join(CONTENTS_DIR, fname2)
            analyze_file(native_path2, f"NATIVE2 ({fname2}, {rc2} resources)")

    # 5. Summary comparison
    if custom_info and native_bundles:
        print("\n" + "="*80)
        print("COMPARISON SUMMARY")
        print("="*80)
        print(f"Custom bundle: {custom_info['resource_count']} resources, {custom_info['total_size']} bytes decompressed")
        if native_bundles:
            print(f"Native bundles with packages: {len(native_bundles)} found")
            for fname, rc, data in native_bundles[:3]:
                rcount = struct.unpack_from('<I', data, 0)[0]
                print(f"  {fname}: {rcount} resources, {len(data)} bytes decompressed")


if __name__ == "__main__":
    main()
