"""
Stingray/Bitsquid render_config binary blob encoder/decoder.

The render_config resource stores a compiled binary object tree (COBJ format).
This module can round-trip all 3 known Gauntlet render_config blobs byte-perfectly.

CONFIRMED SCHEMA (from reverse-engineering 3 game blobs):
=========================================================

Top-level keys:
  resource_generators  (object)
      <generator_name>  (object)
          modifiers  (array of objects)
              Each modifier:
                  type         (string) - see modifier types below
                  target       (string) - texture slot name  [generate_mips only]
                  input        (string) - input texture slot [fullscreen_pass]
                  output       (string) - output texture slot [fullscreen_pass]
                  shader       (string) - shader name[:DEFINE[:DEFINE...]]
                  draw_as_quad (uint32) - 1 = draw as quad mesh, 0 = fullscreen triangle

  brush_resource_generator_mapping  (optional object)
      <brush_name> (string) -> <generator_name> (string)

MODIFIER TYPES:
  generate_mips     - Auto-generates mipmap chain for a texture slot
                      Required field: target (texture slot to generate mips for)

  fullscreen_pass   - Runs a fullscreen GPU shader pass
                      Required field: output (texture to write to)
                      Optional:      input (source texture), shader, draw_as_quad

BINARY FORMAT (COBJ - Stingray Compiled Binary Object):
=======================================================
  Header:        {root_type=6(4), root_offset(4)}
  Object node:   {count(4), {key_ptr(4), vtype(4), vdata(4)} x count}
  Array  node:   {elem_type(4), count(4), {elem_ptr(4)} x count}
  Strings:       null-terminated, 4-byte aligned, deduplicated across whole blob
  Empty array:   {elem_type=0(4), count=0(4)}  (8 bytes total)

Type codes:
  1 = uint32 (value stored inline in vdata/elem_ptr)
  2 = float  (value stored inline, IEEE 754 LE)
  4 = string ref (vdata/elem_ptr = offset into string pool)
  5 = array  (vdata = offset to array node)
  6 = object (vdata = offset to object node)

Layout algorithm (DFS, key-before-value ordering):
  For each object: write struct with all entry placeholders first,
  then for each entry: write key string (dedup), write value recursively,
  patch placeholders. Strings are interleaved with structure nodes.
"""

import struct
import json
import os
import zlib
from typing import Any, Dict, List, Optional, Union


# --- Known render_config bundle hashes ---------------------------------------

RENDER_CONFIG_TYPE_HASH = 0x27862fe24795319c
"""MurmurHash64A("render_config")"""

KNOWN_RENDER_CONFIGS = {
    "96438abc757b9f23": "voxel_mip_generation (clear_voxels + generate_mips)",
    "44bcc04093e5c506": "ao_sun_occlusion",
    "47f1b7369bdf82c5": "terrain_editor_brushes",
}


# --- Decoder -----------------------------------------------------------------

def decode_cobj(blob: bytes) -> Any:
    """Decode a Stingray COBJ binary blob to a Python dict/list tree."""

    def read_str(off: int) -> str:
        end = blob.index(b'\x00', off)
        return blob[off:end].decode('utf-8', errors='replace')

    def decode_node(offset: int, ntype: int) -> Any:
        if ntype == 6:  # object
            count = struct.unpack_from('<I', blob, offset)[0]
            result: Dict[str, Any] = {}
            for i in range(count):
                kp, vt, vd = struct.unpack_from('<III', blob, offset + 4 + i * 12)
                key = read_str(kp)
                if   vt == 6: val = decode_node(vd, 6)
                elif vt == 5: val = decode_node(vd, 5)
                elif vt == 4: val = read_str(vd)
                elif vt == 1: val = vd
                elif vt == 2: val = struct.unpack('<f', struct.pack('<I', vd))[0]
                else:         val = (f'type{vt}', vd)
                result[key] = val
            return result
        elif ntype == 5:  # array
            et, cnt = struct.unpack_from('<II', blob, offset)
            items: List[Any] = []
            for i in range(cnt):
                ep = struct.unpack_from('<I', blob, offset + 8 + i * 4)[0]
                items.append(decode_node(ep, et) if et in (5, 6) else ep)
            return items
        return None

    rt, ro = struct.unpack_from('<II', blob, 0)
    return decode_node(ro, rt)


# --- Encoder -----------------------------------------------------------------

class COBJEncoder:
    """
    Stingray COBJ encoder.

    Usage:
        enc = COBJEncoder()
        blob = enc.encode({
            "resource_generators": {
                "my_generator": {
                    "modifiers": [
                        {"type": "generate_mips", "target": "my_texture"}
                    ]
                }
            }
        })
    """

    def __init__(self):
        self._buf: bytearray = bytearray()
        self._strings: Dict[str, int] = {}

    def _tell(self) -> int:
        return len(self._buf)

    def _write32(self, v: int) -> None:
        self._buf += struct.pack('<I', v & 0xFFFFFFFF)

    def _patch32(self, off: int, v: int) -> None:
        struct.pack_into('<I', self._buf, off, v & 0xFFFFFFFF)

    def _write_string(self, s: str) -> int:
        """Write string to pool (deduplicated), return its offset."""
        if s in self._strings:
            return self._strings[s]
        off = self._tell()
        b = s.encode('utf-8') + b'\x00'
        while len(b) % 4:
            b += b'\x00'
        self._buf += b
        self._strings[s] = off
        return off

    def _infer_type(self, v: Any) -> int:
        if isinstance(v, dict):  return 6
        if isinstance(v, list):  return 5
        if isinstance(v, str):   return 4
        if isinstance(v, int):   return 1
        if isinstance(v, float): return 2
        return 1

    def _encode_node(self, node: Any, ntype: int) -> int:
        """Encode node at current position, return its start offset."""
        if ntype == 6:  # object
            obj_off = self._tell()
            entries = list(node.items())
            self._write32(len(entries))
            # Write all entry placeholder slots first
            slots: List[tuple] = []
            for key, val in entries:
                kp_off = self._tell(); self._write32(0)
                self._write32(self._infer_type(val))
                vd_off = self._tell(); self._write32(0)
                slots.append((kp_off, vd_off))
            # Write key strings and values for each entry
            for (key, val), (kp_off, vd_off) in zip(entries, slots):
                self._patch32(kp_off, self._write_string(key))
                vtype = self._infer_type(val)
                if   vtype in (5, 6): self._patch32(vd_off, self._encode_node(val, vtype))
                elif vtype == 4:      self._patch32(vd_off, self._write_string(val))
                elif vtype == 1:      self._patch32(vd_off, val)
                elif vtype == 2:
                    self._patch32(vd_off, struct.unpack('<I', struct.pack('<f', val))[0])
            return obj_off

        elif ntype == 5:  # array
            arr_off = self._tell()
            if not node:
                self._write32(0); self._write32(0)  # empty: {type=0, count=0}
                return arr_off
            etype = self._infer_type(node[0])
            self._write32(etype)
            self._write32(len(node))
            # Interleave ptr capture WITH placeholder write (critical: don't pre-capture)
            ptr_offs: List[int] = []
            for _ in node:
                ptr_offs.append(self._tell())
                self._write32(0)
            for elem, ptr_off in zip(node, ptr_offs):
                if etype in (5, 6):
                    self._patch32(ptr_off, self._encode_node(elem, etype))
                elif etype == 4:
                    self._patch32(ptr_off, self._write_string(elem))
                else:
                    self._patch32(ptr_off, elem)
            return arr_off

        return self._tell()

    def encode(self, data: dict) -> bytes:
        """Encode a Python dict to COBJ binary blob."""
        self._buf = bytearray()
        self._strings = {}
        self._write32(6)                    # root type = object
        root_ptr_off = self._tell()
        self._write32(0)                    # placeholder for root offset
        self._patch32(root_ptr_off, self._encode_node(data, 6))
        return bytes(self._buf)


# --- High-level helpers -------------------------------------------------------

def make_render_config(generators: Dict[str, List[Dict]],
                       brush_mapping: Optional[Dict[str, str]] = None) -> bytes:
    """
    Build a render_config COBJ blob.

    Args:
        generators: Dict mapping generator_name -> list of modifier dicts.
                    Each modifier must have 'type' key.
        brush_mapping: Optional dict mapping brush_name -> generator_name.

    Example:
        blob = make_render_config({
            "my_gen": [
                {"type": "generate_mips", "target": "my_texture"},
            ]
        })
    """
    doc: Dict[str, Any] = {}

    if brush_mapping:
        doc["brush_resource_generator_mapping"] = brush_mapping

    doc["resource_generators"] = {
        name: {"modifiers": mods}
        for name, mods in generators.items()
    }

    return COBJEncoder().encode(doc)


def decode_render_config_blob(blob: bytes) -> Dict:
    """Decode a raw render_config COBJ blob to a Python dict."""
    return decode_cobj(blob)


# --- Bundle loading helpers ---------------------------------------------------

def _load_bundle_resource0(bundle_path: str) -> bytes:
    """Extract resource-0 data bytes from a compressed game bundle."""
    with open(bundle_path, 'rb') as f:
        data = f.read()
    magic, total_sz, zero, fcsz = struct.unpack('<IIII', data[:16])
    b = bytearray(zlib.decompress(data[16:16 + fcsz]))
    # Handle multi-chunk bundles
    if len(b) < total_sz:
        off = 16 + fcsz
        while len(b) < total_sz and off < len(data):
            csz = struct.unpack_from('<I', data, off)[0]
            off += 4
            b += zlib.decompress(data[off:off + csz])
            off += csz
    b = bytes(b[:total_sz])
    N = struct.unpack_from('<I', b)[0]
    toc_end = 0x104 + (N + 1) * 16
    data_sz = struct.unpack_from('<I', b, toc_end + 12)[0]
    return b[toc_end + 20:toc_end + 20 + data_sz]


def decode_bundle_render_config(bundle_path: str) -> Dict:
    """Decode the render_config from a game bundle file."""
    return decode_cobj(_load_bundle_resource0(bundle_path))


# --- CLI / test ---------------------------------------------------------------

def _self_test(contents_dir: str) -> None:
    """Round-trip test against all known render_config bundles."""
    enc = COBJEncoder()
    all_pass = True
    for bname in KNOWN_RENDER_CONFIGS:
        path = os.path.join(contents_dir, bname)
        if not os.path.exists(path):
            print(f"SKIP {bname} (not found)")
            continue
        orig = _load_bundle_resource0(path)
        decoded = decode_cobj(orig)
        reencoded = enc.encode(decoded)
        ok = (reencoded == orig)
        print(f"{'PASS' if ok else 'FAIL'} {bname} ({len(orig)}B) - {KNOWN_RENDER_CONFIGS[bname]}")
        if not ok:
            all_pass = False
            diff = next((i for i in range(min(len(orig), len(reencoded)))
                         if orig[i] != reencoded[i]), len(orig))
            print(f"     First diff @ {diff:#x}")
    print(f"\nAll pass: {all_pass}")


if __name__ == '__main__':
    import sys
    contents = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser('~/.local/share/Steam/steamapps/common/Gauntlet/contents')

    print("=== render_config_tools self-test ===")
    _self_test(contents)

    print("\n=== Decoded render_configs ===")
    for bname, desc in KNOWN_RENDER_CONFIGS.items():
        path = os.path.join(contents, bname)
        if os.path.exists(path):
            data = decode_bundle_render_config(path)
            print(f"\n{bname} ({desc}):")
            print(json.dumps(data, indent=2))
