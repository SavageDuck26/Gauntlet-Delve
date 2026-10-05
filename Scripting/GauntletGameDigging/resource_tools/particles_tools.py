"""
Stingray .particles resource decode (partial).

Format (from binary analysis):
  Header (variable):
    uint32  flags         = 0xf5 (bitmask of active emitter properties)
    uint32  unknown_hash  possible CRC or type identifier
    uint32  count1        = 1 (number of emitters?)
    uint32  zeros[3]      padding
    uint32  count2        = 1
    uint32  key           = 0x0a

  At offset 0x20: embedded COBJ sub-object (root_type=6, root_off=48)
    Emitter descriptor in COBJ format with properties:
      - transform matrix (identity 4×4)
      - float parameters (bounds, lifetime, speed, etc.)
      - color RGBA values (1.0 = 100%)
      - reference to shader hash

  The overall format is a mixed binary + embedded COBJ structure.
  NOT a top-level COBJ blob — header is raw binary.

Round-trip status: decode-only (raw blob preserved). Full decode and re-encode
requires further reverse-engineering of the emitter parameter layout.
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict

HEADER_SIZE = 32


def decode_particles(blob: bytes) -> Dict[str, Any]:
    """Parse .particles blob → dict with header + raw data."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"blob too short ({len(blob)})")

    flags, unk_hash, count1, z1, z2, z3, count2, key = struct.unpack_from('<8I', blob, 0)

    # Try to find embedded COBJ sub-object at 0x20
    cobj_data = None
    if len(blob) >= 0x20 + 8:
        rt, ro = struct.unpack_from('<II', blob, 0x20)
        if rt == 6:
            cobj_data = {
                "cobj_at_0x20": True,
                "root_type": rt,
                "root_offset": ro,
            }

    return {
        "flags": f"0x{flags:08x}",
        "unknown_hash": f"0x{unk_hash:08x}",
        "emitter_count": count1,
        "count2": count2,
        "key": f"0x{key:02x}",
        "_embedded_cobj": cobj_data,
        "_raw_hex": blob.hex(),
        "_note": (
            "Particles format is mixed binary + embedded COBJ. "
            "Full structural decode not yet implemented. "
            "Use _raw_hex for byte-exact round-trip."
        ),
    }


def encode_particles(data: Dict[str, Any]) -> bytes:
    """Re-encode particles — returns original bytes from _raw_hex."""
    if "_raw_hex" in data:
        return bytes.fromhex(data["_raw_hex"])
    raise ValueError("Cannot encode particles without _raw_hex")


def decode_particles_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_particles(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Decoded {src} → {dst}  ({len(blob)} bytes, flags={data['flags']})")
    return dst


def encode_particles_file(src: str, dst: str | None = None) -> str:
    with open(src) as f:
        data = json.load(f)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.particles'
    open(dst, 'wb').write(encode_particles(data))
    print(f"Encoded {src} → {dst}")
    return dst


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/particles_180586771c034d8c.particles'
        orig = open(sample, 'rb').read()
        data = decode_particles(orig)
        re_enc = encode_particles(data)
        if orig == re_enc:
            print("particles_tools selftest: PASS (byte-exact via raw_hex)")
        else:
            print(f"particles_tools selftest: MISMATCH  orig={len(orig)} re-enc={len(re_enc)}")
        print(f"  emitters={data['emitter_count']}  flags={data['flags']}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_particles_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_particles_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: particles_tools.py selftest | decode <file.particles> | encode <file.json>")
