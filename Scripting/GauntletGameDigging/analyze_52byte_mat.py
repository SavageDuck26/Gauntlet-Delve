#!/usr/bin/env python3
"""Analyze the 52-byte material to understand the minimal texture-bearing format."""
import struct

with open('Exports/extracted_materials/raw/495bf47a4c60ca4d.material', 'rb') as f:
    data = f.read()

print(f'52-byte material with diffuse_map:')
print(f'Hex: {data.hex()}')
print()

# Parse everything
print('Parsed structure:')
print(f'[0:4]   Version: 0x{struct.unpack_from("<I", data, 0)[0]:08X}')
print(f'[4:8]   Sections: {struct.unpack_from("<I", data, 4)[0]}')
print(f'[8:16]  Shader: 0x{struct.unpack_from("<Q", data, 8)[0]:016X}')
print(f'[16:24] Padding: 0x{struct.unpack_from("<Q", data, 16)[0]:016X}')
print(f'[24:28] SlotIdx: {struct.unpack_from("<I", data, 24)[0]}')
print(f'[28:32] ThinHash: 0x{struct.unpack_from("<I", data, 28)[0]:08X}')
print(f'[32:40] Texture: 0x{struct.unpack_from("<Q", data, 32)[0]:016X}')
print(f'[40:44] Zero1: {struct.unpack_from("<I", data, 40)[0]}')
print(f'[44:48] Value: 0x{struct.unpack_from("<I", data, 44)[0]:08X}')
print(f'[48:52] Value: 0x{struct.unpack_from("<I", data, 48)[0]:08X}')
