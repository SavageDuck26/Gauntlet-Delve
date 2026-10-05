import struct, zlib, os

# Parse a bundle properly and extract material data
def decompress_bundle(path):
    with open(path, 'rb') as f:
        data = f.read()
    
    chunks = []
    pos = 12
    while pos < len(data):
        chunk_len = struct.unpack('<I', data[pos:pos+4])[0]
        pos += 4
        chunks.append(zlib.decompress(data[pos:pos+chunk_len]))
        pos += chunk_len
    return b''.join(chunks)

TYPE_MATERIAL = 0xEAC0B497876ADEDF
TYPE_TEXTURE = 0xCD4238C6A0C69E32

def murmur_hash64(key):
    seed = 0
    m = 0xC6A4A7935BD1E995
    r = 47
    h = seed ^ (len(key) * m) & 0xFFFFFFFFFFFFFFFF
    data = key.encode('latin-1') if isinstance(key, str) else key
    length = len(data)
    i = 0
    while i + 8 <= length:
        k = struct.unpack('<Q', data[i:i+8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
        i += 8
    remaining = length - i
    if remaining > 0:
        for j in range(remaining):
            h ^= data[i + j] << (j * 8)
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    return h

# Look at real material resources in bundles 
content_dir = r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents'

# Try several material paths
material_paths = [
    "menu/menu",
    "foundation/gui/gui",
    "hud/hud",
    "menu/standard_elements",
]

for mat_path in material_paths:
    target_hash = murmur_hash64(mat_path)
    print(f"\nLooking for {mat_path} (hash: 0x{target_hash:016X})")
    
    found_material = None

    for fname in os.listdir(content_dir):
        if fname.endswith('.stream'):
            continue
        fpath = os.path.join(content_dir, fname)
        if os.path.getsize(fpath) < 100:
            continue
        try:
            unpacked = decompress_bundle(fpath)
            count = struct.unpack('<I', unpacked[:4])[0]
            if count > 1000:
                continue
            
            entry_start = 4 + count * 8
            data_start = entry_start + count * 36
            
            # Parse resources
            offset = data_start
            for i in range(count):
                pos = entry_start + i * 36
                type_h = struct.unpack('<Q', unpacked[pos:pos+8])[0]
                name_h = struct.unpack('<Q', unpacked[pos+8:pos+16])[0]
                flags = struct.unpack('<I', unpacked[pos+16:pos+20])[0]
                stream_size = struct.unpack('<Q', unpacked[pos+20:pos+28])[0]
                main_size = struct.unpack('<I', unpacked[pos+28:pos+32])[0]
                
                if type_h == TYPE_MATERIAL and name_h == target_hash:
                    print(f"  Found in bundle: {fname}")
                    print(f"    Stream size: {stream_size}, Main size: {main_size}")
                    found_material = (fname, offset, main_size)
                    break
                
                offset += stream_size + main_size
            
            if found_material:
                break
                
        except Exception as e:
            continue
    
    if not found_material:
        print(f"  NOT FOUND")

# Now let's find ANY material and examine it
print("\n\nLooking for ANY material resource...")
for fname in os.listdir(content_dir)[:30]:
    if fname.endswith('.stream'):
        continue
    fpath = os.path.join(content_dir, fname)
    if os.path.getsize(fpath) < 100:
        continue
    try:
        unpacked = decompress_bundle(fpath)
        count = struct.unpack('<I', unpacked[:4])[0]
        if count > 1000:
            continue
        
        entry_start = 4 + count * 8
        data_start = entry_start + count * 36
        
        offset = data_start
        for i in range(count):
            pos = entry_start + i * 36
            type_h = struct.unpack('<Q', unpacked[pos:pos+8])[0]
            name_h = struct.unpack('<Q', unpacked[pos+8:pos+16])[0]
            stream_size = struct.unpack('<Q', unpacked[pos+20:pos+28])[0]
            main_size = struct.unpack('<I', unpacked[pos+28:pos+32])[0]
            
            if type_h == TYPE_MATERIAL and main_size > 0 and main_size < 10000:
                mat_data = unpacked[offset:offset+main_size]
                if len(mat_data) >= 48:  # Ensure we have enough data
                    print(f"Found material in {fname}")
                    print(f"  Name hash: 0x{name_h:016X}")
                    print(f"  Size: {main_size} bytes")
                    print(f"  First 100 bytes:")
                    for j in range(0, min(100, len(mat_data)), 16):
                        hex_str = ' '.join(f'{b:02X}' for b in mat_data[j:j+16])
                        ascii_str = ''.join(chr(b) if 32<=b<127 else '.' for b in mat_data[j:j+16])
                        print(f'    {j:04X}: {hex_str:<48} {ascii_str}')
                    
                    # Quick structure analysis
                    if len(mat_data) >= 4:
                        version = struct.unpack('<I', mat_data[:4])[0]
                        print(f"  Version/Magic: 0x{version:08X}")
                    raise SystemExit()  # Stop after finding one
            
            offset += stream_size + main_size
            
    except SystemExit:
        raise
    except Exception as e:
        continue
