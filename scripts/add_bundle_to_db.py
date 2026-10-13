"""
Add a custom bundle to Gauntlet's bundle_database.data

This script allows you to register a new custom bundle so the game can find it
when you call Game:load_package().

USAGE:
    python add_bundle_to_db.py d5ec4eb9fc5f3c88 --textures 21

This will add entries for your bundle and all its textures to the database.
Make sure to backup the original bundle_database.data first!
"""

import struct
import argparse
import shutil
from pathlib import Path
import zlib

# Paths
CONTENTS_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents")
BUNDLE_DB = CONTENTS_DIR / "bundle_database.data"

def parse_bundle_db(data: bytes):
    """Parse the bundle database to understand its structure.
    
    Entry format:
    - flags (4 bytes) - always 1
    - bundle_len (4 bytes) - length of bundle name (no null)
    - bundle_name (bundle_len bytes) - bundle name without null
    - stream_len (4 bytes) - length of stream name (no null)
    - stream_name (stream_len bytes) - stream name without null
    - null terminator (1 byte) - always 0x00
    """
    version, count = struct.unpack('<II', data[0:8])
    print(f"Database version: {version}")
    print(f"Total entries: {count}")
    
    entries = []
    offset = 8
    
    for i in range(count):
        if offset + 4 > len(data):
            break
        
        flags = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        
        bundle_len = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        bundle_name = data[offset:offset+bundle_len].decode('utf-8')
        offset += bundle_len
        
        stream_len = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        stream_name = data[offset:offset+stream_len].decode('utf-8')
        offset += stream_len
        
        # Skip the null terminator that follows stream_name
        offset += 1
        
        entries.append({
            'flags': flags,
            'bundle': bundle_name,
            'stream': stream_name
        })
    
    return version, entries


def build_bundle_db(version: int, entries: list) -> bytes:
    """Build a new bundle database from entries.
    
    Entry format:
    - flags (4 bytes)
    - bundle_len (4 bytes)
    - bundle_name (bundle_len bytes, no null)
    - stream_len (4 bytes)  
    - stream_name (stream_len bytes, no null)
    - null terminator (1 byte)
    """
    sections = []
    
    # Header: version + count
    sections.append(struct.pack('<II', version, len(entries)))
    
    # Entries
    for entry in entries:
        bundle = entry['bundle']
        stream = entry['stream']
        
        sections.append(struct.pack('<I', entry['flags']))
        sections.append(struct.pack('<I', len(bundle)))
        sections.append(bundle.encode('utf-8'))
        sections.append(struct.pack('<I', len(stream)))
        sections.append(stream.encode('utf-8'))
        sections.append(b'\x00')  # Null terminator after stream name
    
    return b''.join(sections)


def add_bundle_entries(entries: list, bundle_name: str, resource_count: int):
    """Add entries for a new bundle and its resources."""
    new_entries = []
    
    stream_name = f"{bundle_name}.stream"
    
    # Add one entry per resource
    for i in range(resource_count):
        new_entries.append({
            'flags': 1,  # Same as other entries
            'bundle': bundle_name,
            'stream': stream_name
        })
    
    return entries + new_entries


def main():
    parser = argparse.ArgumentParser(description="Add custom bundle to Gauntlet bundle database")
    parser.add_argument('bundle', help="Bundle name (e.g., d5ec4eb9fc5f3c88)")
    parser.add_argument('--textures', '-t', type=int, default=1, help="Number of resources in bundle")
    parser.add_argument('--dry-run', action='store_true', help="Don't modify files, just show what would happen")
    parser.add_argument('--restore', action='store_true', help="Restore from backup")
    args = parser.parse_args()
    
    backup_path = BUNDLE_DB.with_suffix('.data.backup')
    
    if args.restore:
        if backup_path.exists():
            shutil.copy(backup_path, BUNDLE_DB)
            print(f"Restored from {backup_path}")
        else:
            print("No backup found!")
        return
    
    # Read current database
    print(f"Reading {BUNDLE_DB}...")
    with open(BUNDLE_DB, 'rb') as f:
        data = f.read()
    
    version, entries = parse_bundle_db(data)
    print(f"Found {len(entries)} existing entries")
    
    # Check if bundle already exists
    existing_bundles = set(e['bundle'] for e in entries)
    if args.bundle in existing_bundles:
        print(f"Bundle {args.bundle} already exists in database!")
        return
    
    # Add new entries
    print(f"\nAdding {args.textures} entries for bundle {args.bundle}...")
    new_entries = add_bundle_entries(entries, args.bundle, args.textures)
    print(f"New total entries: {len(new_entries)}")
    
    # Build new database
    new_data = build_bundle_db(version, new_entries)
    print(f"New database size: {len(new_data):,} bytes (was {len(data):,})")
    
    if args.dry_run:
        print("\n[DRY RUN] Would write new database but --dry-run was specified")
        return
    
    # Create backup
    if not backup_path.exists():
        print(f"\nCreating backup at {backup_path}...")
        shutil.copy(BUNDLE_DB, backup_path)
    
    # Write new database
    print(f"Writing new database...")
    with open(BUNDLE_DB, 'wb') as f:
        f.write(new_data)
    
    print("\n[ok] Done! Your bundle is now registered in the database.")
    print(f"  Bundle: {args.bundle}")
    print(f"  Stream: {args.bundle}.stream")
    print(f"  Resources: {args.textures}")
    print("\nMake sure to:")
    print(f"  1. Copy your bundle to: {CONTENTS_DIR / args.bundle}")
    print(f"  2. Create empty stream file: {CONTENTS_DIR / (args.bundle + '.stream')}")
    print("  3. Restart the game")


if __name__ == '__main__':
    main()
