#!/usr/bin/env python3
"""Analyze real game bundle structure."""

import struct
import zlib

TYPE_MATERIAL = 0xEAC0B497876ADEDF
TYPE_TEXTURE = 0xCD4238C6A0C69E32
TYPE_PACKAGE = 0xAD9C6D9ED1E5E77A

def analyze_bundle(bundle_path):
    with open(bundle_path, 'rb') as f:
        data = f.read()
    
    # Parse bundle header
    print(f"Bundle file size: {len(data)} bytes")
    sig = struct.unpack_from('<I', data, 0)[0]
    unpacked_size = struct.unpack_from('<I', data, 4)[0]
    print(f"Signature: 0x{sig:08X}")
    print(f"Declared unpacked size: {unpacked_size}")
    
    # Decompress all chunks
    offset = 12  # Skip header
    chunks = []
    while offset < len(data):
        chunk_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        if chunk_size == 0:
            break
        chunk_data = data[offset:offset+chunk_size]
        try:
            decompressed = zlib.decompress(chunk_data)
            chunks.append(decompressed)
        except:
            break
        offset += chunk_size
    
    unpacked = b''.join(chunks)
    print(f"Actually decompressed: {len(unpacked)} bytes")
    
    count = struct.unpack_from('<I', unpacked, 0)[0]
    print(f"Resource count: {count}")
    
    # Entry table location
    entry_offset = 4 + count * 8
    if entry_offset < 0x104:
        entry_offset = 0x104
    
    print(f"Entry table at: 0x{entry_offset:X}")
    
    # Data section after entry table
    data_offset = entry_offset + count * 16
    print(f"Data section starts at: 0x{data_offset:X}")
    
    # Search for type hashes in data section to find resource headers
    print("\nSearching for type hashes in data section...")
    found = []
    for offset in range(data_offset, len(unpacked) - 8, 4):
        val = struct.unpack_from('<Q', unpacked, offset)[0]
        if val == TYPE_MATERIAL or val == TYPE_TEXTURE:
            rtype = "MATERIAL" if val == TYPE_MATERIAL else "TEXTURE"
            found.append((offset, rtype))
    
    print(f"Found {len(found)} type hash occurrences")
    for offset, rtype in found[:10]:
        print(f"  0x{offset:X}: {rtype}")
        # Print surrounding bytes
        if offset + 36 <= len(unpacked):
            header = unpacked[offset:offset+36]
            print(f"    Header: {header.hex()}")
    
    # Try to understand the header format
    if found:
        print("\nAnalyzing first resource header:")
        offset = found[0][0]
        type_hash = struct.unpack_from('<Q', unpacked, offset)[0]
        name_hash = struct.unpack_from('<Q', unpacked, offset + 8)[0]
        print(f"  type_hash @ +0: 0x{type_hash:016X}")
        print(f"  name_hash @ +8: 0x{name_hash:016X}")
        
        # Look at remaining bytes
        for i in range(16, 40, 4):
            if offset + i + 4 <= len(unpacked):
                val = struct.unpack_from('<I', unpacked, offset + i)[0]
                print(f"  uint32 @ +{i}: {val} (0x{val:08X})")
    
    # Now search specifically for MATERIAL type
    print("\nSearching for ALL materials...")
    mat_count = 0
    for offset in range(data_offset, len(unpacked) - 8, 1):  # Check every byte
        val = struct.unpack_from('<Q', unpacked, offset)[0]
        if val == TYPE_MATERIAL:
            mat_count += 1
            print(f"  Material at 0x{offset:X}")
            if offset + 48 <= len(unpacked):
                name_hash = struct.unpack_from('<Q', unpacked, offset + 8)[0]
                flags = struct.unpack_from('<I', unpacked, offset + 16)[0]
                size = struct.unpack_from('<I', unpacked, offset + 28)[0]
                print(f"    name=0x{name_hash:016X}, flags={flags}, size={size}")
                # Show start of material data
                mat_start = offset + 36
                mat_data = unpacked[mat_start:mat_start+48]
                print(f"    data: {mat_data.hex()}")
            if mat_count >= 3:
                break
    
    print(f"\nTotal materials found: {mat_count}")

if __name__ == '__main__':
    analyze_bundle(r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\2366c0121dc7d2de')
