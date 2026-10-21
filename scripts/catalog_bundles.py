#!/usr/bin/env python3
"""
Catalog all bundles and their textures in the Gauntlet contents folder.

Usage:
    python catalog_bundles.py [contents_folder]
    python catalog_bundles.py --output catalog.txt

Creates a human-readable catalog of all bundles and their contents.
"""

import sys
import os
import struct

# Add current directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

# Resource type hashes.
#
# The authoritative list of type NAMES is in list_game_bundles.py - taken verbatim from
# the engine's null-separated type-name string table inside binaries/gauntlet.exe - and
# a type's hash is murmur64A(name, seed=0).  So DERIVE it instead of hardcoding it.
# This used to be a hardcoded table built from earlier guesses, and it was wrong for 14
# of its 15 entries: it called 0x2a690fd348fe9ac5 "material" when that is "level", and
# "unit", "package", "shading_environment", "strings", "render_config" and
# "state_machine" were wrong too.  Re-derive the whole table in one line:
#     python3 -c "from list_game_bundles import TYPE_NAMES as T; from bundle_tools import
#     murmur_hash64 as m; print({f'0x{m(t):016x}': t for t in T})"
from list_game_bundles import TYPE_HASH_TO_NAME

RESOURCE_TYPES = TYPE_HASH_TO_NAME

def analyze_bundle(bundle_path):
    """Analyze a bundle and return info about its contents."""
    try:
        with open(bundle_path, 'rb') as f:
            compressed_data = f.read()
        
        # Decompress using bundle_tools
        data = decompress_bundle(compressed_data)
        
        if len(data) < 0x120:  # Need at least header + some entries
            return None
        
        # After decompression, first 4 bytes is resource count
        count = struct.unpack('<I', data[:4])[0]
        
        # Sanity check
        if count == 0 or count > 100000:
            return None
        
        # Resource index starts at 0x104, 16 bytes per entry (type_hash, name_hash)
        type_counts = {}
        texture_count = 0
        
        for i in range(count):
            pos = 0x104 + i * 16
            if pos + 16 > len(data):
                break
            
            type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
            
            type_name = RESOURCE_TYPES.get(type_hash, f"unknown_{type_hash:016x}")
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            if type_hash == 0xcd4238c6a0c69e32:  # texture
                texture_count += 1
        
        # Check for stream file
        stream_path = bundle_path + ".stream"
        has_stream = os.path.exists(stream_path)
        stream_size = os.path.getsize(stream_path) if has_stream else 0
        
        return {
            'path': bundle_path,
            'name': os.path.basename(bundle_path),
            'compressed_size': len(compressed_data),
            'decompressed_size': len(data),
            'num_resources': count,
            'type_counts': type_counts,
            'texture_count': texture_count,
            'has_stream': has_stream,
            'stream_size': stream_size,
            'total_size': len(compressed_data) + stream_size
        }
    except Exception as e:
        print(f"  Error analyzing {bundle_path}: {e}")
        return None


def identify_bundle_purpose(bundle_info):
    """Try to identify what a bundle is for based on its contents."""
    type_counts = bundle_info['type_counts']
    
    hints = []
    
    if type_counts.get('texture', 0) > 100:
        hints.append("texture-heavy")
    
    if type_counts.get('lua', 0) > 50:
        hints.append("script-heavy")
    
    if type_counts.get('unit', 0) > 20:
        hints.append("many units")
    
    if type_counts.get('material', 0) > 30:
        hints.append("many materials")
    
    if bundle_info['has_stream']:
        hints.append("streaming")
    
    # Check texture ratio
    total = bundle_info['num_resources']
    tex_count = type_counts.get('texture', 0)
    if total > 0 and tex_count > 0:
        tex_ratio = tex_count / total
        if tex_ratio > 0.8:
            hints.append("mostly textures")
        elif tex_ratio > 0.5:
            hints.append("texture-dominant")
    
    return hints


def main():
    # Find contents folder
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        contents_folder = sys.argv[1]
    else:
        contents_folder = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"
    
    if not os.path.exists(contents_folder):
        print(f"Error: Contents folder not found: {contents_folder}")
        sys.exit(1)
    
    # Output file
    output_file = None
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_file = sys.argv[i + 1]
    
    print(f"Cataloging bundles in: {contents_folder}")
    print()
    
    # Find all bundles (files without extension, or specific patterns)
    bundles = []
    for filename in os.listdir(contents_folder):
        filepath = os.path.join(contents_folder, filename)
        if os.path.isfile(filepath) and not filename.endswith('.stream') and not filename.endswith('.backup'):
            bundles.append(filepath)
    
    print(f"Found {len(bundles)} potential bundle files")
    print()
    
    results = []
    for i, bundle_path in enumerate(sorted(bundles)):
        name = os.path.basename(bundle_path)
        print(f"[{i+1}/{len(bundles)}] Analyzing {name}...", end=" ", flush=True)
        
        info = analyze_bundle(bundle_path)
        if info:
            results.append(info)
            tex = info['texture_count']
            total = info['num_resources']
            stream = " [STREAM]" if info['has_stream'] else ""
            print(f"{total} resources, {tex} textures{stream}")
        else:
            print("(not a bundle or empty)")
    
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    # Sort by texture count
    results.sort(key=lambda x: x['texture_count'], reverse=True)
    
    total_textures = sum(r['texture_count'] for r in results)
    total_size = sum(r['total_size'] for r in results)
    
    print(f"\nTotal bundles: {len(results)}")
    print(f"Total textures: {total_textures}")
    print(f"Total size: {total_size / (1024*1024):.1f} MB")
    print()
    
    # Top bundles by texture count
    print("Top bundles by texture count:")
    print("-" * 60)
    for info in results[:15]:
        tex = info['texture_count']
        stream = "*" if info['has_stream'] else " "
        size_mb = info['total_size'] / (1024*1024)
        hints = identify_bundle_purpose(info)
        hint_str = f" ({', '.join(hints)})" if hints else ""
        print(f"  {stream}{info['name']}: {tex:4d} textures, {size_mb:6.1f} MB{hint_str}")
    
    # Resource type summary
    print()
    print("Resource types across all bundles:")
    print("-" * 60)
    all_types = {}
    for info in results:
        for type_name, count in info['type_counts'].items():
            all_types[type_name] = all_types.get(type_name, 0) + count
    
    for type_name, count in sorted(all_types.items(), key=lambda x: -x[1]):
        print(f"  {type_name}: {count}")
    
    # Write to file if requested
    if output_file:
        with open(output_file, 'w') as f:
            f.write("GAUNTLET BUNDLE CATALOG\n")
            f.write("=" * 60 + "\n\n")
            
            for info in results:
                f.write(f"Bundle: {info['name']}\n")
                f.write(f"  Size: {info['compressed_size']:,} bytes (compressed)\n")
                f.write(f"  Size: {info['decompressed_size']:,} bytes (decompressed)\n")
                if info['has_stream']:
                    f.write(f"  Stream: {info['stream_size']:,} bytes\n")
                f.write(f"  Resources: {info['num_resources']}\n")
                f.write(f"  Types:\n")
                for type_name, count in sorted(info['type_counts'].items(), key=lambda x: -x[1]):
                    f.write(f"    {type_name}: {count}\n")
                f.write("\n")
        
        print(f"\nFull catalog written to: {output_file}")


if __name__ == "__main__":
    main()
