"""
Stingray .animation resource decode (partial).

Format (confirmed from binary analysis):
  Header (16 bytes):
    uint32  flags           = 0
    uint32  bone_count      (e.g. 26 — matches companion .bones file)
    float   duration        animation duration in seconds
    uint32  data_size       TOTAL blob size in bytes (= entire file including header)

  Keyframe data (data_size bytes):
    Compressed bone track data — Stingray's internal format.
    Likely uses per-bone compressed quaternion tracks (QTangent or similar).
    NOT standard BVH/FBX keyframe format.

  Re-encoding is not yet possible without reverse-engineering the compression
  scheme. Decode-only for now.

Round-trip status: decode-only. Encode preserves original compressed bytes unchanged.
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict

HEADER_SIZE = 16


def decode_animation(blob: bytes) -> Dict[str, Any]:
    """Parse .animation blob header; raw keyframe data exported as hex."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"blob too short ({len(blob)})")

    flags, bone_count, duration, data_size_raw = struct.unpack_from('<IIfI', blob, 0)

    keyframe_hex = blob[HEADER_SIZE:].hex()

    return {
        "flags": flags,
        "bone_count": bone_count,
        "duration_seconds": round(duration, 6),
        "_data_size_raw": data_size_raw,
        "_raw_keyframe_hex": keyframe_hex,
        "_note": (
            "Keyframe data is Stingray's internal compressed bone track format. "
            "Re-encoding is not yet supported. Edit flags/duration/bone_count only."
        ),
    }


def encode_animation(data: Dict[str, Any]) -> bytes:
    """Re-encode animation. Keyframe data is preserved from _raw_keyframe_hex."""
    keyframe_bytes = bytes.fromhex(data["_raw_keyframe_hex"])
    # Re-pack duration as 32-bit float, preserving original bit pattern if possible
    dur = data["duration_seconds"]
    dur_raw = struct.pack('<f', dur)
    data_size_raw = data.get("_data_size_raw", HEADER_SIZE + len(keyframe_bytes))
    hdr = struct.pack(
        '<II',
        data["flags"],
        data["bone_count"],
    ) + dur_raw + struct.pack('<I', data_size_raw)
    return hdr + keyframe_bytes


def decode_animation_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_animation(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Decoded {src} → {dst}  ({data['bone_count']} bones, {data['duration_seconds']:.3f}s)")
    return dst


def encode_animation_file(src: str, dst: str | None = None) -> str:
    with open(src) as f:
        data = json.load(f)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.animation'
    open(dst, 'wb').write(encode_animation(data))
    print(f"Encoded {src} → {dst}")
    return dst


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/animation_050aae281116ecb3.animation'
        orig = open(sample, 'rb').read()
        data = decode_animation(orig)
        re_enc = encode_animation(data)
        if orig == re_enc:
            print("animation_tools selftest: PASS (byte-exact)")
        else:
            print(f"animation_tools selftest: MISMATCH  orig={len(orig)} re-enc={len(re_enc)}")
            first = next(i for i in range(min(len(orig), len(re_enc))) if orig[i] != re_enc[i])
            print(f"  first diff @ byte {first}: orig=0x{orig[first]:02x} re=0x{re_enc[first]:02x}")
        print(f"  duration={data['duration_seconds']}s  bones={data['bone_count']}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_animation_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_animation_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: animation_tools.py selftest | decode <file.animation> | encode <file.json>")
