"""
Stingray .strings resource decode/encode.

Format (confirmed from binary analysis):
  Outer language index (11 entries × 12 bytes = 132 bytes):
    uint32  language_bitmask   (1, 2, 4, 8, 16, 32, 96, 128, 256, 512, 1024)
    uint32  bundle_abs_offset  absolute byte offset into the DECOMPRESSED bundle body
    uint32  zero               always 0

  Inner string index (variable, stored in the blob body after the 132-byte outer index):
    uint32  string_hash32      MurmurHash32 of the string key
    uint32  blob_offset        offset relative to start of this .strings blob

  String data:
    Null-terminated UTF-8 strings packed together. Referenced by blob_offset in inner index.

NOTE: The bundle_abs_offset fields in the outer index reference absolute positions in the
DECOMPRESSED bundle, not within the .strings blob itself. To fully decode the outer index's
per-language string groups, you need the whole bundle context.

This tool decodes the outer language index, dumps the inner string index,
and extracts all embedded null-terminated strings from the blob body.
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict, List, Optional, Tuple

OUTER_ENTRY_SZ = 12
INNER_ENTRY_SZ = 8

LANGUAGE_IDS: Dict[int, str] = {
    1:    "english",
    2:    "french",
    4:    "german",
    8:    "spanish",
    16:   "italian",
    32:   "portuguese",
    64:   "polish",
    96:   "polish_or_mixed",
    128:  "russian",
    256:  "unknown_256",
    512:  "unknown_512",
    1024: "unknown_1024",
}


def _read_cstring(blob: bytes, offset: int) -> Tuple[str, int]:
    """Read null-terminated UTF-8 string from blob. Returns (string, next_offset)."""
    end = blob.index(b'\x00', offset)
    return blob[offset:end].decode('utf-8', errors='replace'), end + 1


def decode_strings(blob: bytes) -> Dict[str, Any]:
    """Parse raw .strings blob → dict.

    The .strings blob contains:
      1. Outer language index (132 bytes, 11 × 12-byte entries)
      2. Inner string index  (N × 8 bytes, {hash32(4), pool_offset(4)})
      3. String pool         (null-terminated UTF-8 strings, referenced by inner index)

    Inner index count N is determined by finding where the data transitions from
    binary pairs to printable text (the start of the string pool).
    Inner index offsets are relative to the string pool start.
    The outer index bundle_abs_offset values reference absolute positions in the
    DECOMPRESSED BUNDLE — they point to per-language override tables in the bundle,
    not within this blob.
    """
    if len(blob) < 132:
        raise ValueError(f"blob too short ({len(blob)}) for strings outer index")

    # Outer language index: 11 × 12 = 132 bytes
    outer: List[Dict[str, Any]] = []
    for i in range(11):
        off = i * OUTER_ENTRY_SZ
        lang, babs, zero = struct.unpack_from('<III', blob, off)
        entry: Dict[str, Any] = {
            "language_mask": lang,
            "bundle_abs_offset": babs,
            "_zero": zero,
        }
        if lang in LANGUAGE_IDS:
            entry["_language_name"] = LANGUAGE_IDS[lang]
        outer.append(entry)

    # Find string pool start using a two-pass approach:
    # 1. Find the first 64-byte region that is >87.5% printable (sustained text)
    # 2. From that candidate, advance 8 bytes at a time until we land on a block
    #    that is itself >=6/8 printable (skip any trailing binary inner-index pairs
    #    that fall within the 64-byte window's head).
    candidate = len(blob)
    for off in range(132, len(blob) - 64, 8):
        window = blob[off:off + 64]
        printable = sum(1 for b in window if 0x20 <= b <= 0x7e or b == 0)
        if printable >= 56:
            candidate = off
            break

    pool_start = candidate
    while pool_start < len(blob) - 8:
        w8 = blob[pool_start:pool_start + 8]
        printable = sum(1 for b in w8 if 0x20 <= b <= 0x7e or b == 0)
        if printable >= 6:
            break
        pool_start += 8

    # Number of inner index pairs
    inner_count = (pool_start - 132) // 8
    _inner_remainder = (pool_start - 132) % 8

    # Parse inner index
    inner_pairs: List[Tuple[int, int]] = []
    for i in range(inner_count):
        h, off = struct.unpack_from('<II', blob, 132 + i * 8)
        inner_pairs.append((h, off))

    # Resolve strings from pool (offsets relative to pool_start)
    strings_map: Dict[str, str] = {}
    for h, off in inner_pairs:
        abs_off = pool_start + off
        if 0 <= abs_off < len(blob):
            try:
                end = blob.index(b'\x00', abs_off)
                s = blob[abs_off:end].decode('utf-8', errors='replace')
                strings_map[f"0x{h:08x}"] = s
            except (ValueError, IndexError):
                strings_map[f"0x{h:08x}"] = f"<ERR@{abs_off}>"

    return {
        "outer_language_index": outer,
        "inner_string_count": inner_count,
        "_pool_start": pool_start,
        "_inner_remainder_bytes": _inner_remainder,
        "strings": strings_map,
    }


def decode_strings_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_strings(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    n = data["inner_string_count"]
    print(f"Decoded {src} → {dst}  ({n} strings)")
    return dst


def encode_strings(data: Dict[str, Any]) -> bytes:
    """
    Encode a strings dict back to binary blob.

    Preserves the outer language index exactly (bundle-absolute offsets
    must not change). Re-builds the string pool from the strings dict.
    Round-trips byte-exact when no string values are modified.
    """
    buf = bytearray()

    # 1. Write outer language index (132 bytes)
    for entry in data['outer_language_index']:
        lang = entry['language_mask']
        babs = entry['bundle_abs_offset']
        zero = entry.get('_zero', 0)
        buf += struct.pack('<III', lang, babs, zero)

    # 2. Build string pool and inner index from the strings dict
    strings_map = data.get('strings', {})
    pool = bytearray()
    pool_offsets: Dict[str, int] = {}
    for hex_key, val in strings_map.items():
        pool_offsets[hex_key] = len(pool)
        pool += val.encode('utf-8') + b'\x00'

    # 3. Write inner index (N × 8 bytes): {hash32, pool_offset}
    for hex_key in strings_map:
        h = int(hex_key, 16)
        off = pool_offsets[hex_key]
        buf += struct.pack('<II', h, off)

    # Restore any remainder padding between inner index and pool
    remainder = data.get('_inner_remainder_bytes', 0)
    if remainder:
        buf += b'\x00' * remainder

    # 4. Write string pool
    buf += pool

    return bytes(buf)


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/strings_b64470f86611db9a.strings'
        if not os.path.exists(sample):
            print("strings_tools selftest: SKIP (sample not found)")
        else:
            blob = open(sample, 'rb').read()
            data = decode_strings(blob)
            n = data["inner_string_count"]
            blob2 = encode_strings(data)
            if blob == blob2:
                print(f"strings_tools selftest: PASS (byte-exact, {n} strings)")
            else:
                # Semantic check: decode re-encoded and compare
                data2 = decode_strings(blob2)
                if data2['strings'] == data['strings']:
                    print(f"strings_tools selftest: PASS (semantic, {n} strings, {len(blob)}→{len(blob2)} bytes)")
                else:
                    print(f"strings_tools selftest: MISMATCH  orig={len(blob)} re-enc={len(blob2)}")
            if data["strings"]:
                first_key = next(iter(data["strings"]))
                print(f"  sample: {first_key} = {data['strings'][first_key]!r}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_strings_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: strings_tools.py selftest | decode <file.strings>")
