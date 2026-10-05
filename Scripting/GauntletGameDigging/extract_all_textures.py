#!/usr/bin/env python3
"""
Extract ALL textures from ALL bundles in the Gauntlet contents folder.

Usage:
    python extract_all_textures.py [contents_folder] [output_folder]

Defaults:
    contents_folder: C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents
    output_folder: extracted_all

This creates a folder structure like:
    extracted_all/
        0164ad48615ba9ed/
            005e510d595d16ec.dds
            00a89af8035f7f07.dds
            ...
        07c9b8511b5aff2e/
            01f03948e18b4899.dds
            ...
        ...
        _index.txt          <- Master index of all textures
        _by_size.txt        <- Textures sorted by size (largest first)

After extraction, browse the folders to find textures you want to replace.
"""

import sys
import os
import struct

# Add current directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

TEXTURE_TYPE = 0xCD4238C6A0C69E32


def extract_textures_from_bundle(bundle_path, output_folder):
    """Extract all textures from a single bundle. Returns list of texture info."""
    bundle_name = os.path.basename(bundle_path)
    textures = []
    
    try:
        with open(bundle_path, 'rb') as f:
            packed_data = f.read()
        
        data = decompress_bundle(packed_data)
        
        if len(data) < 0x120:
            return textures
        
        count = struct.unpack('<I', data[:4])[0]
        if count == 0 or count > 100000:
            return textures
        
        # Build entry set
        entry_set = set()
        for i in range(count):
            pos = 0x104 + i * 16
            if pos + 16 > len(data):
                break
            type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
            entry_set.add((type_hash, name_hash))
        
        # Create output folder for this bundle
        bundle_output = os.path.join(output_folder, bundle_name)
        os.makedirs(bundle_output, exist_ok=True)
        
        # Parse and extract textures
        pos = 0x104 + count * 16
        while pos + 36 <= len(data):
            type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
            if (type_hash, name_hash) not in entry_set:
                pos += 1
                continue
            
            flags, stream_size, main_size, unk = struct.unpack('<IQII', data[pos+16:pos+36])
            
            if type_hash == TEXTURE_TYPE:
                hash_str = f"{name_hash:016x}"
                dds_data = data[pos+36:pos+36+main_size]
                
                if dds_data[:4] == b'DDS ':
                    # Parse DDS header
                    h, w = struct.unpack('<II', dds_data[12:20])
                    mips = struct.unpack('<I', dds_data[28:32])[0]
                    fourcc = dds_data[84:88]
                    
                    try:
                        fmt_name = fourcc.decode('ascii').strip('\x00')
                    except:
                        fmt_name = "RGB32" if fourcc == b'\x00\x00\x00\x00' else "UNK"
                    if not fmt_name:
                        fmt_name = "RGB32"
                    
                    # Save DDS file
                    output_path = os.path.join(bundle_output, f"{hash_str}.dds")
                    with open(output_path, 'wb') as f:
                        f.write(dds_data)
                    
                    textures.append({
                        'bundle': bundle_name,
                        'hash': hash_str,
                        'width': w,
                        'height': h,
                        'format': fmt_name,
                        'mips': mips,
                        'size': len(dds_data),
                    })
            
            pos += 36 + main_size
        
    except Exception as e:
        print(f"  Error: {e}")
    
    return textures


def main():
    # Parse arguments
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        contents_folder = sys.argv[1]
    else:
        contents_folder = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"
    
    if len(sys.argv) > 2:
        output_folder = sys.argv[2]
    else:
        output_folder = "extracted_all"
    
    if not os.path.exists(contents_folder):
        print(f"Error: Contents folder not found: {contents_folder}")
        sys.exit(1)
    
    print(f"Extracting all textures from: {contents_folder}")
    print(f"Output folder: {output_folder}")
    print()
    
    # Find all bundles
    bundles = []
    for filename in os.listdir(contents_folder):
        filepath = os.path.join(contents_folder, filename)
        if os.path.isfile(filepath) and not filename.endswith(('.stream', '.backup', '.ini', '.data')):
            bundles.append(filepath)
    
    print(f"Found {len(bundles)} potential bundles")
    print()
    
    os.makedirs(output_folder, exist_ok=True)
    
    all_textures = []
    
    for i, bundle_path in enumerate(sorted(bundles)):
        name = os.path.basename(bundle_path)
        print(f"[{i+1}/{len(bundles)}] {name}...", end=" ", flush=True)
        
        textures = extract_textures_from_bundle(bundle_path, output_folder)
        all_textures.extend(textures)
        
        if textures:
            print(f"{len(textures)} textures")
        else:
            print("no textures")
    
    print()
    print("=" * 60)
    print(f"COMPLETE: Extracted {len(all_textures)} textures")
    print("=" * 60)
    
    # Write master index
    index_path = os.path.join(output_folder, "_index.txt")
    with open(index_path, 'w') as f:
        f.write("GAUNTLET TEXTURE INDEX\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total textures: {len(all_textures)}\n\n")
        f.write("Format: bundle/hash.dds | dimensions | format | size\n")
        f.write("-" * 80 + "\n\n")
        
        # Group by bundle
        by_bundle = {}
        for tex in all_textures:
            bundle = tex['bundle']
            if bundle not in by_bundle:
                by_bundle[bundle] = []
            by_bundle[bundle].append(tex)
        
        for bundle in sorted(by_bundle.keys()):
            textures = by_bundle[bundle]
            f.write(f"\n=== {bundle} ({len(textures)} textures) ===\n\n")
            for tex in sorted(textures, key=lambda t: -t['width'] * t['height']):
                f.write(f"  {tex['hash']}.dds  {tex['width']:4d}x{tex['height']:<4d}  {tex['format']:5s}  {tex['size']:,} bytes\n")
    
    print(f"Created index: {index_path}")
    
    # Write size-sorted index
    size_path = os.path.join(output_folder, "_by_size.txt")
    with open(size_path, 'w') as f:
        f.write("GAUNTLET TEXTURES BY SIZE (largest first)\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total textures: {len(all_textures)}\n\n")
        f.write("Use this to find the biggest/most important textures\n")
        f.write("-" * 80 + "\n\n")
        
        for tex in sorted(all_textures, key=lambda t: -t['width'] * t['height']):
            f.write(f"{tex['bundle']}/{tex['hash']}.dds  {tex['width']:4d}x{tex['height']:<4d}  {tex['format']:5s}\n")
    
    print(f"Created size index: {size_path}")
    
    # Summary by dimensions
    print()
    print("Texture dimensions summary:")
    by_dims = {}
    for tex in all_textures:
        dims = f"{tex['width']}x{tex['height']}"
        by_dims[dims] = by_dims.get(dims, 0) + 1
    
    for dims, count in sorted(by_dims.items(), key=lambda x: -x[1])[:15]:
        print(f"  {dims}: {count}")
    
    print()
    print(f"Browse textures in: {os.path.abspath(output_folder)}")
    print()
    print("To replace specific textures:")
    print("  1. Find textures you want to replace in the extracted folders")
    print("  2. Create a folder with your replacement DDS files (same hash names)")
    print("  3. Run: python replace_textures_v4.py <bundle_path> <your_folder>")


if __name__ == "__main__":
    main()
