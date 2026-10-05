#!/usr/bin/env python3
"""Analyze real game materials to understand texture reference format."""

import struct
import os
from pathlib import Path

def analyze_material(filepath):
    """Parse and display material structure."""
    with open(filepath, 'rb') as f:
        data = f.read()
    
    print(f"\n{'='*60}")
    print(f"Material: {filepath}")
    print(f"Size: {len(data)} bytes")
    print(f"{'='*60}")
    
    print("\nHex dump:")
    for i in range(0, len(data), 16):
        hex_part = ' '.join(f'{b:02x}' for b in data[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
        print(f"  {i:04x}: {hex_part:<48} {ascii_part}")
    
    if len(data) >= 8:
        version = struct.unpack_from('<I', data, 0)[0]
        count = struct.unpack_from('<I', data, 4)[0]
        print(f"\nParsed Header:")
        print(f"  Version: 0x{version:08X} ({version})")
        print(f"  Section/Entry Count: {count}")
    
    if len(data) >= 16:
        shader = struct.unpack_from('<Q', data, 8)[0]
        print(f"  Shader Hash: 0x{shader:016X}")
    
    if len(data) >= 24:
        pad1 = struct.unpack_from('<Q', data, 16)[0]
        print(f"  Padding @16: 0x{pad1:016X}")
    
    if len(data) >= 40:
        print(f"\nTexture Entry (if present):")
        slot = struct.unpack_from('<I', data, 24)[0]
        thinhash = struct.unpack_from('<I', data, 28)[0]
        texhash = struct.unpack_from('<Q', data, 32)[0]
        print(f"  Slot Index @24: {slot}")
        print(f"  ThinHash @28: 0x{thinhash:08X}")
        print(f"  Texture Hash @32: 0x{texhash:016X}")
    
    if len(data) >= 56:
        print(f"\nSettings (if present):")
        flags = struct.unpack_from('<I', data, 40)[0]
        marker = struct.unpack_from('<I', data, 44)[0]
        pad2 = struct.unpack_from('<Q', data, 48)[0]
        print(f"  Flags @40: {flags}")
        print(f"  Marker @44: 0x{marker:08X}")
        print(f"  Padding @48: 0x{pad2:016X}")
    
    return data

def main():
    # Analyze test materials
    test_dir = Path("test_materials")
    if test_dir.exists():
        for mat_file in test_dir.glob("*.material"):
            analyze_material(mat_file)
    
    # Also look for any extracted materials from bundles
    exports_dir = Path("Exports")
    if exports_dir.exists():
        mat_count = 0
        for mat_file in exports_dir.rglob("*.material"):
            if mat_count < 5:  # Only show first 5
                analyze_material(mat_file)
                mat_count += 1

if __name__ == '__main__':
    main()
