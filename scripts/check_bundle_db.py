"""Check bundle database for our custom bundle"""
import struct

db_path = r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\bundle_database.data'
with open(db_path, 'rb') as f:
    data = f.read()

bundles = {}
offset = 8
version, count = struct.unpack('<II', data[0:8])
print(f'Database version: {version}, Count: {count}')

for i in range(count):
    flags = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    bundle_len = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    bundle_name = data[offset:offset+bundle_len].decode('utf-8')
    offset += bundle_len
    stream_len = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    stream_name = data[offset:offset+stream_len].decode('utf-8')
    offset += stream_len + 1
    
    bundles[bundle_name] = bundles.get(bundle_name, 0) + 1

print(f'\nUnique bundles: {len(bundles)}')

# Check for our bundle
our_bundle = 'd5ec4eb9fc5f3c88'
if our_bundle in bundles:
    print(f'Our bundle {our_bundle}: {bundles[our_bundle]} entries')
else:
    print(f'Our bundle {our_bundle}: NOT FOUND!')

# Entry count distribution
counts = set(bundles.values())
print(f'\nEntry count values: {sorted(counts)}')

# Show bundles with different counts
for c in sorted(counts):
    matching = [b for b, cnt in bundles.items() if cnt == c]
    if len(matching) <= 5:
        print(f'  {c} entries: {matching}')
    else:
        print(f'  {c} entries: {len(matching)} bundles')
