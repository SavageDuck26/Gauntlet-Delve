#!/usr/bin/env python3
"""Analyze how stream files relate to bundle textures."""

import struct
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

TEXTURE_TYPE = 0xCD4238C6A0C69E32

def analyze_bundle_with_stream(bundle_path):
    """Analyze a bundle that has a .stream file."""
    with open(bundle_path, 'rb') as f:
        data = decompress_bundle(f.read())
    
    stream_path = bundle_path + '.stream'
    with open(stream_path, 'rb') as f:
        stream = f.read()
    
    print(f"Bundle: {len(data):,} bytes (decompressed)")
    print(f"Stream: {len(stream):,} bytes")
    
    # Parse header
    count = struct.unpack('<I', data[:4])[0]
    print(f"Resources: {count}")
    
    # Build entry set
    entry_set = set()
    for i in range(count):
        pos = 0x104 + i * 16
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        entry_set.add((type_hash, name_hash))
    
    # Find textures
    pos = 0x104 + count * 16
    textures = []
    stream_offset = 0
    
    while pos + 36 <= len(data):
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        if (type_hash, name_hash) not in entry_set:
            pos += 1
            continue
        
        flags, stream_size, main_size, unk = struct.unpack('<IQII', data[pos+16:pos+36])
        
        if type_hash == TEXTURE_TYPE:
            dds_data = data[pos+36:pos+36+main_size]
            
            if dds_data[:4] == b'DDS ':
                h, w = struct.unpack('<II', dds_data[12:20])
                mips = struct.unpack('<I', dds_data[28:32])[0]
                fourcc = dds_data[84:88]
                
                # Calculate expected stream offset
                textures.append({
                    'name_hash': name_hash,
                    'flags': flags,
                    'stream_size': stream_size,
                    'main_size': main_size,
                    'width': w,
                    'height': h,
                    'mips': mips,
                    'fourcc': fourcc,
                    'stream_offset': stream_offset if stream_size > 0 else None,
                })
                
                if stream_size > 0:
                    stream_offset += stream_size
        
        pos += 36 + main_size
    
    print(f"\nTextures with stream data: {sum(1 for t in textures if t['stream_size'] > 0)}")
    print(f"Textures main-only: {sum(1 for t in textures if t['stream_size'] == 0)}")
    
    # Show first 5 textures
    print("\n=== First 5 textures ===")
    for i, tex in enumerate(textures[:5]):
        print(f"\n{tex['name_hash']:016x}:")
        print(f"  Main: {tex['width']}x{tex['height']} {tex['fourcc']} {tex['mips']} mips ({tex['main_size']:,} bytes)")
        if tex['stream_size'] > 0:
            print(f"  Stream: {tex['stream_size']:,} bytes at offset {tex['stream_offset']:,}")
            # Check what's at the stream offset
            if tex['stream_offset'] + 128 <= len(stream):
                stream_start = stream[tex['stream_offset']:tex['stream_offset']+128]
                print(f"  Stream starts with: {stream_start[:16].hex()}")
                
                # Check if it's a DDS header
                if stream_start[:4] == b'DDS ':
                    sh, sw = struct.unpack('<II', stream_start[12:20])
                    sm = struct.unpack('<I', stream_start[28:32])[0]
                    sf = stream_start[84:88]
                    print(f"  Stream DDS: {sw}x{sh} {sf} {sm} mips")
    
    # Calculate total stream usage
    total_stream = sum(t['stream_size'] for t in textures)
    print(f"\nTotal stream_size in headers: {total_stream:,}")
    print(f"Actual stream file size: {len(stream):,}")
    
    return textures


def analyze_texture_and_stream(bundle_path):
    """Deep analyze first texture to understand stream format."""
    with open(bundle_path, 'rb') as f:
        data = decompress_bundle(f.read())
    
    stream_path = bundle_path + '.stream'
    with open(stream_path, 'rb') as f:
        stream = f.read()
    
    print(f"Bundle: {len(data):,} bytes")
    print(f"Stream: {len(stream):,} bytes")
    
    count = struct.unpack('<I', data[:4])[0]
    
    # Build entry set
    entry_set = set()
    for i in range(count):
        pos = 0x104 + i * 16
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        entry_set.add((type_hash, name_hash))
    
    # Find first texture
    pos = 0x104 + count * 16
    while pos + 36 <= len(data):
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        if (type_hash, name_hash) not in entry_set:
            pos += 1
            continue
        
        flags, stream_size, main_size, unk = struct.unpack('<IQII', data[pos+16:pos+36])
        
        if type_hash == TEXTURE_TYPE:
            dds_data = data[pos+36:pos+36+main_size]
            
            print(f'\n=== First Texture: {name_hash:016x} ===')
            print(f'Resource header bytes 16-36: {data[pos+16:pos+36].hex()}')
            print(f'  flags={flags}')
            print(f'  stream_size={stream_size:,}')
            print(f'  main_size={main_size:,}')
            print(f'  unk={unk}')
            
            if dds_data[:4] == b'DDS ':
                h, w = struct.unpack('<II', dds_data[12:20])
                mips = struct.unpack('<I', dds_data[28:32])[0]
                pitch = struct.unpack('<I', dds_data[20:24])[0]
                fourcc = dds_data[84:88]
                
                print(f'\nMain DDS: {w}x{h} {fourcc} {mips} mips')
                print(f'Main DDS size: {len(dds_data):,} (header 128 + data {len(dds_data)-128:,})')
                
                # Calculate expected full DDS size
                block_size = 8 if fourcc == b'DXT1' else 16
                expected_size = 128  # header
                tw, th = w, h
                for m in range(mips):
                    bw = max(1, (tw + 3) // 4)
                    bh = max(1, (th + 3) // 4)
                    expected_size += bw * bh * block_size
                    tw = max(1, tw // 2)
                    th = max(1, th // 2)
                print(f'Expected full DDS size: {expected_size:,}')
                print(f'Missing from main (expected in stream): {expected_size - len(dds_data):,}')
            
            break
        pos += 36 + main_size
    
    # Check stream file format
    print(f'\n=== Stream File ===')
    print(f'First 64 bytes: {stream[:64].hex()}')
    if stream[:4] == b'DDS ':
        print('Stream starts with DDS header!')
    else:
        print(f'First 4 bytes as text: {stream[:4]}')
        # Check if it looks like raw texture data (DXT blocks)
        print('Probably raw mipmap data (no DDS header)')


def analyze_texture_flags(bundle_path):
    """Analyze textures by flags."""
    with open(bundle_path, 'rb') as f:
        data = decompress_bundle(f.read())
    
    count = struct.unpack('<I', data[:4])[0]
    
    # Build entry set
    entry_set = set()
    for i in range(count):
        pos = 0x104 + i * 16
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        entry_set.add((type_hash, name_hash))
    
    # Collect textures by flags
    by_flags = {}
    pos = 0x104 + count * 16
    while pos + 36 <= len(data):
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        if (type_hash, name_hash) not in entry_set:
            pos += 1
            continue
        
        flags, stream_size, main_size, unk = struct.unpack('<IQII', data[pos+16:pos+36])
        
        if type_hash == TEXTURE_TYPE:
            dds_data = data[pos+36:pos+36+main_size]
            if dds_data[:4] == b'DDS ':
                h, w = struct.unpack('<II', dds_data[12:20])
                fourcc = dds_data[84:88]
                mips = struct.unpack('<I', dds_data[28:32])[0]
                
                if flags not in by_flags:
                    by_flags[flags] = []
                by_flags[flags].append({
                    'hash': name_hash,
                    'size': f'{w}x{h}',
                    'fmt': fourcc,
                    'mips': mips,
                    'main_size': main_size,
                    'stream_size': stream_size,
                })
        
        pos += 36 + main_size
    
    print("=== Textures by Flags ===")
    for flags in sorted(by_flags.keys()):
        textures = by_flags[flags]
        print(f"\nFlags={flags}: {len(textures)} textures")
        for t in textures[:3]:
            print(f"  {t['hash']:016x}: {t['size']} {t['fmt']} {t['mips']} mips, main={t['main_size']:,}")


if __name__ == "__main__":
    bundle_path = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\0164ad48615ba9ed"
    # analyze_bundle_with_stream(bundle_path)
    # analyze_texture_and_stream(bundle_path)
    analyze_texture_flags(bundle_path)
