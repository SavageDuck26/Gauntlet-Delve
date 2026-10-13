"""Diagnose texture issues in bundles."""
import struct
import sys
from bundle_tools import decompress_bundle

def diagnose(bundle_path, name_hash_hex):
    """Check original and current texture data."""
    name_hash = int(name_hash_hex, 16)
    
    # Try to find backup
    backup_path = bundle_path + ".backup"
    try:
        with open(backup_path, 'rb') as f:
            orig_packed = f.read()
        print(f"Reading backup: {backup_path}")
        orig_data = decompress_bundle(orig_packed)
    except FileNotFoundError:
        print(f"No backup found at {backup_path}")
        orig_data = None
    
    # Read current
    with open(bundle_path, 'rb') as f:
        curr_packed = f.read()
    print(f"Reading current: {bundle_path}")
    curr_data = decompress_bundle(curr_packed)
    
    def find_texture(data, label):
        count = struct.unpack('<I', data[:4])[0]
        
        # Build entry set
        entry_set = set()
        for i in range(count):
            th, nh = struct.unpack('<QQ', data[0x104+i*16:0x104+i*16+16])
            entry_set.add((th, nh))
            if nh == name_hash:
                print(f"\n{label}: Found 0x{name_hash:016x} in entry table")
        
        # Find resource
        pos = 0x104 + count * 16
        while pos + 36 < len(data):
            th, nh = struct.unpack('<QQ', data[pos:pos+16])
            if (th, nh) in entry_set:
                flags, stream_size, main_size, unk = struct.unpack('<IQII', data[pos+16:pos+36])
                if nh == name_hash:
                    tex_data = data[pos+36:pos+36+main_size]
                    print(f"{label}: Offset=0x{pos:x}, flags={flags}, stream_size={stream_size}, main_size={main_size}")
                    print(f"{label}: Texture data size: {len(tex_data)} bytes")
                    
                    # Check if it looks like a DDS
                    if tex_data[:4] == b'DDS ':
                        print(f"{label}: HAS DDS HEADER (embedded)")
                        # Parse DDS
                        height, width = struct.unpack('<II', tex_data[12:20])
                        fourcc = tex_data[84:88]
                        print(f"{label}: Embedded DDS: {width}x{height} {fourcc}")
                    else:
                        print(f"{label}: Raw texture data (no DDS header in bundle)")
                        print(f"{label}: First 64 bytes: {tex_data[:64].hex()}")
                    
                    return tex_data
                pos += 36 + main_size
            else:
                pos += 1
        
        print(f"{label}: Texture not found!")
        return None
    
    if orig_data:
        orig_tex = find_texture(orig_data, "ORIGINAL")
    
    curr_tex = find_texture(curr_data, "CURRENT")
    
    # Also check the user's replacement DDS
    print("\n--- Checking user's replacement file ---")
    try:
        repl_path = f"my_textures/1bbcb9610a009446/{name_hash_hex}.dds"
        with open(repl_path, 'rb') as f:
            repl_data = f.read()
        print(f"Replacement file: {repl_path}")
        print(f"File size: {len(repl_data)} bytes")
        if repl_data[:4] == b'DDS ':
            height, width = struct.unpack('<II', repl_data[12:20])
            fourcc = repl_data[84:88]
            print(f"DDS: {width}x{height} {fourcc}")
            print(f"First 128 bytes: {repl_data[:128].hex()}")
        else:
            print(f"NOT A DDS FILE! First 16 bytes: {repl_data[:16].hex()}")
    except Exception as e:
        print(f"Error reading replacement: {e}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python diagnose_texture.py <bundle_path> <name_hash>")
        print("Example: python diagnose_texture.py bundle.bin ac62dce0c2998776")
        sys.exit(1)
    
    diagnose(sys.argv[1], sys.argv[2])
