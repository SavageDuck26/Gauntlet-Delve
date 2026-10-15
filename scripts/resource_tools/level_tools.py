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

  ENTITY RECORDS  (72 bytes each, at header[0].offset, count = header[0].count):
     Field layout (reverse-engineered; see FINDINGS 9H.2):

     offset  size  field
     ------  ----  -----
       0      4    rotation quaternion  z        (float32)
       4     12    scale                xyz      (float32[3])
      16      8    unused                         (raw; always 0 in the corpus)
      24      8    entity_id                      (uint64, per-instance)
      32      8    template_hash                  (uint64: unit/prefab name hash)
      40      8    material_override_hash         (uint64; 0 or a material variant)
      48     12    position             xyz       (float32[3])
      60      4    rotation quaternion  x        (float32)
      64      4    rotation quaternion  y        (float32)
      68      4    rotation quaternion  w        (float32)

     The full rotation quaternion is (x, y, z, w) = (f60, f64, f0, f68); the Z
     angle `2*atan2(z, w)` lands on 0/90/180/270 degrees for the authored grid
     rotations.  An earlier revision read this as an 80-byte record with the
     transform interpreted as 3 loose floats, which mis-parsed every real level
     (the sample it was derived from round-tripped byte-exactly only because the
     encoder re-packed whatever the decoder read).

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
ENTITY_RECORD_SIZE = 72


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


def _parse_entity(data: bytes) -> Dict[str, Any]:
    """Decode one 72-byte entity record (layout in FINDINGS 9H.2)."""
    entity_id,     = struct.unpack_from('<Q', data, 24)
    template_hash, = struct.unpack_from('<Q', data, 32)
    material_hash, = struct.unpack_from('<Q', data, 40)
    pos_x, pos_y, pos_z = struct.unpack_from('<fff', data, 48)
    scale_x, scale_y, scale_z = struct.unpack_from('<fff', data, 4)
    rot_z, = struct.unpack_from('<f', data, 0)
    rot_x, = struct.unpack_from('<f', data, 60)
    rot_y, = struct.unpack_from('<f', data, 64)
    rot_w, = struct.unpack_from('<f', data, 68)
    return {
        "entity_id":     f"0x{entity_id:016x}",
        "template_hash": f"0x{template_hash:016x}",
        "material_hash": f"0x{material_hash:016x}",
        "position":      [pos_x, pos_y, pos_z],
        "rotation":      [rot_x, rot_y, rot_z, rot_w],   # quaternion xyzw
        "scale":         [scale_x, scale_y, scale_z],
        # bytes 16..23 are unused/unwritten; preserved for a byte-exact re-encode
        "_unused":       data[16:24].hex(),
    }


def _encode_entity(e: Dict[str, Any]) -> bytes:
    entity_id     = int(e["entity_id"], 16)
    template_hash = int(e["template_hash"], 16)
    material_hash = int(e["material_hash"], 16)

    pos = e["position"]
    scale = e["scale"]
    rot_x, rot_y, rot_z, rot_w = e["rotation"]

    out = bytearray(ENTITY_RECORD_SIZE)
    struct.pack_into('<f', out, 0, rot_z)
    struct.pack_into('<fff', out, 4, *scale)
    out[16:24] = bytes.fromhex(e.get("_unused", "00" * 8))
    struct.pack_into('<Q', out, 24, entity_id)
    struct.pack_into('<Q', out, 32, template_hash)
    struct.pack_into('<Q', out, 40, material_hash)
    struct.pack_into('<fff', out, 48, *pos)
    struct.pack_into('<f', out, 60, rot_x)
    struct.pack_into('<f', out, 64, rot_y)
    struct.pack_into('<f', out, 68, rot_w)
    assert len(out) == ENTITY_RECORD_SIZE, f"entity size {len(out)} != {ENTITY_RECORD_SIZE}"
    return bytes(out)


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
    ent_end = ent_off + ent_count * ENTITY_RECORD_SIZE
    for idx, off in enumerate(section_offsets):
        next_off = section_offsets[idx + 1] if idx + 1 < len(section_offsets) else len(blob)
        if off == ent_off:
            # The entity table is rebuilt from the decoded records; preserve
            # whatever sits between it and the next section so re-encoding is
            # byte-exact.
            if ent_end < next_off:
                raw_sections[str(ent_end)] = blob[ent_end:next_off].hex()
            continue
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
            "Entity transform layout (72-byte records, FINDINGS 9H.2): "
            "position/rotation (quaternion xyzw)/scale are decoded and editable; "
            "the rotation is not pre-normalised. "
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
        import glob
        export = os.path.expanduser('~/Documents/Coding/Gauntlet-Export/named')
        samples = sorted(glob.glob(os.path.join(export, '**', '*.level'), recursive=True))
        if not samples:
            print("level_tools selftest: SKIP (no .level samples found)")
            sys.exit(0)
        ok = bad = 0
        for sample in samples:
            orig = open(sample, 'rb').read()
            data = decode_level(orig)
            re_enc = encode_level(data)
            if orig == re_enc:
                ok += 1
            else:
                bad += 1
                if bad == 1:
                    first = next(i for i in range(min(len(orig), len(re_enc)))
                                 if orig[i] != re_enc[i])
                    print(f"  MISMATCH {os.path.basename(sample)}: first diff @ {first}")
        data = decode_level(open(samples[0], 'rb').read())
        print(f"level_tools selftest: {'PASS' if bad == 0 else 'FAIL'} "
              f"(byte-exact {ok}/{len(samples)})")
        print(f"  {os.path.basename(samples[0])}: entities={data['entity_count']}  "
              f"strings={data['_resource_strings'][:3]}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_level_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_level_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: level_tools.py selftest | decode <file.level> | encode <file.json>")
