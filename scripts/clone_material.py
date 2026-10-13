#!/usr/bin/env python3
"""
Gauntlet Material Cloner
=========================
Clones a native Stingray .material binary and patches its texture hash(es)
to point to custom textures. This avoids crashes caused by using simplified
material formats (e.g. 52-byte) with world-object shaders that expect full
parameter layouts (scalars, UV transforms, PBR settings, trailing data).

Usage:
    python clone_material.py <native.material> <output.material> \\
        --remap "old_hash:new_path" ["old_hash2:new_path2"...]
        --remap "gameobjects/food/ham_diff:custom/my_mod/sword_diff"

    python clone_material.py <native.material> --list    # list texture refs
    python clone_material.py --help

Integration:
    In mod.json, use:
    {
        "type": "material",
        "path": "custom/my_mod/sword_mat",
        "clone_from": "Exports/extracted_materials/raw/8aeed77b10003a6c.material",
        "remap_textures": {
            "gameobjects/food/ham_diff": "custom/my_mod/sword_diff"
        }
    }

The clone preserves ALL shader parameters, scalars, and trailing data.
Only the 64-bit texture hash fields are replaced.
"""

import struct
import json
import os
import sys
import argparse
from pathlib import Path
from bundle_tools import murmur_hash64

# The Gauntlet material format embeds texture hashes at MULTIPLE locations:
# 1. The header "texture entries" (24 + i*16 + 8) - these use a different hash system
# 2. The trailing data sections - these use full MurmurHash64 values keyed by ThinHash
#
# Instead of trying to parse both systems (which we don't fully understand),
# we use a byte-level SEARCH-AND-REPLACE approach:
#   - Hash the old texture path with MurmurHash64
#   - Find all occurrences of that 8-byte hash in the binary
#   - Replace with the new hash
# This preserves ALL material structure and parameters.


def clone_material(native_path: str, output_path: str,
                   remap: dict, verbose: bool = False) -> bool:
    """
    Clone a native material by searching and replacing texture hashes.

    Uses byte-level find-and-replace: finds the 8-byte MurmurHash64 of the
    old texture path everywhere in the binary and replaces with the new hash.

    Args:
        native_path: Path to the native .material binary
        output_path: Where to write the cloned material
        remap: Dict mapping old_texture_path -> new_texture_path
               (or old_hash_hex -> new_texture_path)
    Returns:
        True on success
    """
    with open(native_path, 'rb') as f:
        blob = bytearray(f.read())

    if verbose:
        info = list_texture_refs(native_path)
        print(f"Source: {os.path.basename(native_path)} ({info['size']} bytes)")
        print(f"  Shader: {info['shader_hash_hex']}")
        print(f"  Texture slots: {info['tex_count']} (header entries)")
        for ref in info['texture_refs']:
            print(f"    [{ref['index']}] offset={ref['offset']:#06x} "
                  f"slot={ref['slot_index']} "
                  f"name32={ref['name_hash32_hex']} "
                  f"tex64={ref['texture_hash_hex']}")

    # Build remap: old_hash_8bytes -> new_hash_8bytes
    remap_bytes = {}  # bytes (length 8) -> bytes (length 8)
    remap_verbose = []  # for logging
    for old_key, new_path in remap.items():
        old_key = old_key.strip()
        if old_key.startswith('0x') or old_key.startswith('0X'):
            old_hash_int = int(old_key, 16)
        else:
            old_hash_int = murmur_hash64(old_key)
        new_hash_int = murmur_hash64(new_path)
        old_bytes = struct.pack('<Q', old_hash_int)
        new_bytes = struct.pack('<Q', new_hash_int)
        remap_bytes[old_bytes] = new_bytes
        remap_verbose.append((old_key, old_hash_int, new_path, new_hash_int))

    # Byte-level search and replace
    total_replacements = 0
    for old_bytes, new_bytes in remap_bytes.items():
        count = 0
        pos = 0
        while True:
            pos = blob.find(old_bytes, pos)
            if pos == -1:
                break
            # Replace 8 bytes
            blob[pos:pos+8] = new_bytes
            if verbose:
                # Find which remap rule this belongs to
                old_path_str = f"0x{struct.unpack('<Q', old_bytes)[0]:016x}"
                for ok, oh, np, nh in remap_verbose:
                    if struct.pack('<Q', oh) == old_bytes:
                        old_path_str = ok
                        break
                print(f"  [ok] Replaced @ 0x{pos:04x}: 0x{struct.unpack('<Q', old_bytes)[0]:016x} "
                      f"-> 0x{struct.unpack('<Q', new_bytes)[0]:016x} ({old_path_str})")
            count += 1
            pos += 8  # Skip past the replaced bytes to avoid infinite loop
        total_replacements += count
        if count == 0 and verbose:
            old_path_str = f"0x{struct.unpack('<Q', old_bytes)[0]:016x}"
            for ok, oh, np, nh in remap_verbose:
                if struct.pack('<Q', oh) == old_bytes:
                    old_path_str = ok
                    break
            print(f"  - NOT FOUND in file: {old_path_str} "
                  f"(0x{struct.unpack('<Q', old_bytes)[0]:016x})")

    if total_replacements == 0:
        print(f"  [WARNING] No texture hashes matched in file!")
        print(f"  To see what hashes are in this material, use --list")

    # Write output
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(blob))

    print(f"  Cloned: {os.path.basename(native_path)} -> {output_path}")
    print(f"  {total_replacements} hash(es) replaced in {len(blob)}-byte material")
    return True


def list_texture_refs(material_path: str) -> dict:
    """Parse a material binary and list all texture references found."""
    with open(material_path, 'rb') as f:
        blob = f.read()

    if len(blob) < 24:
        return {'error': f'File too small ({len(blob)} bytes)'}

    version, tex_count = struct.unpack_from('<II', blob, 0)
    shader_hash = struct.unpack_from('<Q', blob, 8)[0]

    refs = []
    off = 24
    for i in range(tex_count):
        if off + 16 > len(blob):
            break
        slot_idx, name_hash32, tex_hash = struct.unpack_from('<IIQ', blob, off)
        refs.append({
            'index': i, 'offset': off,
            'slot_index': slot_idx,
            'name_hash32': name_hash32,
            'name_hash32_hex': f'0x{name_hash32:08x}',
            'texture_hash': tex_hash,
            'texture_hash_hex': f'0x{tex_hash:016x}',
        })
        off += 16

    return {
        'path': material_path, 'size': len(blob),
        'version': version, 'tex_count': tex_count,
        'shader_hash': shader_hash,
        'shader_hash_hex': f'0x{shader_hash:016x}',
        'texture_refs': refs,
        'remaining_bytes': len(blob) - off,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Clone a native Gauntlet material and remap its texture hashes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("native", help="Path to native .material binary")
    parser.add_argument("output", nargs="?", help="Output .material path")
    parser.add_argument("--remap", "-r", action="append", default=[],
                        help='Remap rule: "old_path_or_hash:new_texture_path" '
                             '(can specify multiple times)')
    parser.add_argument("--remap-file", "-f",
                        help="JSON file with remap dict {old_path: new_path, ...}")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List texture references and exit")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")

    args = parser.parse_args()

    # --list mode
    if args.list:
        info = list_texture_refs(args.native)
        if 'error' in info:
            print(f"  [ERROR] {info['error']}")
            return
        print(f"Material: {info['path']}")
        print(f"  Size:      {info['size']} bytes")
        print(f"  Version:   {info['version']}")
        print(f"  Shader:    {info['shader_hash_hex']}")
        print(f"  Textures:  {info['tex_count']} slot(s)")
        for ref in info['texture_refs']:
            print(f"\n  Slot [{ref['index']}]:")
            print(f"    Offset:    0x{ref['offset']:04x}")
            print(f"    Slot idx:  {ref['slot_index']}")
            print(f"    ThinHash:  {ref['name_hash32_hex']}")
            print(f"    TexHash:   {ref['texture_hash_hex']}")
        print(f"\n  Remaining payload: {info['remaining_bytes']} bytes")
        return

    if not args.output:
        parser.error("output path is required (unless --list is used)")

    # Build remap dict
    remap = {}
    for r in args.remap:
        if ':' not in r:
            print(f"  [ERROR] Invalid remap rule: '{r}' (expected 'old:new')")
            sys.exit(1)
        old, new = r.split(':', 1)
        remap[old.strip()] = new.strip()

    if args.remap_file:
        with open(args.remap_file) as f:
            remap.update(json.load(f))

    if not remap:
        parser.error("No remap rules specified. Use --remap or --remap-file.")

    clone_material(args.native, args.output, remap, verbose=args.verbose)


if __name__ == '__main__':
    main()
