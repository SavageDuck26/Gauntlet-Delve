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
import json, math, os, struct, sys
from typing import Any, Dict, List, Tuple

HEADER_ENTRY_COUNT = 16
HEADER_SIZE = HEADER_ENTRY_COUNT * 8  # 128 bytes
ENTITY_RECORD_SIZE = 72

# ---------------------------------------------------------------------------
# WHERE A UNIT'S TRANSFORM ACTUALLY LIVES  (FINDINGS 9H.36 - READ FROM THE CODE)
# ---------------------------------------------------------------------------
# The 72-byte stride is real, but a unit's transform is 48 bytes and does not
# start at its record's start: it starts at record+0x30 (48), so its LAST 24
# bytes fall into the NEXT record's first 24.  The engine proves it -
# FUN_00430440 walks the array at `data + 0xb0 + i*0x48` (data+0x80 is the unit
# table, so its entry i is record i + 48) and builds every placement with
#
#     FUN_0042db10(out, entry + 0xc, entry + 0, entry + 0x1c)
#       -> FUN_0042d7f0(out, quaternion, position, scale)
#
# and FUN_0042d7f0 reads FOUR consecutive floats from the quaternion pointer and
# normalises them into a rotation matrix.  So, per unit:
#
#     position   entry + 0x00  = record + 0x30 (3 floats)
#     rotation   entry + 0x0c  = record + 0x3c (4 floats: x,y,z and w at +0x48)
#     scale      entry + 0x1c  = record + 0x4c (3 floats)
#
# The quaternion's w is therefore at record+0x48, which for a 72-byte stride is
# the NEXT record's offset-0 float, and the scale is the next record's offset-4
# fields.  The last unit's overflow sits in the 24 bytes reserved after the
# table (u32[3] = table_end + 24, which every shipped level has, holding
# {w, scale(3), 8 padding} = 1.0,1.0,1.0,1.0,0,0,0,0 when the last unit is
# unrotated with unit scale).
#
# WHAT THE TOOLKIT USED TO DO: treat record i's own offsets 0 and 4 as that
# unit's w and scale.  Its id/template/material/position/rotation-xyz offsets
# were all right - which is why every round trip was byte-exact and every id,
# name and position check passed - but the w and scale it read and wrote
# belonged to the PREVIOUS unit.  Nothing showed on identity placements (xyz is
# zero, so any w is the same rotation) or on unit scales, and it is exactly the
# off-by-one that shipped rotations built from the wrong w.
TRANSFORM_LEAD_SIZE = 24    # rot.w (1 float), scale (3 floats), 8 padding bytes


def unit_transform_lead(blob: bytes, ent_off: int, count: int, index: int) -> bytes:
    """Unit `index`'s 24-byte transform lead: its rotation w, its scale, 8 padding.

    It sits at the NEXT record's start (and, for the last unit, in the block
    reserved after the table).
    """
    off = ent_off + (index + 1) * ENTITY_RECORD_SIZE
    return bytes(blob[off:off + TRANSFORM_LEAD_SIZE])


def table_prologue(blob: bytes, ent_off: int) -> bytes:
    """The 24 bytes in front of unit 0's block - the unit table's own header.

    Its first u32 is the byte COUNT the loader allocates (0 in all 255 shipped
    levels; a float there is a crash - FINDINGS 9H.23.3), the rest is padding.
    """
    return bytes(blob[ent_off:ent_off + TRANSFORM_LEAD_SIZE])


def set_record_rotation(entity: Dict[str, Any], quat: List[float]) -> None:
    """Set a decoded record's rotation, in a record dict, without leaving a stale cache behind.

    `_parse_entity` keeps the record's original three floats as `rotation_vector` so an untouched
    round trip stays byte-exact, and `_encode_entity` prefers that key over `rotation`.  So any
    code that CHANGES an entity's rotation must drop it - otherwise the encoder quietly writes the
    rotation the record already had (the donor path's placements did exactly that) - and dropping
    `flag` lets the encoder derive the w for the new rotation instead of reusing the old one.
    """
    entity['rotation'] = [float(v) for v in quat]
    entity.pop('rotation_vector', None)
    entity.pop('flag', None)


def shift_leads_forward(blob: bytearray, ent_off: int, count: int,
                        prologue: bytes = None) -> None:
    """Move every unit's transform lead one record later - where the engine reads it.

    The encoder writes each record with its OWN lead in its own first 24 bytes
    (that is the record dict's `flag`/`scale`/`_unused`); the file the engine
    wants has each lead 72 bytes further on.  `prologue` restores the unit
    table's header (default: zeros, i.e. a zero count - never unit 0's data,
    which would be read as a byte count and crash the load).
    """
    if count <= 0:
        return
    lead = TRANSFORM_LEAD_SIZE
    leads = [bytes(blob[ent_off + i * ENTITY_RECORD_SIZE:
                        ent_off + i * ENTITY_RECORD_SIZE + lead]) for i in range(count)]
    for i in range(count - 1, 0, -1):
        dst = ent_off + i * ENTITY_RECORD_SIZE
        blob[dst:dst + lead] = leads[i - 1]
    dst = ent_off + count * ENTITY_RECORD_SIZE
    blob[dst:dst + lead] = leads[count - 1]
    blob[ent_off:ent_off + lead] = prologue if prologue is not None else b'\x00' * lead



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


def record_rotation_vector(quat: List[float]) -> List[float]:
    """The three floats a record holds for a rotation: the quaternion's VECTOR part (x, y, z).

    FROM THE CODE (FINDINGS 9H.34, layout corrected in 9H.36).  The per-unit pass builds every
    placement with

        FUN_0042db10(out, entry + 0xc, entry + 0, entry + 0x1c)
          -> FUN_0042d7f0(out, quat, position, scale)

    where `entry` is the unit's transform block, and FUN_0042d7f0 reads FOUR CONSECUTIVE floats
    from the quaternion pointer and normalises them:

        k = 2.0 / (x*x + y*y + z*z + w*w)
        m00 = 1 - k(y*y + z*z)   m01 = k(x*y + w*z)   m02 = k(x*z - w*y)
        m10 = k(x*y - w*z)       m11 = 1 - k(x*x + z*z)   m12 = k(y*z + w*x)
        m20 = k(x*z + w*y)       m21 = k(y*z - w*x)   m22 = 1 - k(x*x + y*y)

    i.e. a NORMALISED unit quaternion, in the ordinary (x, y, z, w) order.  The vector part goes
    in a record's offsets 60/64/68; the w is the fourth consecutive float, at 72 - the next
    record's first float, NOT this record's offset 0 (9H.36).

    So this function is deliberately the identity on the vector part.
    """
    x, y, z, w = (float(v) for v in quat)
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n > 0.0:
        x, y, z, w = x / n, y / n, z / n, w / n
    return [x, y, z]


def quat_from_record_vector(vec: List[float], w: float = None) -> List[float]:
    """The rotation the engine builds for a record: normalize((x, y, z, w)).

    `w` is the FOURTH consecutive float after the vector, i.e. the record's offset-0 float of the
    NEXT record (9H.36) - pass `unit_transform_lead()`'s first float.  When it is not given it is
    reconstructed, which is only right for an identity placement (the vector is then all zeros and
    the angle is 0 whatever the w is).
    """
    x, y, z = (float(v) for v in vec)
    if w is None:
        w = -math.sqrt(max(0.0, 1.0 - x * x - y * y - z * z))
    n = math.sqrt(x * x + y * y + z * z + float(w) * float(w))
    if n == 0.0:
        return [0.0, 0.0, 0.0, 1.0]
    return [x / n, y / n, z / n, float(w) / n]


def _parse_entity(data: bytes, lead: bytes = None) -> Dict[str, Any]:
    """Decode one 72-byte entity record (layout in FINDINGS 9H.2, transform in 9H.36).

    THE ROTATION.  The vector part is three floats at 60/64/68 and the engine reads FOUR
    consecutive floats - so the w is at 72, the next record's offset 0 - and normalises them into
    a rotation matrix (FUN_0042d7f0).  `lead` is that 24-byte block (`unit_transform_lead`): its
    first float is the w, its next three are the unit's scale, its last eight are padding.  The
    record's OWN offsets 0 and 4 belong to the PREVIOUS unit, so reading them as this unit's w
    and scale (what this module did before 9H.36) rotates every placement by its successor's w.

    `lead=None` falls back to the record's own leading float for the w, which is only meaningful
    for an identity placement - pass the real lead whenever it is available.
    """
    entity_id,     = struct.unpack_from('<Q', data, 24)
    template_hash, = struct.unpack_from('<Q', data, 32)
    material_hash, = struct.unpack_from('<Q', data, 40)
    pos_x, pos_y, pos_z = struct.unpack_from('<fff', data, 48)
    if lead is not None:
        flag, = struct.unpack_from('<f', lead, 0)
        scale_x, scale_y, scale_z = struct.unpack_from('<fff', lead, 4)
        unused = bytes(lead[16:24]).hex()
    else:
        flag, = struct.unpack_from('<f', data, 0)
        scale_x, scale_y, scale_z = struct.unpack_from('<fff', data, 4)
        unused = data[16:24].hex()
    vec = [struct.unpack_from('<f', data, 60)[0],
           struct.unpack_from('<f', data, 64)[0],
           struct.unpack_from('<f', data, 68)[0]]
    return {
        "entity_id":     f"0x{entity_id:016x}",
        "template_hash": f"0x{template_hash:016x}",
        "material_hash": f"0x{material_hash:016x}",
        "position":      [pos_x, pos_y, pos_z],
        # the rotation the engine will build: normalize((x, y, z, w)), w = the lead's first float
        "rotation":      quat_from_record_vector(vec, flag),
        "rotation_vector": vec,
        "scale":         [scale_x, scale_y, scale_z],
        "flag":          flag,
        # the unit's own 8 padding bytes; preserved for a byte-exact re-encode
        "_unused":       unused,
    }


def _encode_entity(e: Dict[str, Any]) -> bytes:
    entity_id     = int(e["entity_id"], 16)
    template_hash = int(e["template_hash"], 16)
    material_hash = int(e["material_hash"], 16)

    pos = e["position"]
    scale = e["scale"]
    rot_x, rot_y, rot_z, rot_w = e["rotation"]

    # THE ROTATION THE RECORD HOLDS is the rotation vector, axis * tan(theta/2), NOT the
    # quaternion's vector part: the engine builds q = normalize(vector, 1.0) (FINDINGS 9H.33).
    # A record decoded by this module carries its original three floats as `rotation_vector`, so
    # a round trip is byte-exact; anything authored upstream goes through the division.
    vec = e.get("rotation_vector")
    if vec is None:
        vec = record_rotation_vector([rot_x, rot_y, rot_z, rot_w])

    # THE RECORD'S OWN LEAD IS WRITTEN HERE AND MOVED LATER.  This encoder puts the unit's
    # rotation w, its scale and its 8 padding bytes in the record's own first 24 bytes; the
    # engine reads them 72 bytes further on (9H.36), so `encode_level` runs
    # `shift_leads_forward` over the finished buffer.  Writing them here keeps the round trip
    # readable: one record dict in, the same record dict out.
    if "flag" in e:
        flag = float(e["flag"])
    else:
        flag = -math.sqrt(max(0.0, 1.0 - rot_x * rot_x - rot_y * rot_y - rot_z * rot_z))

    out = bytearray(ENTITY_RECORD_SIZE)
    struct.pack_into('<f', out, 0, flag)
    struct.pack_into('<fff', out, 4, *scale)
    out[16:24] = bytes.fromhex(e.get("_unused", "00" * 8))
    struct.pack_into('<Q', out, 24, entity_id)
    struct.pack_into('<Q', out, 32, template_hash)
    struct.pack_into('<Q', out, 40, material_hash)
    struct.pack_into('<fff', out, 48, *pos)
    struct.pack_into('<fff', out, 60, *vec)
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
                # A unit's rotation w and scale live one record further on (9H.36); the last
                # unit's are in the 24 bytes reserved after the table.
                lead = unit_transform_lead(blob, ent_off, ent_count, i)
                entities.append(_parse_entity(blob[start:end], lead if len(lead) ==
                                              TRANSFORM_LEAD_SIZE else None))

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
        # the unit table's own 24-byte header (its first u32 is the load's byte COUNT); unit 0's
        # transform does NOT live here - it lives one record on, like every other unit's (9H.36)
        "_lead_prologue": table_prologue(blob, ent_off).hex() if ent_count else "",
        "_resource_strings": list(dict.fromkeys(all_strings)),  # unique, ordered
        "_raw_sections": raw_sections,
        "_note": (
            "Entity transform layout (72-byte records, FINDINGS 9H.2/9H.36): "
            "position at 48, the rotation quaternion's x/y/z at 60/64/68 and its w one record "
            "later (with the unit's scale at that record's offset 4); "
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

    # THE LAST STEP: PUT EVERY UNIT'S TRANSFORM LEAD WHERE THE ENGINE READS IT (9H.36).
    # `_encode_entity` writes each unit's rotation w / scale / padding into its own record's
    # first 24 bytes; the engine reads them at record+0x48 and record+0x4c - one record later -
    # so the whole set has to move, with the last unit's landing in the 24 bytes reserved after
    # the table.  This runs after the raw sections so it wins over the copy of the old epilogue.
    if ent_count > 0 and ent_off >= HEADER_SIZE:
        prologue = data.get("_lead_prologue")
        prologue = bytes.fromhex(prologue) if prologue and len(prologue) == 2 * TRANSFORM_LEAD_SIZE \
            else None
        shift_leads_forward(buf, ent_off, ent_count, prologue)

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
