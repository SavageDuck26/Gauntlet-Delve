#!/usr/bin/env python3
"""
Gauntlet Custom Texture Bundle Creator
======================================
Create your own custom texture bundles that can be loaded alongside
the game's original bundles without replacing them.

This tool allows you to:
1. Create new bundles containing your own textures
2. Generate unique hash names for your textures
3. Optionally register the bundle in bundle_database.data

Usage:
    python create_custom_bundle.py <texture_folder> <output_bundle> [options]

    <texture_folder>  Folder containing DDS texture files to pack
    <output_bundle>   Path for the output bundle file (e.g., my_textures)

Options:
    --name-prefix PREFIX    Prefix for texture names (default: "custom/")
    --register              Register bundle in bundle_database.data
    --manifest FILE         Output a manifest JSON mapping names to hashes
    --dry-run               Preview what would be created without writing
    --verbose, -v           Show detailed information

Example:
    python create_custom_bundle.py my_textures/ custom_pack --name-prefix "mymod/"
    
    This creates:
    - custom_pack (bundle file ready to copy to contents/)
    - custom_pack_manifest.json (hash mapping for use in materials/lua)

Texture Naming:
    Textures will be named based on their filename:
    - my_sword.dds -> custom/my_sword (or your prefix)
    - cool_armor_diff.dds -> custom/cool_armor_diff
    
    The hash of this name is what you use to reference the texture.

After Creation:
    1. Copy the bundle file to Gauntlet/contents/
    2. Either use --register OR manually add to bundle_database.data
    3. Reference textures in materials using the hashes from manifest
"""

import struct
import zlib
import os
import sys
import json
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import argparse

# Bundle constants
BUNDLE_SIG_OLD = 0xF0000004
ZLIB_CHUNK = 0x10000  # 64KB

# Type hashes
TEXTURE_TYPE_HASH = 0xCD4238C6A0C69E32


def murmur_hash64(key: str, seed: int = 0) -> int:
    """
    MurmurHash64A - the hash algorithm used by Bitsquid/Stingray.
    This is how the game identifies all resources.
    """
    m = 0xc6a4a7935bd1e995
    r = 47
    
    key_bytes = key.lower().encode('utf-8')
    length = len(key_bytes)
    h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)
    
    # Process 8-byte chunks
    nblocks = length // 8
    for i in range(nblocks):
        k = struct.unpack('<Q', key_bytes[i*8:(i+1)*8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    
    # Process remaining bytes
    tail = key_bytes[nblocks * 8:]
    if len(tail) >= 7:
        h ^= tail[6] << 48
    if len(tail) >= 6:
        h ^= tail[5] << 40
    if len(tail) >= 5:
        h ^= tail[4] << 32
    if len(tail) >= 4:
        h ^= tail[3] << 24
    if len(tail) >= 3:
        h ^= tail[2] << 16
    if len(tail) >= 2:
        h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    
    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    
    return h


@dataclass
class TextureResource:
    """Represents a texture to be packed into the bundle"""
    name: str           # Resource name (e.g., "custom/my_texture")
    name_hash: int      # MurmurHash64 of the name
    filepath: str       # Original file path
    data: bytes         # DDS texture data


def validate_dds(data: bytes) -> Tuple[bool, str, int, int, str]:
    """
    Validate DDS file and extract information.
    Returns: (is_valid, error_msg, width, height, format)
    """
    if len(data) < 128:
        return False, "File too small for DDS header", 0, 0, ""
    
    if data[:4] != b'DDS ':
        return False, "Missing DDS magic signature", 0, 0, ""
    
    # Parse DDS header
    header_size = struct.unpack_from('<I', data, 4)[0]
    if header_size != 124:
        return False, f"Invalid DDS header size: {header_size}", 0, 0, ""
    
    height = struct.unpack_from('<I', data, 12)[0]
    width = struct.unpack_from('<I', data, 16)[0]
    
    # Get format from FourCC
    fourcc = data[0x54:0x58]
    format_map = {
        b'DXT1': 'DXT1',
        b'DXT2': 'DXT2',
        b'DXT3': 'DXT3',
        b'DXT4': 'DXT4',
        b'DXT5': 'DXT5',
        b'ATI1': 'ATI1',
        b'ATI2': 'ATI2',
        b'BC4U': 'BC4',
        b'BC5U': 'BC5',
    }
    dds_format = format_map.get(fourcc, fourcc.decode('ascii', errors='replace'))
    
    return True, "", width, height, dds_format


def collect_textures(folder: str, name_prefix: str) -> List[TextureResource]:
    """
    Collect all DDS textures from a folder.
    """
    textures = []
    folder_path = Path(folder)
    
    # Find all DDS files (recursively)
    dds_files = list(folder_path.glob('**/*.dds'))
    dds_files.extend(folder_path.glob('**/*.DDS'))
    
    for dds_path in sorted(set(dds_files)):
        # Read the file
        with open(dds_path, 'rb') as f:
            data = f.read()
        
        # Validate
        is_valid, error, width, height, fmt = validate_dds(data)
        if not is_valid:
            print(f"  Warning: Skipping {dds_path.name}: {error}")
            continue
        
        # Create resource name from filename
        # Remove .dds extension and convert to resource path
        rel_path = dds_path.relative_to(folder_path)
        name_parts = list(rel_path.parts)
        name_parts[-1] = rel_path.stem  # Remove .dds
        
        # Build resource name with prefix
        resource_name = name_prefix + '/'.join(name_parts)
        resource_name = resource_name.replace('\\', '/')
        
        # Compute hash
        name_hash = murmur_hash64(resource_name)
        
        textures.append(TextureResource(
            name=resource_name,
            name_hash=name_hash,
            filepath=str(dds_path),
            data=data
        ))
        
        print(f"  Found: {dds_path.name} ({width}x{height} {fmt}) -> {resource_name}")
        print(f"         Hash: 0x{name_hash:016X}")
    
    return textures


def build_bundle(textures: List[TextureResource]) -> bytes:
    """
    Build an unpacked bundle containing the given textures.
    
    Bundle format (unpacked):
    - uint32: resource count
    - uint64[count]: name hash table (at offset 4)
    - padding to 0x104
    - Entry table at 0x104: (type_hash, name_hash) × count
    - Resource data section: headers + data for each resource
    """
    if not textures:
        raise ValueError("No textures to pack")
    
    count = len(textures)
    print(f"\nBuilding bundle with {count} textures...")
    
    # Sort textures by hash for consistent ordering
    sorted_textures = sorted(textures, key=lambda t: t.name_hash)
    
    # Build sections
    sections = []
    
    # 1. Resource count (4 bytes)
    sections.append(struct.pack('<I', count))
    
    # 2. Name hash table (count × 8 bytes, starting at offset 4)
    for tex in sorted_textures:
        sections.append(struct.pack('<Q', tex.name_hash))
    
    # 3. Padding to offset 0x104
    current_size = 4 + count * 8
    padding_needed = 0x104 - current_size
    if padding_needed > 0:
        sections.append(b'\x00' * padding_needed)
    
    # 4. Entry table at 0x104 (count × 16 bytes)
    for tex in sorted_textures:
        sections.append(struct.pack('<QQ', TEXTURE_TYPE_HASH, tex.name_hash))
    
    # 5. Resource data section
    # Each resource has a 36-byte header followed by data:
    # - uint64: type hash
    # - uint64: name hash
    # - uint32: flags (1)
    # - uint64: stream size (0 for embedded textures)
    # - uint32: main size (size of DDS data)
    # - uint32: unknown (0)
    
    for tex in sorted_textures:
        main_size = len(tex.data)
        
        # Resource header (36 bytes)
        header = struct.pack('<QQIQII',
            TEXTURE_TYPE_HASH,  # type hash
            tex.name_hash,       # name hash
            1,                   # flags
            0,                   # stream size (no streaming)
            main_size,           # main size
            0                    # unknown
        )
        sections.append(header)
        
        # Resource data (DDS file)
        sections.append(tex.data)
    
    # Combine all sections
    result = b''.join(sections)
    
    # Add trailing padding to align to 4 bytes
    padding = (4 - (len(result) % 4)) % 4
    if padding > 0:
        result += b'\x00' * padding
    
    print(f"  Unpacked size: {len(result):,} bytes")
    return result


def compress_bundle(unpacked_data: bytes) -> bytes:
    """
    Compress data into a bundle file using zlib chunks.
    """
    print("Compressing bundle...")
    
    chunks = []
    
    # Header: signature, uncompressed size, padding
    header = struct.pack('<III', BUNDLE_SIG_OLD, len(unpacked_data), 0)
    chunks.append(header)
    
    # Compress in 64KB chunks
    offset = 0
    chunk_count = 0
    
    while offset < len(unpacked_data):
        chunk = unpacked_data[offset:offset + ZLIB_CHUNK]
        compressed = zlib.compress(chunk, 6)  # Level 6 compression
        
        # Write chunk size and compressed data
        chunks.append(struct.pack('<I', len(compressed)))
        chunks.append(compressed)
        
        offset += ZLIB_CHUNK
        chunk_count += 1
    
    result = b''.join(chunks)
    ratio = (1 - len(result) / len(unpacked_data)) * 100
    print(f"  Compressed {chunk_count} chunks: {len(result):,} bytes ({ratio:.1f}% reduction)")
    
    return result


def generate_bundle_name(output_path: str) -> str:
    """
    Generate a 16-character hex bundle name from the output path.
    Uses the hash of the path to create a unique, consistent name.
    """
    base_name = Path(output_path).stem
    bundle_hash = murmur_hash64(f"custom_bundle/{base_name}")
    return f"{bundle_hash:016x}"


def save_manifest(textures: List[TextureResource], manifest_path: str, bundle_name: str):
    """
    Save a manifest JSON file with texture name-to-hash mappings.
    """
    manifest = {
        "bundle_name": bundle_name,
        "texture_count": len(textures),
        "textures": {}
    }
    
    for tex in textures:
        manifest["textures"][tex.name] = {
            "hash_hex": f"0x{tex.name_hash:016X}",
            "hash_dec": tex.name_hash,
            "original_file": Path(tex.filepath).name,
            "size_bytes": len(tex.data)
        }
    
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"\nManifest saved to: {manifest_path}")


def register_bundle(bundle_name: str, contents_folder: str, has_stream: bool = False):
    """
    Add the bundle to bundle_database.data for the game to load it.
    
    NOTE: This is the most experimental part. The exact format of 
    bundle_database.data entries needs to match what the game expects.
    """
    db_path = os.path.join(contents_folder, 'bundle_database.data')
    
    if not os.path.exists(db_path):
        print(f"  Warning: bundle_database.data not found at {db_path}")
        return False
    
    # Read current database
    with open(db_path, 'rb') as f:
        db_data = bytearray(f.read())
    
    # Parse header
    version = struct.unpack('<I', db_data[:4])[0]
    num_entries = struct.unpack('<I', db_data[4:8])[0]
    
    print(f"  Current database: version={version}, entries={num_entries}")
    
    # Each entry is 51 bytes:
    # - uint32: platform ID (1)
    # - uint32: bundle name length (16)
    # - char[16]: bundle name
    # - uint32: stream name length (0 or 23)
    # - char[0 or 23]: stream filename (if any)
    
    # Create new entry
    new_entry = bytearray()
    new_entry.extend(struct.pack('<I', 1))  # Platform ID
    new_entry.extend(struct.pack('<I', 16))  # Bundle name length
    new_entry.extend(bundle_name.encode('ascii')[:16].ljust(16, b'\x00'))
    
    if has_stream:
        stream_name = bundle_name + '.stream\x00'
        new_entry.extend(struct.pack('<I', len(stream_name)))
        new_entry.extend(stream_name.encode('ascii'))
    else:
        new_entry.extend(struct.pack('<I', 0))  # No stream
    
    # Backup original database
    backup_path = db_path + '.backup'
    if not os.path.exists(backup_path):
        shutil.copy2(db_path, backup_path)
        print(f"  Backup created: {backup_path}")
    
    # Update entry count and append new entry
    struct.pack_into('<I', db_data, 4, num_entries + 1)
    db_data.extend(new_entry)
    
    # Write updated database
    with open(db_path, 'wb') as f:
        f.write(db_data)
    
    print(f"  Added bundle '{bundle_name}' to database (now {num_entries + 1} entries)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Create custom texture bundles for Gauntlet',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python create_custom_bundle.py my_textures/ custom_pack
    python create_custom_bundle.py weapons/ weapon_textures --name-prefix "mods/weapons/"
    python create_custom_bundle.py textures/ mymod --register

After creating a bundle:
    1. Copy it to C:\\Program Files (x86)\\Steam\\steamapps\\common\\Gauntlet\\contents\\
    2. The bundle name will be a 16-character hex string (see output)
    3. Use the manifest file to find texture hashes for material references
        """)
    
    parser.add_argument('texture_folder', help='Folder containing DDS textures')
    parser.add_argument('output_name', help='Base name for output files')
    parser.add_argument('--name-prefix', default='custom/', 
                       help='Prefix for texture resource names (default: custom/)')
    parser.add_argument('--register', action='store_true',
                       help='Register bundle in bundle_database.data')
    parser.add_argument('--contents-folder', 
                       default=r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents',
                       help='Gauntlet contents folder (for --register)')
    parser.add_argument('--manifest', help='Custom manifest output path')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without creating files')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    
    args = parser.parse_args()
    
    # Validate input folder
    if not os.path.isdir(args.texture_folder):
        print(f"Error: Texture folder not found: {args.texture_folder}")
        sys.exit(1)
    
    print("=" * 60)
    print("Gauntlet Custom Texture Bundle Creator")
    print("=" * 60)
    print()
    
    # Ensure prefix ends with /
    name_prefix = args.name_prefix
    if name_prefix and not name_prefix.endswith('/'):
        name_prefix += '/'
    
    print(f"Source folder: {args.texture_folder}")
    print(f"Name prefix: {name_prefix}")
    print()
    
    # Collect textures
    print("Scanning for DDS textures...")
    textures = collect_textures(args.texture_folder, name_prefix)
    
    if not textures:
        print("\nNo valid DDS textures found!")
        print("Make sure your textures are in DDS format (use texconv to convert PNG).")
        sys.exit(1)
    
    print(f"\nFound {len(textures)} textures")
    
    if args.dry_run:
        print("\n[DRY RUN] Would create bundle with these textures:")
        for tex in textures:
            print(f"  {tex.name} -> 0x{tex.name_hash:016X}")
        sys.exit(0)
    
    # Build unpacked bundle
    unpacked_data = build_bundle(textures)
    
    # Compress bundle
    packed_data = compress_bundle(unpacked_data)
    
    # Generate bundle name (16-char hex)
    bundle_name = generate_bundle_name(args.output_name)
    
    # Determine output paths
    output_dir = Path(args.output_name).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True)
    
    # Save bundle
    bundle_path = args.output_name
    if not bundle_path.endswith('.bundle'):
        # Use the hash-based name for the actual file
        base_dir = Path(args.output_name).parent if Path(args.output_name).parent.exists() else Path('.')
        bundle_path = str(base_dir / bundle_name)
    
    with open(bundle_path, 'wb') as f:
        f.write(packed_data)
    print(f"\nBundle saved to: {bundle_path}")
    print(f"Bundle name: {bundle_name}")
    
    # Save manifest
    manifest_path = args.manifest or f"{args.output_name}_manifest.json"
    save_manifest(textures, manifest_path, bundle_name)
    
    # Optional: Register in bundle_database.data
    if args.register:
        print("\nRegistering bundle in bundle_database.data...")
        if register_bundle(bundle_name, args.contents_folder):
            print("  Bundle registered successfully!")
        else:
            print("  Warning: Could not register bundle automatically.")
            print("  You may need to add it manually or use the bundle loader mod.")
    
    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print(f"""
1. Copy the bundle file to Gauntlet's contents folder:
   copy "{bundle_path}" "{args.contents_folder}\\{bundle_name}"

2. To use these textures in-game, you need to reference them by hash.
   Check {manifest_path} for the hash values.

3. In a material or Lua script, use the hex hash to reference textures:
   Example: If your texture "custom/sword" has hash 0x1234567890ABCDEF
   
4. IMPORTANT: The game may need a bundle loader to recognize new bundles.
   Alternatively, modify an existing material to point to your texture hashes.

Alternative method (no bundle_database modification):
   - Use replace_textures_v4.py to replace existing textures with your custom ones
   - This is more reliable but requires replacing rather than adding
""")


if __name__ == '__main__':
    main()
