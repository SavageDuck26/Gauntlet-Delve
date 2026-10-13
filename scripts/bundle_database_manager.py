#!/usr/bin/env python3
"""
Gauntlet Bundle Database Manager
================================
Tools for managing the bundle_database.data file which controls
what bundles the game loads.

According to Bitsquid documentation:
- Bundles listed LATER in the database take PRIORITY
- This means adding your custom bundle at the END will make it
  override any conflicting resources from earlier bundles

Usage:
    python bundle_database_manager.py list              List all bundles
    python bundle_database_manager.py info              Show database info
    python bundle_database_manager.py add <bundle>      Add a bundle entry
    python bundle_database_manager.py remove <bundle>   Remove a bundle entry
    python bundle_database_manager.py backup            Create backup
    python bundle_database_manager.py restore           Restore from backup
"""

import struct
import os
import sys
import shutil
import re
from pathlib import Path
import argparse

# Default Gauntlet path
GAUNTLET_CONTENTS = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"


def murmur_hash64(key: str, seed: int = 0) -> int:
    """MurmurHash64A - for computing bundle name hashes"""
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


class BundleDatabase:
    """
    Parser for bundle_database.data
    
    File format (based on analysis):
    - Header: 8 bytes
      - uint32: version (2 for Gauntlet)
      - uint32: entry count
    - Entries: Variable size (approximately 51 bytes each)
      - uint32: platform ID (usually 1)
      - uint32: bundle name length (16 for hex names)
      - bytes: bundle name
      - uint32: stream name length (0 or varies)
      - bytes: stream name (if length > 0)
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.version = 0
        self.entries = []
        self.raw_data = None
        
        if os.path.exists(db_path):
            self._parse()
    
    def _parse(self):
        """Parse the bundle database file."""
        with open(self.db_path, 'rb') as f:
            self.raw_data = f.read()
        
        if len(self.raw_data) < 8:
            raise ValueError("Database file too small")
        
        self.version = struct.unpack('<I', self.raw_data[:4])[0]
        entry_count = struct.unpack('<I', self.raw_data[4:8])[0]
        
        # Parse entries
        offset = 8
        while offset < len(self.raw_data) and len(self.entries) < entry_count:
            try:
                entry, size = self._parse_entry(offset)
                if entry:
                    self.entries.append(entry)
                    offset += size
                else:
                    break
            except:
                break
    
    def _parse_entry(self, offset: int):
        """
        Parse a single entry from the database.
        Returns (entry_dict, bytes_consumed) or (None, 0) on failure.
        """
        if offset + 8 > len(self.raw_data):
            return None, 0
        
        platform = struct.unpack_from('<I', self.raw_data, offset)[0]
        name_len = struct.unpack_from('<I', self.raw_data, offset + 4)[0]
        
        if name_len == 0 or name_len > 100:
            return None, 0
        
        bundle_name = self.raw_data[offset + 8:offset + 8 + name_len]
        bundle_name = bundle_name.decode('ascii', errors='replace').rstrip('\x00')
        
        # Read stream info
        stream_offset = offset + 8 + name_len
        if stream_offset + 4 > len(self.raw_data):
            return None, 0
        
        stream_len = struct.unpack_from('<I', self.raw_data, stream_offset)[0]
        
        stream_name = None
        total_size = 8 + name_len + 4
        
        if stream_len > 0 and stream_len < 100:
            stream_name = self.raw_data[stream_offset + 4:stream_offset + 4 + stream_len]
            stream_name = stream_name.decode('ascii', errors='replace').rstrip('\x00')
            total_size += stream_len
        
        return {
            'platform': platform,
            'bundle_name': bundle_name,
            'stream_name': stream_name,
            'has_stream': stream_name is not None
        }, total_size
    
    def list_bundles(self):
        """Return list of bundle names."""
        return [e['bundle_name'] for e in self.entries]
    
    def find_bundle(self, name: str):
        """Find an entry by bundle name."""
        for i, entry in enumerate(self.entries):
            if entry['bundle_name'] == name:
                return i, entry
        return -1, None
    
    def add_bundle(self, bundle_name: str, has_stream: bool = False):
        """
        Add a new bundle entry at the end of the database.
        Being at the end gives it highest priority.
        """
        # Check if already exists
        idx, _ = self.find_bundle(bundle_name)
        if idx >= 0:
            print(f"Bundle '{bundle_name}' already in database at index {idx}")
            return False
        
        entry = {
            'platform': 1,
            'bundle_name': bundle_name[:16],  # Max 16 chars
            'stream_name': f"{bundle_name}.stream" if has_stream else None,
            'has_stream': has_stream
        }
        
        self.entries.append(entry)
        return True
    
    def remove_bundle(self, bundle_name: str):
        """Remove a bundle entry."""
        idx, _ = self.find_bundle(bundle_name)
        if idx < 0:
            print(f"Bundle '{bundle_name}' not found in database")
            return False
        
        self.entries.pop(idx)
        return True
    
    def save(self, output_path: str = None):
        """Save the database to file."""
        if output_path is None:
            output_path = self.db_path
        
        # Build new database
        data = bytearray()
        
        # Header
        data.extend(struct.pack('<I', self.version))
        data.extend(struct.pack('<I', len(self.entries)))
        
        # Entries
        for entry in self.entries:
            # Platform
            data.extend(struct.pack('<I', entry['platform']))
            
            # Bundle name
            name_bytes = entry['bundle_name'].encode('ascii')
            data.extend(struct.pack('<I', len(name_bytes)))
            data.extend(name_bytes)
            
            # Stream name
            if entry['has_stream'] and entry['stream_name']:
                stream_bytes = (entry['stream_name'] + '\x00').encode('ascii')
                data.extend(struct.pack('<I', len(stream_bytes)))
                data.extend(stream_bytes)
            else:
                data.extend(struct.pack('<I', 0))
        
        with open(output_path, 'wb') as f:
            f.write(data)
        
        return len(data)


def backup_database(contents_folder: str):
    """Create a backup of the bundle database."""
    db_path = os.path.join(contents_folder, 'bundle_database.data')
    backup_path = db_path + '.backup'
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return False
    
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")
    return True


def restore_database(contents_folder: str):
    """Restore the bundle database from backup."""
    db_path = os.path.join(contents_folder, 'bundle_database.data')
    backup_path = db_path + '.backup'
    
    if not os.path.exists(backup_path):
        print(f"Backup not found: {backup_path}")
        return False
    
    shutil.copy2(backup_path, db_path)
    print(f"Restored from: {backup_path}")
    return True


def cmd_list(args):
    """List all bundles in the database."""
    db = BundleDatabase(os.path.join(args.contents, 'bundle_database.data'))
    
    print(f"Bundle Database: {len(db.entries)} entries")
    print("-" * 50)
    
    for i, entry in enumerate(db.entries):
        stream = " [STREAM]" if entry['has_stream'] else ""
        print(f"{i:4d}: {entry['bundle_name']}{stream}")


def cmd_info(args):
    """Show database information."""
    db = BundleDatabase(os.path.join(args.contents, 'bundle_database.data'))
    
    print("Bundle Database Information")
    print("=" * 50)
    print(f"Path: {db.db_path}")
    print(f"Version: {db.version}")
    print(f"Entries: {len(db.entries)}")
    
    # Count streams
    streams = sum(1 for e in db.entries if e['has_stream'])
    print(f"Bundles with streams: {streams}")
    
    # Show unique bundles
    unique = set(e['bundle_name'] for e in db.entries)
    print(f"Unique bundle names: {len(unique)}")
    
    # Check for actual bundle files
    print("\nBundle file status:")
    for bundle_name in sorted(unique)[:20]:
        path = os.path.join(args.contents, bundle_name)
        exists = "✓" if os.path.exists(path) else "✗"
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"  {exists} {bundle_name} ({size:,} bytes)" if exists == "✓" else f"  {exists} {bundle_name}")


def cmd_add(args):
    """Add a bundle to the database."""
    db_path = os.path.join(args.contents, 'bundle_database.data')
    
    # Create backup first
    backup_path = db_path + '.backup'
    if not os.path.exists(backup_path):
        shutil.copy2(db_path, backup_path)
        print(f"Backup created: {backup_path}")
    
    db = BundleDatabase(db_path)
    
    bundle_name = args.bundle
    # If it's a file path, extract just the name
    if os.path.exists(bundle_name):
        bundle_name = os.path.basename(bundle_name)
    
    # Check for stream file
    has_stream = os.path.exists(os.path.join(args.contents, bundle_name + '.stream'))
    
    if db.add_bundle(bundle_name, has_stream):
        size = db.save()
        print(f"Added bundle '{bundle_name}' to database")
        print(f"New database size: {size} bytes, {len(db.entries)} entries")
        print(f"\nBundle is now at the END = HIGHEST PRIORITY")
    else:
        print("Failed to add bundle")


def cmd_remove(args):
    """Remove a bundle from the database."""
    db_path = os.path.join(args.contents, 'bundle_database.data')
    
    # Create backup first
    backup_path = db_path + '.backup'
    if not os.path.exists(backup_path):
        shutil.copy2(db_path, backup_path)
        print(f"Backup created: {backup_path}")
    
    db = BundleDatabase(db_path)
    
    if db.remove_bundle(args.bundle):
        size = db.save()
        print(f"Removed bundle '{args.bundle}' from database")
        print(f"New database size: {size} bytes, {len(db.entries)} entries")
    else:
        print("Failed to remove bundle")


def cmd_backup(args):
    """Create a backup of the database."""
    backup_database(args.contents)


def cmd_restore(args):
    """Restore database from backup."""
    restore_database(args.contents)


def main():
    parser = argparse.ArgumentParser(
        description='Manage Gauntlet bundle_database.data',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    
    parser.add_argument('--contents', default=GAUNTLET_CONTENTS,
                       help='Path to Gauntlet contents folder')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # list command
    list_parser = subparsers.add_parser('list', help='List all bundles')
    
    # info command
    info_parser = subparsers.add_parser('info', help='Show database info')
    
    # add command
    add_parser = subparsers.add_parser('add', help='Add a bundle')
    add_parser.add_argument('bundle', help='Bundle name or file path')
    
    # remove command
    remove_parser = subparsers.add_parser('remove', help='Remove a bundle')
    remove_parser.add_argument('bundle', help='Bundle name to remove')
    
    # backup command
    backup_parser = subparsers.add_parser('backup', help='Create backup')
    
    # restore command
    restore_parser = subparsers.add_parser('restore', help='Restore from backup')
    
    args = parser.parse_args()
    
    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'info':
        cmd_info(args)
    elif args.command == 'add':
        cmd_add(args)
    elif args.command == 'remove':
        cmd_remove(args)
    elif args.command == 'backup':
        cmd_backup(args)
    elif args.command == 'restore':
        cmd_restore(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
