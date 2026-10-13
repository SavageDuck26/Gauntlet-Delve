"""
Stingray .level resource decode/encode.

Format (reverse-engineered from binary analysis, Gauntlet Slayer Edition):

  HEADER (128 bytes):
    16 x { uint32 field_a, uint32 field_b }
    - Entry [0]: { entities_offset, entity_count }  - entity transform records
    - Entry [1]: { version=1, unknown_size }
    - Entry [2], [7], [8..10]: section offset references
    - Entries where field_a == field_b: sentinel/size markers (e.g., file_size)
    - Known offsets:
        @128: entity records  (count x 80 bytes each)
        @608: resource/layer config section
        @720: sub-section header (small lookup table)
        @824: lighting / render environment matrices

  ENTITY RECORDS  (80 bytes each, at header[0].offset, count = header[0].count):
    uint64  entity_id       - unique instance hash (0 = anonymous)
    uint64  template_hash   - name hash of the unit/prefab template (0 = no template)
    uint64  flags           - unknown; usually 0
    float   position_x
    float   position_y
    float   position_z
    float[2]  unknown_0     - extra floats, likely part of rotation/scale encoding
    float   rot_a           - rotation / basis vector component
    float   rot_b
    float   rot_c           - often 1.0 (scale/w component)
    float   scale           - uniform scale (8.0, 1.0, 64.0 observed)
    float   scale_w
    float[2]  unknown_1
    uint64  tail_hash       - extra hash slot (type unknown; may be component ref)

  CONFIG/RESOURCE SECTION  (at @608 in sample, variable length):
    Contains resource path references and layer names stored as:
      uint32  descriptor values (counts, version flags, hashes)
      { uint32 str_len_incl_null, char[str_len_incl_null] null_term_string }
      (strings padded to 4-byte alignment)
    Observed:  'core/rendering/default_outdoor'  (sky/environment preset)
               'default'                         (default layer name)

  REMAINING SECTIONS:
    The sections at @720 (64 bytes) and @824 (256 bytes) contain
    4x4 identity matrices and render/lighting environment data.
    Fully stored as raw hex for now (format not fully decoded).

Round-trip status: BYTE-EXACT - all unknown sections preserved as raw_hex.
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict, List, Tuple

HEADER_ENTRY_COUNT = 16
HEADER_SIZE = HEADER_ENTRY_COUNT * 8  # 128 bytes
ENTITY_RECORD_SIZE = 80


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _parse_header(blob: bytes) -> List[Tuple[int, int]]:
    """Return 16 (field_a, field_b) uint32 pairs from the 128-byte header."""
    return [struct.unpack_from('<II', blob, i * 8) for i in range(HEADER_ENTRY_COUNT)]


def _encode_header(pairs: List[List[int]]) -> bytes:
    out = b''
    for a, b in pairs:
        out += struct.pack('<II', a, b)
    return out


def _f32_hex(b: bytes, offset: int) -> str:
    """Return a float32 from bytes as a compact hex string for lossless storage."""
    return f"0x{struct.unpack_from('<I', b, offset)[0]:08x}"


def _parse_entity(data: bytes) -> Dict[str, Any]:
    """Decode one 80-byte entity record.

    Entities with template_hash == 0 appear to use the transform region (@24..79)
    for hash/reference data rather than float transforms.  Those bytes are stored
    as raw hex to avoid precision loss.  Entities with template_hash != 0 store
    actual position/rotation/scale floats in that region.
    """
    entity_id, template_hash, flags = struct.unpack_from('<QQQ', data, 0)
    tail_hash = struct.unpack_from('<Q', data, 72)[0]
    base = {
        "entity_id":     f"0x{entity_id:016x}",
        "template_hash": f"0x{template_hash:016x}",
        "flags":         f"0x{flags:016x}",
        "_tail_hash":    f"0x{tail_hash:016x}",
    }
    if template_hash != 0:
        # Transform layout: pos(xyz), pad(2f), rot(3f), scale(2f), unk(2f)
        pos_x, pos_y, pos_z = struct.unpack_from('<fff', data, 24)
        unk0_a, unk0_b      = struct.unpack_from('<ff',  data, 36)
        rot_a, rot_b, rot_c = struct.unpack_from('<fff', data, 44)
        scale, scale_w      = struct.unpack_from('<ff',  data, 56)
        unk1_a, unk1_b      = struct.unpack_from('<ff',  data, 64)
        base.update({
            "position":   [pos_x, pos_y, pos_z],
            "_pad_0":     [_f32_hex(data, 36), _f32_hex(data, 40)],
            "rotation_abc": [rot_a, rot_b, rot_c],
            "scale":      scale,
            "scale_w":    scale_w,
            "_pad_1":     [_f32_hex(data, 64), _f32_hex(data, 68)],
        })
    else:
        # Not a placed unit - store transform region as raw hex
        base["_transform_raw"] = data[24:72].hex()
    return base


def _encode_entity(e: Dict[str, Any]) -> bytes:
    entity_id     = int(e["entity_id"], 16)
    template_hash = int(e["template_hash"], 16)
    flags         = int(e["flags"], 16)
    tail_hash     = int(e["_tail_hash"], 16)

    header = struct.pack('<QQQ', entity_id, template_hash, flags)

    if template_hash != 0:
        pos    = e["position"]
        pad0   = [int(v, 16) for v in e["_pad_0"]]
        rot    = e["rotation_abc"]
        scale  = e["scale"]
        scale_w = e["scale_w"]
        pad1   = [int(v, 16) for v in e["_pad_1"]]
        transform = (
            struct.pack('<fff', *pos)
            + struct.pack('<II', *pad0)
            + struct.pack('<fff', *rot)
            + struct.pack('<ff', scale, scale_w)
            + struct.pack('<II', *pad1)
        )
    else:
        transform = bytes.fromhex(e["_transform_raw"])

    tail = struct.pack('<Q', tail_hash)
    out = header + transform + tail
    assert len(out) == ENTITY_RECORD_SIZE, f"entity size {len(out)} != {ENTITY_RECORD_SIZE}"
    return out


def _extract_strings_from_section(blob: bytes) -> List[str]:
    """Best-effort extraction of Pascal-style strings from config section blob."""
    strings = []
    i = 0
    while i + 4 <= len(blob):
        length = struct.unpack_from('<I', blob, i)[0]
        if 1 <= length <= 256 and i + 4 + length <= len(blob):
            raw = blob[i + 4:i + 4 + length]
            if all(0x20 <= b < 0x7f or b == 0x00 for b in raw):
                s = raw.rstrip(b'\x00').decode('ascii', errors='replace')
                if len(s) >= 3 and s.isprintable():
                    strings.append(s)
        i += 4
    return strings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decode_level(blob: bytes) -> Dict[str, Any]:
    """Parse .level blob into a JSON-serialisable dict."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"blob too short ({len(blob)} bytes)")

    header_pairs = _parse_header(blob)

    # Entity section - entry [0]: (offset, count)
    ent_off, ent_count = header_pairs[0]
    entities = []
    if ent_off >= HEADER_SIZE and ent_count > 0:
        for i in range(ent_count):
            start = ent_off + i * ENTITY_RECORD_SIZE
            end = start + ENTITY_RECORD_SIZE
            if end <= len(blob):
                entities.append(_parse_entity(blob[start:end]))

    # Identify section boundaries from known header entries
    # Collect all distinct non-zero offsets >= HEADER_SIZE, sorted
    section_offsets = sorted(set(
        a for (a, b) in header_pairs
        if a >= HEADER_SIZE and a < len(blob)
    ))

    # Build raw sections dict (key = offset, value = hex)
    raw_sections: Dict[str, str] = {}
    for idx, off in enumerate(section_offsets):
        if off == ent_off:
            continue  # entities section handled above
        next_off = section_offsets[idx + 1] if idx + 1 < len(section_offsets) else len(blob)
        chunk = blob[off:next_off]
        raw_sections[str(off)] = chunk.hex()

    # Extract strings from all raw sections for display
    all_strings: List[str] = []
    for off_str, hex_data in raw_sections.items():
        chunk = bytes.fromhex(hex_data)
        found = _extract_strings_from_section(chunk)
        all_strings.extend(found)

    return {
        "_format": "stingray_level_v1",
        "_file_size": len(blob),
        "header": [[a, b] for (a, b) in header_pairs],
        "entity_count": ent_count,
        "entities": entities,
        "_resource_strings": list(dict.fromkeys(all_strings)),  # unique, ordered
        "_raw_sections": raw_sections,
        "_note": (
            "Entity transform layout is partially reverse-engineered. "
            "position/rotation_abc/scale are editable. "
            "_raw_sections preserve all other level data byte-exactly."
        ),
    }


def encode_level(data: Dict[str, Any]) -> bytes:
    """Re-encode level. All raw sections are preserved unchanged."""
    file_size = data["_file_size"]
    header_pairs = [tuple(p) for p in data["header"]]
    ent_off, ent_count = header_pairs[0]

    # Rebuild full buffer from file_size
    buf = bytearray(file_size)

    # Write header
    buf[0:HEADER_SIZE] = _encode_header(header_pairs)

    # Write entities
    entities = data.get("entities", [])
    for i, e in enumerate(entities):
        start = ent_off + i * ENTITY_RECORD_SIZE
        buf[start:start + ENTITY_RECORD_SIZE] = _encode_entity(e)

    # Write all raw sections back
    for off_str, hex_data in data.get("_raw_sections", {}).items():
        off = int(off_str)
        raw = bytes.fromhex(hex_data)
        buf[off:off + len(raw)] = raw

    return bytes(buf)


# ---------------------------------------------------------------------------
# File-level helpers
# ---------------------------------------------------------------------------

def decode_level_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_level(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w') as f:
        json.dump(data, f, indent=2)
    strings_preview = ', '.join(f"'{s}'" for s in data['_resource_strings'][:4])
    print(f"Decoded {src} -> {dst}  "
          f"({data['entity_count']} entities, strings: [{strings_preview}])")
    return dst


def encode_level_file(src: str, dst: str | None = None) -> str:
    with open(src) as f:
        data = json.load(f)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.level'
    open(dst, 'wb').write(encode_level(data))
    print(f"Encoded {src} -> {dst}")
    return dst


# ---------------------------------------------------------------------------
# CLI / selftest
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/level_24abcdf4b1fb4d4a.level'
        orig = open(sample, 'rb').read()
        data = decode_level(orig)
        re_enc = encode_level(data)
        if orig == re_enc:
            print("level_tools selftest: PASS (byte-exact)")
        else:
            n_diff = sum(1 for a, b in zip(orig, re_enc) if a != b)
            first = next(i for i in range(min(len(orig), len(re_enc))) if orig[i] != re_enc[i])
            print(f"level_tools selftest: MISMATCH  "
                  f"orig={len(orig)} re-enc={len(re_enc)} diff_bytes={n_diff}")
            print(f"  first diff @ byte {first}: orig=0x{orig[first]:02x} re=0x{re_enc[first]:02x}")
        print(f"  entities={data['entity_count']}  "
              f"strings={data['_resource_strings']}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_level_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_level_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: level_tools.py selftest | decode <file.level> | encode <file.json>")
