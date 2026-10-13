"""Inspect a bundle file to verify its structure"""
import struct
import zlib

BUNDLE_SIG_OLD = 0xF0000004
ZLIB_CHUNK = 0x10000

def decompress_bundle(packed_data):
    """Decompress a packed bundle file."""
    if len(packed_data) < 12:
        return packed_data
    
    # Read 12-byte header
    signature, unzipped_size, padding = struct.unpack('<III', packed_data[:12])
    
    if signature != BUNDLE_SIG_OLD:
        print(f"Not a bundle file (signature: 0x{signature:08X})")
        return packed_data
    
    print(f"  Signature: 0x{signature:08X}")
    print(f"  Expected size: {unzipped_size}")
    print(f"  Padding: {padding}")
    
    # Decompress zlib chunks
    offset = 12
    unpacked_chunks = []
    chunk_num = 0
    
    while offset < len(packed_data):
        if offset + 4 > len(packed_data):
            break
            
        chunk_size = struct.unpack('<I', packed_data[offset:offset+4])[0]
        offset += 4
        
        if chunk_size == 0:
            break
            
        if chunk_size == ZLIB_CHUNK:
            # Size marker, skip
            continue
            
        if offset + chunk_size > len(packed_data):
            print(f"  Warning: Chunk {chunk_num} size {chunk_size} exceeds remaining data")
            break
            
        chunk_data = packed_data[offset:offset + chunk_size]
        offset += chunk_size
        chunk_num += 1
        
        try:
            decompressed = zlib.decompress(chunk_data)
            unpacked_chunks.append(decompressed)
            print(f"  Chunk {chunk_num}: {chunk_size} -> {len(decompressed)} bytes")
        except zlib.error as e:
            print(f"  Chunk {chunk_num} decompress failed: {e}")
            break
    
    return b''.join(unpacked_chunks)


def inspect_bundle(path):
    print(f"\n=== Inspecting: {path} ===")
    
    with open(path, 'rb') as f:
        data = f.read()
    
    print(f"File size: {len(data)} bytes")
    print()
    
    # Decompress
    print("Decompressing...")
    unpacked = decompress_bundle(data)
    print(f"Unpacked size: {len(unpacked)} bytes")
    print()
    
    # Parse header
    if len(unpacked) < 0x108:
        print("Bundle too small!")
        return
    
    resource_count = struct.unpack('<I', unpacked[0:4])[0]
    print(f"Resource count: {resource_count}")
    print()
    
    # Resource hash table (64-bit hashes)
    print("Resource hash table:")
    hash_offset = 4
    for i in range(resource_count):
        h = struct.unpack('<Q', unpacked[hash_offset:hash_offset+8])[0]
        print(f"  [{i}] 0x{h:016X}")
        hash_offset += 8
    print()
    
    # Resource entries at offset 0x104
    # 16 bytes each: type_hash (8) + name_hash (8)
    print("Resource entries at 0x104 (16 bytes each):")
    entry_offset = 0x104
    for i in range(resource_count):
        entry = unpacked[entry_offset:entry_offset+16]
        type_hash = struct.unpack('<Q', entry[0:8])[0]
        name_hash = struct.unpack('<Q', entry[8:16])[0]
        
        # Identify type
        if type_hash == 0xAD9C6D9ED1E5E77A:
            type_name = "package"
        elif type_hash == 0xCD4238C6A0C69E32:
            type_name = "texture"
        else:
            type_name = "unknown"
        
        print(f"  [{i}] Type: 0x{type_hash:016X} ({type_name})")
        print(f"       Name: 0x{name_hash:016X}")
        entry_offset += 16
    print()
    
    # Show raw resource data
    data_offset = 0x104 + (resource_count * 16)
    print(f"Resource data starts at offset {data_offset}:")
    print()
    
    # For each resource, show its header and identify it
    for i in range(resource_count):
        print(f"Resource {i} at offset {data_offset}:")
        
        if data_offset + 36 > len(unpacked):
            print("  Not enough data for resource header")
            break
        
        # 36-byte header
        type_h = struct.unpack('<Q', unpacked[data_offset:data_offset+8])[0]
        name_h = struct.unpack('<Q', unpacked[data_offset+8:data_offset+16])[0]
        flags = struct.unpack('<I', unpacked[data_offset+16:data_offset+20])[0]
        stream_size = struct.unpack('<Q', unpacked[data_offset+20:data_offset+28])[0]
        main_size = struct.unpack('<I', unpacked[data_offset+28:data_offset+32])[0]
        unk = struct.unpack('<I', unpacked[data_offset+32:data_offset+36])[0]
        
        # Type name
        if type_h == 0xAD9C6D9ED1E5E77A:
            type_name = "package"
        elif type_h == 0xCD4238C6A0C69E32:
            type_name = "texture"
        else:
            type_name = "unknown"
        
        print(f"  Type: 0x{type_h:016X} ({type_name})")
        print(f"  Name: 0x{name_h:016X}")
        print(f"  Flags: {flags}")
        print(f"  Stream size: {stream_size}")
        print(f"  Main size: {main_size}")
        print(f"  Unknown: {unk}")
        
        # Show first 64 bytes of resource data
        res_data_start = data_offset + 36
        res_data = unpacked[res_data_start:res_data_start+64]
        print(f"  Data (first 64 bytes):")
        for j in range(0, min(64, len(res_data)), 16):
            chunk = res_data[j:j+16]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            print(f"    {j:04x}: {hex_str:<48}  {ascii_str}")
        print()
        
        # Move to next resource
        data_offset = res_data_start + main_size


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        inspect_bundle(sys.argv[1])
    else:
        # Default to our test bundle
        # Default to a locally-built test bundle (output_packages/ is gitignored)
        inspect_bundle("output_packages/cb2d6f461440fb54")
