import struct
import zlib
import os

def decompress_bundle(file_path):
    """Decompress a Bitsquid bundle file"""
    with open(file_path, 'rb') as f:
        data = f.read()
    
    sig = struct.unpack('<I', data[0:4])[0]
    if sig != 0xF0000004:
        raise ValueError(f'Invalid signature: 0x{sig:08X}')
    
    uncompressed_size = struct.unpack('<I', data[4:8])[0]
    
    result = bytearray()
    offset = 8
    
    while offset < len(data) and len(result) < uncompressed_size:
        if offset + 4 > len(data):
            break
            
        val = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        
        if val == 0:
            if offset + 4 > len(data):
                break
            chunk_size = struct.unpack('<I', data[offset:offset+4])[0]
            offset += 4
        else:
            chunk_size = val
        
        if offset >= len(data):
            break
            
        if data[offset:offset+2] == b'\x78\x9c' or data[offset:offset+2] == b'\x78\xda':
            try:
                chunk = zlib.decompress(data[offset:offset+chunk_size])
                result.extend(chunk)
                offset += chunk_size
            except Exception as e:
                break
        else:
            break
    
    return bytes(result)

TYPE_PACKAGE = 0xAD9C6D9ED1E5E77A
TYPE_TEXTURE = 0xCD4238C6A0C69E32

def parse_bundle(decompressed):
    res_count = struct.unpack('<I', decompressed[0:4])[0]
    entry_table_offset = 0x104
    data_section_offset = entry_table_offset + res_count * 16
    
    resources = []
    offset = data_section_offset
    
    for i in range(res_count):
        type_hash = struct.unpack('<Q', decompressed[offset:offset+8])[0]
        name_hash = struct.unpack('<Q', decompressed[offset+8:offset+16])[0]
        main_size = struct.unpack('<I', decompressed[offset+28:offset+32])[0]
        
        data = decompressed[offset+36:offset+36+main_size]
        resources.append({
            'type_hash': type_hash,
            'name_hash': name_hash,
            'data': data,
        })
        offset += 36 + main_size
    
    return resources

# Verify our new bundle's package resource
bundle_path = "path/to/a/bundle/file"   # pass a real bundle to verify

print("=== VERIFYING NEW BUNDLE (local) ===\n")

decompressed = decompress_bundle(bundle_path)
print(f"Decompressed size: {len(decompressed)} bytes")

# Parse header
res_count = struct.unpack('<I', decompressed[0:4])[0]
print(f"Resource count: {res_count}")

# Entry table at 0x104
entry_table_offset = 0x104
data_section_offset = entry_table_offset + res_count * 16

# Read first entry type hash
first_type = struct.unpack('<Q', decompressed[entry_table_offset:entry_table_offset+8])[0]
print(f"\nFirst entry type hash: 0x{first_type:016X}")
print(f"TYPE_TEXTURE = 0x{TYPE_TEXTURE:016X}")
print(f"TYPE_PACKAGE = 0x{TYPE_PACKAGE:016X}")

# Check if our entry table looks correct
print(f"\nEntry table analysis:")
texture_count = 0
package_count = 0
other_count = 0

for i in range(res_count):
    off = entry_table_offset + i * 16
    type_hash = struct.unpack('<Q', decompressed[off:off+8])[0]
    if type_hash == TYPE_TEXTURE:
        texture_count += 1
    elif type_hash == TYPE_PACKAGE:
        package_count += 1
        print(f"  Package at index {i}")
    else:
        other_count += 1
        if other_count <= 3:
            print(f"  Unknown type at index {i}: 0x{type_hash:016X}")

print(f"\nTexture resources: {texture_count}")
print(f"Package resources: {package_count}")
print(f"Other resources: {other_count}")

# If we found a package, get its data
for i in range(res_count):
    off = entry_table_offset + i * 16
    type_hash = struct.unpack('<Q', decompressed[off:off+8])[0]
    name_hash = struct.unpack('<Q', decompressed[off+8:off+16])[0]
    
    if type_hash == TYPE_PACKAGE:
        print(f"\n=== PACKAGE DETAILS ===")
        print(f"Package name hash: 0x{name_hash:016X}")
        
        # Find data offset
        data_off = data_section_offset
        for j in range(i):
            main_size = struct.unpack('<I', decompressed[data_off+28:data_off+32])[0]
            data_off += 36 + main_size
        
        main_size = struct.unpack('<I', decompressed[data_off+28:data_off+32])[0]
        pkg_data = decompressed[data_off+36:data_off+36+main_size]
        
        print(f"Package data at offset 0x{data_off:X}, size {main_size}")
        
        entry_count = struct.unpack('<I', pkg_data[0:4])[0]
        print(f"Package entry count: {entry_count}")
        
        # Show first few entries
        print(f"\nFirst 5 package entries (should have deps=0):")
        off2 = 4
        for k in range(min(5, entry_count)):
            type_h = struct.unpack('<Q', pkg_data[off2:off2+8])[0]
            name_h = struct.unpack('<Q', pkg_data[off2+8:off2+16])[0]
            dep_cnt = struct.unpack('<I', pkg_data[off2+16:off2+20])[0]
            
            type_name = "TEXTURE" if type_h == TYPE_TEXTURE else "other"
            print(f"  Entry {k}: type={type_name} deps={dep_cnt}")
            off2 += 20 + dep_cnt * 4
        
        break
