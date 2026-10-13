"""Find and analyze a real package resource from game bundles"""
import struct
import zlib

BUNDLE_SIG_OLD = 0xF0000004
ZLIB_CHUNK = 0x10000
TYPE_PACKAGE = 0xAD9C6D9ED1E5E77A

def decompress_bundle(packed_data, max_bytes=None):
    """Decompress a packed bundle file."""
    if len(packed_data) < 12:
        return packed_data
    
    signature, unzipped_size, padding = struct.unpack('<III', packed_data[:12])
    
    if signature != BUNDLE_SIG_OLD:
        return packed_data
    
    if max_bytes:
        target_size = min(unzipped_size, max_bytes)
    else:
        target_size = unzipped_size
    
    print(f"  Unzipped size: {unzipped_size:,}, target: {target_size:,}")
    
    offset = 12
    unpacked_chunks = []
    total = 0
    
    while offset < len(packed_data) and total < target_size:
        if offset + 4 > len(packed_data):
            break
            
        chunk_size = struct.unpack('<I', packed_data[offset:offset+4])[0]
        offset += 4
        
        if chunk_size == 0:
            break
        if chunk_size == ZLIB_CHUNK:
            continue
            
        if offset + chunk_size > len(packed_data):
            break
            
        chunk_data = packed_data[offset:offset + chunk_size]
        offset += chunk_size
        
        try:
            decompressed = zlib.decompress(chunk_data)
            unpacked_chunks.append(decompressed)
            total += len(decompressed)
        except:
            break
    
    return b''.join(unpacked_chunks)


def find_package_resources(data):
    """Find all package resources in the data"""
    # Search for package type hash in little endian
    pkg_sig = struct.pack('<Q', TYPE_PACKAGE)
    
    offset = 0
    results = []
    while True:
        pos = data.find(pkg_sig, offset)
        if pos == -1:
            break
        results.append(pos)
        offset = pos + 1
    
    return results


# Scan all bundles in contents for package resources
import os
contents_dir = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"

# Analyze bundle with 6 packages (simpler than 13)
bundle_path = os.path.join(contents_dir, "ec33816f62983aac")
print(f"Analyzing: {bundle_path}")

with open(bundle_path, 'rb') as bf:
    data = bf.read()

unpacked = decompress_bundle(data, max_bytes=None)
print(f"Unpacked: {len(unpacked):,} bytes")

# Parse header
entry_count = struct.unpack('<I', unpacked[0:4])[0]
print(f"Entry count: {entry_count}")

# Find all package entries
print("\nPackage entries in table:")
package_indices = []
for i in range(entry_count):
    entry_off = 0x104 + i * 16
    type_h = struct.unpack('<Q', unpacked[entry_off:entry_off+8])[0]
    name_h = struct.unpack('<Q', unpacked[entry_off+8:entry_off+16])[0]
    
    if type_h == TYPE_PACKAGE:
        package_indices.append(i)
        print(f"  [{i}] 0x{name_h:016X}")

print(f"\nTotal package entries: {len(package_indices)}")

# Now find the resource data section and analyze package data
data_start = 0x104 + entry_count * 16
print(f"\nResource data starts at: 0x{data_start:X}")

# Walk through resources to find first package
offset = data_start
for i in range(entry_count):
    if offset + 36 > len(unpacked):
        break
    
    # Read resource header (36 bytes)
    type_h = struct.unpack('<Q', unpacked[offset:offset+8])[0]
    name_h = struct.unpack('<Q', unpacked[offset+8:offset+16])[0]
    flags = struct.unpack('<I', unpacked[offset+16:offset+20])[0]
    stream_size = struct.unpack('<Q', unpacked[offset+20:offset+28])[0]
    main_size = struct.unpack('<I', unpacked[offset+28:offset+32])[0]
    unk = struct.unpack('<I', unpacked[offset+32:offset+36])[0]
    
    if type_h == TYPE_PACKAGE:
        print(f"\n=== PACKAGE RESOURCE {i} ===")
        print(f"  Name hash: 0x{name_h:016X}")
        print(f"  Flags: {flags}, Stream: {stream_size}, Main: {main_size}")
        
        # Show the package data
        res_data = unpacked[offset+36:offset+36+main_size]
        print(f"  Data ({len(res_data)} bytes):")
        for j in range(0, min(96, len(res_data)), 16):
            chunk = res_data[j:j+16]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            print(f"    {j:04x}: {hex_str}  {ascii_str}")
        
        # Looking at the pattern more carefully:
        # physics hash repeats every 28 bytes: 0x04, 0x20, 0x3C, 0x58...
        # But the first uint32 is 5, not 4. Let's check if there are 5 distinct name hashes.
        
        if len(res_data) >= 4:
            total = struct.unpack('<I', res_data[0:4])[0]
            print(f"\n  Entry count in header: {total}")
            remaining = len(res_data) - 4
            print(f"  Remaining bytes: {remaining}")
            
            # Let's manually list all the 8-byte values after the count
            print(f"\n  All 8-byte values after count:")
            for i in range(0, remaining, 8):
                if 4 + i + 8 > len(res_data):
                    break
                val = struct.unpack('<Q', res_data[4+i:4+i+8])[0]
                # Check if it's a known type (type-hash table, Data/FINDINGS.txt)
                if val == 0x712D6E3DD1024C9C:
                    label = " <- ugg TYPE"
                elif val == 0xCD4238C6A0C69E32:
                    label = " <- texture TYPE"
                elif val == 0xEAC0B497876ADEDF:
                    label = " <- material TYPE"
                elif val == 0xE0A48D0BE9A7453F:
                    label = " <- unit TYPE"
                elif val == 0xA14E8DFA2CD117E2:
                    label = " <- lua TYPE"
                elif val == 0x76015845A6003765:
                    label = " <- xml TYPE"
                elif val == 0xAD9C6D9ED1E5E77A:
                    label = " <- package TYPE"
                elif val == 0x18DEAD01056B72E9:
                    label = " <- bones TYPE"
                elif val == 0xA486D4045106165C:
                    label = " <- state_machine TYPE"
                elif (val & 0xFFFFFFFF) == 0x00000002:
                    label = " <- has 0x00000002 in low 32 bits"
                elif (val >> 32) == 0x82DE0B1B:
                    label = " <- has 0x82DE0B1B in high 32 bits"
                else:
                    label = ""
                print(f"    [{i//8:2d}] @0x{4+i:04X}: 0x{val:016X}{label}")
            
            # Let me also look at 4-byte values
            print(f"\n  All 4-byte values after count (looking for small ints):")
            for i in range(0, remaining, 4):
                if 4 + i + 4 > len(res_data):
                    break
                val = struct.unpack('<I', res_data[4+i:4+i+4])[0]
                if val < 100:  # small integers are interesting
                    print(f"    @0x{4+i:04X}: {val}")
            
            # NEW: Try 4-byte aligned parsing
            # Pattern seems to be: type(8) + name(8) + count(4) + (some 8 or 12 byte struct)*count
            # Then next entry...
            print(f"\n  === 4-BYTE ALIGNED PARSING ===")
            poff = 4
            entry_num = 0
            while poff + 20 <= len(res_data) and entry_num < 10:
                e_type = struct.unpack('<Q', res_data[poff:poff+8])[0]
                e_name = struct.unpack('<Q', res_data[poff+8:poff+16])[0]
                e_count = struct.unpack('<I', res_data[poff+16:poff+20])[0]
                
                # Type lookup from the known type-hash table
                type_names = {
                    0x712D6E3DD1024C9C: "ugg",
                    0xCD4238C6A0C69E32: "texture",
                    0xEAC0B497876ADEDF: "material",
                    0xE0A48D0BE9A7453F: "unit",
                    0xA14E8DFA2CD117E2: "lua",
                    0x76015845A6003765: "xml",
                    0xAD9C6D9ED1E5E77A: "package",
                    0x18DEAD01056B72E9: "bones",
                    0xA486D4045106165C: "state_machine",
                    0x931E336D7646CC26: "animation",
                    0x8FD0D44D20650B68: "data",
                    0x82645835E6B73232: "config",
                    0x92D3EE038EEB610D: "flow",
                }
                t_name = type_names.get(e_type, f"0x{e_type:016X}")
                
                # Sanity check - if count is huge, we're misaligned
                if e_count > 50:
                    print(f"  [{entry_num}] at 0x{poff:04X}: MISALIGNED (count={e_count})")
                    break
                
                print(f"  [{entry_num}] at 0x{poff:04X}: type={t_name}, name=0x{e_name:016X}, sub_count={e_count}")
                poff += 20  # type(8) + name(8) + count(4)
                
                # Read sub-references
                for s in range(e_count):
                    if poff + 8 > len(res_data):
                        print(f"      [truncated]")
                        break
                    sub_val = struct.unpack('<Q', res_data[poff:poff+8])[0]
                    sub_type = type_names.get(sub_val, None)
                    if sub_type:
                        print(f"      sub[{s}]: {sub_type} (0x{sub_val:016X})")
                    else:
                        # Check if upper 32 bits is 0x82DE0B1B
                        if (sub_val >> 32) == 0x82DE0B1B:
                            lower = sub_val & 0xFFFFFFFF
                            print(f"      sub[{s}]: 0x82DE0B1B + 0x{lower:08X}")
                        else:
                            print(f"      sub[{s}]: 0x{sub_val:016X}")
                    poff += 8
                
                entry_num += 1
            
            print(f"\n  Final position: 0x{poff:04X} / 0x{len(res_data):04X}")
        
        # Only show first 2 packages
        if i >= 1:
            break
    
    offset += 36 + main_size
