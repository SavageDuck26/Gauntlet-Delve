#!/usr/bin/env python3
"""
Gauntlet Bundle Database Patcher
================================
Properly adds custom bundle entries to bundle_database.data

The bundle_database.data format:
- Header (8 bytes): version (4), entry_count (4)
- Entries (52 bytes each):
  - platform_id (4): Always 1
  - bundle_name_len (4): Always 16
  - bundle_name (16): 16-char hex bundle name
  - stream_name_len (4): 0 or 23 (for bundles with .stream)
  - stream_name (0 or 23): "bundlename.stream\0" if present
  - padding (5 bytes): fills to 52 bytes

Each resource type+name combo in a bundle gets its own entry.
"""

import struct
import os
import sys
import shutil
import json
from pathlib import Path

GAUNTLET_CONTENTS = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"

def murmur_hash64(key: str, seed: int = 0) -> int:
    """MurmurHash64A"""
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


def read_database(db_path: str) -> tuple:
    """Read the bundle database."""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    version = struct.unpack('<I', data[:4])[0]
    entry_count = struct.unpack('<I', data[4:8])[0]
    
    return version, entry_count, data


def create_entry(bundle_name: str) -> bytes:
    """
    Create a database entry with proper format.
    
    Entry format (VARIABLE LENGTH):
    - uint32: platform (1)
    - uint32: bundle name length (16)
    - char[16]: bundle name (16 hex chars)
    - uint32: stream name length (23)
    - char[23]: stream name ("bundlename.stream")
    - byte: null terminator (0x00)
    
    Total: 4+4+16+4+23+1 = 52 bytes (with stream)
    """
    entry = bytearray()
    
    # Platform ID (always 1 for win32)
    entry.extend(struct.pack('<I', 1))
    
    # Bundle name length (always 16 hex chars)
    entry.extend(struct.pack('<I', 16))
    
    # Bundle name (16 chars)
    name_bytes = bundle_name[:16].encode('ascii')
    if len(name_bytes) < 16:
        name_bytes = name_bytes.ljust(16, b'0')
    entry.extend(name_bytes)
    
    # Stream name: always include it (game expects it even if file doesn't exist)
    stream_name = bundle_name[:16] + ".stream"  # 23 chars
    entry.extend(struct.pack('<I', 23))
    entry.extend(stream_name.encode('ascii'))
    
    # Null terminator
    entry.append(0x00)
    
    return bytes(entry)


def add_bundle_to_database(db_path: str, bundle_name: str, 
                           num_resources: int = 1):
    """
    Add entries for a bundle to the database.
    
    The game expects one entry per resource in the bundle.
    For our custom packages, we need entries for the package + each texture.
    """
    # Read current database
    version, entry_count, data = read_database(db_path)
    
    print(f"Current database: version={version}, entries={entry_count}")
    
    # Create backup
    backup_path = db_path + ".backup_custom"
    if not os.path.exists(backup_path):
        shutil.copy2(db_path, backup_path)
        print(f"Backup created: {backup_path}")
    
    # Create new entries
    new_entries = []
    for i in range(num_resources):
        entry = create_entry(bundle_name)
        new_entries.append(entry)
    
    # Build new database
    new_data = bytearray()
    
    # Header with updated count
    new_count = entry_count + num_resources
    new_data.extend(struct.pack('<I', version))
    new_data.extend(struct.pack('<I', new_count))
    
    # Original entries (skip header)
    new_data.extend(data[8:])
    
    # New entries at the end (highest priority)
    for entry in new_entries:
        new_data.extend(entry)
    
    # Write updated database
    with open(db_path, 'wb') as f:
        f.write(new_data)
    
    print(f"Added {num_resources} entries for bundle '{bundle_name}'")
    print(f"New database: {new_count} entries, {len(new_data)} bytes")
    
    return True


def register_package_from_manifest(manifest_path: str, db_path: str = None):
    """
    Register a custom package from its manifest file.
    """
    if db_path is None:
        db_path = os.path.join(GAUNTLET_CONTENTS, "bundle_database.data")
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    bundle_name = manifest['bundle_name']
    texture_count = manifest.get('texture_count', 0)
    
    # We need entries for: 1 package + N textures
    num_resources = 1 + texture_count
    
    print(f"Registering package from manifest:")
    print(f"  Bundle: {bundle_name}")
    print(f"  Package path: {manifest['package_path']}")
    print(f"  Textures: {texture_count}")
    print(f"  Total resources: {num_resources}")
    print()
    
    return add_bundle_to_database(db_path, bundle_name, num_resources)


def restore_database():
    """Restore the original database from backup."""
    db_path = os.path.join(GAUNTLET_CONTENTS, "bundle_database.data")
    backup_path = db_path + ".backup_custom"
    
    if os.path.exists(backup_path):
        shutil.copy2(backup_path, db_path)
        print(f"Restored database from {backup_path}")
        return True
    else:
        # Try the other backup
        backup_path2 = db_path + ".backup"
        if os.path.exists(backup_path2):
            shutil.copy2(backup_path2, db_path)
            print(f"Restored database from {backup_path2}")
            return True
    
    print("No backup found!")
    return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Register custom bundles in Gauntlet')
    subparsers = parser.add_subparsers(dest='command')
    
    # register command
    reg_parser = subparsers.add_parser('register', help='Register a package from manifest')
    reg_parser.add_argument('manifest', help='Path to manifest JSON file')
    
    # add command
    add_parser = subparsers.add_parser('add', help='Add a bundle directly')
    add_parser.add_argument('bundle', help='Bundle name (16-char hex)')
    add_parser.add_argument('--resources', '-n', type=int, default=1,
                           help='Number of resources in bundle')
    add_parser.add_argument('--stream', action='store_true',
                           help='Bundle has a .stream file')
    
    # restore command
    restore_parser = subparsers.add_parser('restore', help='Restore original database')
    
    # info command
    info_parser = subparsers.add_parser('info', help='Show database info')
    
    args = parser.parse_args()
    
    db_path = os.path.join(GAUNTLET_CONTENTS, "bundle_database.data")
    
    if args.command == 'register':
        register_package_from_manifest(args.manifest, db_path)
        
    elif args.command == 'add':
        add_bundle_to_database(db_path, args.bundle, args.resources, args.stream)
        
    elif args.command == 'restore':
        restore_database()
        
    elif args.command == 'info':
        version, count, data = read_database(db_path)
        print(f"Bundle Database: {db_path}")
        print(f"  Version: {version}")
        print(f"  Entries: {count}")
        print(f"  Size: {len(data)} bytes")
        
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
