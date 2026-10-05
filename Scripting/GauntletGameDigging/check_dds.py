#!/usr/bin/env python3
"""Quick DDS file validator."""
import struct
import sys

dds_path = sys.argv[1] if len(sys.argv) > 1 else 'extracted/big_bundle/8ffce03115c686d8.dds'
with open(dds_path, 'rb') as f:
    data = f.read(256)

magic = data[:4]
print(f'Magic: {magic}')
print(f'Header size: {struct.unpack("<I", data[4:8])[0]}')
print(f'Flags: 0x{struct.unpack("<I", data[8:12])[0]:08x}')
h, w = struct.unpack('<II', data[12:20])
print(f'Dimensions: {w}x{h}')
print(f'Pitch/LinearSize: {struct.unpack("<I", data[20:24])[0]}')
print(f'Depth: {struct.unpack("<I", data[24:28])[0]}')
print(f'Mip count: {struct.unpack("<I", data[28:32])[0]}')
print(f'PixelFormat FourCC: {data[84:88]}')

# Check if pixel data starts properly
print(f'\nFirst 16 bytes of pixel data (after 128-byte header):')
print(data[128:144].hex())
