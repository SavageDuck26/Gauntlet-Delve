"""
Stingray .font resource decode/encode.

Format (confirmed from binary analysis):
  Header (68 bytes):
    uint32  unknown_0       = 5 (variant/type flag)
    float   line_height     = 96.0
    float   ascent          = 96.0
    float   cap_height      = 75.0
    float   tex_scale_x     = 1/texture_width  (e.g. 1/1024)
    float   tex_scale_y     = 1/texture_height (e.g. 1/640)
    uint32  glyph_count     = 256
    uint32  pad0            = 0
    float   bounds_max_x    = 990.0
    float   bounds_min_y    = 0.0
    float   unknown_f2      = 29.0
    float   unknown_f3      = 60.0
    float   unknown_f4      = 10.0
    float   unknown_f5      = 17.0
    float   default_advance = 45.0
    uint32  glyph_count2    = 256
    uint32  pad1            = 0

  Glyph records (32 bytes each, glyph_count records):
    float   x           atlas x position (pixels)
    float   y           atlas y position (pixels)
    float   w           glyph width in atlas (pixels)
    float   h           glyph height in atlas (pixels)
    float   x_offset    bearing x
    float   y_offset    bearing y
    float   x_advance   horizontal advance
    uint32  char_code   unicode codepoint
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict, List

HEADER_SIZE  = 68
GLYPH_SIZE   = 32
HEADER_FMT   = '<I5fII7fII'   # 17 fields (68 bytes)
GLYPH_FMT    = '<7fI'             # 8 fields (32 bytes)


def decode_font(blob: bytes) -> Dict[str, Any]:
    """Parse a raw .font blob → dict with header + glyph list."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"blob too short ({len(blob)}) for font header")

    fields = struct.unpack_from(HEADER_FMT, blob, 0)
    (unknown_0, line_height, ascent, cap_height, tex_scale_x, tex_scale_y,
     glyph_count, pad0,
     bounds_max_x, bounds_min_y, unknown_f2, unknown_f3, unknown_f4, unknown_f5,
     default_advance, glyph_count2, pad1) = fields

    expected = HEADER_SIZE + glyph_count * GLYPH_SIZE
    if len(blob) != expected:
        raise ValueError(f"size mismatch: expected {expected}, got {len(blob)}")

    glyphs: List[Dict[str, Any]] = []
    for i in range(glyph_count):
        off = HEADER_SIZE + i * GLYPH_SIZE
        x, y, w, h, xoff, yoff, xadv, char = struct.unpack_from(GLYPH_FMT, blob, off)
        try:
            char_repr = chr(char)
        except (ValueError, OverflowError):
            char_repr = None
        glyphs.append({
            "char_code": char,
            "char": char_repr,
            "x": x, "y": y, "w": w, "h": h,
            "x_offset": xoff, "y_offset": yoff,
            "x_advance": xadv,
        })

    return {
        "unknown_0": unknown_0,
        "line_height": line_height,
        "ascent": ascent,
        "cap_height": cap_height,
        "tex_scale_x": tex_scale_x,
        "tex_scale_y": tex_scale_y,
        "glyph_count": glyph_count,
        "_pad0": pad0,
        "_bounds_max_x": bounds_max_x,
        "_bounds_min_y": bounds_min_y,
        "_unknown_f2": unknown_f2,
        "_unknown_f3": unknown_f3,
        "_unknown_f4": unknown_f4,
        "_unknown_f5": unknown_f5,
        "_default_advance": default_advance,
        "_glyph_count2": glyph_count2,
        "_pad1": pad1,
        "glyphs": glyphs,
    }


def encode_font(data: Dict[str, Any]) -> bytes:
    """Encode a decoded font dict back to binary blob."""
    glyphs = data["glyphs"]
    n = len(glyphs)

    hdr = struct.pack(
        HEADER_FMT,
        data["unknown_0"],
        data["line_height"], data["ascent"], data["cap_height"],
        data["tex_scale_x"], data["tex_scale_y"],
        n, data.get("_pad0", 0),
        data.get("_bounds_max_x", 0.0), data.get("_bounds_min_y", 0.0),
        data.get("_unknown_f2", 0.0), data.get("_unknown_f3", 0.0),
        data.get("_unknown_f4", 0.0), data.get("_unknown_f5", 0.0),
        data.get("_default_advance", 0.0),
        n, data.get("_pad1", 0),
    )

    glyph_bytes = bytearray()
    for g in glyphs:
        glyph_bytes += struct.pack(
            GLYPH_FMT,
            g["x"], g["y"], g["w"], g["h"],
            g["x_offset"], g["y_offset"], g["x_advance"],
            g["char_code"],
        )
    return hdr + bytes(glyph_bytes)


def decode_font_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_font(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Decoded {src} → {dst}  ({data['glyph_count']} glyphs)")
    return dst


def encode_font_file(src: str, dst: str | None = None) -> str:
    with open(src) as f:
        data = json.load(f)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.font'
    open(dst, 'wb').write(encode_font(data))
    print(f"Encoded {src} → {dst}")
    return dst


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/font_0a77e190efb641c3.font'
        orig = open(sample, 'rb').read()
        data = decode_font(orig)
        re_enc = encode_font(data)
        if orig == re_enc:
            print("font_tools selftest: PASS (byte-exact)")
        else:
            print(f"font_tools selftest: MISMATCH  orig={len(orig)} re-enc={len(re_enc)}")
            first = next(i for i in range(min(len(orig), len(re_enc))) if orig[i] != re_enc[i])
            print(f"  first diff @ byte {first}: orig=0x{orig[first]:02x} re=0x{re_enc[first]:02x}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_font_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_font_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: font_tools.py selftest | decode <file.font> | encode <file.json>")
