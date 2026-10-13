#!/usr/bin/env python3
"""
Extract all textures from a Gauntlet bundle to viewable DDS files.

Usage:
    python extract_textures.py <bundle_path> [output_folder]
    python extract_textures.py <bundle_path> --identify

Examples:
    python extract_textures.py "C:\...\contents\0164ad48615ba9ed"
    python extract_textures.py "C:\...\contents\0164ad48615ba9ed" extracted\level1
    python extract_textures.py "C:\...\contents\07c9b8511b5aff2e" --identify

Output folder defaults to: extracted/<bundle_hash>/

This extracts actual DDS files you can view with any DDS viewer or convert to PNG.
Use --identify to just list textures with their dimensions and formats.
"""

import sys
import os
import struct
import zlib

# Add parent directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle as bt_decompress

# DDS format constants
DDS_MAGIC = 0x20534444  # "DDS "
DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000

DDPF_FOURCC = 0x4
DDPF_RGB = 0x40

DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000
DDSCAPS_COMPLEX = 0x8

def make_fourcc(s):
    return struct.unpack('<I', s.encode('ascii'))[0]

DXT1 = make_fourcc('DXT1')
DXT3 = make_fourcc('DXT3')
DXT5 = make_fourcc('DXT5')
ATI2 = make_fourcc('ATI2')

def format_name(fourcc):
    if fourcc == DXT1: return "DXT1"
    if fourcc == DXT3: return "DXT3"
    if fourcc == DXT5: return "DXT5"
    if fourcc == ATI2: return "ATI2"
    if fourcc == 0: return "RGB32"
    return f"0x{fourcc:08x}"

def create_dds_header(width, height, fourcc, mipmap_count=1):
    """Create a DDS header for the given format."""
    # This function kept for potential future use with stream file extraction
    pass  # Not currently used


def extract_textures(bundle_path, output_folder=None, identify_only=False):
    """Extract all textures from a bundle."""
    bundle_name = os.path.basename(bundle_path)
    
    if output_folder is None:
        output_folder = os.path.join("extracted", bundle_name)
    
    # Read and decompress bundle using bundle_tools
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    print(f"Bundle: {bundle_path}")
    print(f"Packed size: {len(packed_data):,} bytes")
    
    data = bt_decompress(packed_data)
    print(f"Unpacked size: {len(data):,} bytes")
    print()
    
    # Check for stream file
    stream_path = bundle_path + ".stream"
    stream_data = None
    if os.path.exists(stream_path):
        with open(stream_path, 'rb') as f:
            stream_data = f.read()
        print(f"Stream file: {len(stream_data):,} bytes")
        print()
    
    # Parse bundle header (same format as list_textures.py)
    count = struct.unpack('<I', data[:4])[0]
    print(f"Total resources in bundle: {count}")
    
    # Build header entry set (resource index at 0x104)
    TEXTURE_TYPE = 0xCD4238C6A0C69E32
    header_entries = set()
    texture_hashes = set()
    
    for i in range(count):
        pos = 0x104 + i * 16
        if pos + 16 > len(data):
            break
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        header_entries.add((type_hash, name_hash))
        if type_hash == TEXTURE_TYPE:
            texture_hashes.add(name_hash)
    
    print(f"Textures found: {len(texture_hashes)}")
    print()
    
    if not texture_hashes:
        print("No textures in this bundle!")
        return
    
    if not identify_only:
        os.makedirs(output_folder, exist_ok=True)
        print(f"Extracting to: {output_folder}")
        print()
    
    # Parse resources (after header index)
    pos = 0x104 + count * 16
    extracted = 0
    
    while pos + 36 <= len(data):
        if pos + 20 > len(data):
            break
            
        type_hash, name_hash, flags = struct.unpack('<QQI', data[pos:pos+20])
        
        # Validate this is a real resource entry
        if (type_hash, name_hash) not in header_entries:
            pos += 1
            continue
        
        # Read sizes
        stream_size = struct.unpack('<Q', data[pos+20:pos+28])[0]
        main_size = struct.unpack('<I', data[pos+28:pos+32])[0]
        
        # Check if this is a texture
        if type_hash == TEXTURE_TYPE:
            hash_str = f"{name_hash:016x}"
            
            # The resource data starts at pos+36 and is a complete DDS file
            dds_data = data[pos+36:pos+36+main_size]
            
            if dds_data[:4] == b'DDS ':
                # Parse DDS header
                height = struct.unpack('<I', dds_data[12:16])[0]
                width = struct.unpack('<I', dds_data[16:20])[0]
                mip_count = struct.unpack('<I', dds_data[28:32])[0]
                fourcc_bytes = dds_data[84:88]
                
                try:
                    fmt_name = fourcc_bytes.decode('ascii').strip('\x00')
                except:
                    fmt_name = "RGB32" if fourcc_bytes == b'\x00\x00\x00\x00' else "UNK"
                
                if not fmt_name:
                    fmt_name = "RGB32"
                
                if identify_only:
                    stream_note = " [streaming]" if stream_size > 0 else ""
                    print(f"  {hash_str}: {width}x{height} {fmt_name} ({mip_count} mips){stream_note}")
                else:
                    # Save DDS file
                    # If streaming, we need to combine main data with stream data
                    if stream_size > 0 and stream_data is not None:
                        # Main file has header + low-res mips
                        # Stream has high-res mip data
                        # For now, just save what we have in main
                        pass  # Use main DDS as-is
                    
                    output_path = os.path.join(output_folder, f"{hash_str}.dds")
                    with open(output_path, 'wb') as f:
                        f.write(dds_data)
                    
                    print(f"  {hash_str}: {width}x{height} {fmt_name}")
                    extracted += 1
            else:
                print(f"  {hash_str}: Not a valid DDS (magic: {dds_data[:4]})")
        
        pos += 36 + main_size
    
    if not identify_only:
        print()
        print(f"Extracted {extracted} textures to {output_folder}")
        print()
        print("TIP: View these with any DDS viewer, or convert to PNG with tools like:")
        print("  - texconv.exe (Microsoft DirectXTex)")
        print("  - GIMP with DDS plugin")
        print("  - XnView / IrfanView with plugins")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    bundle_path = sys.argv[1]
    
    if not os.path.exists(bundle_path):
        print(f"Error: Bundle not found: {bundle_path}")
        sys.exit(1)
    
    identify_only = "--identify" in sys.argv
    
    output_folder = None
    for arg in sys.argv[2:]:
        if not arg.startswith("--"):
            output_folder = arg
            break
    
    extract_textures(bundle_path, output_folder, identify_only)

if __name__ == "__main__":
    main()
