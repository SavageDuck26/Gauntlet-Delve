#!/usr/bin/env python3
"""
Create Simple Materials for Gauntlet Textures
==============================================

Creates simple materials that reference a single texture (diffuse_map).
These materials can then be used with bg_img in the GUI system.

Material Binary Format (Gauntlet 2014):
---------------------------------------
Header (24 bytes):
  uint32: version (0x0A = 10)
  uint32: section_count (1 for simple materials)
  uint64: shader/base hash
  uint64: zero padding
  
Texture Entry (16 bytes):
  uint32: slot_index (0)
  uint32: thin_hash (diffuse_map = 0x3aa8b87e)
  uint64: texture_resource_hash

Trailing (12 bytes):
  Settings/padding

Total minimal material: ~40-60 bytes

Based on analysis of working game materials.
"""

import struct
import os
import sys
from pathlib import Path

# ============================================================================
# MurmurHash64 Implementation
# ============================================================================

def murmur_hash64(key: str, seed: int = 0) -> int:
    """MurmurHash64A - the hash algorithm used by Bitsquid/Stingray."""
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


def thin_hash(name: str) -> int:
    """Get the upper 32 bits of the MurmurHash64 (ThinHash)."""
    full = murmur_hash64(name)
    return (full >> 32) & 0xFFFFFFFF


# ============================================================================
# Known Constants
# ============================================================================

# Shader hashes from working materials (found by analyzing extracted materials)
# IMPORTANT: These are from REAL extracted game materials - January 2026 update
SHADER_DIFFUSE_SIMPLE = 0xBA25DE3579DC6624  # From 52-byte material with diffuse_map (495bf47a4c60ca4d.material)
SHADER_GUI_ICON = 0x5EEF29E143D1CA88        # From 72-byte materials with diffuse_map (3cd91c54a3c80f1a.material)
SHADER_GUI = 0x35AAF8BA4EF11D9E             # GUI shader (48-byte - has NO texture slot!)
SHADER_SIMPLE = 0xF1EE9D7D2D10CF4F          # simple/unlit shader
SHADER_BASIC = 0x708CF7F5EE10D9BD           # basic shader (from 40-byte materials)

# ThinHash for texture slots
THINHASH_DIFFUSE = 0x3aa8b87e      # diffuse_map
THINHASH_EMISSIVE = 0x4dc19f08     # emissive_map

# Common settings marker
SETTINGS_MARKER = 0x46F80ADE       # Observed in many materials


# ============================================================================
# Material Creation
# ============================================================================

def create_simple_material(texture_hash: int, shader_hash: int = None) -> bytes:
    """
    Create a minimal material that references a single diffuse texture (52 bytes).
    
    UPDATED January 2026: Now uses the CORRECT format based on real game materials!
    
    Based on analysis of 495bf47a4c60ca4d.material (52 bytes with diffuse_map):
    This is the SMALLEST working material format that has a texture reference.
    
    CRITICAL FIXES:
    - Slot index MUST be 1, not 0
    - Uses shader 0xBA25DE3579DC6624 which supports diffuse_map
    - The 48-byte GUI shader (0x35AAF8BA4EF11D9E) has NO texture slot!
    
    52-byte Format:
      [0:4]   uint32: version (0x0A = 10)
      [4:8]   uint32: section_count (1)
      [8:16]  uint64: shader_hash
      [16:24] uint64: padding (zeros)
      [24:28] uint32: slot_index (1 - MUST BE 1!)
      [28:32] uint32: thin_hash (diffuse_map = 0x3AA8B87E)
      [32:40] uint64: texture_hash
      [40:52] 12 bytes: trailing zeros
    """
    if shader_hash is None:
        shader_hash = SHADER_DIFFUSE_SIMPLE
        
    data = struct.pack('<I', 0x0A)           # Version = 10
    data += struct.pack('<I', 1)              # Section count = 1
    data += struct.pack('<Q', shader_hash)    # Shader hash
    data += struct.pack('<Q', 0)              # Padding (zeros)
    
    # Texture entry - SLOT INDEX MUST BE 1!
    data += struct.pack('<I', 1)              # Slot index = 1 (NOT 0!)
    data += struct.pack('<I', THINHASH_DIFFUSE)  # diffuse_map thin hash
    data += struct.pack('<Q', texture_hash)   # Actual texture hash
    
    # Trailing zeros (12 bytes to reach 52 total)
    data += struct.pack('<I', 0)
    data += struct.pack('<I', 0)
    data += struct.pack('<I', 0)
    
    return data


def create_gui_material(texture_hash: int) -> bytes:
    """
    Create a material suitable for GUI/2D rendering (52 bytes).
    
    UPDATED January 2026: Uses the same 52-byte format as create_simple_material.
    The old 48-byte GUI shader format does NOT support texture slots!
    
    For GUI widgets (bg_img) and icons, this format works correctly
    with Gui.material() and Gui.bitmap() calls.
    """
    # Use the working 52-byte format with diffuse shader
    return create_simple_material(texture_hash, SHADER_DIFFUSE_SIMPLE)


def create_unlit_material(texture_hash: int) -> bytes:
    """
    Create an unlit/fullbright material - good for UI and icons.
    
    Based on analysis of simple materials that just show a texture
    without lighting calculations.
    """
    data = struct.pack('<I', 0x0A)           # Version = 10
    data += struct.pack('<I', 1)              # Section count = 1
    
    # Use the simple/unlit shader
    data += struct.pack('<Q', SHADER_SIMPLE)  # Shader hash
    data += struct.pack('<Q', 0)              # Padding
    
    # Diffuse texture
    data += struct.pack('<I', 0)              # Slot index = 0
    data += struct.pack('<I', THINHASH_DIFFUSE)  # diffuse_map
    data += struct.pack('<Q', texture_hash)   # Texture hash
    
    # Standard settings/flags
    data += struct.pack('<I', 1)              # Flags
    data += struct.pack('<I', SETTINGS_MARKER)
    data += struct.pack('<Q', 0)              # Padding
    
    return data


# ============================================================================
# Main
# ============================================================================

def main():
    """Test material creation."""
    
    # Test with one of our texture hashes
    test_texture_hash = 0x2F5C6FD2331936DD  # 93fd6865a4093d17 (128x128 icon)
    
    # Create different material types
    simple_mat = create_simple_material(test_texture_hash)
    gui_mat = create_gui_material(test_texture_hash)
    unlit_mat = create_unlit_material(test_texture_hash)
    
    print("Material Binary Creation Test")
    print("=" * 60)
    
    print(f"\nSimple Material ({len(simple_mat)} bytes):")
    print(simple_mat.hex())
    
    print(f"\nGUI Material ({len(gui_mat)} bytes):")
    print(gui_mat.hex())
    
    print(f"\nUnlit Material ({len(unlit_mat)} bytes):")
    print(unlit_mat.hex())
    
    # Save test materials
    output_dir = Path("test_materials")
    output_dir.mkdir(exist_ok=True)
    
    with open(output_dir / "test_simple.material", "wb") as f:
        f.write(simple_mat)
    with open(output_dir / "test_gui.material", "wb") as f:
        f.write(gui_mat)
    with open(output_dir / "test_unlit.material", "wb") as f:
        f.write(unlit_mat)
    
    print(f"\nTest materials saved to {output_dir}/")
    
    # Compare with a real 60-byte material
    real_mat_path = Path("Exports/extracted_materials/raw/feb26df5a7383006.material")
    if real_mat_path.exists():
        with open(real_mat_path, "rb") as f:
            real_data = f.read()
        print(f"\nReal 60-byte material for comparison:")
        print(real_data.hex())
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
