#!/usr/bin/env python3
"""Inspect a Gauntlet bundle file and compare against a known-working one."""

import struct, zlib, sys
from pathlib import Path

CONTENTS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents")

TYPE_NAMES = {
    0xCD4238C6A0C69E32: "texture",
    0xEAC0B497876ADEDF: "material",
    0xAD9C6D9ED1E5E77A: "package",
    0xA14E8DFA2CD117E2: "lua",
    0xE0A48D0BE9A7453F: "unit",
    0x48FF313713A997A1: "mesh",
    0x82645835E6B73232: "config",
    0xCCE8D5B5F5AE333F: "shader",
}


def decompress_bundle(data):
    sig, unp_size, unk = struct.unpack("<III", data[:12])
    print(f"  Signature:     0x{sig:08X}  {'OK' if sig == 0xF0000004 else 'BAD!'}")
    print(f"  Unpacked size: {unp_size:,}")
    print(f"  Header unk:    {unk}")
    print(f"  File size:     {len(data):,}")

    offset = 12
    chunks = []
    while offset < len(data):
        csize = struct.unpack("<I", data[offset : offset + 4])[0]
        offset += 4
        chunk = zlib.decompress(data[offset : offset + csize])
        chunks.append(chunk)
        offset += csize
    unpacked = b"".join(chunks)
    print(f"  Decompressed:  {len(unpacked):,}  match={'YES' if len(unpacked)==unp_size else 'NO!'}")
    return unpacked


def inspect_unpacked(unpacked, label=""):
    count = struct.unpack("<I", unpacked[:4])[0]
    print(f"\n  Resource count: {count}")

    # Name hash table
    print(f"\n  Name hash table (offset 0x04):")
    hashes = []
    for i in range(min(count, 5)):
        h = struct.unpack("<Q", unpacked[4 + i * 8 : 4 + (i + 1) * 8])[0]
        hashes.append(h)
        print(f"    [{i}] 0x{h:016X}")
    if count > 5:
        for i in range(5, count):
            h = struct.unpack("<Q", unpacked[4 + i * 8 : 4 + (i + 1) * 8])[0]
            hashes.append(h)
        print(f"    ... ({count - 5} more)")

    sorted_ok = all(hashes[i] <= hashes[i + 1] for i in range(len(hashes) - 1))
    print(f"  Sorted: {'YES' if sorted_ok else 'NO - PROBLEM!'}")

    nhash_end = 4 + count * 8
    print(f"  Hash table ends at 0x{nhash_end:X}")

    if nhash_end <= 0x104:
        et_offset = 0x104
        padding = 0x104 - nhash_end
        pad_bytes = unpacked[nhash_end:0x104]
        pad_ok = all(b == 0 for b in pad_bytes)
        print(f"  Padding to 0x104: {padding} bytes (all zeros: {'YES' if pad_ok else 'NO!'})")
    else:
        et_offset = nhash_end
        print(f"  No padding (large bundle), entry table at 0x{et_offset:X}")

    # Entry table
    print(f"\n  Entry table (offset 0x{et_offset:X}):")
    entry_hashes = []
    for i in range(min(count, 10)):
        off = et_offset + i * 16
        th, nh = struct.unpack("<QQ", unpacked[off : off + 16])
        tname = TYPE_NAMES.get(th, "UNKNOWN")
        print(f"    [{i}] type=0x{th:016X} ({tname})  name=0x{nh:016X}")
        entry_hashes.append(nh)
    if count > 10:
        for i in range(10, count):
            off = et_offset + i * 16
            th, nh = struct.unpack("<QQ", unpacked[off : off + 16])
            entry_hashes.append(nh)
        print(f"    ... ({count - 10} more)")
    
    match_ok = entry_hashes[:min(count,10)] == hashes[:min(count,10)]
    print(f"  Entry hashes match name table: {'YES' if match_ok else 'NO - PROBLEM!'}")

    # Resource data
    doff = et_offset + count * 16
    print(f"\n  Resource data (offset 0x{doff:X}):")
    for i in range(min(count, 10)):
        rtype, rname, flags = struct.unpack("<QQI", unpacked[doff : doff + 20])
        ss = struct.unpack("<Q", unpacked[doff + 20 : doff + 28])[0]
        ms, unk = struct.unpack("<II", unpacked[doff + 28 : doff + 36])
        tname = TYPE_NAMES.get(rtype, "UNKNOWN")

        print(f"    [{i}] {tname}  name=0x{rname:016X}")
        print(f"        flags={flags}  stream_size={ss}  main_size={ms}  unk={unk}")

        data_start = doff + 36
        fb = unpacked[data_start : data_start + min(32, ms)]
        if fb[:4] == b"DDS ":
            dds_h = struct.unpack_from("<I", fb, 12)[0]
            dds_w = struct.unpack_from("<I", fb, 16)[0]
            print(f"        DDS magic OK, {dds_w}x{dds_h}")
        elif tname == "package":
            pkg_count = struct.unpack("<I", fb[:4])[0]
            print(f"        Package entries: {pkg_count}")

        doff += 36 + ms
    if count > 10:
        for i in range(10, count):
            rtype, rname, flags = struct.unpack("<QQI", unpacked[doff : doff + 20])
            ss = struct.unpack("<Q", unpacked[doff + 20 : doff + 28])[0]
            ms, unk = struct.unpack("<II", unpacked[doff + 28 : doff + 36])
            doff += 36 + ms
        print(f"    ... ({count - 10} more resources)")

    remaining = len(unpacked) - doff
    print(f"\n  Total parsed to 0x{doff:X}, remaining: {remaining} bytes")
    if remaining > 0 and remaining <= 16:
        print(f"  Trailing: {unpacked[doff:].hex()}")


def inspect_bundle_db_for(bundle_name):
    print(f"\n  DB entries for '{bundle_name}':")
    with open(CONTENTS / "bundle_database.data", "rb") as f:
        data = f.read()
    version, bcount = struct.unpack("<II", data[:8])
    
    offset = 8
    matches = 0
    for i in range(bcount):
        flags = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
        blen = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
        bname = data[offset:offset+blen].decode("utf-8"); offset += blen
        slen = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
        sname = data[offset:offset+slen].decode("utf-8"); offset += slen
        offset += 1
        if bname == bundle_name:
            matches += 1
            if matches <= 3:
                print(f"    flags={flags} bundle='{bname}' stream='{sname}'")
    print(f"    Total: {matches} entries")
    return matches


def main():
    test_bundle = "b5ddd5abe546fd2c"
    known_good = "d5ec4eb9fc5f3c88"

    for name in [test_bundle, known_good]:
        path = CONTENTS / name
        if not path.exists():
            print(f"\nBundle {name} not found!")
            continue
        print(f"\n{'='*70}")
        label = "TEST (our bundle)" if name == test_bundle else "KNOWN GOOD (verified Jan 9)"
        print(f" {label}: {name}")
        print(f"{'='*70}")
        with open(path, "rb") as f:
            raw = f.read()
        unpacked = decompress_bundle(raw)
        inspect_unpacked(unpacked, name)
    
    print(f"\n{'='*70}")
    print(f" BUNDLE DATABASE")
    print(f"{'='*70}")
    inspect_bundle_db_for(test_bundle)
    inspect_bundle_db_for(known_good)

    print(f"\n{'='*70}")
    print(f" HASH VERIFICATION")
    print(f"{'='*70}")
    
    def murmur_hash64(key, seed=0):
        m = 0xC6A4A7935BD1E995; r = 47
        kb = key.lower().encode("utf-8"); length = len(kb)
        h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)
        nb = length // 8
        for i in range(nb):
            k = struct.unpack("<Q", kb[i*8:(i+1)*8])[0]
            k = (k * m) & 0xFFFFFFFFFFFFFFFF; k ^= (k >> r)
            k = (k * m) & 0xFFFFFFFFFFFFFFFF; h ^= k
            h = (h * m) & 0xFFFFFFFFFFFFFFFF
        tail = kb[nb * 8:]
        if len(tail) >= 7: h ^= tail[6] << 48
        if len(tail) >= 6: h ^= tail[5] << 40
        if len(tail) >= 5: h ^= tail[4] << 32
        if len(tail) >= 4: h ^= tail[3] << 24
        if len(tail) >= 3: h ^= tail[2] << 16
        if len(tail) >= 2: h ^= tail[1] << 8
        if len(tail) >= 1: h ^= tail[0]; h = (h * m) & 0xFFFFFFFFFFFFFFFF
        h ^= (h >> r); h = (h * m) & 0xFFFFFFFFFFFFFFFF; h ^= (h >> r)
        return h

    tests = [
        ("resource_packages/custom/TestBundle", test_bundle),
        ("resource_packages/custom/global_textures", known_good),
        ("custom/TestBundle/test_bundle_image", None),
        ("texture", None),
        ("package", None),
    ]
    for path, expected in tests:
        h = murmur_hash64(path)
        hx = f"{h:016x}"
        match = ""
        if expected:
            match = f"  {'MATCH' if hx == expected else 'MISMATCH! expected ' + expected}"
        print(f"  '{path}' -> 0x{h:016X} ({hx}){match}")


if __name__ == "__main__":
    main()
