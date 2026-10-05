#!/usr/bin/env python3
"""
Build a COMPLETE hash-to-name database for Gauntlet resources.

This does an exhaustive brute-force approach:
1. Extracts ALL texture hashes from game bundles
2. Scans the ENTIRE source code folder structure
3. Generates ALL possible path combinations with ALL suffixes
4. Cross-references every hash to find matches

This may take a while but will build the most complete database possible.

Usage:
    python build_complete_hash_database.py
"""

import os
import sys
import json
import re
import struct
from pathlib import Path
from collections import defaultdict

# Add current directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

TEXTURE_TYPE = 0xCD4238C6A0C69E32

# MurmurHash64A implementation
def murmur_hash64(key: str, seed: int = 0) -> int:
    """MurmurHash64A implementation for matching Bitsquid resource names."""
    m = 0xc6a4a7935bd1e995
    r = 47
    
    key_bytes = key.lower().encode('utf-8')
    length = len(key_bytes)
    h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)
    
    nblocks = length // 8
    for i in range(nblocks):
        k = struct.unpack('<Q', key_bytes[i*8:(i+1)*8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    
    tail = key_bytes[nblocks * 8:]
    if len(tail) >= 7: h ^= tail[6] << 48
    if len(tail) >= 6: h ^= tail[5] << 40
    if len(tail) >= 5: h ^= tail[4] << 32
    if len(tail) >= 4: h ^= tail[3] << 24
    if len(tail) >= 3: h ^= tail[2] << 16
    if len(tail) >= 2: h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    
    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    
    return h


def extract_all_texture_hashes(contents_folder: str) -> dict:
    """Extract ALL unique texture hashes from all bundles."""
    print("=" * 70)
    print("PHASE 1: EXTRACTING ALL TEXTURE HASHES FROM BUNDLES")
    print("=" * 70)
    
    all_hashes = {}  # hash_str -> {width, height, format, bundles}
    
    bundles = []
    for filename in os.listdir(contents_folder):
        filepath = os.path.join(contents_folder, filename)
        if os.path.isfile(filepath) and not filename.endswith(('.stream', '.backup', '.ini', '.data')):
            bundles.append(filepath)
    
    print(f"Found {len(bundles)} bundles to scan")
    
    for i, bundle_path in enumerate(sorted(bundles)):
        bundle_name = os.path.basename(bundle_path)
        print(f"[{i+1}/{len(bundles)}] {bundle_name}...", end=" ", flush=True)
        
        try:
            with open(bundle_path, 'rb') as f:
                packed_data = f.read()
            
            data = decompress_bundle(packed_data)
            
            if len(data) < 0x120:
                print("too small")
                continue
            
            count = struct.unpack('<I', data[:4])[0]
            if count == 0 or count > 100000:
                print("invalid count")
                continue
            
            # Build entry set
            entry_set = set()
            for j in range(count):
                pos = 0x104 + j * 16
                if pos + 16 > len(data):
                    break
                type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
                entry_set.add((type_hash, name_hash))
            
            # Find textures
            texture_count = 0
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
                        h, w = struct.unpack('<II', dds_data[12:20])
                        fourcc = dds_data[84:88]
                        
                        try:
                            fmt_name = fourcc.decode('ascii').strip('\x00')
                        except:
                            fmt_name = "RGB32" if fourcc == b'\x00\x00\x00\x00' else "UNK"
                        if not fmt_name:
                            fmt_name = "RGB32"
                        
                        if hash_str not in all_hashes:
                            all_hashes[hash_str] = {
                                'width': w,
                                'height': h,
                                'format': fmt_name,
                                'bundles': [bundle_name]
                            }
                        else:
                            if bundle_name not in all_hashes[hash_str]['bundles']:
                                all_hashes[hash_str]['bundles'].append(bundle_name)
                        
                        texture_count += 1
                
                pos += 36 + main_size
            
            print(f"{texture_count} textures")
            
        except Exception as e:
            print(f"error: {e}")
    
    print()
    print(f"Total unique texture hashes: {len(all_hashes)}")
    return all_hashes


def scan_source_structure(source_folder: str) -> set:
    """Scan the entire source folder structure to get all possible paths."""
    print()
    print("=" * 70)
    print("PHASE 2: SCANNING SOURCE CODE STRUCTURE")
    print("=" * 70)
    
    paths = set()
    source_path = Path(source_folder)
    
    if not source_path.exists():
        print(f"Warning: Source folder not found: {source_folder}")
        return paths
    
    # Get all folders in the source
    folders = set()
    for item in source_path.rglob('*'):
        if item.is_dir():
            rel_path = item.relative_to(source_path)
            folders.add(str(rel_path).replace('\\', '/'))
    
    print(f"Found {len(folders)} folders in source")
    
    # Get all Lua files and extract paths from them
    lua_paths = set()
    lua_count = 0
    for lua_file in source_path.rglob('*.lua'):
        try:
            content = lua_file.read_text(encoding='utf-8', errors='ignore')
            
            # Extract all quoted strings that look like paths
            for match in re.finditer(r'["\']([a-zA-Z0-9_/]+(?:/[a-zA-Z0-9_]+)*)["\']', content):
                path = match.group(1)
                if '/' in path and not any(x in path.lower() for x in ['http', 'www.', 'file://', '//']):
                    lua_paths.add(path)
            
            lua_count += 1
        except:
            pass
    
    print(f"Scanned {lua_count} Lua files, found {len(lua_paths)} paths")
    
    # Combine folder paths with Lua paths
    paths.update(lua_paths)
    
    # Add folder-based paths (convert folder structure to resource paths)
    for folder in folders:
        # Skip __pycache__ and similar
        if '__' in folder or '.git' in folder:
            continue
        paths.add(folder)
    
    return paths


def generate_exhaustive_paths(base_paths: set) -> set:
    """Generate ALL possible texture path variations."""
    print()
    print("=" * 70)
    print("PHASE 3: GENERATING EXHAUSTIVE PATH VARIATIONS")
    print("=" * 70)
    
    # Comprehensive suffix list
    suffixes = [
        '',  # No suffix
        # Diffuse/Color
        '_diffuse', '_diff', '_d', '_color', '_col', '_albedo', '_basecolor', '_base_color',
        # Normal maps
        '_normal', '_norm', '_n', '_nrm', '_normalmap', '_normal_map',
        # Specular/Gloss
        '_specular', '_spec', '_s', '_gloss', '_glossy', '_roughness', '_rough',
        # Other PBR
        '_ao', '_ambient', '_occlusion', '_ambient_occlusion',
        '_height', '_h', '_bump', '_displacement', '_disp',
        '_emissive', '_emit', '_glow', '_emission',
        '_metallic', '_metal', '_metalness',
        # Masks
        '_mask', '_alpha', '_opacity', '_blend',
        # Detail
        '_detail', '_det', '_overlay',
        # Common variations
        '_01', '_02', '_03', '_04', '_05',
        '_a', '_b', '_c',
        '_var01', '_var02', '_var03',
        # Combinations
        '_diffuse_01', '_normal_01', '_spec_01',
        '_diff_01', '_norm_01',
    ]
    
    # Level/environment specific prefixes and names
    level_types = ['caves', 'crypt', 'lava', 'arcade', 'common', 'swamp', 'desert', 'forest']
    level_prefixes = ['d01_', 'd02_', 'd03_', '']
    
    # Surface types for environment textures
    surfaces = [
        'floor', 'wall', 'ceiling', 'trim', 'detail', 'rock', 'stone', 'brick',
        'tile', 'wood', 'metal', 'grass', 'dirt', 'sand', 'water', 'lava_flow',
        'pillar', 'column', 'arch', 'door', 'gate', 'statue', 'torch', 'brazier'
    ]
    
    all_paths = set()
    
    # Add base paths with all suffixes
    print(f"Processing {len(base_paths)} base paths with {len(suffixes)} suffixes...")
    for path in base_paths:
        for suffix in suffixes:
            all_paths.add(f"{path}{suffix}")
    
    # Generate block/environment texture paths
    print("Generating environment texture paths...")
    for level in level_types:
        for prefix in level_prefixes:
            level_name = f"{prefix}{level}"
            
            for surface in surfaces:
                # Various path patterns for environment textures
                patterns = [
                    f"blocks/{level_name}/{surface}",
                    f"blocks/{level_name}/{level_name}_{surface}",
                    f"units/blocks/{level_name}/{surface}",
                    f"textures/environment/{level}/{surface}",
                    f"textures/dungeon/{level}/{surface}",
                    f"environment/{level}/{surface}",
                    f"{level}/{surface}",
                    f"{level_name}/{surface}",
                    f"textures/{level_name}_{surface}",
                ]
                
                for pattern in patterns:
                    for suffix in suffixes:
                        all_paths.add(f"{pattern}{suffix}")
    
    # Generate numbered block paths (common in level editors)
    print("Generating numbered block paths...")
    for level in level_types:
        for prefix in level_prefixes:
            level_name = f"{prefix}{level}"
            for i in range(1, 100):  # blocks numbered 01-99
                num = f"{i:02d}"
                patterns = [
                    f"blocks/{level_name}/block_{num}",
                    f"blocks/{level_name}/{level_name}_{num}",
                    f"blocks/{level_name}/floor_{num}",
                    f"blocks/{level_name}/wall_{num}",
                    f"blocks/{level_name}/trim_{num}",
                    f"blocks/{level_name}/detail_{num}",
                    f"blocks/{level_name}/rock_{num}",
                    f"blocks/{level_name}/pillar_{num}",
                ]
                for pattern in patterns:
                    for suffix in ['', '_diffuse', '_diff', '_normal', '_norm', '_spec']:
                        all_paths.add(f"{pattern}{suffix}")
    
    # GUI/Menu textures
    print("Generating GUI texture paths...")
    gui_elements = [
        'button', 'background', 'frame', 'icon', 'border', 'panel', 'overlay',
        'cursor', 'arrow', 'checkbox', 'slider', 'bar', 'fill', 'glow'
    ]
    gui_folders = ['gui', 'menu', 'hud', 'ui', 'interface']
    
    for folder in gui_folders:
        for element in gui_elements:
            patterns = [
                f"{folder}/{element}",
                f"{folder}/{folder}_{element}",
                f"textures/{folder}/{element}",
            ]
            for pattern in patterns:
                for suffix in ['', '_01', '_02', '_over', '_down', '_disabled', '_hover', '_active']:
                    all_paths.add(f"{pattern}{suffix}")
    
    # Loading screens and cutscenes
    print("Generating loading screen paths...")
    for i in range(1, 20):
        num = f"{i:02d}"
        patterns = [
            f"loading_screens/loading_{num}",
            f"loading_screens/screen_{num}",
            f"loading/loading_{num}",
            f"cutscenes/cutscene_{num}",
            f"splash/splash_{num}",
        ]
        for pattern in patterns:
            all_paths.add(pattern)
    
    # Character ability textures
    print("Generating ability texture paths...")
    characters = ['warrior', 'valkyrie', 'wizard', 'elf', 'necromagus']
    abilities = [
        'spell', 'projectile', 'effect', 'aura', 'shield', 'buff', 'debuff',
        'fire', 'ice', 'lightning', 'poison', 'holy', 'dark', 'arcane'
    ]
    
    for char in characters:
        for ability in abilities:
            patterns = [
                f"characters/avatar_{char}/abilities/{ability}",
                f"characters/avatar_{char}/abilities/{char}_{ability}",
                f"abilities/{char}/{ability}",
                f"effects/{char}_{ability}",
            ]
            for pattern in patterns:
                for suffix in suffixes[:15]:  # Just common suffixes
                    all_paths.add(f"{pattern}{suffix}")
    
    # Effect/particle textures
    print("Generating effect texture paths...")
    effect_types = [
        'fire', 'smoke', 'spark', 'glow', 'flash', 'explosion', 'impact',
        'trail', 'beam', 'ring', 'wave', 'burst', 'cloud', 'mist', 'fog',
        'blood', 'gore', 'splat', 'splash', 'drip', 'pool'
    ]
    
    for effect in effect_types:
        for i in range(1, 10):
            patterns = [
                f"effects/{effect}",
                f"effects/{effect}_{i:02d}",
                f"particles/{effect}",
                f"particles/{effect}_{i:02d}",
                f"textures/effects/{effect}",
                f"textures/particles/{effect}",
                f"vfx/{effect}",
            ]
            for pattern in patterns:
                all_paths.add(pattern)
    
    print(f"Total paths generated: {len(all_paths)}")
    return all_paths


def build_hash_lookup(paths: set) -> dict:
    """Build a hash lookup table from all paths."""
    print()
    print("=" * 70)
    print("PHASE 4: COMPUTING HASHES FOR ALL PATHS")
    print("=" * 70)
    
    hash_to_name = {}
    total = len(paths)
    
    for i, path in enumerate(paths):
        if i % 100000 == 0:
            print(f"  Progress: {i}/{total} ({100*i/total:.1f}%)")
        
        hash_val = murmur_hash64(path)
        hash_str = f"{hash_val:016x}"
        
        if hash_str not in hash_to_name:
            hash_to_name[hash_str] = path
        else:
            # Keep shorter path (more likely to be correct)
            if len(path) < len(hash_to_name[hash_str]):
                hash_to_name[hash_str] = path
    
    print(f"  Computed {len(hash_to_name)} unique hashes")
    return hash_to_name


def match_textures(texture_hashes: dict, hash_lookup: dict) -> tuple:
    """Match texture hashes against the lookup table."""
    print()
    print("=" * 70)
    print("PHASE 5: MATCHING TEXTURE HASHES")
    print("=" * 70)
    
    matched = {}
    unmatched = {}
    
    for hash_str, info in texture_hashes.items():
        if hash_str in hash_lookup:
            matched[hash_str] = {
                'name': hash_lookup[hash_str],
                **info
            }
        else:
            unmatched[hash_str] = info
    
    print(f"Matched: {len(matched)} ({100*len(matched)/len(texture_hashes):.1f}%)")
    print(f"Unmatched: {len(unmatched)} ({100*len(unmatched)/len(texture_hashes):.1f}%)")
    
    return matched, unmatched


def save_database(matched: dict, unmatched: dict, output_folder: str):
    """Save the complete database."""
    print()
    print("=" * 70)
    print("PHASE 6: SAVING DATABASE")
    print("=" * 70)
    
    os.makedirs(output_folder, exist_ok=True)
    
    # Save matched as main database
    db = {h: info['name'] for h, info in matched.items()}
    db_path = os.path.join(output_folder, "texture_database.json")
    with open(db_path, 'w') as f:
        json.dump(db, f, indent=2, sort_keys=True)
    print(f"Saved database: {db_path}")
    
    # Save detailed matched info
    matched_path = os.path.join(output_folder, "matched_textures.txt")
    with open(matched_path, 'w') as f:
        f.write("MATCHED GAUNTLET TEXTURES\n")
        f.write("=" * 100 + "\n")
        f.write(f"Total matched: {len(matched)}\n\n")
        f.write(f"{'Hash':<20} {'Name':<60} {'Size':<12} {'Format'}\n")
        f.write("-" * 100 + "\n")
        for h in sorted(matched.keys()):
            info = matched[h]
            size = f"{info['width']}x{info['height']}"
            f.write(f"{h}  {info['name']:<60} {size:<12} {info['format']}\n")
    print(f"Saved matched list: {matched_path}")
    
    # Save unmatched for analysis
    unmatched_path = os.path.join(output_folder, "unmatched_textures.txt")
    with open(unmatched_path, 'w') as f:
        f.write("UNMATCHED GAUNTLET TEXTURES\n")
        f.write("=" * 100 + "\n")
        f.write(f"Total unmatched: {len(unmatched)}\n")
        f.write("These textures have no known name - may need manual identification\n\n")
        f.write(f"{'Hash':<20} {'Size':<12} {'Format':<8} {'Bundles'}\n")
        f.write("-" * 100 + "\n")
        
        # Sort by size (largest first - more likely to be important)
        sorted_unmatched = sorted(unmatched.items(), 
                                   key=lambda x: -x[1]['width'] * x[1]['height'])
        for h, info in sorted_unmatched:
            size = f"{info['width']}x{info['height']}"
            bundles = ', '.join(info['bundles'][:3])
            if len(info['bundles']) > 3:
                bundles += f" +{len(info['bundles'])-3} more"
            f.write(f"{h}  {size:<12} {info['format']:<8} {bundles}\n")
    print(f"Saved unmatched list: {unmatched_path}")
    
    # Save summary
    summary_path = os.path.join(output_folder, "summary.txt")
    with open(summary_path, 'w') as f:
        f.write("GAUNTLET TEXTURE DATABASE SUMMARY\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total unique textures: {len(matched) + len(unmatched)}\n")
        f.write(f"Matched: {len(matched)} ({100*len(matched)/(len(matched)+len(unmatched)):.1f}%)\n")
        f.write(f"Unmatched: {len(unmatched)} ({100*len(unmatched)/(len(matched)+len(unmatched)):.1f}%)\n\n")
        
        # Breakdown by category
        f.write("MATCHED BY CATEGORY:\n")
        f.write("-" * 40 + "\n")
        categories = defaultdict(int)
        for info in matched.values():
            parts = info['name'].split('/')
            cat = parts[0] if parts else 'root'
            categories[cat] += 1
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            f.write(f"  {cat}: {count}\n")
        
        f.write("\nUNMATCHED BY SIZE:\n")
        f.write("-" * 40 + "\n")
        sizes = defaultdict(int)
        for info in unmatched.values():
            size = f"{info['width']}x{info['height']}"
            sizes[size] += 1
        for size, count in sorted(sizes.items(), key=lambda x: -x[1])[:20]:
            f.write(f"  {size}: {count}\n")
    
    print(f"Saved summary: {summary_path}")


def main():
    contents_folder = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"
    source_folder = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\Aussiemon-gauntlet-slayer-edition-source-code-74e4ee3ab612"
    output_folder = "texture_database"
    
    print()
    print("=" * 70)
    print("GAUNTLET COMPLETE TEXTURE DATABASE BUILDER")
    print("=" * 70)
    print()
    print("This will exhaustively scan all bundles and source code to build")
    print("the most complete texture name database possible.")
    print()
    print("This may take several minutes...")
    print()
    
    # Phase 1: Extract all texture hashes
    texture_hashes = extract_all_texture_hashes(contents_folder)
    
    # Phase 2: Scan source structure
    base_paths = scan_source_structure(source_folder)
    
    # Phase 3: Generate exhaustive paths
    all_paths = generate_exhaustive_paths(base_paths)
    
    # Phase 4: Build hash lookup
    hash_lookup = build_hash_lookup(all_paths)
    
    # Phase 5: Match textures
    matched, unmatched = match_textures(texture_hashes, hash_lookup)
    
    # Phase 6: Save results
    save_database(matched, unmatched, output_folder)
    
    print()
    print("=" * 70)
    print("COMPLETE!")
    print("=" * 70)
    print(f"Results saved to: {output_folder}/")
    print()
    print(f"Matched: {len(matched)} textures ({100*len(matched)/(len(matched)+len(unmatched)):.1f}%)")
    print(f"Unmatched: {len(unmatched)} textures")
    print()
    print("Use texture_database.json with extract_textures_named.py for named extraction.")


if __name__ == "__main__":
    main()
