#!/usr/bin/env python3
"""
Extract ALL textures from ALL bundles with proper names from hash database.

This is an improved version of extract_all_textures.py that uses the hash
database to give textures their proper names instead of raw hashes.

Usage:
    python extract_textures_named.py [contents_folder] [output_folder]

Defaults:
    contents_folder: C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents
    output_folder: extracted_named

This creates a folder structure like:
    extracted_named/
        by_name/
            characters/
                warrior/
                    warrior.dds
                    warrior_diffuse.dds
            gui/
                menu/
                    buttons.dds
            ...
        by_bundle/
            0164ad48615ba9ed/
                005e510d595d16ec.dds  (if no name found)
                ...
        _index.txt          <- Master index with names
        _unknown.txt        <- Textures without known names
"""

import sys
import os
import struct
import json
from pathlib import Path

# Add current directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

TEXTURE_TYPE = 0xCD4238C6A0C69E32


def load_hash_database() -> dict:
    """Load the hash-to-name database. 
    Tries texture_database.json first (comprehensive), then hash_database.json (original).
    """
    # Try the comprehensive texture database first
    paths_to_try = [
        "texture_database/texture_database.json",
        "hash_database.json"
    ]
    
    for db_path in paths_to_try:
        if os.path.exists(db_path):
            print(f"Loading hash database from: {db_path}")
            with open(db_path, 'r') as f:
                db = json.load(f)
            print(f"  Loaded {len(db)} hash-to-name mappings")
            return db
    
    print("Warning: No hash database found!")
    print("Run build_hash_database.py or build_complete_hash_database.py first.")
    return {}


def safe_filename(name: str) -> str:
    """Convert a resource path to a safe filename."""
    # Replace path separators with actual directory structure
    # Remove any dangerous characters
    safe = name.replace('\\', '/').strip('/')
    # Remove any characters that aren't safe for filenames
    for char in '<>:"|?*':
        safe = safe.replace(char, '_')
    return safe


def extract_textures_from_bundle(bundle_path: str, output_folder: str, 
                                  hash_db: dict, stats: dict):
    """Extract all textures from a single bundle with proper names."""
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
                    
                    # Look up the name
                    known_name = hash_db.get(hash_str)
                    
                    if known_name:
                        # Save with proper name in organized structure
                        safe_name = safe_filename(known_name)
                        output_path = os.path.join(output_folder, "by_name", safe_name + ".dds")
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        stats['named'] += 1
                    else:
                        # Save in by_bundle folder with hash
                        output_path = os.path.join(output_folder, "by_bundle", bundle_name, f"{hash_str}.dds")
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        stats['unknown'] += 1
                    
                    with open(output_path, 'wb') as f:
                        f.write(dds_data)
                    
                    textures.append({
                        'bundle': bundle_name,
                        'hash': hash_str,
                        'name': known_name,
                        'width': w,
                        'height': h,
                        'format': fmt_name,
                        'mips': mips,
                        'size': len(dds_data),
                        'path': output_path,
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
        output_folder = "extracted_named"
    
    if not os.path.exists(contents_folder):
        print(f"Error: Contents folder not found: {contents_folder}")
        sys.exit(1)
    
    print("=" * 70)
    print("GAUNTLET TEXTURE EXTRACTOR WITH PROPER NAMES")
    print("=" * 70)
    print()
    
    # Change to script directory so database paths work
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Load hash database (automatically finds best available database)
    hash_db = load_hash_database()
    print()
    
    print(f"Extracting textures from: {contents_folder}")
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
    os.makedirs(os.path.join(output_folder, "by_name"), exist_ok=True)
    os.makedirs(os.path.join(output_folder, "by_bundle"), exist_ok=True)
    
    all_textures = []
    stats = {'named': 0, 'unknown': 0}
    
    for i, bundle_path in enumerate(sorted(bundles)):
        name = os.path.basename(bundle_path)
        print(f"[{i+1}/{len(bundles)}] {name}...", end=" ", flush=True)
        
        textures = extract_textures_from_bundle(bundle_path, output_folder, hash_db, stats)
        all_textures.extend(textures)
        
        if textures:
            named = sum(1 for t in textures if t['name'])
            print(f"{len(textures)} textures ({named} named)")
        else:
            print("no textures")
    
    print()
    print("=" * 70)
    print(f"COMPLETE: Extracted {len(all_textures)} textures")
    print(f"  Named:   {stats['named']} ({100*stats['named']/len(all_textures):.1f}%)")
    print(f"  Unknown: {stats['unknown']} ({100*stats['unknown']/len(all_textures):.1f}%)")
    print("=" * 70)
    
    # Write master index with names
    index_path = os.path.join(output_folder, "_index.txt")
    with open(index_path, 'w') as f:
        f.write("GAUNTLET TEXTURE INDEX (WITH NAMES)\n")
        f.write("=" * 100 + "\n")
        f.write(f"Total textures: {len(all_textures)}\n")
        f.write(f"Named: {stats['named']} | Unknown: {stats['unknown']}\n\n")
        f.write("Format: hash -> name | dimensions | format\n")
        f.write("-" * 100 + "\n\n")
        
        # Named textures first, sorted by name
        f.write("=== NAMED TEXTURES ===\n\n")
        named_textures = [t for t in all_textures if t['name']]
        for tex in sorted(named_textures, key=lambda t: t['name']):
            f.write(f"{tex['hash']}  {tex['name']:<60s}  {tex['width']:4d}x{tex['height']:<4d}  {tex['format']}\n")
        
        # Unknown textures
        f.write("\n\n=== UNKNOWN TEXTURES ===\n\n")
        unknown_textures = [t for t in all_textures if not t['name']]
        for tex in sorted(unknown_textures, key=lambda t: -t['width'] * t['height']):
            f.write(f"{tex['hash']}  {tex['bundle']}  {tex['width']:4d}x{tex['height']:<4d}  {tex['format']}\n")
    
    print(f"Created index: {index_path}")
    
    # Write unknown textures list (for future database updates)
    unknown_path = os.path.join(output_folder, "_unknown.txt")
    with open(unknown_path, 'w') as f:
        f.write("UNKNOWN TEXTURE HASHES\n")
        f.write("=" * 80 + "\n")
        f.write("These textures have no known name in the database.\n")
        f.write("Add names to the hash database to properly identify them.\n\n")
        
        unknown_textures = [t for t in all_textures if not t['name']]
        for tex in sorted(unknown_textures, key=lambda t: -t['width'] * t['height']):
            f.write(f"{tex['hash']}  {tex['width']:4d}x{tex['height']:<4d}  {tex['format']:5s}  {tex['bundle']}\n")
    
    print(f"Created unknown list: {unknown_path}")
    
    # Summary by type (if we can infer from paths)
    print()
    print("Named textures by category:")
    by_category = {}
    for tex in all_textures:
        if tex['name']:
            parts = tex['name'].split('/')
            cat = parts[0] if len(parts) > 1 else 'root'
            by_category[cat] = by_category.get(cat, 0) + 1
    
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1])[:15]:
        print(f"  {cat}: {count}")
    
    print()


if __name__ == "__main__":
    main()
