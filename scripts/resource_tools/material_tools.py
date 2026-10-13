#!/usr/bin/env python3
"""
Stingray .material resource encoder/decoder
Type hash: 0xEAC0B497876ADEDF

Binary layout (version=10):
  uint32  version         = 10
  uint32  tex_count       number of texture slots
  uint64  shader_hash     MurmurHash64 of the shader name
  uint64  zeros           padding zeros
  tex_count × TextureEntry:
    uint32  slot_index    binding slot / layer index
    uint32  name_hash32   MurmurHash32 of the texture slot name
    uint64  texture_hash  MurmurHash64 of the texture asset name
  uint32  zero_sep        = 0  (separator)
  uint32  scalar_count    number of scalar/vector parameter slots
  scalar_count × ScalarEntry (16 bytes each):
    uint32  slot_index
    uint32[3]  data       raw float/uint data (inline parameter values)
  uint32  trailing_count  count of trailing float4 values
  trailing_count × float[4]  inline float4 parameters (tiling, color, etc.)

Round-trip: binary ↔ JSON
"""

import struct, json, sys, os

TYPE_HASH = 0xEAC0B497876ADEDF


def decode_material(blob: bytes) -> dict:
    """Decode a .material binary blob to a Python dict."""
    if len(blob) < 24:
        raise ValueError(f"Too short: {len(blob)}")

    version, tex_count = struct.unpack_from('<II', blob, 0)
    shader_hash = struct.unpack_from('<Q', blob, 8)[0]
    zeros_check = struct.unpack_from('<Q', blob, 16)[0]

    off = 24
    textures = []
    for i in range(tex_count):
        slot_idx, name_hash, tex_hash = struct.unpack_from('<IIQ', blob, off)
        textures.append({
            'slot_index': slot_idx,
            'name_hash32': f'{name_hash:#010x}',
            'texture_hash': f'{tex_hash:#018x}',
        })
        off += 16

    scalars = []
    if off + 8 <= len(blob):
        zero_sep, scalar_count = struct.unpack_from('<II', blob, off)
        off += 8
        for i in range(scalar_count):
            if off + 16 > len(blob):
                break
            slot_idx = struct.unpack_from('<I', blob, off)[0]
            raw_data = blob[off+4:off+16]
            scalars.append({
                'slot_index': slot_idx,
                'data_hex': raw_data.hex(),
            })
            off += 16

    # Remaining trailing data (float4 parameters, tiling, etc.)
    trailing_hex = blob[off:].hex() if off < len(blob) else ''

    result = {
        'version': version,
        'shader_hash': f'{shader_hash:#018x}',
        'textures': textures,
        'scalars': scalars,
    }
    if trailing_hex:
        result['_trailing_hex'] = trailing_hex
    return result


def encode_material(data: dict) -> bytes:
    """Encode a material dict back to binary blob."""
    version = data.get('version', 10)
    shader_hash = int(data['shader_hash'], 16)
    textures = data.get('textures', [])
    scalars = data.get('scalars', [])

    out = struct.pack('<II', version, len(textures))
    out += struct.pack('<Q', shader_hash)
    out += b'\x00' * 8  # zeros

    for t in textures:
        slot_idx = t['slot_index']
        name_hash = int(t['name_hash32'], 16)
        tex_hash = int(t['texture_hash'], 16)
        out += struct.pack('<IIQ', slot_idx, name_hash, tex_hash)

    out += struct.pack('<II', 0, len(scalars))
    for s in scalars:
        slot_idx = s['slot_index']
        raw = bytes.fromhex(s['data_hex'])
        out += struct.pack('<I', slot_idx) + raw[:12].ljust(12, b'\x00')

    if '_trailing_hex' in data:
        out += bytes.fromhex(data['_trailing_hex'])

    return out


def selftest():
    sample = os.path.join(os.path.dirname(__file__), '..', 'Exports', 'samples',
                          'material_180586771c034d8c.material')
    if not os.path.exists(sample):
        print("SKIP: sample not found")
        return
    blob = open(sample, 'rb').read()
    data = decode_material(blob)
    import json as _json
    print("Decoded material:")
    print(_json.dumps(data, indent=2))
    blob2 = encode_material(data)
    if blob == blob2:
        print("material_tools selftest: PASS (byte-exact)")
    else:
        print(f"material_tools selftest: MISMATCH  orig={len(blob)} re={len(blob2)}")
        for i, (a, b) in enumerate(zip(blob, blob2)):
            if a != b:
                print(f"  first diff @ byte {i}: orig={a:#04x} re={b:#04x}")
                break
        if len(blob) != len(blob2):
            print(f"  length: orig={len(blob)} re={len(blob2)}")


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
        data = decode_material(blob)
        out = path.rsplit('.', 1)[0] + '.json'
        with open(out, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Decoded {path} → {out}")
        print(f"  shader_hash={data['shader_hash']}")
        print(f"  {len(data['textures'])} texture(s), {len(data.get('scalars',[]))} scalar(s)")

    elif cmd == 'encode':
        path = sys.argv[2]
        out = sys.argv[3] if len(sys.argv) > 3 else path.rsplit('.', 1)[0] + '.material'
        with open(path) as f:
            data = json.load(f)
        blob = encode_material(data)
        with open(out, 'wb') as f:
            f.write(blob)
        print(f"Encoded {path} → {out}  ({len(blob)} bytes)")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
