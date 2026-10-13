"""
Gauntlet Bundle Tools
Utilities for unpacking and analyzing Bitsquid/Stingray bundle files.

Based on analysis of the Gauntlet game files and the C++ unpacker by iamlupo.
"""

import zlib
import struct
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

# Bundle signatures
BUNDLE_SIG_OLD = 0xF0000004
BUNDLE_SIG_NEW = 0xF0000005
ZLIB_CHUNK = 0x10000  # 64KB chunks

@dataclass
class BundleHeader:
    signature: int
    unzipped_size: int
    padding: int
    
    @property
    def is_valid(self) -> bool:
        return self.signature in (BUNDLE_SIG_OLD, BUNDLE_SIG_NEW)
    
    @property
    def signature_name(self) -> str:
        if self.signature == BUNDLE_SIG_OLD:
            return "OLD (0xF0000004)"
        elif self.signature == BUNDLE_SIG_NEW:
            return "NEW (0xF0000005)"
        return f"UNKNOWN (0x{self.signature:08X})"


@dataclass 
class ResourceEntry:
    """Represents a resource entry in an unpacked bundle"""
    type_hash: int      # 8 bytes - resource type (murmurhash64)
    name_hash: int      # 8 bytes - resource name (murmurhash64)
    flags: int          # 4 bytes - flags
    size: int           # Size of the resource data
    offset: int         # Offset in the unpacked data
    data: bytes         # Raw resource data


def murmur_hash64(key: str, seed: int = 0) -> int:
    """
    MurmurHash64A implementation for matching Bitsquid resource names.
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


# Known resource type hashes (from Vermintide/Bitsquid documentation)
KNOWN_TYPES = {
    murmur_hash64("lua"): "lua",
    murmur_hash64("unit"): "unit", 
    murmur_hash64("texture"): "texture",
    murmur_hash64("material"): "material",
    murmur_hash64("shader"): "shader",
    murmur_hash64("animation"): "animation",
    murmur_hash64("bones"): "bones",
    murmur_hash64("state_machine"): "state_machine",
    murmur_hash64("package"): "package",
    murmur_hash64("level"): "level",
    murmur_hash64("physics"): "physics",
    murmur_hash64("sound"): "sound",
    murmur_hash64("font"): "font",
    murmur_hash64("strings"): "strings",
    murmur_hash64("config"): "config",
    murmur_hash64("flow"): "flow",
    murmur_hash64("network_config"): "network_config",
    murmur_hash64("timpani_bank"): "timpani_bank",
    murmur_hash64("timpani_master"): "timpani_master",
    murmur_hash64("render_config"): "render_config",
    murmur_hash64("particles"): "particles",
    murmur_hash64("bik"): "bik",
    murmur_hash64("wwise_bank"): "wwise_bank",
    murmur_hash64("wwise_stream"): "wwise_stream",
    murmur_hash64("wwise_dep"): "wwise_dep",
    murmur_hash64("wwise_metadata"): "wwise_metadata",
    murmur_hash64("scene"): "scene",
    murmur_hash64("shading_environment"): "shading_environment",
    murmur_hash64("shading_environment_mapping"): "shading_environment_mapping",
    murmur_hash64("physx_metadata"): "physx_metadata",
    murmur_hash64("navmesh"): "navmesh",
}


def read_bundle_header(data: bytes) -> BundleHeader:
    """Read the 12-byte bundle header"""
    if len(data) < 12:
        raise ValueError("Data too small for bundle header")
    
    signature, unzipped_size, padding = struct.unpack('<III', data[:12])
    return BundleHeader(signature, unzipped_size, padding)


def decompress_bundle(packed_data: bytes) -> bytes:
    """
    Decompress a packed bundle file.
    
    Bundle format:
    - 12 byte header (signature, unzipped_size, padding)
    - Sequence of zlib chunks, each prefixed with 4-byte size
    """
    header = read_bundle_header(packed_data)
    
    if not header.is_valid:
        raise ValueError(f"Invalid bundle signature: 0x{header.signature:08X}")
    
    print(f"Bundle Header:")
    print(f"  Signature: {header.signature_name}")
    print(f"  Unzipped size: {header.unzipped_size:,} bytes")
    print(f"  Padding: {header.padding}")
    
    # Decompress zlib chunks
    offset = 12  # Skip header
    unpacked_chunks = []
    chunk_num = 0
    
    while offset < len(packed_data):
        # Read chunk size
        chunk_size = struct.unpack('<I', packed_data[offset:offset+4])[0]
        offset += 4
        
        if chunk_size == ZLIB_CHUNK:
            # This is just a marker, skip it
            continue
            
        if chunk_size == 0:
            break
            
        # Read and decompress the chunk
        chunk_data = packed_data[offset:offset + chunk_size]
        offset += chunk_size
        chunk_num += 1
        
        try:
            decompressed = zlib.decompress(chunk_data)
            unpacked_chunks.append(decompressed)
        except zlib.error as e:
            print(f"  Warning: Chunk {chunk_num} decompression failed: {e}")
            # Try raw deflate
            try:
                decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                decompressed = decompressor.decompress(chunk_data)
                unpacked_chunks.append(decompressed)
            except:
                print(f"  Error: Could not decompress chunk {chunk_num}")
                break
    
    print(f"  Decompressed {chunk_num} chunks")
    
    result = b''.join(unpacked_chunks)
    print(f"  Total unpacked size: {len(result):,} bytes")
    
    return result


def compress_bundle(unpacked_data: bytes, signature: int = BUNDLE_SIG_OLD) -> bytes:
    """
    Compress data into a bundle file.
    """
    chunks = []
    
    # Create header
    header = struct.pack('<III', signature, len(unpacked_data), 0)
    chunks.append(header)
    
    # Compress in 64KB chunks
    offset = 0
    while offset < len(unpacked_data):
        chunk = unpacked_data[offset:offset + ZLIB_CHUNK]
        # Pad to ZLIB_CHUNK if this is not the last chunk or if it's partial
        if len(chunk) < ZLIB_CHUNK:
            chunk = chunk + b'\x00' * (ZLIB_CHUNK - len(chunk))
        
        compressed = zlib.compress(chunk)
        
        # Write chunk size and data
        chunks.append(struct.pack('<I', len(compressed)))
        chunks.append(compressed)
        
        offset += ZLIB_CHUNK
    
    return b''.join(chunks)


def analyze_unpacked_bundle(data: bytes) -> List[Dict]:
    """
    Analyze the structure of unpacked bundle data.
    Returns information about the resources contained.
    """
    resources = []
    
    if len(data) < 8:
        return resources
    
    # The unpacked bundle starts with resource entries
    # Each entry has: type_hash (8), name_hash (8), flags (4), size (4), padding (4)
    # Total: 28 bytes per entry header (may vary by version)
    
    print("\nAnalyzing unpacked bundle structure...")
    print(f"First 64 bytes (hex): {data[:64].hex()}")
    
    # Try to detect the resource table structure
    # In Bitsquid, bundles typically have a resource table at the start
    
    # Check for potential file magic / count at the start
    potential_count = struct.unpack('<I', data[:4])[0]
    print(f"\nFirst 4 bytes as uint32: {potential_count}")
    
    # Look for patterns that might indicate resource entries
    # Each resource should have two 64-bit hashes (type and name)
    
    if len(data) >= 24:
        # Try reading first potential resource entry
        type_hash = struct.unpack('<Q', data[0:8])[0]
        name_hash = struct.unpack('<Q', data[8:16])[0]
        flags_or_size = struct.unpack('<I', data[16:20])[0]
        
        type_name = KNOWN_TYPES.get(type_hash, f"0x{type_hash:016X}")
        
        print(f"\nPotential first resource:")
        print(f"  Type hash: 0x{type_hash:016X} ({type_name})")
        print(f"  Name hash: 0x{name_hash:016X}")
        print(f"  Flags/Size: {flags_or_size}")
    
    return resources


def find_textures_in_bundle(data: bytes) -> List[Tuple[int, str]]:
    """
    Search for DDS texture signatures in unpacked bundle data.
    DDS files start with "DDS " (0x44445320)
    """
    dds_magic = b'DDS '
    textures = []
    
    offset = 0
    while True:
        pos = data.find(dds_magic, offset)
        if pos == -1:
            break
        textures.append((pos, "DDS texture"))
        offset = pos + 4
    
    return textures


def unpack_bundle_file(input_path: str, output_path: str) -> bool:
    """
    Unpack a bundle file to disk.
    """
    print(f"\nUnpacking: {input_path}")
    
    with open(input_path, 'rb') as f:
        packed_data = f.read()
    
    try:
        unpacked_data = decompress_bundle(packed_data)
        
        with open(output_path, 'wb') as f:
            f.write(unpacked_data)
        
        print(f"Saved to: {output_path}")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False


def pack_bundle_file(input_path: str, output_path: str, signature: int = BUNDLE_SIG_OLD) -> bool:
    """
    Pack a raw data file into a bundle.
    """
    print(f"\nPacking: {input_path}")
    
    with open(input_path, 'rb') as f:
        unpacked_data = f.read()
    
    try:
        packed_data = compress_bundle(unpacked_data, signature)
        
        with open(output_path, 'wb') as f:
            f.write(packed_data)
        
        print(f"Saved to: {output_path}")
        print(f"  Original size: {len(unpacked_data):,} bytes")
        print(f"  Packed size: {len(packed_data):,} bytes")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False


def analyze_bundle_file(path: str) -> None:
    """
    Analyze a bundle file and print information about its contents.
    """
    print(f"\n{'='*60}")
    print(f"Analyzing: {path}")
    print(f"{'='*60}")
    
    with open(path, 'rb') as f:
        packed_data = f.read()
    
    print(f"File size: {len(packed_data):,} bytes")
    
    try:
        unpacked_data = decompress_bundle(packed_data)
        
        # Analyze structure
        analyze_unpacked_bundle(unpacked_data)
        
        # Look for textures
        textures = find_textures_in_bundle(unpacked_data)
        if textures:
            print(f"\nFound {len(textures)} DDS textures:")
            for offset, desc in textures[:10]:  # Show first 10
                print(f"  Offset 0x{offset:08X}: {desc}")
            if len(textures) > 10:
                print(f"  ... and {len(textures) - 10} more")
        
    except Exception as e:
        print(f"Error: {e}")


def list_bundles(contents_dir: str) -> List[str]:
    """
    List all bundle files in a Gauntlet contents directory.
    """
    bundles = []
    path = Path(contents_dir)
    
    for f in path.iterdir():
        if f.is_file() and not f.suffix and len(f.name) == 16:
            # Likely a bundle file (16 hex chars, no extension)
            bundles.append(f.name)
    
    return sorted(bundles)


if __name__ == "__main__":
    import sys
    
    # Default Gauntlet contents path
    GAUNTLET_CONTENTS = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            print("Bundles in Gauntlet contents directory:")
            for bundle in list_bundles(GAUNTLET_CONTENTS):
                print(f"  {bundle}")
                
        elif command == "analyze" and len(sys.argv) > 2:
            bundle_name = sys.argv[2]
            bundle_path = os.path.join(GAUNTLET_CONTENTS, bundle_name)
            if os.path.exists(bundle_path):
                analyze_bundle_file(bundle_path)
            else:
                print(f"Bundle not found: {bundle_path}")
                
        elif command == "unpack" and len(sys.argv) > 3:
            input_path = sys.argv[2]
            output_path = sys.argv[3]
            unpack_bundle_file(input_path, output_path)
            
        elif command == "pack" and len(sys.argv) > 3:
            input_path = sys.argv[2]
            output_path = sys.argv[3]
            pack_bundle_file(input_path, output_path)
            
        else:
            print("Usage:")
            print("  python bundle_tools.py list")
            print("  python bundle_tools.py analyze <bundle_name>")
            print("  python bundle_tools.py unpack <input_path> <output_path>")
            print("  python bundle_tools.py pack <input_path> <output_path>")
    else:
        # Demo: analyze a bundle
        print("Gauntlet Bundle Tools")
        print("=====================")
        print()
        
        bundles = list_bundles(GAUNTLET_CONTENTS)
        print(f"Found {len(bundles)} bundles in Gauntlet contents directory")
        
        if bundles:
            # Analyze the first small bundle we find
            for bundle in bundles:
                bundle_path = os.path.join(GAUNTLET_CONTENTS, bundle)
                size = os.path.getsize(bundle_path)
                if size < 1_000_000:  # Less than 1MB
                    analyze_bundle_file(bundle_path)
                    break
