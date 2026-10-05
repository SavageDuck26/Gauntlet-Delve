"""
Gauntlet Bundle Repacker
Tool for replacing textures in bundles and repacking them.

This allows modifying game textures by:
1. Extracting original textures from bundles
2. Modifying them (externally as PNG)
3. Converting modified PNG back to DDS
4. Replacing the texture in the bundle
5. Recompressing the bundle

Usage:
  python bundle_repacker.py info <bundle>                  - List textures in bundle
  python bundle_repacker.py extract <bundle> <hash> <out>  - Extract single texture
  python bundle_repacker.py replace <bundle> <hash> <png>  - Replace texture with PNG
  python bundle_repacker.py patch <bundle> <mapping_file>  - Batch replace from mapping
"""

import struct
import zlib
import os
import sys
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import argparse

try:
    from PIL import Image
    import numpy as np
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: PIL/Pillow not available. PNG conversion disabled.")

# Bundle constants
BUNDLE_SIG_OLD = 0xF0000004
ZLIB_CHUNK = 0x10000  # 64KB chunks


@dataclass
class TextureInfo:
    """Information about a texture found in a bundle"""
    offset: int           # Offset in unpacked data
    header_offset: int    # Offset of the DDS header
    width: int
    height: int
    mipmap_count: int
    format: str           # DXT1, DXT5, ATI2, etc.
    fourcc: bytes
    data_size: int        # Size of texture data (including mipmaps)
    name_hash: int        # Resource name hash (if known)
    

def decompress_bundle(packed_data: bytes, quiet: bool = False) -> bytes:
    """Decompress a packed bundle file."""
    if len(packed_data) < 12:
        raise ValueError("Data too small for bundle header")
    
    signature, unzipped_size, padding = struct.unpack('<III', packed_data[:12])
    
    if signature != BUNDLE_SIG_OLD:
        raise ValueError(f"Invalid bundle signature: 0x{signature:08X}")
    
    if not quiet:
        print(f"Decompressing bundle ({unzipped_size:,} bytes expected)...")
    
    offset = 12
    unpacked_chunks = []
    
    while offset < len(packed_data):
        chunk_size = struct.unpack('<I', packed_data[offset:offset+4])[0]
        offset += 4
        
        if chunk_size == ZLIB_CHUNK:
            continue
        if chunk_size == 0:
            break
            
        chunk_data = packed_data[offset:offset + chunk_size]
        offset += chunk_size
        
        try:
            decompressed = zlib.decompress(chunk_data)
            unpacked_chunks.append(decompressed)
        except zlib.error:
            try:
                decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                decompressed = decompressor.decompress(chunk_data)
                unpacked_chunks.append(decompressed)
            except:
                break
    
    result = b''.join(unpacked_chunks)
    if not quiet:
        print(f"Decompressed to {len(result):,} bytes")
    return result


def compress_bundle(unpacked_data: bytes, quiet: bool = False) -> bytes:
    """Compress data into a bundle file."""
    if not quiet:
        print(f"Compressing bundle ({len(unpacked_data):,} bytes)...")
    
    chunks = []
    
    # Header
    header = struct.pack('<III', BUNDLE_SIG_OLD, len(unpacked_data), 0)
    chunks.append(header)
    
    # Compress in 64KB chunks
    offset = 0
    chunk_count = 0
    while offset < len(unpacked_data):
        chunk = unpacked_data[offset:offset + ZLIB_CHUNK]
        compressed = zlib.compress(chunk, 6)  # Level 6 compression
        
        chunks.append(struct.pack('<I', len(compressed)))
        chunks.append(compressed)
        
        offset += ZLIB_CHUNK
        chunk_count += 1
    
    result = b''.join(chunks)
    if not quiet:
        print(f"Compressed {chunk_count} chunks to {len(result):,} bytes")
    return result


def find_textures(data: bytes) -> List[TextureInfo]:
    """Find all DDS textures in unpacked bundle data."""
    textures = []
    dds_magic = b'DDS '
    
    offset = 0
    while True:
        pos = data.find(dds_magic, offset)
        if pos == -1:
            break
        
        # Parse DDS header
        if pos + 128 > len(data):
            offset = pos + 4
            continue
        
        header_size = struct.unpack_from('<I', data, pos + 4)[0]
        flags = struct.unpack_from('<I', data, pos + 8)[0]
        height = struct.unpack_from('<I', data, pos + 12)[0]
        width = struct.unpack_from('<I', data, pos + 16)[0]
        pitch = struct.unpack_from('<I', data, pos + 20)[0]
        depth = struct.unpack_from('<I', data, pos + 24)[0]
        mipmap_count = struct.unpack_from('<I', data, pos + 28)[0]
        
        # Get FourCC format
        pf_flags = struct.unpack_from('<I', data, pos + 80)[0]
        fourcc = data[pos + 84:pos + 88]
        
        # Determine format name
        if fourcc == b'DXT1':
            fmt = 'DXT1'
            block_size = 8
        elif fourcc == b'DXT3':
            fmt = 'DXT3'
            block_size = 16
        elif fourcc == b'DXT5':
            fmt = 'DXT5'
            block_size = 16
        elif fourcc == b'ATI2':
            fmt = 'ATI2'
            block_size = 16
        elif fourcc == b'BC5U':
            fmt = 'BC5U'
            block_size = 16
        else:
            fmt = fourcc.decode('ascii', errors='replace')
            block_size = 16  # Assume 16
        
        # Calculate data size (with mipmaps)
        data_size = 0
        w, h = width, height
        for mip in range(max(1, mipmap_count)):
            blocks_x = max(1, (w + 3) // 4)
            blocks_y = max(1, (h + 3) // 4)
            data_size += blocks_x * blocks_y * block_size
            w = max(1, w // 2)
            h = max(1, h // 2)
        
        tex_info = TextureInfo(
            offset=pos,
            header_offset=pos,
            width=width,
            height=height,
            mipmap_count=mipmap_count,
            format=fmt,
            fourcc=fourcc,
            data_size=data_size,
            name_hash=0
        )
        textures.append(tex_info)
        
        offset = pos + 128 + data_size
    
    return textures


def list_textures(bundle_path: str):
    """List all textures in a bundle."""
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    data = decompress_bundle(packed_data)
    textures = find_textures(data)
    
    print(f"\nFound {len(textures)} textures:\n")
    print(f"{'Index':<6} {'Offset':<12} {'Size':<10} {'Format':<8} {'Dimensions':<12} {'Mipmaps'}")
    print("-" * 70)
    
    for i, tex in enumerate(textures):
        print(f"{i:<6} 0x{tex.offset:08X}  {tex.data_size:<10} {tex.format:<8} {tex.width}x{tex.height:<6} {tex.mipmap_count}")
    
    return textures


def extract_texture(bundle_path: str, index_or_offset: str, output_path: str):
    """Extract a single texture from a bundle."""
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    data = decompress_bundle(packed_data)
    textures = find_textures(data)
    
    # Find the texture
    target_tex = None
    
    if index_or_offset.startswith('0x'):
        # By offset
        offset = int(index_or_offset, 16)
        for tex in textures:
            if tex.offset == offset:
                target_tex = tex
                break
    else:
        # By index
        idx = int(index_or_offset)
        if 0 <= idx < len(textures):
            target_tex = textures[idx]
    
    if not target_tex:
        print(f"Texture not found: {index_or_offset}")
        return False
    
    # Extract DDS data
    dds_data = data[target_tex.offset:target_tex.offset + 128 + target_tex.data_size]
    
    # Write to file
    with open(output_path, 'wb') as f:
        f.write(dds_data)
    
    print(f"Extracted {target_tex.format} texture ({target_tex.width}x{target_tex.height}) to {output_path}")
    return True


def png_to_dds(png_path: str, target_format: str, target_mipmaps: int) -> bytes:
    """
    Convert a PNG image to DDS format.
    
    This is a simplified conversion that creates DDS with the specified format.
    For best results, use a proper DDS converter like texconv.
    """
    if not HAS_PIL:
        raise RuntimeError("PIL/Pillow required for PNG conversion")
    
    img = Image.open(png_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    width, height = img.size
    
    # For now, we'll create uncompressed DDS and rely on the user
    # to use proper tools for BC compression
    # This is a placeholder - real implementation would need BC encoder
    
    print(f"Warning: Direct PNG->DDS compression not fully implemented.")
    print(f"For best results, use texconv or similar tools to create DDS,")
    print(f"then use 'replace_dds' command instead.")
    
    raise NotImplementedError("Use external DDS conversion tools")


def replace_texture_dds(bundle_path: str, index_or_offset: str, dds_path: str, output_path: str = None):
    """
    Replace a texture in a bundle with a new DDS file.
    
    The replacement DDS MUST be the same format and size as the original.
    """
    # Read the bundle
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    data = bytearray(decompress_bundle(packed_data))
    textures = find_textures(bytes(data))
    
    # Find the target texture
    target_tex = None
    target_idx = -1
    
    if index_or_offset.startswith('0x'):
        offset = int(index_or_offset, 16)
        for i, tex in enumerate(textures):
            if tex.offset == offset:
                target_tex = tex
                target_idx = i
                break
    else:
        idx = int(index_or_offset)
        if 0 <= idx < len(textures):
            target_tex = textures[idx]
            target_idx = idx
    
    if not target_tex:
        print(f"Texture not found: {index_or_offset}")
        return False
    
    # Read the replacement DDS
    with open(dds_path, 'rb') as f:
        new_dds = f.read()
    
    # Validate the new DDS
    if not new_dds.startswith(b'DDS '):
        print("Error: Replacement file is not a valid DDS")
        return False
    
    new_width = struct.unpack_from('<I', new_dds, 16)[0]
    new_height = struct.unpack_from('<I', new_dds, 12)[0]
    new_fourcc = new_dds[84:88]
    
    expected_size = 128 + target_tex.data_size
    
    print(f"Original texture: {target_tex.width}x{target_tex.height} {target_tex.format}")
    print(f"Replacement:      {new_width}x{new_height} {new_fourcc.decode('ascii', errors='replace')}")
    
    if new_width != target_tex.width or new_height != target_tex.height:
        print("Warning: Dimensions don't match! This may cause issues.")
    
    if new_fourcc != target_tex.fourcc:
        print("Warning: Format doesn't match! This may cause issues.")
    
    if len(new_dds) != expected_size:
        print(f"Error: Size mismatch. Expected {expected_size} bytes, got {len(new_dds)} bytes.")
        print("The replacement DDS must be EXACTLY the same size as the original.")
        return False
    
    # Replace the texture data
    data[target_tex.offset:target_tex.offset + expected_size] = new_dds
    
    # Recompress the bundle
    new_packed = compress_bundle(bytes(data))
    
    # Write output
    if output_path is None:
        output_path = bundle_path + ".modified"
    
    with open(output_path, 'wb') as f:
        f.write(new_packed)
    
    print(f"\nBundle saved to: {output_path}")
    print(f"\nTo apply the mod:")
    print(f"  1. Backup the original: {os.path.basename(bundle_path)}")
    print(f"  2. Copy {os.path.basename(output_path)} to the game's contents folder")
    print(f"  3. Rename it to: {os.path.basename(bundle_path)}")
    
    return True


def create_backup(bundle_path: str) -> str:
    """Create a backup of the original bundle."""
    backup_path = bundle_path + ".backup"
    if not os.path.exists(backup_path):
        shutil.copy2(bundle_path, backup_path)
        print(f"Created backup: {backup_path}")
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Gauntlet Bundle Texture Repacker")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # info command
    info_parser = subparsers.add_parser('info', help='List textures in a bundle')
    info_parser.add_argument('bundle', help='Path to bundle file')
    
    # extract command
    extract_parser = subparsers.add_parser('extract', help='Extract a texture from bundle')
    extract_parser.add_argument('bundle', help='Path to bundle file')
    extract_parser.add_argument('index', help='Texture index or offset (0x...)')
    extract_parser.add_argument('output', help='Output DDS file path')
    
    # replace command
    replace_parser = subparsers.add_parser('replace', help='Replace texture with new DDS')
    replace_parser.add_argument('bundle', help='Path to bundle file')
    replace_parser.add_argument('index', help='Texture index or offset (0x...)')
    replace_parser.add_argument('dds', help='Path to replacement DDS file')
    replace_parser.add_argument('-o', '--output', help='Output bundle path (default: bundle.modified)')
    replace_parser.add_argument('--backup', action='store_true', help='Create backup of original')
    
    args = parser.parse_args()
    
    if args.command == 'info':
        list_textures(args.bundle)
    elif args.command == 'extract':
        extract_texture(args.bundle, args.index, args.output)
    elif args.command == 'replace':
        if args.backup:
            create_backup(args.bundle)
        replace_texture_dds(args.bundle, args.index, args.dds, args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
