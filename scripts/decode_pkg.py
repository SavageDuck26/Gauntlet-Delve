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

def parse_package(pkg_data):
    entry_count = struct.unpack('<I', pkg_data[0:4])[0]
    entries = []
    
    off = 4
    for i in range(entry_count):
        if off + 20 > len(pkg_data):
            break
        type_h = struct.unpack('<Q', pkg_data[off:off+8])[0]
        name_h = struct.unpack('<Q', pkg_data[off+8:off+16])[0]
        dep_cnt = struct.unpack('<I', pkg_data[off+16:off+20])[0]
        
        deps = []
        for d in range(dep_cnt):
            if off + 20 + (d+1)*4 > len(pkg_data):
                break
            dep = struct.unpack('<I', pkg_data[off+20+d*4:off+24+d*4])[0]
            deps.append(dep)
        
        entries.append({'type_hash': type_h, 'name_hash': name_h, 'deps': deps})
        off += 20 + dep_cnt * 4
    
    return entries

# Look for packages that contain textures with minimal/no dependencies
contents_path = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"

print("=== SEARCHING FOR TEXTURE ENTRIES WITH 0 DEPS ===\n")

bundles_to_check = []
for f in os.listdir(contents_path):
    full_path = os.path.join(contents_path, f)
    if os.path.isfile(full_path) and not f.endswith('.stream'):
        size = os.path.getsize(full_path)
        if 5000 < size < 10000000:
            bundles_to_check.append((full_path, size))

found = False
for bundle_path, size in bundles_to_check:
    try:
        decompressed = decompress_bundle(bundle_path)
        resources = parse_bundle(decompressed)
        
        for res in resources:
            if res['type_hash'] == TYPE_PACKAGE:
                entries = parse_package(res['data'])
                texture_entries = [e for e in entries if e['type_hash'] == TYPE_TEXTURE]
                
                # Look for textures with 0 deps
                zero_dep_textures = [e for e in texture_entries if len(e['deps']) == 0]
                
                if zero_dep_textures:
                    print(f"FOUND in {os.path.basename(bundle_path)}:")
                    print(f"  {len(zero_dep_textures)} textures with 0 deps")
                    for t in zero_dep_textures[:3]:
                        print(f"    0x{t['name_hash']:016X}")
                    found = True
                    break
        
        if found:
            break
            
    except:
        continue

if not found:
    print("No textures with 0 deps found")
    print("\nLet's check what the dep_count=3 entries look like in detail...")
    
    # Check a package with dep_count=3 textures
    bundle_path = os.path.join(contents_path, "ec33816f62983aac")
    decompressed = decompress_bundle(bundle_path)
    resources = parse_bundle(decompressed)
    
    for res in resources:
        if res['type_hash'] == TYPE_PACKAGE:
            entries = parse_package(res['data'])
            texture_entries = [e for e in entries if e['type_hash'] == TYPE_TEXTURE]
            three_dep = [e for e in texture_entries if len(e['deps']) == 3]
            
            print(f"\nTextures with exactly 3 deps ({len(three_dep)}):")
            for t in three_dep[:5]:
                print(f"  name=0x{t['name_hash']:016X}")
                print(f"    deps: {[f'0x{d:08X}' for d in t['deps']]}")
            break
