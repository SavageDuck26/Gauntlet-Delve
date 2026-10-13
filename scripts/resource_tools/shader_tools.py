"""
Stingray .shader resource decode (read-only).

Format (from binary analysis):
  Header (~48 bytes):
    uint32  version       = 8
    uint32  hash          content hash
    uint32  table_offset  = 0x30 (48) — offset to program table
    uint32  prog_count    number of compiled shader programs

  Program table (at table_offset):
    prog_count × {uint32 offset, uint32 size, ...}  (entry size TBD)

  Shader program blobs (HLSL/GLSL compiled bytecode):
    Raw compiled shader data. Cannot be recompiled to HLSL source.

Round-trip status: decode-only. The compiled shader blobs are preserved as hex.
Editing shader source requires an HLSL compiler and re-linking.
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict, List

HEADER_SIZE = 48


def decode_shader(blob: bytes) -> Dict[str, Any]:
    """Parse .shader blob → dict with header info + program list."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"blob too short ({len(blob)})")

    version, hash_val, table_off, prog_count = struct.unpack_from('<IIII', blob, 0)

    # Read the full header region as hex for reference
    header_hex = blob[:HEADER_SIZE].hex()

    # Parse program table entries
    programs: List[Dict[str, Any]] = []
    pos = table_off
    for i in range(prog_count):
        if pos + 8 > len(blob):
            break
        off, sz = struct.unpack_from('<II', blob, pos)
        prog_data = blob[off:off + sz] if off + sz <= len(blob) else b''
        programs.append({
            "index": i,
            "offset": off,
            "size": sz,
            "_hex": prog_data.hex(),
        })
        pos += 8

    return {
        "version": version,
        "hash": f"0x{hash_val:08x}",
        "table_offset": table_off,
        "program_count": prog_count,
        "_header_hex": header_hex,
        "programs": programs,
        "_raw_hex": blob.hex(),
        "_note": (
            "Shader programs are compiled HLSL/GLSL bytecode. "
            "Cannot reconstruct source. Use _raw_hex for byte-exact round-trip."
        ),
    }


def encode_shader(data: Dict[str, Any]) -> bytes:
    """Re-encode shader — returns original bytes from _raw_hex."""
    if "_raw_hex" in data:
        return bytes.fromhex(data["_raw_hex"])
    raise ValueError("Cannot encode shader without _raw_hex (compiled bytecode)")


def decode_shader_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_shader(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Decoded {src} → {dst}  (v{data['version']}, {data['program_count']} programs)")
    return dst


def encode_shader_file(src: str, dst: str | None = None) -> str:
    with open(src) as f:
        data = json.load(f)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.shader'
    open(dst, 'wb').write(encode_shader(data))
    print(f"Encoded {src} → {dst}")
    return dst


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/shader_742180a78ec737ad.shader'
        orig = open(sample, 'rb').read()
        data = decode_shader(orig)
        re_enc = encode_shader(data)
        if orig == re_enc:
            print("shader_tools selftest: PASS (byte-exact via raw_hex)")
        else:
            print(f"shader_tools selftest: MISMATCH  orig={len(orig)} re-enc={len(re_enc)}")
        print(f"  version={data['version']}  programs={data['program_count']}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_shader_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_shader_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: shader_tools.py selftest | decode <file.shader> | encode <file.json>")
