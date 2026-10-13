#!/usr/bin/env python3
"""
Gauntlet Mod Bundle Builder
============================
Builds a complete mod bundle folder from a mod.json definition.
Supports textures (DDS/PNG), units (GLB/OBJ), materials, Lua scripts, and more.

The output is a ready-to-use mod folder for the GauntletModLoader:
    mods/bundles/<ModName>/
        bundle.ini
        <hash>           <- compressed bundle file
        <hash>.stream    <- empty stream file (required by engine)
        manifest.json    <- human-readable summary

=============================================================================
MOD.JSON FORMAT
=============================================================================

{
  "name":         "MyMod",
  "package_path": "resource_packages/custom/my_mod",
  "boot_overlay": {
    "phase":    "post_splash",
    "priority": 100,
    "required": false
  },
  "resources": [
    {
      "type":   "texture",
      "path":   "custom/my_mod/sword_diff",
      "source": "textures/sword_diff.dds"
    },
    {
      "type":   "texture",
      "path":   "custom/my_mod/sword_diff",
      "source": "textures/sword_diff.png"
    },
    {
      "type":    "unit",
      "path":    "units/custom/my_mod/sword",
      "source":  "models/sword.glb"
    },
    {
      "type":    "material",
      "path":    "custom/my_mod/sword_mat",
      "texture": "custom/my_mod/sword_diff"
    },
    {
      "type":   "lua",
      "path":   "scripts/custom/my_mod/init",
      "source": "scripts/init.lua"
    }
  ]
}

=============================================================================
RESOURCE TYPES
=============================================================================

  texture   DDS or PNG -> texture resource (DDS stored directly; PNG auto-converted)
  unit      GLB or OBJ -> Stingray .unit binary (via gltf_to_unit.py)
  material  JSON config or texture reference -> 52-byte Stingray material binary
  lua       .lua source file -> Lua resource
  bones     binary .bones file -> bones resource
  raw       any pre-built binary -> stored as-is with the given type

=============================================================================
USAGE
=============================================================================

  python mod_bundle_builder.py mod.json [--output-dir mods/bundles]
  python mod_bundle_builder.py mod.json --output-dir C:/Gauntlet/mods/bundles
  python mod_bundle_builder.py --help

=============================================================================
REPLACEMENT TEXTURES
=============================================================================

To replace existing game textures, use the game's EXACT resource path:
    "path": "characters/avatar_warrior/warrior_diff"

The hash will match the original, so your texture overrides the game's globally.
You still need to load your package via Game:load_package().

Known texture hashes:
    characters/avatar_warrior/warrior_diff -> 0x67111D9E39E1CABC
    characters/avatar_warrior/warrior_norm -> 0xF8C23D1F8B219C6D
    characters/avatar_elf/elf_diff         -> 0x5A946011CD458AA6

=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# -- optional PIL import for PNG->DDS --------------------------------------------
try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# -- constants ------------------------------------------------------------------

BUNDLE_SIG  = 0xF0000004
ZLIB_CHUNK  = 0x10000   # 64 KB

# Resource type hashes (MurmurHash64A of type name, seed=0, lowercase)
TYPE_HASHES: Dict[str, int] = {
    "texture":          0xCD4238C6A0C69E32,
    "unit":             0xE0A48D0BE9A7453F,
    "material":         0xEAC0B497876ADEDF,
    "lua":              0xA14E8DFA2CD117E2,
    "package":          0xAD9C6D9ED1E5E77A,
    "bones":            0x18DEAD01056B72E9,
    "mesh":             0xF7505491A64F4B44,
    "animation":        0x6AA91AA3C4D9E90F,
    "shader":           0x7FFD67AEB2A75069,
    "level":            0xB7893ADF7567506A,
    "physics":          0x82645835E6B73232,
    "config":           0x2B02B3A4E0E594F5,
    "render_config":    0x27862FE24795319C,
    "strings":          0xA8193123526FAD64,
    "particles":        0xD7468465328C897F,
    "font":             0x9E5B493B3A5F1B3C,
}

# Material shader/slot constants (from verified game material analysis)
_SHADER_DIFFUSE  = 0xBA25DE3579DC6624  # 52-byte diffuse material shader
_THINHASH_DIFFUSE = 0x3AA8B87E          # "diffuse_map" upper32 slot hash

_STATIC_UNIT_FOOTER_TEMPLATE = bytes.fromhex(
    "000000005000000000000000020000007d77773f50000000000000000100ff7fff7fff7f03082080"
    "ff7fff7fff7f0308208000c000000308208010c0c6030308208000800000ff7fff7fff7f1080c603"
    "ff7fff7fff7f0300010000000000000002000000ffffffff00000000010000000000803f00000000"
    "00000000000000000000803f0000000000000000000000000000803f000000000000000000000000"
    "0000803f0000803f0000803f0000803f000000000000000000000000000000000000803f00000000"
    "0000000000000000000000000000803f000000000000000000000000000000000000803f00000000"
    "edd76d7601000000edd76d7600000000010000000000000001000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000008000000ffffffff00000000000000"
    "00000000000000000004000000000000000000000000000000362bd572ad181b1500000000000000"
    "00"
)
_STATIC_UNIT_FOOTER_KEY_OFFSET = 0xF0
_STATIC_UNIT_FOOTER_HASH_OFFSET = 0x159
_STATIC_UNIT_FOOTER_CONTENT_KEY = 0x766DD7ED

# -- MurmurHash64A --------------------------------------------------------------

def murmur64(key: str, seed: int = 0) -> int:
    """MurmurHash64A - Bitsquid/Stingray engine hash, seed=0, lowercase."""
    m  = 0xC6A4A7935BD1E995
    r  = 47
    kb = key.lower().encode('utf-8')
    ln = len(kb)
    h  = (seed ^ ((ln * m) & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF

    for i in range(ln // 8):
        k = struct.unpack_from('<Q', kb, i * 8)[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h  = (h * m) & 0xFFFFFFFFFFFFFFFF

    tail = kb[ln & ~7:]
    if len(tail) >= 7: h ^= tail[6] << 48
    if len(tail) >= 6: h ^= tail[5] << 40
    if len(tail) >= 5: h ^= tail[4] << 32
    if len(tail) >= 4: h ^= tail[3] << 24
    if len(tail) >= 3: h ^= tail[2] << 16
    if len(tail) >= 2: h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h  = (h * m) & 0xFFFFFFFFFFFFFFFF

    h ^= h >> r
    h  = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> r
    return h


def _unit_mesh_end(data: bytes) -> Optional[int]:
    """Best-effort parse of mesh blocks to find the end of the unit body."""
    if len(data) < 8:
        return None
    try:
        sig, mesh_count = struct.unpack_from('<II', data, 0)
    except struct.error:
        return None
    if sig != 0x00010090 or mesh_count > 1024:
        return None

    offset = 8
    for _ in range(mesh_count):
        if offset + 4 > len(data):
            return None
        vertex_buffer_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4 + vertex_buffer_size
        offset += 8  # padding
        if offset + 12 > len(data):
            return None
        _, _, element_count = struct.unpack_from('<III', data, offset)
        offset += 12 + element_count * 17 + 12
        if offset + 8 > len(data):
            return None
        total_index_count, index_buffer_size = struct.unpack_from('<II', data, offset)
        offset += 8 + index_buffer_size
        if offset + 4 > len(data):
            return None
        shape_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4 + shape_count * 16 + 28
        if offset + 4 > len(data):
            return None
        material_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        for _ in range(material_count):
            if offset + 4 > len(data):
                return None
            name_len = struct.unpack_from('<I', data, offset)[0]
            offset += 4 + name_len

    return offset if offset <= len(data) else None


def _append_static_unit_footer(data: bytes, resource_name: str) -> bytes:
    """Append a minimal native-style footer to generated static units."""
    body_end = _unit_mesh_end(data)
    if body_end is None or body_end != len(data):
        return data

    footer = bytearray(_STATIC_UNIT_FOOTER_TEMPLATE)
    struct.pack_into('<I', footer, _STATIC_UNIT_FOOTER_KEY_OFFSET, _STATIC_UNIT_FOOTER_CONTENT_KEY)
    struct.pack_into('<I', footer, _STATIC_UNIT_FOOTER_KEY_OFFSET + 8, _STATIC_UNIT_FOOTER_CONTENT_KEY)
    struct.pack_into('<Q', footer, _STATIC_UNIT_FOOTER_HASH_OFFSET, murmur64(resource_name))
    return data + bytes(footer)


def _extract_unit_material_names(unit_data: bytes) -> List[str]:
    """Extract material names embedded in a compiled .unit payload."""
    if len(unit_data) < 8:
        return []

    try:
        _sig, mesh_count = struct.unpack_from('<II', unit_data, 0)
    except struct.error:
        return []

    if mesh_count <= 0 or mesh_count > 4096:
        return []

    offset = 8
    names: List[str] = []

    for _ in range(mesh_count):
        if offset + 4 > len(unit_data):
            return names
        vertex_buffer_size = struct.unpack_from('<I', unit_data, offset)[0]
        offset += 4 + vertex_buffer_size

        if offset + 8 + 12 > len(unit_data):
            return names
        offset += 8

        _vertex_count, _vertex_stride, element_count = struct.unpack_from('<III', unit_data, offset)
        offset += 12

        for _ in range(element_count):
            if offset + 17 > len(unit_data):
                return names
            offset += 17

        if offset + 12 > len(unit_data):
            return names
        offset += 12

        if offset + 8 > len(unit_data):
            return names
        _index_count, index_buffer_size = struct.unpack_from('<II', unit_data, offset)
        offset += 8 + index_buffer_size

        if offset + 4 > len(unit_data):
            return names
        shape_count = struct.unpack_from('<I', unit_data, offset)[0]
        offset += 4 + shape_count * 16

        if offset + 28 > len(unit_data):
            return names
        offset += 28

        if offset + 4 > len(unit_data):
            return names
        material_count = struct.unpack_from('<I', unit_data, offset)[0]
        offset += 4

        for _ in range(material_count):
            if offset + 4 > len(unit_data):
                return names
            name_len = struct.unpack_from('<I', unit_data, offset)[0]
            offset += 4
            if offset + name_len > len(unit_data):
                return names

            raw_name = unit_data[offset:offset + name_len]
            offset += name_len

            name = raw_name.decode('utf-8', errors='replace').rstrip('\x00')
            if name:
                names.append(name)

    deduped: List[str] = []
    seen = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _dependency_ref_from_name_hash(name_hash: int) -> int:
    """Convert a 64-bit resource hash into the package's 32-bit dependency reference."""
    return (name_hash >> 32) & 0xFFFFFFFF


def _parse_dependency_ref(raw: Any) -> Optional[int]:
    """Parse a dependency ref from int or hex string form."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw & 0xFFFFFFFF
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        if not text:
            return None
        try:
            return int(text, 16) & 0xFFFFFFFF
        except ValueError:
            return None
    return None

# -- resource data types --------------------------------------------------------

@dataclass
class Resource:
    type_hash: int
    name_hash: int
    data: bytes
    name: str = ""        # human-readable, for manifest/debug only

    @property
    def type_name(self) -> str:
        for k, v in TYPE_HASHES.items():
            if v == self.type_hash:
                return k
        return f"0x{self.type_hash:016x}"

# -- resource encoders ---------------------------------------------------------

def _encode_texture(src: str, resource_name: str, mod_dir: str) -> bytes:
    """Load DDS (or convert PNG->DDS) and return raw DDS bytes."""
    src_path = Path(mod_dir) / src if not Path(src).is_absolute() else Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"Texture source not found: {src_path}")

    if src_path.suffix.lower() in ('.dds',):
        return src_path.read_bytes()

    if src_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.tga', '.bmp'):
        # Try texconv first (Windows native DXT compression)
        dds_out = src_path.with_suffix('.dds')
        if _try_texconv(src_path, dds_out):
            return dds_out.read_bytes()

        # Fallback: use PIL's resource_tools/texture_tools.py encode path
        here = Path(__file__).parent
        tt = here / 'resource_tools' / 'texture_tools.py'
        if tt.exists():
            result = subprocess.run(
                [sys.executable, str(tt), 'encode', str(src_path), str(dds_out)],
                capture_output=True, text=True
            )
            if result.returncode == 0 and dds_out.exists():
                return dds_out.read_bytes()
            print(f"  [warn] texture_tools encode failed: {result.stderr.strip()}")

        # Last resort: PIL uncompressed BGRA DDS
        if _HAS_PIL:
            return _png_to_dds_uncompressed(src_path)

        raise RuntimeError(
            f"Cannot convert {src_path.name} to DDS - install Pillow or texconv"
        )

    raise ValueError(f"Unsupported texture source format: {src_path.suffix}")


def _try_texconv(src: Path, dst: Path) -> bool:
    """Attempt texconv.exe for DXT compression (Windows/Wine only)."""
    try:
        r = subprocess.run(
            ['texconv', '-nologo', '-y', '-o', str(dst.parent),
             '-f', 'BC3_UNORM', str(src)],
            capture_output=True, timeout=30
        )
        return r.returncode == 0 and dst.exists()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _png_to_dds_uncompressed(src: Path) -> bytes:
    """Convert PNG to uncompressed BGRA DDS using PIL (fallback)."""
    img = Image.open(src).convert('RGBA')
    w, h = img.size
    pixels = bytearray(img.tobytes())
    # Swap R<->B for BGRA
    for i in range(0, len(pixels), 4):
        pixels[i], pixels[i+2] = pixels[i+2], pixels[i]
    raw = bytes(pixels)

    # DDS header (128 bytes)
    dw_flags = 0x1007  # CAPS | HEIGHT | WIDTH | PIXELFORMAT
    pitch = w * 4
    pf_flags = 0x41    # RGB | ALPHAPIXELS
    hdr = struct.pack('<4sIIIIII44x'
                      'IIIII4sIIIIII16x'  # pixel format
                      'II28x',            # caps
        b'DDS ', 124, dw_flags, h, w, pitch, 0,  # base header
        32, pf_flags, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000,  # pixel format
        0x1000, 0                         # caps, caps2
    )
    return hdr + raw


def _encode_unit(src: str, resource_name: str, mod_dir: str) -> bytes:
    """Convert GLB/OBJ -> Stingray .unit binary via gltf_to_unit.py."""
    import tempfile
    src_path = Path(mod_dir) / src if not Path(src).is_absolute() else Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"Unit source not found: {src_path}")

    # If already a binary unit file, use as-is
    if src_path.suffix.lower() == '.unit':
        return src_path.read_bytes()

    here = Path(__file__).parent
    encoder = here / 'gltf_to_unit.py'
    if not encoder.exists():
        raise FileNotFoundError(f"gltf_to_unit.py not found at {encoder}")

    # Write output to a temp file so we don't litter the source directory
    with tempfile.NamedTemporaryFile(suffix='.unit', delete=False) as tf:
        out_path = Path(tf.name)

    try:
        result = subprocess.run(
            [sys.executable, str(encoder), str(src_path), str(out_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"gltf_to_unit.py failed for {src_path.name}:\n{result.stderr}")

        if not out_path.exists():
            raise RuntimeError(f"gltf_to_unit.py did not produce output: {out_path}")

        data = out_path.read_bytes()
        data = _append_static_unit_footer(data, resource_name)
        print(f"  Encoded unit: {src_path.name} -> {len(data):,} bytes")
        return data
    finally:
        out_path.unlink(missing_ok=True)


def _encode_material(spec: Dict[str, Any], resources: Dict[str, Resource]) -> bytes:
    """
    Build or pass through a Stingray material binary.

    spec may contain:
      "source":  pre-built .material binary file path -> stored as-is
      "texture": resource path string  -> builds 52-byte diffuse material (GUI/icon use)
      "shader":  hex uint64 shader hash (optional override for "texture" mode)
      "data":    pre-built binary data as hex string (raw mode)

      "clone_from": path to native .material binary -> clone it with texture remapping
      "remap_textures": { "old_texture_path": "new_texture_path", ... }
                        Only used with "clone_from". Uses byte-level search-and-replace
                        of MurmurHash64 values, preserving all shader parameters and
                        trailing data. This is the RECOMMENDED way to create materials
                        for world objects (avoids crashes from simplified formats).
    """
    if "source" in spec:
        return _encode_raw(spec["source"], spec.get("_mod_dir", ""))

    if "data" in spec:
        return bytes.fromhex(spec["data"])

    if "clone_from" in spec:
        # Clone a native material with texture remapping
        native_path = spec["clone_from"]
        if not os.path.isabs(native_path):
            # Resolve relative to: mod directory -> script directory
            found = False
            mod_dir = spec.get("_mod_dir", "")
            if mod_dir:
                candidate = os.path.join(mod_dir, native_path)
                if os.path.exists(candidate):
                    native_path = candidate
                    found = True
            if not found:
                script_dir = os.path.dirname(__file__)
                candidate = os.path.join(script_dir, native_path)
                if os.path.exists(candidate):
                    native_path = candidate
                    found = True
            if not found:
                raise FileNotFoundError(
                    f"clone_from material not found: '{native_path}' "
                    f"(checked mod_dir={mod_dir!r}, script_dir={script_dir!r})"
                )

        remap = spec.get("remap_textures", {})
        if not remap:
            raise ValueError("Material clone_from requires 'remap_textures' dict")

        verbose = spec.get("_verbose", False)

        # Import and use clone_material
        from clone_material import clone_material
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.material', delete=False) as tf:
            out_path = tf.name
        try:
            clone_material(native_path, out_path, remap, verbose=verbose)
            with open(out_path, 'rb') as f:
                data = f.read()
            return data
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    if "texture" in spec:
        tex_path = spec["texture"]
        tex_hash = murmur64(tex_path)
        shader = int(spec.get("shader", hex(_SHADER_DIFFUSE)), 16)

        return struct.pack(
            '<II Q Q I I Q III',
            0x0A, 1,
            shader, 0,
            1, _THINHASH_DIFFUSE, tex_hash,
            0, 0, 0,
        )

    raise ValueError(
        "Material spec needs 'source', 'clone_from', 'texture', or 'data' key"
    )


def _encode_lua(src: str, mod_dir: str) -> bytes:
    """Load .lua source file and return its bytes."""
    src_path = Path(mod_dir) / src if not Path(src).is_absolute() else Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"Lua source not found: {src_path}")
    return src_path.read_bytes()


def _encode_raw(src: str, mod_dir: str) -> bytes:
    """Load any binary file as-is."""
    src_path = Path(mod_dir) / src if not Path(src).is_absolute() else Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"Resource source not found: {src_path}")
    return src_path.read_bytes()

# -- package resource builder --------------------------------------------------

def _build_package_resource(non_pkg_resources: List[Resource],
                            dependency_base_ref: Optional[int] = None,
                            resource_specs_by_name: Optional[Dict[str, Dict[str, Any]]] = None) -> bytes:
    """
    Build the .package resource blob listing all non-package resources.

    CORRECTED FORMAT (28-byte fixed entries - verified against native bundles):
      uint32  entry_count
      per entry (28 bytes each):
        uint64  type_hash     [0:8]
        uint64  name_hash     [8:16]
        uint32  c1            [16:20] = ALWAYS 2 (native requirement)
        uint32  c2            [20:24] = 0 (safe for custom bundles)
        uint32  name_hi32     [24:28] = upper 32 bits of name_hash
      uint8   trailer = 0x01

    PRIOR 20-byte variable-size format was WRONG and caused buffer overruns
    when the engine read entries past the end of the undersized payload.
    (See FINDINGS.txt Section 9B.1 for the byte-level confirmation.)

    Dependencies are NOT emitted inline - they are expressed implicitly through
    the resource ordering and the engine's built-in dependency resolution.
    Material->texture and unit->material relationships are resolved at runtime
    by the engine's resource manager scanning name hashes.
    """
    count = len(non_pkg_resources)
    body = struct.pack('<I', count)  # entry_count header

    for r in non_pkg_resources:
        name_hi32 = (r.name_hash >> 32) & 0xFFFFFFFF
        body += struct.pack(
            '<QQIII',
            r.type_hash,   # uint64: resource type hash
            r.name_hash,   # uint64: resource name hash
            2,             # uint32: c1 = 2 (REQUIRED - native bundles ALWAYS use 2)
            0,             # uint32: c2 = 0 (safe for custom bundles)
            name_hi32,     # uint32: upper 32 bits of name_hash
        )

    body += b'\x01'  # trailer byte (always 0x01 in native bundles)
    return body

# -- bundle assembler ----------------------------------------------------------

def _build_bundle(all_resources: List[Resource]) -> bytes:
    """
    Assemble an unpacked bundle body.

    CORRECTED FORMAT (verified byte-for-byte against native Gauntlet bundles):
      [0x000:0x004]  uint32  N  - resource count
      [0x004:0x058]  84-byte PREAMBLE (all zeros for custom bundles)
      [0x058:0x104]  172-byte PADDING (zeros)
      [0x104:]       TOC - (N+1) x 16-byte entries
          Each entry: {uint64 type_hash, uint64 name_hash}
          CRITICAL: entry[N] is a SENTINEL = exact copy of entry[0]
      [toc_end:]     RESOURCE-0 METADATA - 20 bytes
          uint32  flags       (normally 1)
          uint64  zeros       (always 0)
          uint32  data_sz     (byte count of resource-0 data)
          uint32  stream_sz   (0 = no stream data)
      [toc_end+20:]  RESOURCE-0 DATA - data_sz bytes
      [after res-0:] RESOURCES 1..N-1 (each starts with a 36-byte header)
          uint64  type_hash
          uint64  name_hash
          uint32  flags       (normally 1)
          uint64  zeros       (always 0)
          uint32  data_sz
          uint32  stream_sz
          bytes[data_sz]  resource data

    The resource-0 is always the package resource (sorted first).
    Its header is 20 bytes (no type/name fields) - NOT the 36-byte format
    used by resources 1..N-1.  See FINDINGS.txt Section 4 for full details.
    """
    if not all_resources:
        raise ValueError("Bundle has no resources")

    n = len(all_resources)

    # Sort by name_hash for stable ordering (package resource first)
    pkg_type = TYPE_HASHES["package"]
    pkg_res  = [r for r in all_resources if r.type_hash == pkg_type]
    other    = [r for r in all_resources if r.type_hash != pkg_type]
    sorted_res = pkg_res + sorted(other, key=lambda r: r.name_hash)

    parts: List[bytes] = []

    # 1. Resource count
    parts.append(struct.pack('<I', n))

    # 2. 84-byte preamble (zeros for custom bundles)
    parts.append(b'\x00' * 84)

    # 3. 172-byte padding to offset 0x104
    #    (84 bytes preamble + 172 bytes = 256 bytes from offset 4)
    parts.append(b'\x00' * 172)

    # 4. TOC - (N+1) x 16-byte entries with sentinel
    for r in sorted_res:
        parts.append(struct.pack('<QQ', r.type_hash, r.name_hash))
    # Sentinel: entry[N] = exact copy of entry[0]
    parts.append(struct.pack('<QQ', sorted_res[0].type_hash, sorted_res[0].name_hash))

    # 5. Resource-0 (package) - 20-byte header (NO type/name fields)
    r0 = sorted_res[0]
    sz0 = len(r0.data)
    parts.append(struct.pack('<IQII',
        1,     # uint32: flags
        0,     # uint64: zeros
        sz0,   # uint32: data_sz
        0      # uint32: stream_sz
    ))
    parts.append(r0.data)

    # 6. Resources 1..N-1 - each with 36-byte header + data
    # CRITICAL: each resource must start on a 4-byte boundary.
    # Pad to 4-byte alignment after resource-0 data before writing
    # the first 36-byte resource header, and again after each
    # resource's data before the next header.
    for r in sorted_res[1:]:
        # Align to 4 bytes before writing this resource
        current = b''.join(parts)
        misalign = len(current) % 4
        if misalign:
            parts.append(b'\x00' * (4 - misalign))

        sz = len(r.data)
        parts.append(struct.pack('<QQIQII',
            r.type_hash, r.name_hash,
            1,   # flags
            0,   # stream_size (uint64)
            sz,  # data_size
            0    # unknown
        ))
        parts.append(r.data)

    raw = b''.join(parts)

    # 7. Final 4-byte alignment (safety)
    pad = (4 - len(raw) % 4) % 4
    if pad:
        raw += b'\x00' * pad

    return raw


def _compress_bundle(unpacked: bytes) -> bytes:
    """
    Compress bundle data using zlib chunking.

    Format:
      uint32  sig  = 0xF0000004
      uint32  uncompressed_size
      uint32  padding = 0
      [N chunks]: uint32 compressed_chunk_size + zlib_deflate_bytes

    IMPORTANT: last chunk is NOT padded to 64KB - stored at its actual size.
    """
    sig_hdr = struct.pack('<III', BUNDLE_SIG, len(unpacked), 0)
    chunks  = [sig_hdr]
    offset  = 0
    while offset < len(unpacked):
        chunk = unpacked[offset:offset + ZLIB_CHUNK]
        cdata = zlib.compress(chunk, 6)
        chunks.append(struct.pack('<I', len(cdata)))
        chunks.append(cdata)
        offset += ZLIB_CHUNK
    return b''.join(chunks)

# -- bundle.ini writer ---------------------------------------------------------

def _write_bundle_ini(out_dir: Path, package_path: str, resource_count: int,
                      has_stream: bool, boot_overlay: Optional[Dict]) -> None:
    lines = [
        "[Bundle]",
        f"PackagePath={package_path}",
        f"ResourceCount={resource_count}",
        f"HasStream={'true' if has_stream else 'false'}",
    ]
    if boot_overlay:
        phase    = boot_overlay.get("phase",    "post_splash")
        priority = boot_overlay.get("priority", 100)
        required = boot_overlay.get("required", False)
        lines += [
            "",
            "[BootOverlay]",
            f"Phase={phase}",
            f"Priority={priority}",
            f"Required={'true' if required else 'false'}",
        ]
    (out_dir / "bundle.ini").write_text('\n'.join(lines) + '\n')

# -- manifest writer -----------------------------------------------------------

def _write_manifest(out_dir: Path, mod_name: str, package_path: str,
                    bundle_hash: str, all_resources: List[Resource],
                    source_specs: List[Dict]) -> None:
    resources_out = {}
    for r in all_resources:
        resources_out[r.name or f"0x{r.name_hash:016x}"] = {
            "type":      r.type_name,
            "type_hash": f"0x{r.type_hash:016x}",
            "name_hash": f"0x{r.name_hash:016x}",
            "size":      len(r.data),
        }

    manifest = {
        "mod_name":    mod_name,
        "package_path": package_path,
        "bundle_hash": bundle_hash,
        "resource_count": len(all_resources),
        "resources":   resources_out,
        "lua_load_code": f'Game:load_package("{package_path}", true)',
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + '\n'
    )

# -- main builder --------------------------------------------------------------

def build_mod_bundle(mod_json_path: str, output_dir: Optional[str] = None,
                     verbose: bool = False, flat: bool = False) -> str:
    """
    Build a complete mod bundle folder from a mod.json definition.

    Returns the path to the output bundle folder.
    """
    mod_json = Path(mod_json_path).resolve()
    if not mod_json.exists():
        raise FileNotFoundError(f"mod.json not found: {mod_json}")

    with mod_json.open() as f:
        spec = json.load(f)

    mod_dir      = mod_json.parent
    mod_name     = spec.get("name", mod_json.stem)
    package_path = spec.get("package_path",
                             f"resource_packages/custom/{mod_name}").lower().strip('/')
    boot_overlay = spec.get("boot_overlay", None)
    dependency_base_ref = _parse_dependency_ref(spec.get("dependency_base_ref"))
    resource_specs = spec.get("resources", [])

    print("=" * 70)
    print(f"Mod Bundle Builder - {mod_name}")
    print("=" * 70)
    print(f"Package path : {package_path}")

    # Compute package hash -> bundle filename
    bundle_hash_int = murmur64(package_path)
    bundle_hash     = f"{bundle_hash_int:016x}"
    print(f"Bundle hash  : {bundle_hash}")
    print()

    # -- Process each resource spec ------------------------------------------
    non_pkg_resources: List[Resource] = []
    source_specs: List[Dict] = []

    for i, rs in enumerate(resource_specs):
        res_type = rs.get("type", "").lower()
        res_path = rs.get("path", "")
        if not res_path:
            print(f"  [warn] Resource #{i} has no 'path', skipping")
            continue
        if res_type not in TYPE_HASHES:
            print(f"  [warn] Unknown resource type '{res_type}' for '{res_path}', skipping")
            continue

        print(f"  [{res_type:10s}] {res_path}")

        type_hash = TYPE_HASHES[res_type]
        name_hash = murmur64(res_path)

        try:
            if res_type == "texture":
                data = _encode_texture(rs["source"], res_path, str(mod_dir))
                print(f"              -> {len(data):,} bytes  (hash 0x{name_hash:016X})")

            elif res_type == "unit":
                data = _encode_unit(rs["source"], res_path, str(mod_dir))
                print(f"              -> {len(data):,} bytes  (hash 0x{name_hash:016X})")

            elif res_type == "material":
                material_spec = dict(rs)
                material_spec["_mod_dir"] = mod_dir
                data = _encode_material(material_spec, {r.name: r for r in non_pkg_resources})
                print(f"              -> {len(data):,} bytes  (hash 0x{name_hash:016X})")

            elif res_type == "lua":
                data = _encode_lua(rs["source"], str(mod_dir))
                print(f"              -> {len(data):,} bytes  (hash 0x{name_hash:016X})")

            elif res_type == "bones":
                data = _encode_raw(rs["source"], str(mod_dir))
                print(f"              -> {len(data):,} bytes  (hash 0x{name_hash:016X})")

            else:  # raw / any other
                data = _encode_raw(rs["source"], str(mod_dir))
                print(f"              -> {len(data):,} bytes  (hash 0x{name_hash:016X})")

        except Exception as e:
            print(f"  [ERROR] Failed to encode '{res_path}': {e}")
            raise

        res = Resource(
            type_hash=type_hash,
            name_hash=name_hash,
            data=data,
            name=res_path,
        )
        non_pkg_resources.append(res)
        source_specs.append(rs)

    # -- Build package resource --------------------------------------------
    resource_specs_by_name = {
        rs.get("path", ""): rs
        for rs in resource_specs
        if isinstance(rs, dict) and rs.get("path")
    }

    pkg_data  = _build_package_resource(
        non_pkg_resources,
        dependency_base_ref=dependency_base_ref,
        resource_specs_by_name=resource_specs_by_name,
    )
    pkg_res   = Resource(
        type_hash = TYPE_HASHES["package"],
        name_hash = murmur64(package_path),
        data      = pkg_data,
        name      = package_path,
    )
    print(f"\n  [{'package':10s}] {package_path}")
    print(f"              -> {len(pkg_data):,} bytes  ({len(non_pkg_resources)} entries)")

    all_resources = [pkg_res] + non_pkg_resources
    total = len(all_resources)
    print(f"\nTotal resources: {total}")

    # -- Assemble + compress bundle -----------------------------------------
    print("\nAssembling bundle...")
    unpacked = _build_bundle(all_resources)
    print(f"  Unpacked : {len(unpacked):,} bytes")

    compressed = _compress_bundle(unpacked)
    ratio = (1 - len(compressed) / len(unpacked)) * 100 if len(unpacked) else 0
    print(f"  Packed   : {len(compressed):,} bytes  ({ratio:.1f}% compression)")

    # -- Write output --------------------------------------------------------
    if output_dir is None:
        # Default: sibling 'output/<ModName>' folder relative to mod.json
        out_dir = mod_json.parent / "output" / mod_name
    elif flat:
        # --flat: write directly into the given output-dir (no name subfolder)
        out_dir = Path(output_dir)
    else:
        out_dir = Path(output_dir) / mod_name

    out_dir.mkdir(parents=True, exist_ok=True)

    # Bundle file
    bundle_file = out_dir / bundle_hash
    bundle_file.write_bytes(compressed)

    # Empty .stream file (engine requires presence of stream file)
    (out_dir / f"{bundle_hash}.stream").write_bytes(b'')

    # bundle.ini
    _write_bundle_ini(out_dir, package_path, total,
                      has_stream=False, boot_overlay=boot_overlay)

    # manifest.json
    _write_manifest(out_dir, mod_name, package_path, bundle_hash,
                    all_resources, source_specs)

    print(f"\n[ok] Bundle written to: {out_dir}")
    print()
    print("-" * 70)
    print("MOD LOADER INSTALLATION")
    print("-" * 70)
    print(f"Copy the folder to your game's mod loader:")
    print(f"    {out_dir}")
    print(f"  -> <Gauntlet>/mods/bundles/{mod_name}/")
    print()
    print("LUA LOAD (if not using BootOverlay):")
    print(f'    Game:load_package("{package_path}", true)')
    print()
    print("RESOURCE HASHES for Lua reference:")
    for r in non_pkg_resources:
        print(f"    {r.name:50s} 0x{r.name_hash:016X}")
    print()

    return str(out_dir)

# -- CLI ------------------------------------------------------------------------

def _make_example_mod_json(out_path: str) -> None:
    """Write an example mod.json to out_path."""
    example = {
        "name": "ExampleMod",
        "package_path": "resource_packages/custom/example_mod",
        "boot_overlay": {
            "phase":    "post_splash",
            "priority": 100,
            "required": False
        },
        "resources": [
            {
                "_comment": "Texture: DDS or PNG accepted",
                "type":   "texture",
                "path":   "custom/example_mod/my_texture",
                "source": "textures/my_texture.dds"
            },
            {
                "_comment": "Material referencing a texture by path",
                "type":    "material",
                "path":    "custom/example_mod/my_material",
                "texture": "custom/example_mod/my_texture"
            },
            {
                "_comment": "Unit from Blender GLB export",
                "type":   "unit",
                "path":   "units/custom/example_mod/my_model",
                "source": "models/my_model.glb"
            },
            {
                "_comment": "Lua script bundled with the mod",
                "type":   "lua",
                "path":   "scripts/custom/example_mod/main",
                "source": "scripts/main.lua"
            }
        ]
    }
    Path(out_path).write_text(json.dumps(example, indent=2) + '\n')
    print(f"Example mod.json written to: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a Gauntlet mod bundle from a mod.json definition.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("mod_json", nargs="?",
                        help="Path to mod.json definition file")
    parser.add_argument("--output-dir", "-o",
                        help="Output directory (default: <mod.json dir>/output/<ModName>)")
    parser.add_argument("--flat", action="store_true",
                        help="Write files directly into --output-dir (no ModName subfolder). "
                             "Use when output-dir IS the target bundle folder, e.g. mods/bundles/MyMod/")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print verbose debug info")
    parser.add_argument("--example", metavar="PATH",
                        help="Generate an example mod.json at PATH and exit")
    parser.add_argument("--hash", metavar="STRING",
                        help="Print MurmurHash64 of STRING and exit")

    args = parser.parse_args()

    if args.hash:
        h = murmur64(args.hash)
        print(f"MurmurHash64({args.hash!r}) = 0x{h:016X}  ({h})")
        return

    if args.example:
        _make_example_mod_json(args.example)
        return

    if not args.mod_json:
        parser.print_help()
        sys.exit(1)

    try:
        build_mod_bundle(args.mod_json, args.output_dir, args.verbose, flat=args.flat)
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
