#!/usr/bin/env python3
"""Analyze material format from real bundles."""

import struct

# Real material data from bundle (116 bytes total according to header)
# But we only captured 48 bytes in the hex dump
mat_data = bytes.fromhex('0a0000000100000035bfc2e75ba355b30000000000000000010000007eb8a83a69dfc8cd856c58840000000003000000')

print(f'Material data captured: {len(mat_data)} bytes')
print('Analyzing material format:')
print(f'  [0:4]   Version: {struct.unpack_from("<I", mat_data, 0)[0]}')
print(f'  [4:8]   Sections: {struct.unpack_from("<I", mat_data, 4)[0]}')
print(f'  [8:16]  Shader: 0x{struct.unpack_from("<Q", mat_data, 8)[0]:016X}')
print(f'  [16:24] Padding: 0x{struct.unpack_from("<Q", mat_data, 16)[0]:016X}')
print(f'  [24:28] SlotIdx: {struct.unpack_from("<I", mat_data, 24)[0]}')
print(f'  [28:32] ThinHash: 0x{struct.unpack_from("<I", mat_data, 28)[0]:08X}')
print(f'  [32:40] TexHash: 0x{struct.unpack_from("<Q", mat_data, 32)[0]:016X}')
print(f'  [40:44] Zero1: {struct.unpack_from("<I", mat_data, 40)[0]}')
print(f'  [44:48] Count/Marker: {struct.unpack_from("<I", mat_data, 44)[0]}')

print()
print('Compare with our 48-byte GUI material (test_gui.material):')
with open('test_materials/test_gui.material', 'rb') as f:
    gui_data = f.read()

print(f'GUI material: {len(gui_data)} bytes')
print(f'  [0:4]   Version: {struct.unpack_from("<I", gui_data, 0)[0]}')
print(f'  [4:8]   Sections: {struct.unpack_from("<I", gui_data, 4)[0]}')
print(f'  [8:16]  Shader: 0x{struct.unpack_from("<Q", gui_data, 8)[0]:016X}')
print(f'  [16:24] Padding: 0x{struct.unpack_from("<Q", gui_data, 16)[0]:016X}')
print(f'  [24:28] SlotIdx: {struct.unpack_from("<I", gui_data, 24)[0]}')
print(f'  [28:32] ThinHash: 0x{struct.unpack_from("<I", gui_data, 28)[0]:08X}')
print(f'  [32:40] TexHash: 0x{struct.unpack_from("<Q", gui_data, 32)[0]:016X}')
print(f'  [40:48] Trail: 0x{struct.unpack_from("<Q", gui_data, 40)[0]:016X}')

print()
print('Real bundle material shader:  0xB355A35BE7C2BF35')
print('GUI material shader:          0x35AAF8BA4EF11D9E')
print()
print('Key differences:')
print('  - Real material has SlotIdx=1, GUI has SlotIdx=0')
print('  - Different shaders')
print('  - Real material is 116 bytes, GUI is 48 bytes')
