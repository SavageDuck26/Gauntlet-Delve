"""Debug bundle structure"""
import struct
import zlib

TYPE_TEXTURE = 0xCD4238C6A0C69E32
TYPE_MATERIAL = 0xEAC0B497876ADEDF
TYPE_PACKAGE = 0xAD9C6D9ED1E5E77A
TYPE_LUA = 0x0D972BAB10B40FD3
TYPES = {TYPE_TEXTURE: 'texture', TYPE_MATERIAL: 'material', TYPE_PACKAGE: 'package', TYPE_LUA: 'lua'}

def decompress(data):
    chunks = []
    pos = 12
    while pos < len(data):
        chunk_len = struct.unpack('<I', data[pos:pos+4])[0]
        pos += 4
        chunks.append(zlib.decompress(data[pos:pos+chunk_len]))
        pos += chunk_len
    return b''.join(chunks)

def analyze_real_bundle():
    """Analyze a real game bundle with proper structure"""
    print("=== Analyzing real bundle b22560b172a4cff8 ===")
    with open(r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\b22560b172a4cff8', 'rb') as f:
        data = f.read()
    
    unpacked = decompress(data)
    count = struct.unpack('<I', unpacked[:4])[0]
    print(f'Count: {count}')
    print(f'Unpacked size: {len(unpacked)}')
    
    # Name hashes
    print('\nName hashes:')
    for i in range(count):
        nh = struct.unpack('<Q', unpacked[4+i*8:12+i*8])[0]
        print(f'  [{i}] 0x{nh:016X}')
    
    name_table_end = 4 + count * 8
    print(f'\nName table end: 0x{name_table_end:X}')
    
    # Check for padding until 0x104
    padding = unpacked[name_table_end:0x104]
    zeros = b'\x00' * len(padding)
    print(f'Padding (0x{name_table_end:X} to 0x104): {len(padding)} bytes, all zeros: {padding == zeros}')
    
    # Entry table at 0x104
    print(f'\nEntry table at 0x104:')
    for i in range(count):
        offset = 0x104 + i * 16
        type_h, name_h = struct.unpack('<QQ', unpacked[offset:offset+16])
        tn = TYPES.get(type_h, f'0x{type_h:X}')
        print(f'  [{i}] type={tn}, name=0x{name_h:016X}')
    
    # Data section
    entry_table_end = 0x104 + count * 16
    print(f'\nData section starts at: 0x{entry_table_end:X}')
    print(f'First 64 bytes: {unpacked[entry_table_end:entry_table_end+64].hex()}')
    
    # Parse first resource header (36 bytes)
    type_h, name_h, flags, stream_size, main_size, unk = struct.unpack('<QQIQII', unpacked[entry_table_end:entry_table_end+36])
    print(f'\nFirst resource header (36 bytes):')
    print(f'  type: 0x{type_h:X} ({TYPES.get(type_h, "unknown")})')
    print(f'  name: 0x{name_h:X}')
    print(f'  flags: {flags}')
    print(f'  stream_size: {stream_size}')
    print(f'  main_size: {main_size}')
    print(f'  unknown: {unk}')

def analyze_our_bundle():
    """Analyze our generated bundle"""
    print("\n=== Analyzing our bundle ===")
    with open(r'test_bundle_output\5336b90f589342b6', 'rb') as f:
        data = f.read()
    
    unpacked = decompress(data)
    count = struct.unpack('<I', unpacked[:4])[0]
    print(f'Count: {count}')
    print(f'Unpacked size: {len(unpacked)}')
    
    name_table_end = 4 + count * 8
    print(f'Name table end: 0x{name_table_end:X}')
    
    # First 5 name hashes
    print('\nFirst 5 name hashes:')
    for i in range(min(5, count)):
        nh = struct.unpack('<Q', unpacked[4+i*8:12+i*8])[0]
        print(f'  [{i}] 0x{nh:016X}')
    
    # Check padding
    padding = unpacked[name_table_end:0x104]
    zeros = b'\x00' * len(padding)
    print(f'Padding (0x{name_table_end:X} to 0x104): {len(padding)} bytes, all zeros: {padding == zeros}')
    
    # Entry table
    print(f'\nEntry table at 0x104 (first 5):')
    for i in range(min(5, count)):
        offset = 0x104 + i * 16
        type_h, name_h = struct.unpack('<QQ', unpacked[offset:offset+16])
        tn = TYPES.get(type_h, f'0x{type_h:X}')
        print(f'  [{i}] type={tn}, name=0x{name_h:016X}')
    
    # Data section
    entry_table_end = 0x104 + count * 16
    print(f'\nData section starts at: 0x{entry_table_end:X}')
    print(f'First 64 bytes: {unpacked[entry_table_end:entry_table_end+64].hex()}')
    
    # Parse first resource header
    type_h, name_h, flags, stream_size, main_size, unk = struct.unpack('<QQIQII', unpacked[entry_table_end:entry_table_end+36])
    print(f'\nFirst resource header (36 bytes):')
    print(f'  type: 0x{type_h:X} ({TYPES.get(type_h, "unknown")})')
    print(f'  name: 0x{name_h:X}')
    print(f'  flags: {flags}')
    print(f'  stream_size: {stream_size}')
    print(f'  main_size: {main_size}')
    print(f'  unknown: {unk}')

def analyze_our_entry_table():
    """Check where entry table actually starts in our bundle"""
    print("\n=== Checking our bundle entry table location ===")
    with open(r'test_bundle_output\5336b90f589342b6', 'rb') as f:
        data = f.read()
    
    unpacked = decompress(data)
    count = struct.unpack('<I', unpacked[:4])[0]
    print(f'Count: {count}')
    
    name_table_end = 4 + count * 8
    entry_table_end = name_table_end + count * 16
    print(f'Name table end: 0x{name_table_end:X}')
    print(f'Entry table end: 0x{entry_table_end:X}')
    
    # Check entry table at name_table_end
    print(f'\nFirst 5 entries at name_table_end (0x{name_table_end:X}):')
    for i in range(min(5, count)):
        offset = name_table_end + i * 16
        th, nh = struct.unpack('<QQ', unpacked[offset:offset+16])
        tn = TYPES.get(th, '?')
        print(f'  [{i}] type=0x{th:X} ({tn}), name=0x{nh:X}')
    
    # Check data section at entry_table_end
    print(f'\nData section at 0x{entry_table_end:X}:')
    print(f'  First 48 bytes: {unpacked[entry_table_end:entry_table_end+48].hex()}')
    
    type_h, name_h, flags, stream_size, main_size, unk = struct.unpack('<QQIQII', unpacked[entry_table_end:entry_table_end+36])
    print(f'\nFirst resource header:')
    print(f'  type: 0x{type_h:X} ({TYPES.get(type_h, "?")})')
    print(f'  name: 0x{name_h:X}')
    print(f'  flags: {flags}')
    print(f'  stream_size: {stream_size}')
    print(f'  main_size: {main_size}')
    print(f'  unknown: {unk}')

def compare_bundles():
    """Compare our bundle with a working large bundle"""
    print("\n=== Comparing bundles ===")
    
    # Real large bundle  
    with open(r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\07cdebae91f29fae', 'rb') as f:
        real = decompress(f.read())
    # Our bundle
    with open(r'test_bundle_output\5336b90f589342b6', 'rb') as f:
        ours = decompress(f.read())
    
    real_count = struct.unpack('<I', real[:4])[0]
    our_count = struct.unpack('<I', ours[:4])[0]
    
    print(f'Real count: {real_count}')
    print(f'Our count: {our_count}')
    
    real_nte = 4 + real_count * 8
    our_nte = 4 + our_count * 8
    
    print(f'\nName table ends: real=0x{real_nte:X}, ours=0x{our_nte:X}')
    
    # First entry in each
    real_type, real_name = struct.unpack('<QQ', real[real_nte:real_nte+16])
    our_type, our_name = struct.unpack('<QQ', ours[our_nte:our_nte+16])
    
    print(f'First entry after name table:')
    print(f'  Real: type=0x{real_type:X} ({TYPES.get(real_type, "?")}), name=0x{real_name:X}')
    print(f'  Ours: type=0x{our_type:X} ({TYPES.get(our_type, "?")}), name=0x{our_name:X}')
    
    # Check data section
    real_ete = real_nte + real_count * 16
    our_ete = our_nte + our_count * 16
    
    print(f'\nData section starts: real=0x{real_ete:X}, ours=0x{our_ete:X}')
    
    # First resource header
    real_rh = struct.unpack('<QQIQII', real[real_ete:real_ete+36])
    our_rh = struct.unpack('<QQIQII', ours[our_ete:our_ete+36])
    
    print(f'First resource header:')
    print(f'  Real: type=0x{real_rh[0]:X}, name=0x{real_rh[1]:X}, flags={real_rh[2]}, stream={real_rh[3]}, main={real_rh[4]}')
    print(f'  Ours: type=0x{our_rh[0]:X}, name=0x{our_rh[1]:X}, flags={our_rh[2]}, stream={our_rh[3]}, main={our_rh[4]}')

def find_first_resource_in_large_bundle():
    """Find where resources actually start in the large bundle"""
    print("\n=== Finding resources in large bundle ===")
    
    with open(r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\07cdebae91f29fae', 'rb') as f:
        unpacked = decompress(f.read())
    
    count = 592
    entry_table_end = 4 + count * 8 + count * 16  # 0x3784
    
    print(f'Entry table ends at: 0x{entry_table_end:X}')
    
    # Search for first valid resource header
    print('Searching for first valid resource header...')
    for offset in range(entry_table_end, min(len(unpacked) - 36, entry_table_end + 0x100000), 4):
        type_h = struct.unpack('<Q', unpacked[offset:offset+8])[0]
        if type_h in TYPES:
            # Check if this looks like a valid header
            header = unpacked[offset:offset+36]
            if len(header) < 36:
                continue
            _, name_h, flags, stream_size, main_size, unk = struct.unpack('<QQIQII', header)
            if flags in [0, 1, 2] and stream_size == 0 and main_size < 100000000 and unk == 0:
                print(f'  Found at 0x{offset:X}:')
                print(f'    type: 0x{type_h:X} ({TYPES.get(type_h, "?")})')
                print(f'    name: 0x{name_h:X}')
                print(f'    flags: {flags}, main_size: {main_size}')
                print(f'    Gap from entry table: {offset - entry_table_end} bytes')
                break

def compare_with_without_materials():
    """Compare bundle with materials vs without materials"""
    print("\n=== Comparing bundle WITH vs WITHOUT materials ===")
    
    # With materials
    with open(r'test_bundle_output\5336b90f589342b6', 'rb') as f:
        with_mat = decompress(f.read())
    
    # Without materials
    with open(r'test_bundle_output\726eb8f6cebe4825', 'rb') as f:
        without_mat = decompress(f.read())
    
    with_count = struct.unpack('<I', with_mat[:4])[0]
    without_count = struct.unpack('<I', without_mat[:4])[0]
    
    print(f'With materials: count={with_count}')
    print(f'Without materials: count={without_count}')
    
    # Check layouts
    for name, data, count in [('With', with_mat, with_count), ('Without', without_mat, without_count)]:
        nte = 4 + count * 8
        ete = nte + count * 16
        print(f'\n{name}:')
        print(f'  Name table end: 0x{nte:X}')
        print(f'  Entry table end: 0x{ete:X}')
        
        # First entry type
        type_h = struct.unpack('<Q', data[nte:nte+8])[0]
        print(f'  First entry type: 0x{type_h:X} ({TYPES.get(type_h, "?")})')
        
        # First resource header
        type_h, name_h, flags, _, main_size, _ = struct.unpack('<QQIQII', data[ete:ete+36])
        print(f'  First resource: type=0x{type_h:X} ({TYPES.get(type_h, "?")}), flags={flags}, size={main_size}')

def analyze_without_materials():
    """Analyze the bundle without materials"""
    print("\n=== Analyzing bundle WITHOUT materials ===")
    
    with open(r'test_bundle_output\726eb8f6cebe4825', 'rb') as f:
        unpacked = decompress(f.read())
    
    count = struct.unpack('<I', unpacked[:4])[0]
    print(f'Count: {count}')
    
    name_table_end = 4 + count * 8
    print(f'Name table end: 0x{name_table_end:X}')
    
    # With 21 entries, name table ends at 0xAC which is < 0x104
    # So there should be padding
    
    # Check bytes from name_table_end to 0x104
    print(f'Bytes from 0x{name_table_end:X} to 0x104:')
    gap = unpacked[name_table_end:0x104]
    print(f'  Length: {len(gap)}')
    print(f'  All zeros: {gap == bytes(len(gap))}')
    print(f'  First 32 bytes: {gap[:32].hex()}')
    
    # Entry table at 0x104
    print(f'\nEntry table at 0x104:')
    for i in range(5):
        offset = 0x104 + i * 16
        type_h, name_h = struct.unpack('<QQ', unpacked[offset:offset+16])
        tn = TYPES.get(type_h, '?')
        print(f'  [{i}] type=0x{type_h:X} ({tn})')
    
    # Data section
    entry_table_end = 0x104 + count * 16
    print(f'\nData section at 0x{entry_table_end:X}:')
    type_h, name_h, flags, _, main_size, _ = struct.unpack('<QQIQII', unpacked[entry_table_end:entry_table_end+36])
    tn = TYPES.get(type_h, '?')
    print(f'  First resource: type=0x{type_h:X} ({tn}), flags={flags}, size={main_size}')

def analyze_with_materials_detailed():
    """Analyze the bundle WITH materials in detail"""
    print("\n=== Analyzing bundle WITH materials (detailed) ===")
    
    with open(r'test_bundle_output\5336b90f589342b6', 'rb') as f:
        unpacked = decompress(f.read())
    
    count = struct.unpack('<I', unpacked[:4])[0]
    print(f'Count: {count}')
    
    name_table_end = 4 + count * 8  # 0x14C
    print(f'Name table end: 0x{name_table_end:X}')
    
    # Since 0x14C > 0x104, entry table should start at 0x14C
    entry_table_start = name_table_end  # No padding
    entry_table_end = entry_table_start + count * 16
    
    print(f'Entry table: 0x{entry_table_start:X} - 0x{entry_table_end:X}')
    
    # Check entry table
    print(f'\nEntry table entries (first 10):')
    for i in range(min(10, count)):
        offset = entry_table_start + i * 16
        type_h, name_h = struct.unpack('<QQ', unpacked[offset:offset+16])
        tn = TYPES.get(type_h, '?')
        print(f'  [{i}] type=0x{type_h:X} ({tn}), name=0x{name_h:X}')
    
    # Check data section
    print(f'\nData section at 0x{entry_table_end:X}:')
    print(f'  First 48 bytes: {unpacked[entry_table_end:entry_table_end+48].hex()}')
    
    type_h, name_h, flags, stream_size, main_size, unk = struct.unpack('<QQIQII', unpacked[entry_table_end:entry_table_end+36])
    tn = TYPES.get(type_h, '?')
    print(f'\nFirst resource header:')
    print(f'  type: 0x{type_h:X} ({tn})')
    print(f'  name: 0x{name_h:X}')
    print(f'  flags: {flags}')
    print(f'  stream_size: {stream_size}')
    print(f'  main_size: {main_size}')
    print(f'  unknown: {unk}')
    
    # Check the first 5 resources  
    print(f'\nFirst 5 resources:')
    pos = entry_table_end
    for i in range(5):
        type_h, name_h, flags, stream_size, main_size, unk = struct.unpack('<QQIQII', unpacked[pos:pos+36])
        tn = TYPES.get(type_h, '?')
        print(f'  [{i}] type={tn}, name=0x{name_h:X}, size={main_size}')
        pos += 36 + main_size

if __name__ == '__main__':
    analyze_with_materials_detailed()
