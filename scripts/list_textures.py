"""
List all textures in a Gauntlet bundle.

Usage:
    python list_textures.py <bundle_path>
    
Outputs texture hashes that can be used with replace_textures_v2.py
"""

import struct
import sys
import os

# Add parent directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

TEXTURE_TYPE_HASH = 0xCD4238C6A0C69E32


def list_textures(bundle_path):
    """List all textures in a bundle."""
    
    # Load and decompress
    with open(bundle_path, 'rb') as f:
        packed = f.read()
    
    data = decompress_bundle(packed)
    count = struct.unpack('<I', data[:4])[0]
    
    # Build header entry set
    header_entries = set()
    for i in range(count):
        pos = 0x104 + i * 16
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        header_entries.add((type_hash, name_hash))
    
    # Parse resources
    textures = []
    pos = 0x104 + count * 16
    
    while pos + 36 <= len(data):
        type_hash, name_hash, flags = struct.unpack('<QQI', data[pos:pos+20])
        
        if (type_hash, name_hash) not in header_entries:
            pos += 1
            continue
        
        stream_size = struct.unpack('<Q', data[pos+20:pos+28])[0]
        main_size = struct.unpack('<I', data[pos+28:pos+32])[0]
        
        if type_hash == TEXTURE_TYPE_HASH:
            # Parse DDS header
            dds_data = data[pos+36:pos+36+main_size]
            if dds_data[:4] == b'DDS ':
                height = struct.unpack('<I', dds_data[12:16])[0]
                width = struct.unpack('<I', dds_data[16:20])[0]
                mips = struct.unpack('<I', dds_data[28:32])[0]
                fourcc = dds_data[84:88].decode('ascii', errors='replace')
                
                textures.append({
                    'hash': name_hash,
                    'width': width,
                    'height': height,
                    'mips': mips,
                    'format': fourcc,
                    'size': main_size,
                    'streaming': stream_size > 0
                })
        
        pos += 36 + main_size
    
    return textures


def main():
    if len(sys.argv) < 2:
        print("Usage: python list_textures.py <bundle_path>")
        return
    
    bundle_path = sys.argv[1]
    
    if not os.path.exists(bundle_path):
        print(f"Bundle not found: {bundle_path}")
        return
    
    print(f"Bundle: {bundle_path}")
    
    # Check for stream file
    stream_path = bundle_path + '.stream'
    has_stream = os.path.exists(stream_path)
    print(f"Has stream file: {has_stream}")
    print()
    
    textures = list_textures(bundle_path)
    
    print(f"Found {len(textures)} textures:\n")
    print(f"{'Hash':<18} {'Size':>10} {'Dims':>12} {'Mips':>5} {'Format':>6} {'Streaming':>9}")
    print("-" * 70)
    
    for tex in sorted(textures, key=lambda t: t['size'], reverse=True):
        dims = f"{tex['width']}x{tex['height']}"
        print(f"{tex['hash']:016x}   {tex['size']:>8}   {dims:>10}   {tex['mips']:>3}   {tex['format']:>6}   {'Yes' if tex['streaming'] else 'No':>7}")
    
    print()
    print("To replace textures, create DDS files named <hash>.dds in a folder")
    print("and run: python replace_textures_v2.py <bundle> <folder>")


if __name__ == '__main__':
    main()
