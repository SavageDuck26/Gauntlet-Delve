#!/usr/bin/env python3
"""
Stingray .bones resource encoder/decoder
Type hash: 0x18DEAD01056B72E9

Binary layout (confirmed, 363-byte sample):
  uint32  bone_count
  uint32  unknown = 1     (possibly format version or flags)
  bone_count × uint32     name_hash32  (MurmurHash32 of each bone name)
  uint32  string_count    = bone_count (redundant, always matches)
  string_count × str\0    null-terminated bone name strings, packed

NOTE: This resource contains only the bone name list.
The parent hierarchy is stored in the .unit resource (node tree).
The hashes allow animation tracks to reference bones efficiently.

Round-trip: binary ↔ JSON
"""

import struct, json, sys, os

TYPE_HASH = 0x18DEAD01056B72E9


# Stingray uses a 32-bit variant of MurmurHash.
# The .bones file stores lower-32 bits of Stingray's murmur64 hash.
# For encoding, if you change bone names you must recompute hashes.
def stingray_hash32(name: str) -> int:
    """
    Compute the 32-bit name hash used in Stingray .bones files.
    This is the lower 32 bits of MurmurHash64A seeded with 0.
    """
    # Stingray uses MurmurHash64A with seed=0, little-endian
    # Here we just use Python's built-in murmur approximation via mmh3 if available,
    # or fall back to a basic implementation.
    try:
        import mmh3
        # mmh3.hash64 returns (high, low) as signed ints
        lo, hi = mmh3.hash64(name.encode('utf-8'), seed=0, signed=False)
        return lo & 0xFFFFFFFF
    except ImportError:
        pass

    # Fallback: simple MurmurHash64A implementation
    data = name.encode('utf-8')
    seed = 0
    m = 0xC6A4A7935BD1E995
    r = 47
    h = (seed ^ (len(data) * m)) & 0xFFFFFFFFFFFFFFFF
    i = 0
    while i + 8 <= len(data):
        k = struct.unpack_from('<Q', data, i)[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
        i += 8
    remaining = len(data) - i
    if remaining > 0:
        tail = data[i:]
        k = 0
        for j in range(remaining - 1, -1, -1):
            k = (k << 8) | tail[j]
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> r
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> r
    return h & 0xFFFFFFFF


def decode_bones(blob: bytes) -> dict:
    """Decode a .bones binary blob to a Python dict."""
    if len(blob) < 8:
        raise ValueError(f"Too short: {len(blob)}")

    bone_count, unknown = struct.unpack_from('<II', blob, 0)
    off = 8

    name_hashes = []
    for i in range(bone_count):
        h = struct.unpack_from('<I', blob, off)[0]
        name_hashes.append(f'{h:#010x}')
        off += 4

    string_count = struct.unpack_from('<I', blob, off)[0]
    off += 4

    names = []
    for _ in range(string_count):
        end = blob.index(b'\x00', off)
        names.append(blob[off:end].decode('utf-8', 'replace'))
        off = end + 1

    bones = []
    for i in range(min(len(names), bone_count)):
        bones.append({
            'name': names[i],
            'hash32': name_hashes[i] if i < len(name_hashes) else '0x00000000',
        })

    return {
        'bone_count': bone_count,
        'unknown': unknown,
        'bones': bones,
    }


def encode_bones(data: dict) -> bytes:
    """Encode a bones dict back to binary blob."""
    bones = data['bones']
    unknown = data.get('unknown', 1)
    bone_count = len(bones)

    out = struct.pack('<II', bone_count, unknown)

    for b in bones:
        if 'hash32' in b and b['hash32']:
            h = int(b['hash32'], 16)
        else:
            h = stingray_hash32(b['name'])
        out += struct.pack('<I', h)

    out += struct.pack('<I', bone_count)
    for b in bones:
        out += b['name'].encode('utf-8') + b'\x00'

    return out


def selftest():
    sample = os.path.join(os.path.dirname(__file__), '..', 'Exports', 'samples',
                          'bones_e8a62af86d41f0e5.bones')
    if not os.path.exists(sample):
        print("SKIP: sample not found")
        return
    blob = open(sample, 'rb').read()
    data = decode_bones(blob)
    print(f"Decoded {data['bone_count']} bones:")
    for b in data['bones'][:6]:
        print(f"  {b['hash32']}  {b['name']}")
    if len(data['bones']) > 6:
        print(f"  ... ({len(data['bones'])} total)")
    blob2 = encode_bones(data)
    if blob == blob2:
        print("bones_tools selftest: PASS (byte-exact)")
    else:
        print(f"bones_tools selftest: MISMATCH  orig={len(blob)} re={len(blob2)}")
        for i, (a, b) in enumerate(zip(blob, blob2)):
            if a != b:
                print(f"  first diff @ byte {i}: orig={a:#04x} re={b:#04x}")
                break


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]

    if cmd == 'selftest':
        selftest()

    elif cmd == 'decode':
        path = sys.argv[2]
        blob = open(path, 'rb').read()
        data = decode_bones(blob)
        out = path.rsplit('.', 1)[0] + '.json'
        with open(out, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Decoded {data['bone_count']} bones → {out}")

    elif cmd == 'encode':
        path = sys.argv[2]
        out = sys.argv[3] if len(sys.argv) > 3 else path.rsplit('.', 1)[0] + '.bones'
        with open(path) as f:
            data = json.load(f)
        blob = encode_bones(data)
        with open(out, 'wb') as f:
            f.write(blob)
        print(f"Encoded {len(data['bones'])} bones → {out}  ({len(blob)} bytes)")

    elif cmd == 'bvh':
        # bones_tools bvh <file.bones>  [out.bvh]
        path = sys.argv[2]
        out  = sys.argv[3] if len(sys.argv) > 3 else path.rsplit('.', 1)[0] + '.bvh'
        blob = open(path, 'rb').read()
        data = decode_bones(blob)
        export_bvh(data, out)

    elif cmd == 'armature':
        # bones_tools armature <file.bones>  [out.json]
        path = sys.argv[2]
        out  = sys.argv[3] if len(sys.argv) > 3 else path.rsplit('.', 1)[0] + '_armature.json'
        blob = open(path, 'rb').read()
        data = decode_bones(blob)
        export_armature_json(data, out)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


# ── Blender / BVH export ──────────────────────────────────────────────────────

def export_bvh(bones_json: dict, out_path: str,
               parent_indices: list | None = None) -> str:
    """
    Export a bones dict to BVH (Biovision Hierarchy) skeleton file.

    BVH can be imported into Blender via File > Import > Motion Capture (.bvh).
    The skeleton uses identity bind pose (T-pose at origin).

    parent_indices: list of int (parent bone index, -1 for root).
                    If None, all bones are children of bone 0 (flat hierarchy).
    """
    bones = bones_json['bones']
    n = len(bones)

    if parent_indices is None:
        # Flat hierarchy: bone 0 is root, all others are children of 0
        parent_indices = [-1] + [0] * (n - 1) if n > 0 else []

    # Build children map
    children: dict[int, list[int]] = {i: [] for i in range(n)}
    roots: list[int] = []
    for i, p in enumerate(parent_indices):
        if p < 0:
            roots.append(i)
        elif p < n:
            children[p].append(i)

    if not roots:
        roots = [0]

    lines = ['HIERARCHY']

    def write_joint(idx: int, depth: int) -> None:
        indent = '\t' * depth
        name = bones[idx]['name'] if idx < n else f'bone_{idx}'
        is_end = not children[idx]
        tag = 'ROOT' if depth == 0 else 'JOINT'
        lines.append(f'{indent}{tag} {name}')
        lines.append(f'{indent}{{')
        lines.append(f'{indent}\tOFFSET 0.00 0.00 0.00')
        lines.append(f'{indent}\tCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation')
        for child in children[idx]:
            write_joint(child, depth + 1)
        if is_end:
            lines.append(f'{indent}\tEnd Site')
            lines.append(f'{indent}\t{{')
            lines.append(f'{indent}\t\tOFFSET 0.00 1.00 0.00')
            lines.append(f'{indent}\t}}')
        lines.append(f'{indent}}}')

    for root_idx in roots:
        write_joint(root_idx, 0)

    # Motion section (1 frame, identity pose)
    lines.append('MOTION')
    lines.append('Frames: 1')
    lines.append('Frame Time: 0.033333')
    # 6 channels per bone × n bones, all zero (identity)
    lines.append(' '.join(['0.00'] * 6 * n))

    with open(out_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print(f"Exported {n} bones → {out_path}")
    return out_path


def export_armature_json(bones_json: dict, out_path: str,
                         parent_indices: list | None = None) -> str:
    """
    Export skeleton as a simple JSON armature definition.
    This can be consumed by a Blender Python script to create an armature.
    """
    bones = bones_json['bones']
    n = len(bones)
    if parent_indices is None:
        parent_indices = [-1] + [0] * (n - 1) if n > 0 else []

    armature = {
        '_note': (
            'Import into Blender: run blender_import_armature.py script, '
            'or use File > Import > glTF if exported from unit_to_gltf.py'
        ),
        'bones': [
            {
                'name': bones[i]['name'],
                'hash32': bones[i].get('hash32', '0x00000000'),
                'parent': parent_indices[i] if i < len(parent_indices) else -1,
                'head': [0.0, 0.0, float(i) * 0.1],  # stacked vertically
                'tail': [0.0, 0.0, float(i) * 0.1 + 0.1],
            }
            for i in range(n)
        ]
    }
    with open(out_path, 'w') as f:
        json.dump(armature, f, indent=2)
    print(f"Exported armature JSON ({n} bones) → {out_path}")
    return out_path


if __name__ == '__main__':
    main()
