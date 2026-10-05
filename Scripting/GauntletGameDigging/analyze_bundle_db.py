"""Analyze the bundle_database.data file structure"""
import struct
import sys

# Read bundle database  
db_path = r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\bundle_database.data'

with open(db_path, 'rb') as f:
    data = f.read()

# Parse header
version, count = struct.unpack('<II', data[0:8])
print(f'Version: {version}, Count: {count}')
print()

# Parse entries
offset = 8
entries = []
bundle_names = set()

for i in range(min(count, 100)):  # Parse first 100 entries
    if offset + 8 > len(data):
        break
    
    # Each entry format:
    # - 4 bytes: some flag (0 or 1)
    # - 4 bytes: string length
    # - N bytes: string (bundle name, no null terminator in length)
    
    flags = struct.unpack('<I', data[offset:offset+4])[0]
    str_len = struct.unpack('<I', data[offset+4:offset+8])[0]
    
    if str_len > 0 and str_len < 100 and offset + 8 + str_len <= len(data):
        name = data[offset+8:offset+8+str_len].decode('utf-8', errors='replace')
        # Handle null terminator
        if name.endswith('\x00'):
            name = name[:-1]
        entries.append((flags, name))
        bundle_names.add(name.replace('.stream',''))
        print(f'{i:4d}: flags={flags}, len={str_len:2d}, name="{name}"')
        offset += 8 + str_len
    else:
        print(f'Entry {i} at offset {offset:X}: invalid str_len={str_len}')
        break

print()
print(f'Parsed {len(entries)} entries')
print()

# Check if our bundle is listed
our_bundle = 'd5ec4eb9fc5f3c88'
if our_bundle in bundle_names:
    print(f'*** Our bundle {our_bundle} IS in the database! ***')
else:
    print(f'*** Our bundle {our_bundle} is NOT in the database ***')
