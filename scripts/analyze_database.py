"""Analyze the bundle_database.data structure"""
import struct
import os
import re

GAUNTLET = r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents'

db_file = os.path.join(GAUNTLET, 'bundle_database.data')
with open(db_file, 'rb') as f:
    db_data = f.read()

# Header
version = struct.unpack('<I', db_data[:4])[0]
num_entries = struct.unpack('<I', db_data[4:8])[0]

print(f'bundle_database.data structure:')
print(f'  Version: {version}')
print(f'  Number of entries: {num_entries}')

# Find all bundle name occurrences using regex
bundle_pattern = rb'([0-9a-f]{16})'
matches = list(re.finditer(bundle_pattern, db_data))

# Get unique bundle names
unique_bundles = set()
for m in matches:
    unique_bundles.add(m.group(1).decode('ascii'))

print(f'\nFound {len(unique_bundles)} unique bundle names in database')
print(f'\nBundle names:')
for name in sorted(unique_bundles)[:30]:
    print(f'  {name}')
if len(unique_bundles) > 30:
    print(f'  ... and {len(unique_bundles) - 30} more')

# Try to understand the entry structure better
print(f'\n=== Entry structure analysis ===')

# Look for pattern transitions (where bundle name changes)
offset = 8  # Skip header
prev_bundle = None
entry_starts = []

while offset < min(20000, len(db_data)):
    # Look for the pattern: 01 00 00 00 10 00 00 00
    if db_data[offset:offset+8] == b'\x01\x00\x00\x00\x10\x00\x00\x00':
        # Read bundle name (16 hex chars)
        bundle_name = db_data[offset+8:offset+24].decode('ascii', errors='replace')
        if bundle_name != prev_bundle:
            entry_starts.append((offset, bundle_name))
            prev_bundle = bundle_name
    offset += 1

print(f'Found {len(entry_starts)} unique bundle sections in first 20KB:')
for off, name in entry_starts[:30]:
    print(f'  Offset 0x{off:04X}: {name}')

# Try to find the actual record structure
# Based on the hex dump, it looks like entries might be 51 bytes each:
# 01 00 00 00 (4) + 10 00 00 00 (4) + name (16) + 17 00 00 00 (4) + name.stream + 00 (24)
# = 4 + 4 + 16 + 4 + 23 = 51 bytes

record_size = 51
print(f'\n=== Testing {record_size}-byte record theory ===')
offset = 8
for i in range(5):
    record = db_data[offset:offset+record_size]
    platform = struct.unpack('<I', record[0:4])[0]
    name_len = struct.unpack('<I', record[4:8])[0]
    name = record[8:8+name_len].decode('ascii', errors='replace')
    stream_len = struct.unpack('<I', record[24:28])[0]
    stream = record[28:28+stream_len].decode('ascii', errors='replace').rstrip('\x00')
    print(f'  Record {i}: platform={platform}, name_len={name_len}, name={name}, stream_len={stream_len}, stream={stream}')
    offset += record_size
