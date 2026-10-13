#!/usr/bin/env python3
"""
Gauntlet Global Texture Package Creator
=======================================
Creates standalone texture bundles with package resources that can be
loaded from Lua scripts using Game:load_package().

=============================================================================
HOW GAUNTLET'S RESOURCE SYSTEM WORKS (IMPORTANT!)
=============================================================================

1. ALL resources are identified by MurmurHash64 of their path:
   "characters/avatar_warrior/warrior_diff" -> 0x67111D9E39E1CABC
   
2. Materials contain HARDCODED texture hashes, not paths.
   This means a material will always look for a specific hash.
   
3. When you load a package, textures become GLOBALLY available.
   Any code/material requesting that hash will get your texture.

4. To REPLACE a game texture, your texture must have the SAME HASH.
   Same hash = same path. Use --replace mode!

=============================================================================
TWO MODES OF OPERATION
=============================================================================

MODE 1: REPLACEMENT (--replace)
-------------------------------
Use this to override existing game textures globally.

Your folder structure MUST match the game's original paths:
    my_mod/
    +-- characters/
        +-- avatar_warrior/
            +-- warrior_diff.dds      <- Becomes "characters/avatar_warrior/warrior_diff"
                                        Hash: 0x67111D9E39E1CABC (matches original!)

When loaded, your texture REPLACES the original everywhere in the game.

Example:
    python create_texture_package.py my_warrior_skin warrior_reskin --replace
    
    # Your textures now override originals globally!
    Game:load_package("resource_packages/replacements/warrior_reskin", true)


MODE 2: NEW CONTENT (default)
-----------------------------
Use this to add NEW textures (not replacing existing ones).

Your textures get a custom path prefix:
    my_mod/
    +-- cool_sword.dds                <- Becomes "custom/my_pack/cool_sword"
                                        Hash: 0xNEW_UNIQUE_HASH

These textures won't automatically appear on existing objects.
You need custom materials/units that reference your texture hashes.

Example:
    python create_texture_package.py my_textures my_pack
    
    # Load and use with hash from manifest
    Game:load_package("resource_packages/custom/my_pack", true)
    local tex = 0x1234567890ABCDEF  -- Your unique hash

=============================================================================
WHY THINGS DON'T WORK (COMMON ISSUES)
=============================================================================

"My texture isn't showing up!"
  -> Check if your texture hash matches what materials expect.
  -> Use --replace mode if replacing existing textures.
  -> Verify bundle is in Gauntlet/contents/ folder.

"I put the file in the game folder but nothing changed!"
  -> Gauntlet doesn't load loose files! Only bundles.
  -> You MUST use this tool to create a bundle.

"The original texture still shows!"
  -> Your package might load before the game's.
  -> Ensure your package loads AFTER core game packages.
  -> Or use the game's package as a dependency.

"Replacement mode hashes don't match!"
  -> Your folder structure doesn't match the original.
  -> Check the game's texture paths in the documentation.
  -> Path must be EXACT: "characters/avatar_warrior/warrior_diff"

=============================================================================
USAGE
=============================================================================

Replace existing textures (global override):
    python create_texture_package.py <folder> <name> --replace
    
Add new textures (for custom content):
    python create_texture_package.py <folder> <name>
    python create_texture_package.py <folder> <name> --prefix "mods"

=============================================================================
TEXTURE FORMATS
=============================================================================

- Diffuse/Color: DXT1 (no alpha) or DXT5 (with alpha)
- Normal maps:   ATI2/BC5
- Specular:      DXT1 or DXT5
- Emissive:      DXT1

Match the original texture's dimensions when replacing!

=============================================================================
"""

import struct
import zlib
import os
import sys
import json
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Set
import argparse

# ============================================================================
# Constants
# ============================================================================

BUNDLE_SIG_OLD = 0xF0000004
ZLIB_CHUNK = 0x10000  # 64KB

# Resource type hashes (MurmurHash64 of type name)
TYPE_TEXTURE = 0xCD4238C6A0C69E32
TYPE_MATERIAL = 0xEAC0B497876ADEDF
TYPE_PACKAGE = 0xAD9C6D9ED1E5E77A
NATIVE_PACKAGE_TRAILER_BYTE = b"\x01"

# ============================================================================
# MurmurHash64 Implementation
# ============================================================================

def murmur_hash64(key: str, seed: int = 0) -> int:
    """
    MurmurHash64A - the hash algorithm used by Bitsquid/Stingray.
    All resource names are hashed with this function.
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
# Resource Classes
# ============================================================================

@dataclass
class Resource:
    """Base class for a resource"""
    type_hash: int
    name: str
    name_hash: int
    data: bytes

@dataclass 
class TextureResource(Resource):
    """A texture resource"""
    width: int = 0
    height: int = 0
    format: str = ""
    filepath: str = ""

@dataclass
class MaterialResource(Resource):
    """A material resource that references a texture"""
    texture_hash: int = 0
    texture_name: str = ""

@dataclass
class PackageResource(Resource):
    """A package resource listing other resources to load"""
    textures: List[str] = None
    materials: List[str] = None
    
    def __post_init__(self):
        if self.textures is None:
            self.textures = []
        if self.materials is None:
            self.materials = []

# ============================================================================
# Material Constants
# ============================================================================

# ThinHash for texture slots (upper 32 bits of MurmurHash64)
THINHASH_DIFFUSE = 0x3aa8b87e      # diffuse_map

# Shader hashes from working game materials
# IMPORTANT: These are from REAL extracted game materials!
SHADER_DIFFUSE_SIMPLE = 0xBA25DE3579DC6624  # From 52-byte material with diffuse_map (495bf47a4c60ca4d.material)
SHADER_GUI_ICON = 0x5EEF29E143D1CA88        # From 72-byte materials with diffuse_map (3cd91c54a3c80f1a.material)
SHADER_BASIC = 0x708CF7F5EE10D9BD           # Simple shader (from basic materials)
SHADER_GUI = 0x35AAF8BA4EF11D9E             # GUI shader (from 48-byte gui materials - NO TEXTURE!)

# Settings marker observed in materials
SETTINGS_MARKER = 0x46F80ADE

# ============================================================================
# Material Builder
# ============================================================================

def create_simple_material_data(texture_hash: int) -> bytes:
    """
    Create binary data for a simple diffuse material (52 bytes).
    
    This matches the exact format of 495bf47a4c60ca4d.material which is
    a real working game material with a diffuse_map texture.
    
    52-byte Material format (from game):
      [0:4]   uint32: version (0x0A = 10)
      [4:8]   uint32: section_count (1)
      [8:16]  uint64: shader_hash (0xBA25DE3579DC6624)
      [16:24] uint64: padding (zeros)
      [24:28] uint32: slot_index (1 - MUST BE 1, NOT 0!)
      [28:32] uint32: thin_hash (diffuse_map = 0x3AA8B87E)
      [32:40] uint64: texture_hash
      [40:52] 12 bytes: trailing zeros
    
    Total: 52 bytes
    
    CRITICAL FIX (January 2026):
    - Slot index MUST be 1, not 0
    - The 48-byte GUI shader format has NO texture slot at all!
    - This 52-byte format is the minimal working texture-bearing material
    """
    data = struct.pack('<I', 0x0A)           # Version = 10
    data += struct.pack('<I', 1)              # Section count = 1
    data += struct.pack('<Q', SHADER_DIFFUSE_SIMPLE)  # Working shader with diffuse support
    data += struct.pack('<Q', 0)              # Padding
    
    # Diffuse texture slot entry - SLOT INDEX MUST BE 1!
    data += struct.pack('<I', 1)              # Slot index = 1 (NOT 0!)
    data += struct.pack('<I', THINHASH_DIFFUSE)  # diffuse_map thin hash
    data += struct.pack('<Q', texture_hash)   # Texture resource hash
    
    # Trailing zeros (12 bytes total to reach 52 bytes)
    data += struct.pack('<I', 0)              # Zero
    data += struct.pack('<I', 0)              # Zero  
    data += struct.pack('<I', 0)              # Zero
    
    return data

def create_materials_for_textures(textures: List[TextureResource]) -> List[MaterialResource]:
    """
    Create material resources for each texture.
    
    The material name is based on the texture filename (without path).
    This allows GUI code to use: bg_img = "93fd6865a4093d17"
    which will find material "93fd6865a4093d17" that displays that texture.
    """
    materials = []
    
    for tex in textures:
        # Extract just the filename without path or extension
        # e.g., "custom/global_textures/93fd6865a4093d17" -> "93fd6865a4093d17"
        material_name = Path(tex.name).name  # Get filename part
        
        # Create material data that references this texture
        material_data = create_simple_material_data(tex.name_hash)
        
        # Material hash is based on the short name (for GUI lookup)
        material_hash = murmur_hash64(material_name)
        
        material = MaterialResource(
            type_hash=TYPE_MATERIAL,
            name=material_name,
            name_hash=material_hash,
            data=material_data,
            texture_hash=tex.name_hash,
            texture_name=tex.name
        )
        materials.append(material)
    
    return materials

# ============================================================================
# DDS Handling
# ============================================================================

def validate_dds(data: bytes) -> Tuple[bool, str, int, int, str]:
    """Validate DDS file and extract info."""
    if len(data) < 128 or data[:4] != b'DDS ':
        return False, "Invalid DDS", 0, 0, ""
    
    height = struct.unpack_from('<I', data, 12)[0]
    width = struct.unpack_from('<I', data, 16)[0]
    fourcc = data[0x54:0x58].decode('ascii', errors='replace')
    
    return True, "", width, height, fourcc

# ============================================================================
# Package Resource Builder
# ============================================================================

def build_package_data(package_name: str, texture_names: List[str], 
                       material_names: List[str] = None) -> bytes:
    """
    Build the binary data for a package resource.
    
    Package format (compiled) - UPDATED January 8, 2026:
    
    The package resource contains a list of entries, each describing a resource
    to load along with its dependencies.
    
    Header:
      uint32: entry_count
    
    Each entry (variable size):
      uint64: resource_type_hash  (e.g., texture, material, unit)
      uint64: resource_name_hash  (MurmurHash64 of resource path)
      uint32: dependency_count    (number of 4-byte dependency refs)
      uint32[dependency_count]: dependency_references
    
    Entry size = 20 + (dependency_count x 4) bytes
    Trailer = one byte (native packages typically use 0x01)
    
    For simple standalone textures, we use dependency_count=0 
    since textures don't have resource dependencies themselves.
    The dependency mechanism is for resource loading order, but
    textures are standalone resources.
    """
    entries = []
    
    # Build texture entries
    if texture_names:
        for name in texture_names:
            name_hash = murmur_hash64(name)
            name_hi32 = (name_hash >> 32) & 0xFFFFFFFF
            
            # 28-byte fixed format: type_hash(8) + name_hash(8) + c1=2(4) + c2=0(4) + name_hi32(4)
            entry = struct.pack('<QQIII', TYPE_TEXTURE, name_hash, 2, 0, name_hi32)
            entries.append(entry)
    
    # Build material entries
    if material_names:
        for name in material_names:
            name_hash = murmur_hash64(name)
            name_hi32 = (name_hash >> 32) & 0xFFFFFFFF
            
            # 28-byte fixed format
            entry = struct.pack('<QQIII', TYPE_MATERIAL, name_hash, 2, 0, name_hi32)
            entries.append(entry)
    
    # Build package data: count + entries + trailer byte
    data = struct.pack('<I', len(entries))
    data += b''.join(entries)
    data += NATIVE_PACKAGE_TRAILER_BYTE
    
    return data


# ============================================================================
# Bundle Builder
# ============================================================================

def build_bundle(resources: List[Resource]) -> bytes:
    """
    CORRECTED FORMAT (verified against native Gauntlet bundles):
      [0x000]  uint32 N  -- resource count
      [0x004]  84-byte PREAMBLE (zeros for custom bundles)
      [0x058]  172-byte PADDING (zeros)
      [0x104]  TOC -- (N+1) x 16-byte entries (entry[N] is sentinel)
      [toc_end]  RESOURCE-0 -- 20-byte header (no type/name), then data
      [after]    RESOURCES 1..N-1 -- 36-byte header + data each
    """
    if not resources:
        raise ValueError("No resources to pack")
    
    count = len(resources)
    sorted_resources = sorted(resources, key=lambda r: r.name_hash)
    sections = []
    
    sections.append(struct.pack('<I', count))
    sections.append(b'\x00' * 84)   # preamble
    sections.append(b'\x00' * 172)  # padding to 0x104
    
    # TOC: N+1 entries with sentinel
    for res in sorted_resources:
        sections.append(struct.pack('<QQ', res.type_hash, res.name_hash))
    sections.append(struct.pack('<QQ', sorted_resources[0].type_hash, sorted_resources[0].name_hash))
    
    # Resource-0: 20-byte header (NO type/name)
    r0 = sorted_resources[0]
    sections.append(struct.pack('<IQII', 1, 0, len(r0.data), 0))
    sections.append(r0.data)
    
    # Resources 1..N-1: 36-byte header + data
    for res in sorted_resources[1:]:
        sections.append(struct.pack('<QQIQII', res.type_hash, res.name_hash, 1, 0, len(res.data), 0))
        sections.append(res.data)
    
    result = b''.join(sections)
    pad = (4 - (len(result) % 4)) % 4
    if pad:
        result += b'\x00' * pad
    return result


def compress_bundle(unpacked_data: bytes) -> bytes:
    """Compress data into a bundle file using zlib."""
    chunks = []
    
    # Header
    header = struct.pack('<III', BUNDLE_SIG_OLD, len(unpacked_data), 0)
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
# Texture Collection
# ============================================================================

def collect_textures(folder: str, prefix: str, replacement_mode: bool = False) -> List[TextureResource]:
    """
    Collect all DDS textures from a folder.
    
    Args:
        folder: Path to folder containing textures
        prefix: Prefix to add to resource paths (ignored in replacement mode)
        replacement_mode: If True, use folder structure as-is for hash collision
        
    Returns:
        List of TextureResource objects ready for bundling
    """
    textures = []
    folder_path = Path(folder)
    
    dds_files = list(folder_path.glob('**/*.dds'))
    dds_files.extend(folder_path.glob('**/*.DDS'))
    
    for dds_path in sorted(set(dds_files)):
        with open(dds_path, 'rb') as f:
            data = f.read()
        
        is_valid, error, width, height, fmt = validate_dds(data)
        if not is_valid:
            print(f"  Warning: Skipping {dds_path.name}: {error}")
            continue
        
        # Build resource name based on mode
        rel_path = dds_path.relative_to(folder_path)
        name_parts = list(rel_path.parts)
        name_parts[-1] = rel_path.stem  # Remove .dds extension
        
        if replacement_mode:
            # REPLACEMENT MODE: Use exact folder structure (no prefix)
            # This creates hashes that match the original game textures
            resource_name = '/'.join(name_parts)
        else:
            # NEW CONTENT MODE: Add prefix for unique hashes
            resource_name = prefix + '/'.join(name_parts)
        
        resource_name = resource_name.replace('\\', '/')
        name_hash = murmur_hash64(resource_name)
        
        tex = TextureResource(
            type_hash=TYPE_TEXTURE,
            name=resource_name,
            name_hash=name_hash,
            data=data,
            width=width,
            height=height,
            format=fmt,
            filepath=str(dds_path)
        )
        
        textures.append(tex)
        
        mode_indicator = "[REPLACE]" if replacement_mode else "[NEW]"
        print(f"  {mode_indicator} {dds_path.name} ({width}x{height} {fmt})")
        print(f"           Path: {resource_name}")
        print(f"           Hash: 0x{name_hash:016X}")
    
    return textures

# ============================================================================
# Main Functions
# ============================================================================

def create_texture_package(texture_folder: str, package_name: str, 
                          output_dir: str = None,
                          prefix: str = "custom",
                          replacement_mode: bool = False,
                          verbose: bool = False,
                          with_materials: bool = False) -> Dict:
    """
    Create a complete texture package bundle.
    
    Args:
        texture_folder: Folder containing DDS textures
        package_name: Name for the package
        output_dir: Where to save the bundle and manifest
        prefix: Prefix for resource paths (ignored in replacement mode)
        replacement_mode: If True, textures use original paths for hash collision
        verbose: Print extra debug info
        with_materials: If True, also create materials for each texture (for GUI usage)
    
    Returns:
        Dict with package info and manifest, or None on failure
    
    ==========================================================================
    HOW GLOBAL TEXTURES WORK
    ==========================================================================
    
    Once a package is loaded, ALL textures in it are globally available.
    Any material or code requesting a texture by hash will find it.
    
    REPLACEMENT MODE (--replace):
        Your texture path matches the original -> same hash -> your texture wins!
        Example: "characters/avatar_warrior/warrior_diff" replaces the original
    
    NEW CONTENT MODE (default):
        Your texture gets a unique path/hash -> won't conflict with game textures
        Example: "custom/my_pack/sword_diff" is a brand new texture
    
    ==========================================================================
    """
    print("=" * 70)
    print("Gauntlet Global Texture Package Creator")
    print("=" * 70)
    print()
    
    if replacement_mode:
        print("MODE: REPLACEMENT (textures will override originals globally)")
        print("      Your folder structure should match the game's texture paths!")
    else:
        print("MODE: NEW CONTENT (textures get unique paths/hashes)")
        print("      These won't replace existing textures automatically.")
    print()
    
    # Normalize paths
    if output_dir is None:
        output_dir = "."
    
    # Full package path (how it will be loaded in Lua)
    if replacement_mode:
        full_package_path = f"resource_packages/replacements/{package_name}"
        texture_prefix = ""  # No prefix - use exact paths for hash collision
    else:
        full_package_path = f"resource_packages/{prefix}/{package_name}"
        texture_prefix = f"{prefix}/{package_name}/"
    
    package_hash = murmur_hash64(full_package_path)
    
    print(f"Package name: {package_name}")
    print(f"Package path: {full_package_path}")
    print(f"Package hash: 0x{package_hash:016X}")
    if not replacement_mode:
        print(f"Texture prefix: {texture_prefix}")
    print()
    
    # Collect textures
    print("Scanning for DDS textures...")
    textures = collect_textures(texture_folder, texture_prefix, replacement_mode)
    
    if not textures:
        print("\nNo valid DDS textures found!")
        print("Make sure your folder contains .dds files.")
        return None
    
    print(f"\nFound {len(textures)} textures")
    
    # Create materials for textures if requested
    materials = []
    if with_materials:
        print("\nCreating materials for GUI usage...")
        materials = create_materials_for_textures(textures)
        print(f"Created {len(materials)} materials")
    
    # Create the package resource - include both textures and materials
    texture_names = [tex.name for tex in textures]
    material_names = [mat.name for mat in materials]
    package_data = build_package_data(package_name, texture_names, material_names)
    
    package_resource = Resource(
        type_hash=TYPE_PACKAGE,
        name=full_package_path,
        name_hash=package_hash,
        data=package_data
    )
    
    # Combine all resources
    all_resources = [package_resource] + textures + materials
    
    material_count = len(materials)
    print(f"\nBuilding bundle with {len(all_resources)} resources...")
    print(f"  1 package resource")
    print(f"  {len(textures)} texture resources")
    if material_count > 0:
        print(f"  {material_count} material resources")
    
    # Build and compress bundle
    unpacked_data = build_bundle(all_resources)
    print(f"  Unpacked size: {len(unpacked_data):,} bytes")
    
    packed_data = compress_bundle(unpacked_data)
    ratio = (1 - len(packed_data) / len(unpacked_data)) * 100
    print(f"  Compressed size: {len(packed_data):,} bytes ({ratio:.1f}% reduction)")
    
    # Generate bundle filename (16-char hex hash)
    bundle_name = f"{package_hash:016x}"
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Save bundle
    bundle_path = os.path.join(output_dir, bundle_name)
    with open(bundle_path, 'wb') as f:
        f.write(packed_data)
    print(f"\nBundle saved: {bundle_path}")
    
    # Create manifest
    manifest = {
        "package_name": package_name,
        "package_path": full_package_path,
        "package_hash": f"0x{package_hash:016X}",
        "bundle_name": bundle_name,
        "mode": "replacement" if replacement_mode else "new_content",
        "texture_count": len(textures),
        "material_count": len(materials),
        "textures": {},
        "materials": {},
        "lua_load_code": f'Game:load_package("{full_package_path}", true)',
        "install_path": f"Gauntlet/contents/{bundle_name}",
    }
    
    for tex in textures:
        manifest["textures"][tex.name] = {
            "hash_hex": f"0x{tex.name_hash:016X}",
            "hash_dec": tex.name_hash,
            "dimensions": f"{tex.width}x{tex.height}",
            "format": tex.format,
            "original_file": Path(tex.filepath).name,
            "is_replacement": replacement_mode
        }
    
    for mat in materials:
        manifest["materials"][mat.name] = {
            "hash_hex": f"0x{mat.name_hash:016X}",
            "hash_dec": mat.name_hash,
            "texture_hash": f"0x{mat.texture_hash:016X}",
            "gui_usage": f'bg_img = "{mat.name}"'
        }
    
    manifest_path = os.path.join(output_dir, f"{package_name}_manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest saved: {manifest_path}")
    
    # Print usage instructions
    print()
    print("=" * 70)
    print("INSTALLATION & USAGE")
    print("=" * 70)
    
    if replacement_mode:
        print(f"""
+======================================================================+
|  REPLACEMENT MODE - Your textures will GLOBALLY override originals  |
+======================================================================+

1. INSTALL: Copy the bundle to Gauntlet's contents folder:
   
   copy "{bundle_path}" "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Gauntlet\\contents\\{bundle_name}"

2. LOAD: Add this to your Lua mod (or boot script):
   
   Game:load_package("{full_package_path}", true)

3. DONE! All textures are now replaced globally. No further code needed.

   The game's materials already reference these texture hashes.
   Your textures will automatically appear wherever the originals were used.

TEXTURES THAT WILL BE REPLACED:
""")
    else:
        print(f"""
+======================================================================+
|  NEW CONTENT MODE - Textures available for custom materials/units   |
+======================================================================+

1. INSTALL: Copy the bundle to Gauntlet's contents folder:
   
   copy "{bundle_path}" "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Gauntlet\\contents\\{bundle_name}"

2. LOAD: Add this to your Lua mod:
   
   Game:load_package("{full_package_path}", true)

3. USE: Reference textures by their hashes in your custom materials/code:
   
   -- Example: Get a texture hash from the manifest
   local my_texture = {textures[0].name_hash}  -- 0x{textures[0].name_hash:016X}

NOTE: These textures won't automatically appear on existing game objects!
      You need to create custom materials that reference these hashes,
      or use Lua hooks to redirect texture lookups.

AVAILABLE TEXTURES:
""")
    
    for tex in textures:
        print(f"  {tex.name}")
        print(f"    Hash: 0x{tex.name_hash:016X}")
        print(f"    Size: {tex.width}x{tex.height} {tex.format}")
        print()
    
    # Additional help for replacement mode
    if replacement_mode:
        print("=" * 70)
        print("VERIFICATION")
        print("=" * 70)
        print("""
To verify your hashes match the originals, check against known hashes:

  Warrior Textures:
    characters/avatar_warrior/warrior_diff -> 0x67111D9E39E1CABC
    characters/avatar_warrior/warrior_norm -> 0xF8C23D1F8B219C6D
    characters/avatar_warrior/warrior_spec -> 0x6A77D7C1FF442EE7
    
  Elf Textures:
    characters/avatar_elf/elf_diff -> 0x5A946011CD458AA6
    characters/avatar_elf/elf_norm -> 0x6F9F0047B68BC00E
    characters/avatar_elf/elf_spec -> 0x7E3347EB6249EBFF

If your hashes don't match, your folder structure is wrong!
The path from your texture folder root must exactly match the game's paths.
""")
    
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description='Create global texture packages for Gauntlet',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
=============================================================================
MODES
=============================================================================

REPLACEMENT MODE (--replace):
  Textures use exact game paths -> same hash -> overrides originals globally!
  
  Your folder structure must match the game's:
    my_mod/characters/avatar_warrior/warrior_diff.dds
           v
    Path: "characters/avatar_warrior/warrior_diff"
    Hash: 0x67111D9E39E1CABC (matches original!)
  
  Example:
    python create_texture_package.py warrior_skin my_skin --replace

NEW CONTENT MODE (default):
  Textures get unique paths/hashes for custom content.
  Won't replace existing textures automatically.
  
  Example:
    python create_texture_package.py my_textures my_pack
    python create_texture_package.py my_textures my_pack --prefix "mods"

=============================================================================
EXAMPLES
=============================================================================

1. Replace the warrior's textures globally:
   
   # Folder structure:
   #   warrior_reskin/
   #   +-- characters/
   #       +-- avatar_warrior/
   #           +-- warrior_diff.dds
   #           +-- warrior_norm.dds
   #           +-- warrior_spec.dds
   
   python create_texture_package.py warrior_reskin my_warrior --replace

2. Add new textures for custom weapons:
   
   # Folder structure:
   #   my_weapons/
   #   +-- cool_sword_diff.dds
   #   +-- cool_sword_norm.dds
   
   python create_texture_package.py my_weapons weapon_pack

3. Load in Lua:
   
   Game:load_package("resource_packages/replacements/my_warrior", true)
   Game:load_package("resource_packages/custom/weapon_pack", true)

=============================================================================
        """)
    
    parser.add_argument('texture_folder', 
                        help='Folder containing DDS textures')
    parser.add_argument('package_name', 
                        help='Name for the package')
    parser.add_argument('--replace', '-r', action='store_true',
                        help='REPLACEMENT MODE: Use original game paths for hash collision. '
                             'Your folder structure must match the game\'s texture paths exactly.')
    parser.add_argument('--prefix', default='custom',
                        help='Prefix for resource paths in new content mode (default: custom)')
    parser.add_argument('--output', '-o', default='.',
                        help='Output directory for bundle and manifest')
    parser.add_argument('--with-materials', '-m', action='store_true',
                        help='Also create materials for each texture (for GUI bg_img usage)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print extra debug information')
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.texture_folder):
        print(f"Error: Folder not found: {args.texture_folder}")
        sys.exit(1)
    
    result = create_texture_package(
        args.texture_folder,
        args.package_name,
        args.output,
        args.prefix,
        args.replace,  # replacement_mode
        args.verbose,
        args.with_materials  # with_materials
    )
    
    if result is None:
        sys.exit(1)
    
    # Final summary
    print("=" * 70)
    print("SUCCESS!")
    print("=" * 70)
    if args.replace:
        print("Your replacement texture package is ready.")
        print("When loaded, these textures will override the originals GLOBALLY.")
    else:
        print("Your new content texture package is ready.")
        if args.with_materials:
            print("Materials were created for GUI usage (bg_img = 'texture_name').")
        else:
            print("Remember: You need custom materials/code to use these textures.")
            print("Tip: Use --with-materials to create materials for GUI usage.")
    print()


if __name__ == '__main__':
    main()
