"""Quick script to analyze database entry format"""
import struct

# Check CURRENT database (after our modifications)
db_path = r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\bundle_database.data'
with open(db_path, 'rb') as f:
    data = f.read()

print('CURRENT DATABASE:')
print(f'  Version: {struct.unpack("<I", data[0:4])[0]}')
print(f'  Count: {struct.unpack("<I", data[4:8])[0]}')
print(f'  File size: {len(data)}')
print()

# Show the last 200 bytes (our added entries should be at end)
print('Last 200 bytes of file (hex dump):')
start = len(data) - 200
for i in range(0, 200, 16):
    chunk = data[start+i:start+i+16]
    hex_str = ' '.join(f'{b:02x}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'  {start+i:04x}: {hex_str}  {ascii_str}')
print()

# Parse entries and look for our bundle
entries = []
offset = 8
count = struct.unpack('<I', data[4:8])[0]

for i in range(count):
    entry_start = offset
    
    platform = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    
    name_len = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    
    # Sanity check
    if name_len > 50 or name_len == 0:
        print(f'Invalid entry at {entry_start}: name_len={name_len}')
        break
    
    name = data[offset:offset+name_len].decode('ascii', errors='replace')
    offset += name_len
    
    stream_len = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    
    if stream_len > 0 and stream_len < 100:
        stream = data[offset:offset+stream_len].decode('ascii', errors='replace')
        offset += stream_len
    else:
        stream = ''
    
    # Skip null terminator
    offset += 1
    
    entries.append({
        'platform': platform,
        'name': name,
        'stream': stream,
        'size': offset - entry_start
    })

print(f'Parsed {len(entries)} entries')
print()

# Look for our custom bundle
custom_entries = [e for e in entries if 'cb2d6f461440fb54' in e['name']]
print(f'Found {len(custom_entries)} entries for cb2d6f461440fb54:')
for e in custom_entries:
    print(f'  Platform: {e["platform"]}, Name: {e["name"]}, Stream: {e["stream"]}')
