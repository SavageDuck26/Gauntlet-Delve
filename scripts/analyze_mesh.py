"""
Gauntlet Mesh/Unit Analyzer
Explore the structure of unit and mesh resources in Gauntlet bundles.
"""

import zlib
import struct
import os
from pathlib import Path

BUNDLE_SIG_OLD = 0xF0000004
BUNDLE_SIG_NEW = 0xF0000005
GAUNTLET_CONTENTS = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"

# Known type hashes
TYPE_HASHES = {
    0xCD4238C6A0C69E32: "texture",
    0xEAC0B497876ADEDF: "material",
    0xA14E8DFA2CD117E2: "lua",
    0xE0A48D0BE9A7453F: "unit",
    0xCCE8D5B5F5AE333F: "shader",
    0x931E336D7646CC26: "animation",
    0xAD9C6D9ED1E5E77A: "package",
    0x2A690FD348FE9AC5: "level",
    0x5F7203C8F280DAB8: "physics",
    0x82645835E6B73232: "config",
    0x9EFE0A916AAE7880: "font",
    0x0D972BAB10B40FD3: "strings",
    0xA8193123526FAD64: "unknown_1",
}

def murmur_hash64(data: bytes, seed: int = 0) -> int:
    """Compute MurmurHash64A."""
    m = 0xc6a4a7935bd1e995
    r = 47
    mask = 0xFFFFFFFFFFFFFFFF
    h = (seed ^ (len(data) * m)) & mask
    
    # Process 8-byte chunks
    for i in range(0, len(data) // 8 * 8, 8):
        k = struct.unpack('<Q', data[i:i+8])[0]
        k = (k * m) & mask
        k ^= (k >> r)
        k = (k * m) & mask
        h ^= k
        h = (h * m) & mask
    
    # Handle remaining bytes
    remaining = len(data) % 8
    if remaining > 0:
        tail = data[-(remaining):]
        k = 0
        for i in range(remaining - 1, -1, -1):
            k = (k << 8) | tail[i]
        h ^= k
        h = (h * m) & mask
    
    h ^= (h >> r)
    h = (h * m) & mask
    h ^= (h >> r)
    return h


def decompress_bundle(packed_data: bytes) -> bytes:
    """Decompress a packed bundle file."""
    sig = struct.unpack('<I', packed_data[:4])[0]
    if sig not in (BUNDLE_SIG_OLD, BUNDLE_SIG_NEW):
        raise ValueError(f"Invalid bundle signature: 0x{sig:08X}")
    
    offset = 12
    unpacked_chunks = []
    
    while offset < len(packed_data):
        if offset + 4 > len(packed_data):
            break
        chunk_size = struct.unpack('<I', packed_data[offset:offset+4])[0]
        offset += 4
        
        if chunk_size == 0x10000 or chunk_size == 0:
            continue
        
        if offset + chunk_size > len(packed_data):
            break
            
        chunk_data = packed_data[offset:offset + chunk_size]
        offset += chunk_size
        
        try:
            decompressed = zlib.decompress(chunk_data)
            unpacked_chunks.append(decompressed)
        except zlib.error:
            break
    
    return b''.join(unpacked_chunks)


def find_resource_types(data: bytes) -> dict:
    """Find all resource types and their locations in the bundle."""
    resources = {}
    
    if len(data) < 0x104:
        return resources
    
    count = struct.unpack('<I', data[0:4])[0]
    if count > 10000:  # Sanity check
        count = 10000
    
    entry_offset = 0x104
    for i in range(count):
        if entry_offset + 16 > len(data):
            break
        
        type_hash = struct.unpack('<Q', data[entry_offset:entry_offset+8])[0]
        name_hash = struct.unpack('<Q', data[entry_offset+8:entry_offset+16])[0]
        
        type_name = TYPE_HASHES.get(type_hash, f"0x{type_hash:016X}")
        
        if type_name not in resources:
            resources[type_name] = []
        resources[type_name].append(name_hash)
        
        entry_offset += 16
    
    return resources


def find_mesh_signatures(data: bytes) -> list:
    """Find potential mesh data signatures in the bundle."""
    # Common 3D model signatures
    signatures = {
        b'mesh': "mesh header",
        b'MESH': "MESH header",
        b'geom': "geometry",
        b'GEOM': "GEOMETRY",
        b'vert': "vertices",
        b'VERT': "VERTICES",
        b'indx': "indices",
        b'INDX': "INDICES",
        b'bone': "bones",
        b'BONE': "BONES",
        b'skin': "skinning",
        b'node': "nodes",
        b'NODE': "NODES",
    }
    
    found = []
    for sig, name in signatures.items():
        pos = 0
        while True:
            pos = data.find(sig, pos)
            if pos == -1:
                break
            found.append((pos, sig, name))
            pos += 1
    
    found.sort(key=lambda x: x[0])
    return found


def analyze_unit_data(data: bytes, resources: dict) -> None:
    """Analyze unit resource data structure."""
    if "unit" not in resources:
        print("No unit resources found in this bundle.")
        return
    
    print(f"\nFound {len(resources['unit'])} unit resources")
    
    # Look for patterns near unit data
    # In Bitsquid, unit files reference mesh files by name hash
    
    # Find sections that could be unit definitions
    # Units typically have:
    # - Mesh references (hash)
    # - Material references (hash)
    # - Bone definitions
    # - Animation references
    
    # Let's look for common patterns
    mesh_hash = murmur_hash64(b"mesh")
    print(f"'mesh' type hash: 0x{mesh_hash:016X}")
    
    # Search for this hash in the data
    mesh_hash_bytes = struct.pack('<Q', mesh_hash)
    pos = 0
    count = 0
    while True:
        pos = data.find(mesh_hash_bytes, pos)
        if pos == -1:
            break
        count += 1
        pos += 1
    print(f"Found 'mesh' hash {count} times in bundle")


def hex_dump(data: bytes, offset: int, length: int = 256, bytes_per_line: int = 32) -> str:
    """Create a hex dump of data."""
    lines = []
    end = min(offset + length, len(data))
    for i in range(offset, end, bytes_per_line):
        hex_part = ' '.join(f'{b:02X}' for b in data[i:min(i+bytes_per_line, end)])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:min(i+bytes_per_line, end)])
        lines.append(f"{i:08X}: {hex_part:<{bytes_per_line*3}} {ascii_part}")
    return '\n'.join(lines)


def find_vertex_data(data: bytes) -> list:
    """Look for potential vertex data structures."""
    # Vertex data typically has:
    # - Consistent stride (12 bytes for XYZ, 24 for XYZ+normal, 32+ for full vertex)
    # - Float values in reasonable range (-100 to +100 for positions)
    # - Often aligned to 4 or 16 bytes
    
    candidates = []
    
    # Look for sections with many consecutive floats
    for offset in range(0, len(data) - 48, 4):
        try:
            # Check for 4 consecutive valid floats (potential vertices)
            floats = struct.unpack('<12f', data[offset:offset+48])
            valid = True
            for f in floats:
                if not (-1000 < f < 1000) or f != f:  # NaN check
                    valid = False
                    break
            
            if valid:
                # Check if this looks like vertex data (reasonable x,y,z pattern)
                candidates.append(offset)
        except:
            pass
    
    return candidates


def analyze_bundle_for_mesh(bundle_path: Path) -> None:
    """Analyze a bundle for mesh/unit data."""
    print(f"\nAnalyzing: {bundle_path.name}")
    print("=" * 60)
    
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    data = decompress_bundle(packed_data)
    print(f"Decompressed size: {len(data):,} bytes")
    
    # Find resource types
    resources = find_resource_types(data)
    print(f"\nResource types found:")
    for type_name, hashes in sorted(resources.items()):
        print(f"  {type_name}: {len(hashes)} resources")
    
    # Analyze unit data if present
    if "unit" in resources:
        analyze_unit_data(data, resources)
    
    # Look for mesh signatures
    sigs = find_mesh_signatures(data)
    if sigs:
        print(f"\nMesh-related signatures found: {len(sigs)}")
        for pos, sig, name in sigs[:20]:  # Show first 20
            context = data[pos:pos+40]
            context_hex = ' '.join(f'{b:02X}' for b in context[:20])
            print(f"  0x{pos:08X}: {sig.decode('latin-1', errors='replace')} ({name}) - {context_hex}...")
    
    # Look for float arrays that could be vertices
    print("\nSearching for potential vertex data...")
    candidates = find_vertex_data(data)
    if candidates:
        print(f"Found {len(candidates)} potential vertex data regions")
        # Show first few
        for offset in candidates[:5]:
            floats = struct.unpack('<12f', data[offset:offset+48])
            print(f"  0x{offset:08X}: {floats[:3]} | {floats[3:6]} | {floats[6:9]} | {floats[9:12]}")


def scan_all_bundles() -> None:
    """Scan all bundles for unit/mesh resources."""
    contents = Path(GAUNTLET_CONTENTS)
    
    bundles_with_units = []
    bundles_with_mesh = []
    
    for f in sorted(contents.iterdir()):
        if not f.is_file() or f.suffix or len(f.name) != 16:
            continue
        try:
            int(f.name, 16)
        except ValueError:
            continue
        
        try:
            with open(f, 'rb') as fp:
                packed_data = fp.read()
            
            data = decompress_bundle(packed_data)
            resources = find_resource_types(data)
            
            unit_count = len(resources.get("unit", []))
            
            # Check for mesh signatures
            has_mesh_sig = any(
                sig in data for sig in [b'mesh', b'MESH', b'geom', b'GEOM', b'vert']
            )
            
            status = []
            if unit_count > 0:
                status.append(f"{unit_count} units")
                bundles_with_units.append((f.name, unit_count))
            if has_mesh_sig:
                status.append("mesh sigs")
                bundles_with_mesh.append(f.name)
            
            if status:
                print(f"{f.name}: {', '.join(status)}")
            
        except Exception as e:
            print(f"{f.name}: ERROR - {e}")
    
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Bundles with units: {len(bundles_with_units)}")
    print(f"  Bundles with mesh signatures: {len(bundles_with_mesh)}")
    
    if bundles_with_units:
        print(f"\nTop bundles by unit count:")
        for name, count in sorted(bundles_with_units, key=lambda x: -x[1])[:10]:
            print(f"  {name}: {count} units")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "scan":
            scan_all_bundles()
        else:
            bundle_path = Path(GAUNTLET_CONTENTS) / sys.argv[1]
            if bundle_path.exists():
                analyze_bundle_for_mesh(bundle_path)
            else:
                print(f"Bundle not found: {bundle_path}")
    else:
        print("Usage:")
        print("  python analyze_mesh.py scan              - Scan all bundles")
        print("  python analyze_mesh.py <bundle_name>     - Analyze specific bundle")
