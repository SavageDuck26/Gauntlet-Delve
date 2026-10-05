#!/usr/bin/env python3
"""
================================================================================
GAUNTLET FULL BUNDLE/MOD CREATION SYSTEM
================================================================================
Creates complete bundle files for Gauntlet Slayer Edition.

Based on reverse engineering of:
- Gauntlet's Bitsquid engine (0xF0000004 format)
- Vermintide 2's Stingray mod_bundle format (0xF0000006 - for reference)
- Working mod analysis from Vermintide 2 "Loremaster's Armoury" mod

================================================================================
GAUNTLET BUNDLE FORMAT (0xF0000004 - "OLD" Bitsquid Format)
================================================================================

COMPRESSED BUNDLE STRUCTURE:
    [0:4]   uint32: Signature = 0xF0000004
    [4:8]   uint32: Uncompressed size
    [8:12]  uint32: Padding (0)
    [12:]   Zlib compressed chunks:
            - Each chunk: [4-byte size][zlib data]
            - Chunks are 64KB uncompressed

UNCOMPRESSED BUNDLE STRUCTURE (confirmed by byte-level reverse engineering):

    [0x000:0x004]  uint32: Resource count N
    [0x004:0x058]  84-byte preamble (zeros for custom; native bundles have hash-like data)
    [0x058:0x104]  Zero padding (172 bytes)
    [0x104:]       TOC: (N+1) x 16-byte entries {type_hash(8), name_hash(8)}
                   entry[N] = sentinel = copy of entry[0]
    [toc_end:]     Resource-0 metadata (20 bytes):
                       {flags(4), zeros(8), data_sz(4), stream_sz(4)}
    [toc_end+20:]  Resource-0 data (data_sz bytes)
    [after res-0:] For each resource i in 1..N-1:
                       36-byte header {type(8), name(8), flags(4), zeros(8), data_sz(4), stream_sz(4)}
                       + data (data_sz bytes)

================================================================================
VERMINTIDE MOD_BUNDLE FORMAT (0xF0000006 - for reference)
================================================================================

The Vermintide 2 mod_bundle format is different:
- Signature: 0xF0000006
- No name hash table (zeros padding to 0x104)
- 24-byte entry format: type(8) + name(8) + flags(4) + size(4)
- Resource data directly follows entries (no per-resource headers)
- Textures have custom header before DDS data

This script focuses on Gauntlet's 0xF0000004 format.

================================================================================
RESOURCE TYPES
================================================================================

Type Name       Hash Value              Notes
---------------------------------------------------------------------------
texture         0xCD4238C6A0C69E32      DDS format, stored directly
material        0xEAC0B497876ADEDF      References textures/shaders
package         0xAD9C6D9ED1E5E77A      Lists resources to load together
lua             0xA14E8DFA2CD117E2      Compiled Lua scripts
unit            0xE0A48D0BE9A7453F      3D models with mesh data
shader          0xCCE8D5B5F5AE333F      Shader programs
animation       0x931E336D7646CC26      Animation data
bones           0x18DEAD01056B72E9      Skeleton data

================================================================================
USAGE
================================================================================

# Create a texture replacement bundle:
python create_full_bundle_system.py create_texture_bundle \\
    --folder my_textures \\
    --name my_mod \\
    --replace

# Create a bundle with Lua scripts:
python create_full_bundle_system.py create_lua_bundle \\
    --folder my_scripts \\
    --name my_mod

# Analyze an existing bundle:
python create_full_bundle_system.py analyze \\
    --bundle path/to/bundle

# Create a complete mod with multiple resource types:
python create_full_bundle_system.py create_mod \\
    --config mod_config.json

================================================================================
"""

import struct
import zlib
import os
import sys
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
import argparse

# ============================================================================
# CONSTANTS
# ============================================================================

# Bundle signatures
BUNDLE_SIG_OLD = 0xF0000004      # Gauntlet uses this
BUNDLE_SIG_NEW = 0xF0000005      # Later Bitsquid games
BUNDLE_SIG_MOD = 0xF0000006      # Vermintide 2 mod_bundle

ZLIB_CHUNK = 0x10000  # 64KB chunks

# Resource type hashes (MurmurHash64 of type name)
RESOURCE_TYPES = {
    "texture":        0xCD4238C6A0C69E32,
    "material":       0xEAC0B497876ADEDF,
    "package":        0xAD9C6D9ED1E5E77A,
    "lua":            0xA14E8DFA2CD117E2,
    "unit":           0xE0A48D0BE9A7453F,
    "mesh":           0x48FF313713A997A1,
    "shader":         0xCCE8D5B5F5AE333F,
    "animation":      0x931E336D7646CC26,
    "bones":          0x18DEAD01056B72E9,
    "level":          0x2A690FD348FE9AC5,
    "physics":        0x5F7203C8F280DAB8,
    "config":         0x82645835E6B73232,
    "font":           0x9EFE0A916AAE7880,
    "strings":        0x0D972BAB10B40FD3,
    "particles":      0xA8193123526FAD64,
    "wwise_bank":     0xA4F6EC21F1D51F87,
    "wwise_stream":   0xBABF50B45F1D9B7C,
    "render_config":  0x27862FE24795319C,
}

# Reverse lookup
TYPE_NAMES = {v: k for k, v in RESOURCE_TYPES.items()}

# ThinHash for texture slots (upper 32 bits of MurmurHash64)
THINHASH_DIFFUSE = 0x3aa8b87e
THINHASH_NORMAL = 0xf5c97d31
THINHASH_SPECULAR = 0x50968221
THINHASH_EMISSIVE = 0x4dc19f08

# Shader hashes from working game materials
SHADER_DIFFUSE_SIMPLE = 0xBA25DE3579DC6624

# ============================================================================
# MURMURHASH64 IMPLEMENTATION
# ============================================================================

def murmur_hash64(key: str, seed: int = 0) -> int:
    """
    MurmurHash64A - the hash algorithm used by Bitsquid/Stingray.
    All resource names are hashed with this function.
    
    Example:
        murmur_hash64("texture") = 0xCD4238C6A0C69E32
        murmur_hash64("characters/avatar_warrior/warrior_diff") = 0x67111D9E39E1CABC
    """
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

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Resource:
    """Represents a resource in a bundle."""
    type_name: str
    type_hash: int
    name: str
    name_hash: int
    data: bytes
    flags: int = 1
    stream_size: int = 0
    
    @classmethod
    def create(cls, resource_type: str, name: str, data: bytes, **kwargs):
        """Create a resource with automatic hash computation."""
        type_hash = RESOURCE_TYPES.get(resource_type.lower())
        if type_hash is None:
            raise ValueError(f"Unknown resource type: {resource_type}")
        
        return cls(
            type_name=resource_type.lower(),
            type_hash=type_hash,
            name=name,
            name_hash=murmur_hash64(name),
            data=data,
            **kwargs
        )

@dataclass
class BundleInfo:
    """Information about a bundle."""
    path: str
    signature: int
    uncompressed_size: int
    resource_count: int
    resources: List[Dict] = field(default_factory=list)

# ============================================================================
# BUNDLE COMPRESSION/DECOMPRESSION
# ============================================================================

def decompress_bundle(packed_data: bytes) -> bytes:
    """Decompress a packed bundle file."""
    if len(packed_data) < 12:
        raise ValueError("Data too small for bundle header")
    
    sig, unzip_size, padding = struct.unpack('<III', packed_data[:12])
    
    if sig not in (BUNDLE_SIG_OLD, BUNDLE_SIG_NEW, BUNDLE_SIG_MOD):
        raise ValueError(f"Invalid bundle signature: 0x{sig:08X}")
    
    # Decompress zlib chunks
    offset = 12
    chunks = []
    
    while offset < len(packed_data):
        if offset + 4 > len(packed_data):
            break
            
        chunk_size = struct.unpack('<I', packed_data[offset:offset+4])[0]
        offset += 4
        
        if chunk_size == ZLIB_CHUNK or chunk_size == 0:
            continue
        
        if chunk_size > len(packed_data) - offset:
            break
            
        try:
            chunk = zlib.decompress(packed_data[offset:offset + chunk_size])
            chunks.append(chunk)
        except zlib.error:
            break
            
        offset += chunk_size
    
    return b''.join(chunks)


def compress_bundle(unpacked_data: bytes, signature: int = BUNDLE_SIG_OLD) -> bytes:
    """Compress data into a bundle file."""
    chunks = []
    
    # Header
    header = struct.pack('<III', signature, len(unpacked_data), 0)
    chunks.append(header)
    
    # Compress in 64KB chunks
    offset = 0
    while offset < len(unpacked_data):
        chunk = unpacked_data[offset:offset + ZLIB_CHUNK]
        compressed = zlib.compress(chunk, 6)
        chunks.append(struct.pack('<I', len(compressed)))
        chunks.append(compressed)
        offset += ZLIB_CHUNK
    
    return b''.join(chunks)

# ============================================================================
# BUNDLE BUILDING (GAUNTLET FORMAT)
# ============================================================================

def build_bundle(resources: List[Resource]) -> bytes:
    """
    Build an uncompressed bundle body for Gauntlet's 0xF0000004 format.

    Confirmed layout (reverse-engineered from native bundles):
        [0x000:0x004]  uint32 N  — resource count
        [0x004:0x058]  84-byte preamble (zeros for custom bundles)
        [0x058:0x104]  zeros (padding to 0x104)
        [0x104:]       (N+1) × 16-byte TOC {type(8), name(8)}
                       entry[N] = sentinel = copy of entry[0]
        [toc_end:]     20-byte resource-0 metadata:
                           {flags(4), zeros(8), data_sz(4), stream_sz(4)}
        [toc_end+20:]  resource-0 data
        [after res-0:] for each remaining resource i in 1..N-1:
                           36-byte header {type(8), name(8), flags(4),
                                           zeros(8), data_sz(4), stream_sz(4)}
                           + data bytes
    """
    if not resources:
        raise ValueError("No resources to pack")

    count = len(resources)
    sorted_resources = sorted(resources, key=lambda r: r.name_hash)

    buf = bytearray()

    # 1. Resource count
    buf += struct.pack('<I', count)

    # 2. Preamble: 84 bytes zeros + padding to 0x104
    buf += b'\x00' * (0x104 - 4)

    # 3. TOC: (N+1) entries — last entry is a sentinel = copy of entry[0]
    for res in sorted_resources:
        buf += struct.pack('<QQ', res.type_hash, res.name_hash)
    # sentinel
    buf += struct.pack('<QQ', sorted_resources[0].type_hash, sorted_resources[0].name_hash)

    # 4. Resource-0: 20-byte metadata (no type/name), then data
    res0 = sorted_resources[0]
    data_sz0 = len(res0.data)
    buf += struct.pack('<IQII',
        res0.flags,      # 4 bytes  flags
        0,               # 8 bytes  zeros
        data_sz0,        # 4 bytes  data size
        0,               # 4 bytes  stream size
    )
    buf += res0.data

    # 5. Resources 1..N-1: 36-byte header then data
    for res in sorted_resources[1:]:
        data_sz = len(res.data)
        buf += struct.pack('<QQIQII',
            res.type_hash,  # 8 bytes
            res.name_hash,  # 8 bytes
            res.flags,      # 4 bytes
            0,              # 8 bytes zeros
            data_sz,        # 4 bytes
            0,              # 4 bytes stream size
        )
        buf += res.data

    # Align to 4 bytes
    rem = len(buf) % 4
    if rem:
        buf += b'\x00' * (4 - rem)

    return bytes(buf)

# ============================================================================
# BUNDLE ANALYSIS
# ============================================================================

def analyze_bundle(bundle_path: str) -> BundleInfo:
    """Analyze a bundle file and return detailed information."""
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    sig = struct.unpack('<I', packed_data[:4])[0]
    unzip_size = struct.unpack('<I', packed_data[4:8])[0]
    
    unpacked = decompress_bundle(packed_data)
    
    resource_count = struct.unpack('<I', unpacked[:4])[0]
    
    info = BundleInfo(
        path=bundle_path,
        signature=sig,
        uncompressed_size=unzip_size,
        resource_count=resource_count,
        resources=[]
    )
    
    # Parse based on bundle format
    if sig == BUNDLE_SIG_OLD:
        # Gauntlet 0xF0000004 format (confirmed layout):
        #   [0x104] (N+1) × 16-byte TOC entries; entry[N] = sentinel = copy of entry[0]
        #   [toc_end] resource-0: 20-byte metadata {flags(4), zeros(8), data_sz(4), stream_sz(4)}
        #   [after res-0] resources 1..N-1: 36-byte header {type(8),name(8),flags(4),zeros(8),data_sz(4),stream_sz(4)}
        toc_start = 0x104
        toc_end   = toc_start + (resource_count + 1) * 16  # N+1 entries (sentinel)

        data_offset = toc_end
        for i in range(resource_count):
            entry_ofs = toc_start + i * 16
            type_h = struct.unpack('<Q', unpacked[entry_ofs:entry_ofs+8])[0]
            name_h = struct.unpack('<Q', unpacked[entry_ofs+8:entry_ofs+16])[0]

            if i == 0:
                # 20-byte resource-0 metadata: {flags(4), zeros(8), data_sz(4), stream_sz(4)}
                if data_offset + 20 > len(unpacked):
                    break
                rh_flags  = struct.unpack('<I', unpacked[data_offset:data_offset+4])[0]
                rh_size   = struct.unpack('<I', unpacked[data_offset+12:data_offset+16])[0]
                rh_stream = struct.unpack('<I', unpacked[data_offset+16:data_offset+20])[0]
                type_name = TYPE_NAMES.get(type_h, f"0x{type_h:016X}")
                info.resources.append({
                    "index": i,
                    "type": type_name,
                    "type_hash": f"0x{type_h:016X}",
                    "name_hash": f"0x{name_h:016X}",
                    "flags": rh_flags,
                    "stream_size": rh_stream,
                    "data_size": rh_size,
                    "data_offset": data_offset + 20,
                })
                data_offset += 20 + rh_size
            else:
                # 36-byte header: {type(8), name(8), flags(4), zeros(8), data_sz(4), stream_sz(4)}
                if data_offset + 36 > len(unpacked):
                    break
                rh_type   = struct.unpack('<Q', unpacked[data_offset:data_offset+8])[0]
                rh_name   = struct.unpack('<Q', unpacked[data_offset+8:data_offset+16])[0]
                rh_flags  = struct.unpack('<I', unpacked[data_offset+16:data_offset+20])[0]
                rh_size   = struct.unpack('<I', unpacked[data_offset+28:data_offset+32])[0]
                rh_stream = struct.unpack('<I', unpacked[data_offset+32:data_offset+36])[0]
                type_name = TYPE_NAMES.get(rh_type, f"0x{rh_type:016X}")
                info.resources.append({
                    "index": i,
                    "type": type_name,
                    "type_hash": f"0x{rh_type:016X}",
                    "name_hash": f"0x{rh_name:016X}",
                    "flags": rh_flags,
                    "stream_size": rh_stream,
                    "data_size": rh_size,
                    "data_offset": data_offset + 36,
                })
                data_offset += 36 + rh_size

    elif sig == BUNDLE_SIG_MOD:
        # Vermintide mod_bundle format (24-byte entries)
        entry_table_start = 0x104
        res_data_start = entry_table_start + resource_count * 24

        data_offset = res_data_start
        for i in range(resource_count):
            entry_ofs = entry_table_start + i * 24
            type_h = struct.unpack('<Q', unpacked[entry_ofs:entry_ofs+8])[0]
            name_h = struct.unpack('<Q', unpacked[entry_ofs+8:entry_ofs+16])[0]
            flags  = struct.unpack('<I', unpacked[entry_ofs+16:entry_ofs+20])[0]
            size   = struct.unpack('<I', unpacked[entry_ofs+20:entry_ofs+24])[0]
            type_name = TYPE_NAMES.get(type_h, f"0x{type_h:016X}")
            info.resources.append({
                "index": i,
                "type": type_name,
                "type_hash": f"0x{type_h:016X}",
                "name_hash": f"0x{name_h:016X}",
                "flags": flags,
                "data_size": size,
                "data_offset": data_offset,
            })
            data_offset += size

    return info

# ============================================================================
# RESOURCE BUILDERS
# ============================================================================

def create_texture_resource(dds_path: str, resource_name: str) -> Resource:
    """Create a texture resource from a DDS file."""
    with open(dds_path, 'rb') as f:
        data = f.read()
    
    if data[:4] != b'DDS ':
        raise ValueError(f"Not a valid DDS file: {dds_path}")
    
    return Resource.create("texture", resource_name, data)


def create_package_resource(package_name: str,
                            resource_list: List[tuple] = None,
                            texture_names: List[str] = None,
                            material_names: List[str] = None) -> Resource:
    """
    Create a package resource that lists other resources to load.

    Confirmed format (reverse-engineered from native bundles):
        uint32 N
        N x 28-byte entries:
            uint64  type_hash
            uint64  name_hash
            uint32  c1         = always 2
            uint32  c2         = 0 for custom bundles (engine doesn't validate at runtime)
            uint32  name_hi32  = name_hash >> 32
        uint8 trailing = 0x01

    Args:
        package_name:  Resource path for this package.
        resource_list: List of (type_name_str, resource_path_str) tuples.
        texture_names: Shorthand for texture entries.
        material_names: Shorthand for material entries.
    """
    entries_raw = []

    def _add(type_hash: int, name_hash: int) -> None:
        entries_raw.append(struct.pack('<QQIII',
            type_hash,
            name_hash,
            2,                    # c1 = always 2
            0,                    # c2 = 0 (safe for custom bundles)
            name_hash >> 32,      # name_hi32
        ))

    if resource_list:
        for type_name, res_path in resource_list:
            _add(RESOURCE_TYPES[type_name], murmur_hash64(res_path))

    if texture_names:
        for name in texture_names:
            _add(RESOURCE_TYPES["texture"], murmur_hash64(name))

    if material_names:
        for name in material_names:
            _add(RESOURCE_TYPES["material"], murmur_hash64(name))

    data  = struct.pack('<I', len(entries_raw))
    data += b''.join(entries_raw)
    data += b'\x01'  # confirmed trailing byte

    return Resource.create("package", package_name, data)


def create_material_resource(material_name: str, texture_hash: int) -> Resource:
    """
    Create a simple diffuse material that references a texture.
    
    Material format (52 bytes):
        uint32: version (10)
        uint32: section_count (1)
        uint64: shader_hash
        uint64: padding
        uint32: slot_index (1)
        uint32: thin_hash (diffuse_map)
        uint64: texture_hash
        12 bytes: zeros
    """
    data = struct.pack('<I', 0x0A)  # Version
    data += struct.pack('<I', 1)     # Section count
    data += struct.pack('<Q', SHADER_DIFFUSE_SIMPLE)
    data += struct.pack('<Q', 0)     # Padding
    data += struct.pack('<I', 1)     # Slot index (MUST be 1!)
    data += struct.pack('<I', THINHASH_DIFFUSE)
    data += struct.pack('<Q', texture_hash)
    data += b'\x00' * 12
    
    return Resource.create("material", material_name, data)

# ============================================================================
# HIGH-LEVEL BUNDLE CREATION
# ============================================================================

def create_texture_bundle(texture_folder: str, 
                         bundle_name: str,
                         output_dir: str = ".",
                         replacement_mode: bool = False,
                         prefix: str = "custom",
                         with_materials: bool = False) -> Dict[str, Any]:
    """
    Create a complete texture bundle with package resource.
    
    Args:
        texture_folder: Folder containing DDS textures
        bundle_name: Name for the package
        output_dir: Output directory
        replacement_mode: Use original game paths for hash collision
        prefix: Prefix for new content paths
        with_materials: Also create material resources for GUI usage
    
    Returns:
        Manifest dictionary with all resource information
    """
    folder = Path(texture_folder)
    if not folder.exists():
        raise ValueError(f"Folder not found: {texture_folder}")
    
    # Collect DDS files
    dds_files = list(folder.glob('**/*.dds')) + list(folder.glob('**/*.DDS'))
    if not dds_files:
        raise ValueError(f"No DDS files found in: {texture_folder}")
    
    # Build package path
    if replacement_mode:
        package_path = f"resource_packages/replacements/{bundle_name}"
        texture_prefix = ""
    else:
        package_path = f"resource_packages/{prefix}/{bundle_name}"
        texture_prefix = f"{prefix}/{bundle_name}/"
    
    package_hash = murmur_hash64(package_path)
    bundle_filename = f"{package_hash:016x}"
    
    print(f"\n{'='*70}")
    print(f"Creating Texture Bundle: {bundle_name}")
    print(f"{'='*70}")
    print(f"Package path: {package_path}")
    print(f"Package hash: 0x{package_hash:016X}")
    print(f"Bundle file: {bundle_filename}")
    print(f"Mode: {'REPLACEMENT' if replacement_mode else 'NEW CONTENT'}")
    print()
    
    # Create resources
    resources = []
    textures = []
    
    print("Processing textures:")
    for dds_path in sorted(dds_files):
        # Build resource name
        rel_path = dds_path.relative_to(folder)
        name_parts = list(rel_path.parts)
        name_parts[-1] = rel_path.stem
        
        if replacement_mode:
            resource_name = '/'.join(name_parts)
        else:
            resource_name = texture_prefix + '/'.join(name_parts)
        
        resource_name = resource_name.replace('\\', '/')
        
        try:
            tex_res = create_texture_resource(str(dds_path), resource_name)
            resources.append(tex_res)
            textures.append({
                "name": resource_name,
                "hash": tex_res.name_hash,
                "file": dds_path.name,
                "size": len(tex_res.data)
            })
            print(f"  ✓ {dds_path.name} → {resource_name}")
            print(f"    Hash: 0x{tex_res.name_hash:016X}")
        except Exception as e:
            print(f"  ✗ {dds_path.name}: {e}")
    
    if not resources:
        raise ValueError("No valid textures processed")
    
    # Create materials if requested
    materials = []
    if with_materials:
        print("\nCreating materials:")
        for tex in textures:
            mat_name = Path(tex["name"]).stem
            mat_res = create_material_resource(mat_name, tex["hash"])
            resources.append(mat_res)
            materials.append({
                "name": mat_name,
                "hash": mat_res.name_hash,
                "texture_hash": tex["hash"]
            })
            print(f"  ✓ {mat_name} → 0x{mat_res.name_hash:016X}")
    
    # Create package resource
    texture_names = [t["name"] for t in textures]
    material_names = [m["name"] for m in materials]
    pkg_res = create_package_resource(package_path, texture_names, material_names)
    resources.insert(0, pkg_res)
    
    print(f"\nPackage resource created with {len(textures)} textures, {len(materials)} materials")
    
    # Build and compress bundle
    print("\nBuilding bundle...")
    unpacked = build_bundle(resources)
    packed = compress_bundle(unpacked)
    
    ratio = (1 - len(packed) / len(unpacked)) * 100
    print(f"  Unpacked: {len(unpacked):,} bytes")
    print(f"  Packed: {len(packed):,} bytes ({ratio:.1f}% compression)")
    
    # Save bundle
    os.makedirs(output_dir, exist_ok=True)
    bundle_path = os.path.join(output_dir, bundle_filename)
    with open(bundle_path, 'wb') as f:
        f.write(packed)
    print(f"\nBundle saved: {bundle_path}")
    
    # Create manifest
    manifest = {
        "bundle_name": bundle_name,
        "bundle_file": bundle_filename,
        "package_path": package_path,
        "package_hash_hex": f"0x{package_hash:016X}",
        "package_hash_dec": package_hash,
        "mode": "replacement" if replacement_mode else "new_content",
        "resource_count": len(resources),
        "texture_count": len(textures),
        "material_count": len(materials),
        "textures": textures,
        "materials": materials,
        "install_path": f"Gauntlet/contents/{bundle_filename}",
        "lua_load": f'Game:load_package("{package_path}", true)'
    }
    
    manifest_path = os.path.join(output_dir, f"{bundle_name}_manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest saved: {manifest_path}")
    
    # Print installation instructions
    print(f"""
{'='*70}
INSTALLATION INSTRUCTIONS
{'='*70}

1. Copy bundle to Gauntlet:
   copy "{bundle_path}" "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Gauntlet\\contents\\{bundle_filename}"

2. Register in bundle_database.data (use add_bundle_to_db.py):
   python add_bundle_to_db.py {bundle_filename}

3. Load in Lua:
   Game:load_package("{package_path}", true)

{'='*70}
""")
    
    return manifest


def create_mod_bundle(config_path: str, output_dir: str = ".") -> Dict[str, Any]:
    """
    Create a complete mod bundle from a configuration file.
    
    Config JSON format:
    {
        "name": "my_mod",
        "prefix": "custom",
        "replacement_mode": false,
        "textures": [
            {"path": "folder/texture.dds", "name": "path/to/texture"}
        ],
        "materials": [
            {"name": "material_name", "texture": "texture_name"}
        ],
        "lua_scripts": [
            {"path": "script.lua", "name": "scripts/mods/my_mod/main"}
        ]
    }
    """
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    mod_name = config.get("name", "unnamed_mod")
    prefix = config.get("prefix", "custom")
    replacement_mode = config.get("replacement_mode", False)
    
    if replacement_mode:
        package_path = f"resource_packages/replacements/{mod_name}"
    else:
        package_path = f"resource_packages/{prefix}/{mod_name}"
    
    package_hash = murmur_hash64(package_path)
    bundle_filename = f"{package_hash:016x}"
    
    resources = []
    texture_names = []
    material_names = []
    
    # Process textures
    for tex_cfg in config.get("textures", []):
        tex_res = create_texture_resource(tex_cfg["path"], tex_cfg["name"])
        resources.append(tex_res)
        texture_names.append(tex_cfg["name"])
    
    # Process materials
    for mat_cfg in config.get("materials", []):
        tex_hash = murmur_hash64(mat_cfg["texture"])
        mat_res = create_material_resource(mat_cfg["name"], tex_hash)
        resources.append(mat_res)
        material_names.append(mat_cfg["name"])
    
    # Process Lua scripts
    for lua_cfg in config.get("lua_scripts", []):
        with open(lua_cfg["path"], 'rb') as f:
            lua_data = f.read()
        lua_res = Resource.create("lua", lua_cfg["name"], lua_data)
        resources.append(lua_res)
    
    # Create package
    pkg_res = create_package_resource(package_path, texture_names, material_names)
    resources.insert(0, pkg_res)
    
    # Build bundle
    unpacked = build_bundle(resources)
    packed = compress_bundle(unpacked)
    
    # Save
    os.makedirs(output_dir, exist_ok=True)
    bundle_path = os.path.join(output_dir, bundle_filename)
    with open(bundle_path, 'wb') as f:
        f.write(packed)
    
    return {
        "bundle_file": bundle_filename,
        "package_path": package_path,
        "resource_count": len(resources)
    }

# ============================================================================
# COMMAND-LINE INTERFACE
# ============================================================================

def cmd_analyze(args):
    """Analyze a bundle file."""
    info = analyze_bundle(args.bundle)
    
    sig_names = {
        BUNDLE_SIG_OLD: "OLD (0xF0000004) - Gauntlet",
        BUNDLE_SIG_NEW: "NEW (0xF0000005)",
        BUNDLE_SIG_MOD: "MOD (0xF0000006) - Vermintide 2"
    }
    
    print(f"\n{'='*70}")
    print(f"Bundle Analysis: {args.bundle}")
    print(f"{'='*70}")
    print(f"Signature: {sig_names.get(info.signature, f'0x{info.signature:08X}')}")
    print(f"Uncompressed size: {info.uncompressed_size:,} bytes")
    print(f"Resource count: {info.resource_count}")
    
    # Count by type
    type_counts = {}
    for res in info.resources:
        t = res["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    
    print(f"\nResource types:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    
    if args.verbose:
        print(f"\nAll resources:")
        for res in info.resources[:args.limit]:
            print(f"  {res['index']:4}: {res['type']:15} {res['name_hash']} size={res['data_size']}")
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump({
                "path": info.path,
                "signature": f"0x{info.signature:08X}",
                "uncompressed_size": info.uncompressed_size,
                "resource_count": info.resource_count,
                "resources": info.resources
            }, f, indent=2)
        print(f"\nSaved analysis to: {args.output}")


def cmd_create_texture_bundle(args):
    """Create a texture bundle."""
    manifest = create_texture_bundle(
        args.folder,
        args.name,
        args.output,
        args.replace,
        args.prefix,
        args.with_materials
    )
    
    print(f"\n✓ Bundle created successfully!")
    print(f"  {manifest['texture_count']} textures")
    if manifest['material_count'] > 0:
        print(f"  {manifest['material_count']} materials")


def cmd_create_mod(args):
    """Create a mod from config file."""
    result = create_mod_bundle(args.config, args.output)
    print(f"\n✓ Mod bundle created: {result['bundle_file']}")
    print(f"  Package path: {result['package_path']}")
    print(f"  Resources: {result['resource_count']}")


def cmd_hash(args):
    """Calculate MurmurHash64 for a string."""
    h = murmur_hash64(args.string)
    print(f"'{args.string}'")
    print(f"  Hash: 0x{h:016X}")
    print(f"  Decimal: {h}")


def main():
    parser = argparse.ArgumentParser(
        description='Gauntlet Full Bundle/Mod Creation System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
================================================================================
EXAMPLES
================================================================================

Analyze a bundle:
  python create_full_bundle_system.py analyze --bundle contents/07c9b8511b5aff2e

Create texture bundle (replacement mode):
  python create_full_bundle_system.py create_texture_bundle \\
      --folder my_textures --name my_reskin --replace

Create texture bundle (new content):
  python create_full_bundle_system.py create_texture_bundle \\
      --folder my_textures --name my_pack --with-materials

Create mod from config:
  python create_full_bundle_system.py create_mod --config mod.json

Calculate hash:
  python create_full_bundle_system.py hash "characters/avatar_warrior/warrior_diff"

================================================================================
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze a bundle file')
    analyze_parser.add_argument('--bundle', '-b', required=True, help='Bundle file path')
    analyze_parser.add_argument('--output', '-o', help='Save analysis to JSON')
    analyze_parser.add_argument('--verbose', '-v', action='store_true', help='Show all resources')
    analyze_parser.add_argument('--limit', type=int, default=50, help='Max resources to show')
    
    # Create texture bundle command
    tex_parser = subparsers.add_parser('create_texture_bundle', help='Create texture bundle')
    tex_parser.add_argument('--folder', '-f', required=True, help='Folder with DDS textures')
    tex_parser.add_argument('--name', '-n', required=True, help='Bundle/package name')
    tex_parser.add_argument('--output', '-o', default='.', help='Output directory')
    tex_parser.add_argument('--replace', '-r', action='store_true', 
                           help='Replacement mode (use original paths)')
    tex_parser.add_argument('--prefix', default='custom', help='Prefix for new content')
    tex_parser.add_argument('--with-materials', '-m', action='store_true',
                           help='Create materials for GUI usage')
    
    # Create mod command
    mod_parser = subparsers.add_parser('create_mod', help='Create mod from config')
    mod_parser.add_argument('--config', '-c', required=True, help='Config JSON file')
    mod_parser.add_argument('--output', '-o', default='.', help='Output directory')
    
    # Hash command
    hash_parser = subparsers.add_parser('hash', help='Calculate MurmurHash64')
    hash_parser.add_argument('string', help='String to hash')
    
    args = parser.parse_args()
    
    if args.command == 'analyze':
        cmd_analyze(args)
    elif args.command == 'create_texture_bundle':
        cmd_create_texture_bundle(args)
    elif args.command == 'create_mod':
        cmd_create_mod(args)
    elif args.command == 'hash':
        cmd_hash(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
