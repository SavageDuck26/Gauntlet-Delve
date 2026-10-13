#!/usr/bin/env python3
"""
Gauntlet Texture Injector - Alternative Method
===============================================
Instead of creating new bundles (which may not be loaded), this tool
lets you inject custom textures by:

1. Creating a texture that REPLACES an existing game texture (by hash)
2. Putting your custom texture in an existing bundle (override)

This is more reliable than adding new bundles because:
- The game's material system already references existing texture hashes
- You don't need to modify bundle_database.data
- The texture replacement system (replace_textures_v4.py) is proven to work

Strategy: "Texture Slot Injection"
==================================
1. Find an unused/unimportant texture in the game
2. Replace it with your custom texture
3. Modify the material that uses the texture you want to change
   to point to the "injected" texture hash instead

This script helps with step 1: finding good candidate textures to replace.

Usage:
    python texture_injector.py find-candidates <bundle>  Find replaceable textures
    python texture_injector.py inject <source.dds> <target_hash> <bundle>
    python texture_injector.py list-used                 Show which textures are used by materials
    python texture_injector.py create-replacement-pack   Package textures for injection

Example Workflow:
    1. python texture_injector.py find-candidates 07c9b8511b5aff2e
       -> Shows textures that might be safe to replace
       
    2. Pick a texture hash (e.g., one that's 128x128 DXT5)
    
    3. python replace_textures_v4.py <bundle> my_textures/
       -> Where my_textures/ contains <target_hash>.dds with your texture
    
    4. Your texture is now in the game under that hash!
"""

import struct
import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import argparse

# Add current dir for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from bundle_tools import decompress_bundle, murmur_hash64
except ImportError:
    print("Warning: bundle_tools.py not found, some features disabled")
    decompress_bundle = None

# Type hash for textures
TEXTURE_TYPE_HASH = 0xCD4238C6A0C69E32

# Default game path
GAUNTLET_CONTENTS = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"


def get_dds_info(data: bytes) -> Dict:
    """Extract info from DDS header."""
    if len(data) < 128 or data[:4] != b'DDS ':
        return None
    
    height = struct.unpack_from('<I', data, 12)[0]
    width = struct.unpack_from('<I', data, 16)[0]
    mipmap_count = struct.unpack_from('<I', data, 28)[0]
    fourcc = data[0x54:0x58].decode('ascii', errors='replace')
    
    return {
        'width': width,
        'height': height,
        'mipmaps': mipmap_count,
        'format': fourcc,
        'size': len(data)
    }


def find_textures_in_bundle(bundle_path: str) -> List[Dict]:
    """
    Find all textures in a bundle with their hashes and info.
    """
    if not decompress_bundle:
        print("Error: bundle_tools.py required")
        return []
    
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    data = decompress_bundle(packed_data)
    
    # Parse bundle header
    resource_count = struct.unpack_from('<I', data, 0)[0]
    
    # Get texture entries from entry table at 0x104
    textures = []
    for i in range(resource_count):
        offset = 0x104 + i * 16
        type_hash, name_hash = struct.unpack_from('<QQ', data, offset)
        
        if type_hash == TEXTURE_TYPE_HASH:
            textures.append({
                'index': i,
                'name_hash': name_hash,
                'hash_hex': f"0x{name_hash:016X}",
            })
    
    # Find actual texture data (DDS)
    dds_positions = []
    offset = 0x104 + resource_count * 16
    while True:
        pos = data.find(b'DDS ', offset)
        if pos == -1:
            break
        dds_positions.append(pos)
        offset = pos + 4
    
    # Match textures with their DDS data
    for i, tex in enumerate(textures):
        if i < len(dds_positions):
            dds_pos = dds_positions[i]
            # Get size from header (8 bytes before DDS magic)
            size = struct.unpack_from('<I', data, dds_pos - 8)[0]
            dds_data = data[dds_pos:dds_pos + size - 4]  
            
            info = get_dds_info(dds_data)
            if info:
                tex.update(info)
    
    return textures


def load_material_database(db_path: str = None) -> Dict:
    """Load the material->texture mapping database if available."""
    if db_path is None:
        # Try common locations
        candidates = [
            'decoded_materials/texture_to_materials.json',
            'extracted_materials/texture_to_materials.json',
            'texture_to_materials.json'
        ]
        for path in candidates:
            if os.path.exists(path):
                db_path = path
                break
    
    if db_path and os.path.exists(db_path):
        with open(db_path, 'r') as f:
            return json.load(f)
    
    return {}


def find_replacement_candidates(bundle_path: str, 
                                  material_db: Dict = None,
                                  min_size: int = 0,
                                  max_size: int = 0,
                                  format_filter: str = None) -> List[Dict]:
    """
    Find textures that are good candidates for replacement.
    
    Good candidates are:
    - Not used by many materials (less chance of side effects)
    - Match your desired size/format
    - Preferably small or unimportant textures
    """
    textures = find_textures_in_bundle(bundle_path)
    
    if material_db is None:
        material_db = load_material_database()
    
    candidates = []
    for tex in textures:
        hash_hex = f"0x{tex['name_hash']:016X}"
        
        # Check material usage
        material_count = 0
        if hash_hex in material_db:
            material_count = len(material_db[hash_hex])
        
        tex['material_count'] = material_count
        tex['is_unused'] = material_count == 0
        
        # Apply filters
        if min_size > 0 and tex.get('size', 0) < min_size:
            continue
        if max_size > 0 and tex.get('size', 0) > max_size:
            continue
        if format_filter and tex.get('format', '') != format_filter:
            continue
        
        candidates.append(tex)
    
    # Sort by material count (unused first, then least-used)
    candidates.sort(key=lambda x: x['material_count'])
    
    return candidates


def cmd_find_candidates(args):
    """Find textures that are good replacement candidates."""
    bundle_path = args.bundle
    if not os.path.isabs(bundle_path):
        full_path = os.path.join(GAUNTLET_CONTENTS, bundle_path)
        if os.path.exists(full_path):
            bundle_path = full_path
    
    if not os.path.exists(bundle_path):
        print(f"Bundle not found: {bundle_path}")
        return
    
    print(f"Analyzing bundle: {bundle_path}")
    print()
    
    # Load material database if available
    material_db = load_material_database()
    if material_db:
        print(f"Loaded material database with {len(material_db)} texture entries")
    else:
        print("No material database found - can't determine usage")
    print()
    
    # Find candidates
    candidates = find_replacement_candidates(
        bundle_path,
        material_db,
        min_size=args.min_size if hasattr(args, 'min_size') else 0,
        max_size=args.max_size if hasattr(args, 'max_size') else 0,
        format_filter=args.format if hasattr(args, 'format') else None
    )
    
    # Group by format and size for easy selection
    print("=" * 70)
    print("REPLACEMENT CANDIDATES (sorted by material usage)")
    print("=" * 70)
    print()
    print(f"{'Hash':<20} {'Size':>10} {'Dimensions':>12} {'Format':<6} {'Materials':<10}")
    print("-" * 70)
    
    # Show unused textures first
    unused = [c for c in candidates if c['is_unused']]
    used = [c for c in candidates if not c['is_unused']]
    
    if unused:
        print(f"\n=== UNUSED TEXTURES (Best candidates - {len(unused)} found) ===\n")
        for tex in unused[:20]:
            dims = f"{tex.get('width', '?')}x{tex.get('height', '?')}"
            print(f"{tex['hash_hex']:<20} {tex.get('size', 0):>10} {dims:>12} {tex.get('format', '?'):<6} 0 materials")
    
    if used:
        print(f"\n=== LIGHTLY-USED TEXTURES ({len(used)} found) ===\n")
        for tex in used[:20]:
            dims = f"{tex.get('width', '?')}x{tex.get('height', '?')}"
            print(f"{tex['hash_hex']:<20} {tex.get('size', 0):>10} {dims:>12} {tex.get('format', '?'):<6} {tex['material_count']} materials")
    
    print()
    print("=" * 70)
    print("HOW TO USE:")
    print("=" * 70)
    print(f"""
1. Pick a texture hash from above (preferably unused)

2. Create your replacement texture as DDS with SAME format
   Example: If target is 128x128 DXT5, make your texture 128x128 DXT5
   (Or use replace_textures_v4.py which auto-converts!)

3. Name your DDS file with the target hash:
   {candidates[0]['hash_hex'][2:] if candidates else 'abcd1234abcd1234'}.dds

4. Run the replacement:
   python replace_textures_v4.py "{bundle_path}" your_texture_folder/

5. Your texture is now in the game at that hash!

To use it: Modify a material's texture hash to point to your injected hash.
""")


def cmd_list_by_format(args):
    """List all textures grouped by format and size."""
    bundle_path = args.bundle
    if not os.path.isabs(bundle_path):
        full_path = os.path.join(GAUNTLET_CONTENTS, bundle_path)
        if os.path.exists(full_path):
            bundle_path = full_path
    
    textures = find_textures_in_bundle(bundle_path)
    
    # Group by format
    by_format = {}
    for tex in textures:
        fmt = tex.get('format', 'unknown')
        if fmt not in by_format:
            by_format[fmt] = []
        by_format[fmt].append(tex)
    
    print(f"Textures in {os.path.basename(bundle_path)}:")
    print()
    
    for fmt, tex_list in sorted(by_format.items()):
        print(f"\n{fmt} ({len(tex_list)} textures):")
        print("-" * 50)
        
        # Group by dimensions
        by_dims = {}
        for tex in tex_list:
            dims = (tex.get('width', 0), tex.get('height', 0))
            if dims not in by_dims:
                by_dims[dims] = []
            by_dims[dims].append(tex)
        
        for dims, tex_list2 in sorted(by_dims.items()):
            print(f"  {dims[0]}x{dims[1]}: {len(tex_list2)} textures")


def cmd_create_mapping(args):
    """
    Create a hash mapping file for your textures.
    
    This helps you keep track of which game hashes you're replacing
    with which custom textures.
    """
    print("Interactive Hash Mapping Creator")
    print("=" * 50)
    print()
    print("This creates a mapping file to track your texture replacements.")
    print()
    
    mappings = []
    
    while True:
        print("\nAdd a mapping (or 'done' to finish):")
        
        custom_name = input("  Your texture name (e.g., 'my_sword'): ").strip()
        if custom_name.lower() == 'done':
            break
        
        target_hash = input("  Target game hash (e.g., 0x1234...): ").strip()
        
        # Compute hash for the custom name
        custom_hash = murmur_hash64(f"custom/{custom_name}")
        
        mappings.append({
            'custom_name': custom_name,
            'custom_hash': f"0x{custom_hash:016X}",
            'replaces_hash': target_hash,
            'notes': ''
        })
        
        print(f"  Added: {custom_name} (0x{custom_hash:016X}) -> {target_hash}")
    
    if mappings:
        output_file = args.output or 'texture_mappings.json'
        with open(output_file, 'w') as f:
            json.dump({'mappings': mappings}, f, indent=2)
        print(f"\nSaved mappings to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Gauntlet Texture Injection Helper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool helps you inject custom textures into Gauntlet by finding
existing texture slots you can safely replace.

Since creating entirely new texture bundles can be unreliable (the game
may not load them), this approach replaces existing textures - which is
proven to work with replace_textures_v4.py.
        """)
    
    subparsers = parser.add_subparsers(dest='command')
    
    # find-candidates
    find_parser = subparsers.add_parser('find-candidates', 
                                         help='Find textures safe to replace')
    find_parser.add_argument('bundle', help='Bundle file to analyze')
    find_parser.add_argument('--min-size', type=int, default=0)
    find_parser.add_argument('--max-size', type=int, default=0)
    find_parser.add_argument('--format', help='Filter by format (DXT1, DXT5, etc)')
    
    # list-by-format
    list_parser = subparsers.add_parser('list-by-format',
                                         help='List textures grouped by format')
    list_parser.add_argument('bundle', help='Bundle file to analyze')
    
    # create-mapping
    map_parser = subparsers.add_parser('create-mapping',
                                        help='Create a texture mapping file')
    map_parser.add_argument('--output', '-o', help='Output JSON file')
    
    args = parser.parse_args()
    
    if args.command == 'find-candidates':
        cmd_find_candidates(args)
    elif args.command == 'list-by-format':
        cmd_list_by_format(args)
    elif args.command == 'create-mapping':
        cmd_create_mapping(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
