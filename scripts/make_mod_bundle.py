#!/usr/bin/env python3
"""
Gauntlet Mod Bundle Maker - All-in-One
=======================================
Creates complete mod bundles for the Gauntlet Mod Loader from a simple
folder of assets. Supports textures (.dds), materials (auto-generated
from textures), and 3D models (.fbx -> compiled .unit).

USAGE:
  # Single file - output goes next to the file
  python make_mod_bundle.py /path/to/model.fbx

  # Folder of assets - output goes in that folder
  python make_mod_bundle.py my_mod_folder

  # Explicit mod name (default: derived from file/folder name)
  python make_mod_bundle.py my_mod_folder MyModName

  # Custom output directory
  python make_mod_bundle.py my_mod_folder -o output/

  # With texture replacement (match original game paths)
  python make_mod_bundle.py my_mod_folder --replace

  # Skip material generation for textures
  python make_mod_bundle.py my_mod_folder --no-materials

  # Multi-slot materials (diffuse + normal + specular auto-grouped)
  python make_mod_bundle.py my_mod_folder --auto-group

FOLDER STRUCTURE:
  my_mod_folder/
    textures/
      warrior_diff.dds         # Diffuse textures
      warrior_norm.dds         # Normal maps (auto-detected by suffix)
      warrior_spec.dds         # Specular maps
    models/
    my_sword.fbx             # FBX models (converted to .unit)
    my_sword.unit            # Precompiled unit files (optional)
    materials/
      custom_mat.material      # Pre-built binary materials (optional)
    lua/
      my_script.lua            # Lua scripts (optional)

  Or just dump everything in the root:
    my_mod_folder/
      texture1.dds
      model.fbx

OUTPUT (in mods/bundles/ layout for the mod loader):
  <output>/
    MyModName/
      bundle.ini               # Mod loader manifest
      <hex_bundle_file>        # The compiled bundle
      <hex>.stream             # Empty stream file
      manifest.json            # Human-readable resource listing

ENTITIES vs UNITS:
  In Bitsquid/Stingray, a "unit" is a binary resource containing mesh data,
  material references, and optional script data. An "entity" is a RUNTIME
  concept - it's a unit that has been enhanced with Lua components and
  registered with the network game object system.

  There is NO separate "entity" resource type. A unit becomes an entity if:
    1. It has script data with a "components" key
    2. Generated Lua lookup tables map the unit path to component lists
    3. Settings Lua files define entity properties (hitpoints, speed, etc.)

  To add NEW entity types, you'd also need to modify:
    - lua/generated/unit_path_to_components.lua
    - lua/generated/units_with_settings.lua
  These are Lua scripts loaded by the engine at runtime.

FLOW CHARTS:
  Flow is Bitsquid/Stingray's visual scripting system. Flow resources
  (type hash 0x897A83FF37DAB3DD) are compiled binary node graphs that
  the C++ engine evaluates. They're attached to units and levels.

  Flow operates through events:
    - Lua triggers: Unit.flow_event(unit, "on_death")
    - The engine evaluates the unit's flow graph
    - Flow nodes execute (play sound, animation, particles, etc.)
    - "Lua Callback" nodes call back into FlowCallbacks table

  Creating new Flow resources requires the Stingray Editor (discontinued).
  For modding, use Lua hooks via FlowCallbacks to intercept and modify
  flow behavior, or trigger existing flow events from Lua code.

  The FlowCallbackRouter broadcasts any unknown key to all registered
  routers, so you can define new callbacks:
    FlowCallbacks.my_custom_event = function(params) ... end
"""

import struct
import zlib
import os
import sys
import json
import math
import argparse
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


# ============================================================================
# Constants
# ============================================================================

BUNDLE_SIG_OLD = 0xF0000004
ZLIB_CHUNK = 0x10000  # 64KB

# Resource type hashes (MurmurHash64 of type name, seed=0, lowercase)
TYPE_TEXTURE    = 0xCD4238C6A0C69E32
TYPE_MATERIAL   = 0xEAC0B497876ADEDF
TYPE_UNIT       = 0xE0A48D0BE9A7453F
TYPE_PACKAGE    = 0xAD9C6D9ED1E5E77A
TYPE_LUA        = 0xA14E8DFA2CD117E2
TYPE_MESH       = 0x48FF313713A997A1
TYPE_BONES      = 0x18DEAD01056B72E9
TYPE_ANIMATION  = 0x931E336D7646CC26
TYPE_FLOW       = 0x897A83FF37DAB3DD

# Common first dependency value observed across many native unit package entries.
OBSERVED_NATIVE_UNIT_BASE_DEP = 0x6B1FEA56
NATIVE_PACKAGE_TRAILER_BYTE = b"\x01"

# Shader hashes for materials
SHADER_DIFFUSE_SIMPLE = 0xBA25DE3579DC6624  # Supports diffuse_map
SHADER_DIFFUSE_NORMAL = 0xBA25DE3579DC6624  # Same shader, multiple slots

# ThinHash values for texture slots (upper 32 bits of MurmurHash64)
THINHASH_DIFFUSE  = 0x3AA8B87E   # diffuse_map
THINHASH_NORMAL   = 0xF5C97D31   # normal_map
THINHASH_SPECULAR = 0x50968221   # specular_map
THINHASH_EMISSIVE = 0x4DC19F08   # emissive_map

# Suffixes that identify texture types
TEXTURE_SUFFIXES = {
    '_diff':  'diffuse',
    '_diffuse': 'diffuse',
    '_color': 'diffuse',
    '_albedo': 'diffuse',
    '_norm':  'normal',
    '_normal': 'normal',
    '_nrm':   'normal',
    '_spec':  'specular',
    '_specular': 'specular',
    '_gloss': 'specular',
    '_emissive': 'emissive',
    '_emit':  'emissive',
    '_glow':  'emissive',
    '_mask':  'diffuse',  # Treat masks as diffuse
}


# ============================================================================
# MurmurHash64A (Bitsquid variant)
# ============================================================================

def murmur_hash64(key: str, seed: int = 0) -> int:
    """MurmurHash64A - Bitsquid/Stingray resource hashing."""
    m = 0xC6A4A7935BD1E995
    r = 47
    key_bytes = key.lower().encode('utf-8')
    length = len(key_bytes)
    h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)

    nblocks = length // 8
    for i in range(nblocks):
        k = struct.unpack('<Q', key_bytes[i*8:(i+1)*8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    tail = key_bytes[nblocks * 8:]
    if len(tail) >= 7: h ^= tail[6] << 48
    if len(tail) >= 6: h ^= tail[5] << 40
    if len(tail) >= 5: h ^= tail[4] << 32
    if len(tail) >= 4: h ^= tail[3] << 24
    if len(tail) >= 3: h ^= tail[2] << 16
    if len(tail) >= 2: h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    return h


# ============================================================================
# Resource Data Classes
# ============================================================================

@dataclass
class Resource:
    """A single resource to pack into a bundle."""
    type_hash: int
    name: str          # Human-readable resource path
    name_hash: int     # MurmurHash64 of name
    data: bytes        # Raw resource data


@dataclass
class TextureInfo:
    """Metadata about a collected texture."""
    path: Path
    resource_name: str
    name_hash: int
    width: int
    height: int
    fmt: str           # DXT1, DXT5, ATI2, etc.
    role: str          # diffuse, normal, specular, emissive
    group: str         # Grouping key (stem without suffix)
    data: bytes


@dataclass
class PackageEntry:
    """A package entry with optional 32-bit dependency references."""
    type_hash: int
    name_hash: int
    dependencies: List[int] = field(default_factory=list)


# ============================================================================
# DDS Helpers
# ============================================================================

def parse_dds(data: bytes) -> Tuple[bool, int, int, str]:
    """Parse a DDS file header. Returns (ok, width, height, format)."""
    if len(data) < 128 or data[:4] != b'DDS ':
        return False, 0, 0, ""
    height = struct.unpack_from('<I', data, 12)[0]
    width = struct.unpack_from('<I', data, 16)[0]
    fourcc = data[0x54:0x58]
    fmt_map = {b'DXT1': 'DXT1', b'DXT3': 'DXT3', b'DXT5': 'DXT5',
               b'ATI2': 'ATI2', b'BC5U': 'BC5U', b'ATI1': 'ATI1'}
    fmt = fmt_map.get(fourcc, fourcc.decode('ascii', errors='replace'))
    return True, width, height, fmt


def detect_texture_role(stem: str) -> str:
    """Detect texture role (diffuse/normal/specular/emissive) from filename."""
    stem_lower = stem.lower()
    for suffix, role in TEXTURE_SUFFIXES.items():
        if stem_lower.endswith(suffix):
            return role
    return 'diffuse'  # Default


def get_texture_group(stem: str) -> str:
    """Get grouping key by stripping the role suffix."""
    stem_lower = stem.lower()
    for suffix in TEXTURE_SUFFIXES:
        if stem_lower.endswith(suffix):
            return stem[:len(stem) - len(suffix)]
    return stem


# ============================================================================
# Material Builder
# ============================================================================

def build_material_single(texture_hash: int, slot_thinhash: int = THINHASH_DIFFUSE,
                          slot_index: int = 1) -> bytes:
    """
    Build a 52-byte material with a single texture slot.

    Format (verified from real game materials):
      [0:4]   uint32  version = 0x0A
      [4:8]   uint32  section_count = 1
      [8:16]  uint64  shader_hash
      [16:24] uint64  padding = 0
      [24:28] uint32  slot_index (MUST be 1 for diffuse!)
      [28:32] uint32  thin_hash
      [32:40] uint64  texture_hash
      [40:52] 12 bytes zeros
    """
    data = struct.pack('<II', 0x0A, 1)
    data += struct.pack('<Q', SHADER_DIFFUSE_SIMPLE)
    data += struct.pack('<Q', 0)
    data += struct.pack('<I', slot_index)
    data += struct.pack('<I', slot_thinhash)
    data += struct.pack('<Q', texture_hash)
    data += b'\x00' * 12
    return data


def build_material_multi(slots: List[Tuple[int, int, int]]) -> bytes:
    """
    Build a material with multiple texture slots.

    Each slot is (slot_index, thin_hash, texture_hash).
    The material grows by 16 bytes per additional slot beyond the first.

    Base: 52 bytes (1 slot). Each extra slot adds 16 bytes at the end
    (adjusting trailing zeros).
    """
    if not slots:
        raise ValueError("Need at least one texture slot")

    if len(slots) == 1:
        idx, th, tex = slots[0]
        return build_material_single(tex, th, idx)

    # Multi-slot: version + sections + shader + padding + slots + trailing
    section_count = len(slots)
    data = struct.pack('<II', 0x0A, section_count)
    data += struct.pack('<Q', SHADER_DIFFUSE_SIMPLE)
    data += struct.pack('<Q', 0)

    for idx, th, tex in slots:
        data += struct.pack('<I', idx)
        data += struct.pack('<I', th)
        data += struct.pack('<Q', tex)

    # Trailing zeros
    data += b'\x00' * 12
    return data


# ============================================================================
# FBX -> Stingray .unit Converter
# ============================================================================

def fbx_to_unit(fbx_path: str) -> bytes:
    """
    Convert an FBX/OBJ/glTF file to Gauntlet's .unit binary format.

    Uses assimp-py for broad format support (FBX, OBJ, glTF, DAE, etc.).
    Install: pip install assimp-py

    Gauntlet .unit format:
      Header (8 bytes):
        uint32  signature = 0x00010090
        uint32  mesh_count

      Per mesh:
        uint32  vertex_buffer_size
        bytes   vertex_data (interleaved)
        8 bytes padding
        uint32  vertex_count
        uint32  vertex_stride
        uint32  element_count
        [element descriptors]
        12 bytes padding
        uint32  total_index_count
        uint32  index_buffer_size
        uint16[] indices
        uint32  shape_count
        [shapes: material_idx, index_offset, index_count, shape_idx]
        float[7] bounding box
        uint32  material_count
        [materials: uint32 name_len + chars]
    """
    try:
        import assimp_py
    except ImportError:
        print("  ERROR: 'assimp-py' package required for model import.")
        print("         Install with: pip install assimp-py")
        return None

    flags = (assimp_py.Process_Triangulate |
             assimp_py.Process_GenNormals |
             assimp_py.Process_CalcTangentSpace |
             assimp_py.Process_JoinIdenticalVertices)
    try:
        scene = assimp_py.import_file(fbx_path, flags)
    except Exception as e:
        print(f"  ERROR loading model: {e}")
        return None

    if not scene.meshes:
        print(f"  ERROR: No meshes found in {fbx_path}")
        return None

    # Build the .unit binary
    out = bytearray()
    out += struct.pack('<II', 0x00010090, len(scene.meshes))

    for mesh_idx, mesh in enumerate(scene.meshes):
        # assimp-py gives flat lists: vertices=[x,y,z,x,y,z,...]
        raw_verts = mesh.vertices
        vertex_count = len(raw_verts) // 3

        raw_normals = mesh.normals if mesh.normals else []
        has_normals = len(raw_normals) == vertex_count * 3

        raw_tangents = mesh.tangents if mesh.tangents else []
        has_tangents = len(raw_tangents) == vertex_count * 3

        raw_bitangents = mesh.bitangents if mesh.bitangents else []
        has_bitangents = len(raw_bitangents) == vertex_count * 3

        # UVs: assimp-py gives texcoords as list of channels; each channel is [u,v,w, u,v,w,...]
        has_uv = bool(mesh.texcoords) and len(mesh.texcoords[0]) >= vertex_count * 3
        raw_uvs = mesh.texcoords[0] if has_uv else []

        # Build element list and compute stride
        elements = []
        stride = 0

        # Position (always)
        elements.append((0, 2, 0, 0))  # POSITION, 3 components
        stride += 12

        # Normal
        if has_normals:
            elements.append((1, 2, 0, 0))
            stride += 12

        # Tangent + Binormal (only if both available)
        if has_tangents and has_bitangents:
            elements.append((2, 2, 0, 0))  # TANGENT
            stride += 12
            elements.append((3, 2, 0, 0))  # BINORMAL
            stride += 12

        # UV
        if has_uv:
            elements.append((4, 1, 0, 0))  # UV_COORDS, 2 components
            stride += 8

        # Build interleaved vertex buffer
        vb = bytearray()
        for i in range(vertex_count):
            b = i * 3
            # Position
            vb += struct.pack('<fff', raw_verts[b], raw_verts[b+1], raw_verts[b+2])
            # Normal
            if has_normals:
                vb += struct.pack('<fff', raw_normals[b], raw_normals[b+1], raw_normals[b+2])
            # Tangent + Binormal
            if has_tangents and has_bitangents:
                vb += struct.pack('<fff', raw_tangents[b], raw_tangents[b+1], raw_tangents[b+2])
                vb += struct.pack('<fff', raw_bitangents[b], raw_bitangents[b+1], raw_bitangents[b+2])
            # UV (flip V for Stingray - origin at top-left)
            if has_uv:
                vb += struct.pack('<ff', raw_uvs[b], 1.0 - raw_uvs[b+1])

        # vertex_buffer_size + data
        out += struct.pack('<I', len(vb))
        out += bytes(vb)

        # 8 bytes padding
        out += b'\x00' * 8

        # Mesh metadata
        out += struct.pack('<III', vertex_count, stride, len(elements))

        # Element descriptors
        for etype, esize, elayer, efmt in elements:
            out += struct.pack('<IIII', etype, esize, elayer, efmt)
            out += struct.pack('<B', 0)  # end marker

        # 12 bytes padding
        out += b'\x00' * 12

        # Index buffer - assimp-py gives flat list [i0,i1,i2, i0,i1,i2,...]
        raw_indices = mesh.indices
        index_count = len(raw_indices)
        max_idx = max(raw_indices) if raw_indices else 0
        if max_idx > 65535:
            print(f"  WARNING: Mesh {mesh_idx} has >65535 vertices, clamping indices")
            raw_indices = [min(idx, 65535) for idx in raw_indices]

        index_buf = struct.pack(f'<{index_count}H', *raw_indices)

        out += struct.pack('<II', index_count, len(index_buf))
        out += index_buf

        # Shapes (one shape per mesh covering all triangles)
        out += struct.pack('<I', 1)  # shape_count = 1
        out += struct.pack('<IIII', 0, 0, index_count, 0)

        # Bounding box
        xs = raw_verts[0::3]
        ys = raw_verts[1::3]
        zs = raw_verts[2::3]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        radius = max(max_x - min_x, max_y - min_y, max_z - min_z) / 2.0
        out += struct.pack('<fffffff', min_x, min_y, min_z, max_x, max_y, max_z, radius)

        # Material name
        mat_name = f"m_{Path(fbx_path).stem}"
        mat_bytes = mat_name.encode('utf-8')
        out += struct.pack('<I', 1)  # material_count = 1
        out += struct.pack('<I', len(mat_bytes))
        out += mat_bytes

    return bytes(out)


def extract_unit_material_names(unit_data: bytes) -> List[str]:
    """Extract material names embedded in a compiled .unit payload."""
    if len(unit_data) < 8:
        return []

    try:
        _sig, mesh_count = struct.unpack_from('<II', unit_data, 0)
    except struct.error:
        return []

    # Defensive cap for malformed payloads.
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
        offset += 8  # mesh padding

        _vertex_count, _vertex_stride, element_count = struct.unpack_from('<III', unit_data, offset)
        offset += 12

        # Each element descriptor is 16 bytes + 1 byte marker.
        for _ in range(element_count):
            if offset + 17 > len(unit_data):
                return names
            offset += 17

        if offset + 12 > len(unit_data):
            return names
        offset += 12  # padding before index data

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
        offset += 28  # bounding box

        if offset + 4 > len(unit_data):
            return names
        material_count = struct.unpack_from('<I', unit_data, offset)[0]
        offset += 4

        for _ in range(material_count):
            if offset + 4 > len(unit_data):
                return names
            name_len = struct.unpack_from('<I', unit_data, offset)[0]
            offset += 4
            if name_len < 0 or offset + name_len > len(unit_data):
                return names
            raw_name = unit_data[offset:offset + name_len]
            offset += name_len

            mat_name = raw_name.decode('utf-8', errors='replace').rstrip('\x00')
            if mat_name:
                names.append(mat_name)

    # Preserve order while removing duplicates.
    deduped: List[str] = []
    seen = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def dependency_ref_from_name_hash(name_hash: int) -> int:
    """Convert a 64-bit resource hash into the 32-bit dependency ref format."""
    return (name_hash >> 32) & 0xFFFFFFFF


# ============================================================================
# Package Resource Builder
# ============================================================================

def build_package_data(entries: List[PackageEntry]) -> bytes:
    """Build package resource binary from package entries.

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
    (See FINDINGS.txt Section 9B.1 for byte-level confirmation.)
    """
    data = struct.pack('<I', len(entries))
    for entry in entries:
        name_hi32 = (entry.name_hash >> 32) & 0xFFFFFFFF
        data += struct.pack('<QQIII',
            entry.type_hash,
            entry.name_hash,
            2,           # c1 = ALWAYS 2
            0,           # c2 = 0 (safe for custom)
            name_hi32,   # upper 32 bits of name_hash
        )
    data += NATIVE_PACKAGE_TRAILER_BYTE
    return data


# ============================================================================
# Bundle Builder
# ============================================================================

def build_bundle(resources: List[Resource]) -> bytes:
    """
    Build an unpacked bundle in the 0xF0000004 format.

    CORRECTED FORMAT (verified byte-for-byte against native Gauntlet bundles):
      [0x000]  uint32  N  - resource count
      [0x004]  84-byte PREAMBLE (zeros for custom bundles)
      [0x058]  172-byte PADDING (zeros)
      [0x104]  TOC - (N+1) x 16-byte entries
          entry[N] is a SENTINEL = exact copy of entry[0]
      [toc_end]  RESOURCE-0 - 20-byte header (no type/name), then data
      [after]    RESOURCES 1..N-1 - 36-byte header + data each

    See FINDINGS.txt Section 4 for full byte-level confirmation.
    """
    count = len(resources)
    sorted_res = sorted(resources, key=lambda r: r.name_hash)

    parts = []

    # 1. Resource count
    parts.append(struct.pack('<I', count))

    # 2. 84-byte preamble (zeros for custom bundles)
    parts.append(b'\x00' * 84)

    # 3. 172-byte padding to offset 0x104
    parts.append(b'\x00' * 172)

    # 4. TOC - (N+1) x 16-byte entries with sentinel
    for r in sorted_res:
        parts.append(struct.pack('<QQ', r.type_hash, r.name_hash))
    # Sentinel: entry[N] = exact copy of entry[0]
    parts.append(struct.pack('<QQ', sorted_res[0].type_hash, sorted_res[0].name_hash))

    # 5. Resource-0 - 20-byte header (NO type/name fields) + data
    r0 = sorted_res[0]
    sz0 = len(r0.data)
    parts.append(struct.pack('<IQII',
        1,     # flags
        0,     # zeros (uint64)
        sz0,   # data_sz
        0      # stream_sz
    ))
    parts.append(r0.data)

    # 6. Resources 1..N-1 - 36-byte header + data each
    for r in sorted_res[1:]:
        main_size = len(r.data)
        parts.append(struct.pack('<QQIQII',
                                 r.type_hash, r.name_hash,
                                 1,          # flags
                                 0,          # stream_size
                                 main_size,  # main_size
                                 0))         # unknown
        parts.append(r.data)

    result = b''.join(parts)
    # Align to 4 bytes
    pad = (4 - (len(result) % 4)) % 4
    if pad:
        result += b'\x00' * pad
    return result


def compress_bundle(unpacked: bytes) -> bytes:
    """Compress unpacked data into a zlib-chunked bundle."""
    parts = [struct.pack('<III', BUNDLE_SIG_OLD, len(unpacked), 0)]
    offset = 0
    while offset < len(unpacked):
        chunk = unpacked[offset:offset + ZLIB_CHUNK]
        compressed = zlib.compress(chunk, 6)
        parts.append(struct.pack('<I', len(compressed)))
        parts.append(compressed)
        offset += ZLIB_CHUNK
    return b''.join(parts)


# ============================================================================
# Asset Collection
# ============================================================================

def collect_textures(folder: Path, prefix: str, replace_mode: bool) -> List[TextureInfo]:
    """Scan folder for DDS textures and classify them."""
    textures = []
    dds_files = sorted(set(list(folder.rglob('*.dds')) + list(folder.rglob('*.DDS'))))

    for dds_path in dds_files:
        with open(dds_path, 'rb') as f:
            data = f.read()

        ok, width, height, fmt = parse_dds(data)
        if not ok:
            print(f"  SKIP (invalid DDS): {dds_path.name}")
            continue

        stem = dds_path.stem
        role = detect_texture_role(stem)
        group = get_texture_group(stem)

        # Build resource name
        rel = dds_path.relative_to(folder)
        parts = list(rel.parts)
        parts[-1] = rel.stem  # Drop .dds

        if replace_mode:
            resource_name = '/'.join(parts)
        else:
            resource_name = prefix + '/'.join(parts)

        resource_name = resource_name.replace('\\', '/')
        name_hash = murmur_hash64(resource_name)

        textures.append(TextureInfo(
            path=dds_path, resource_name=resource_name,
            name_hash=name_hash, width=width, height=height,
            fmt=fmt, role=role, group=group, data=data
        ))

        mode_tag = "[REPLACE]" if replace_mode else "[NEW]"
        print(f"  {mode_tag} {dds_path.name} ({width}x{height} {fmt}) [{role}]")
        print(f"           -> {resource_name}  (0x{name_hash:016X})")

    return textures


def collect_fbx(folder: Path, prefix: str) -> List[Tuple[Path, str, int]]:
    """Scan folder for model/unit files. Returns list of (path, resource_name, name_hash)."""
    results = []
    model_files = sorted(set(
        list(folder.rglob('*.fbx')) + list(folder.rglob('*.FBX')) +
        list(folder.rglob('*.obj')) + list(folder.rglob('*.OBJ')) +
        list(folder.rglob('*.gltf')) + list(folder.rglob('*.glb')) +
        list(folder.rglob('*.dae')) + list(folder.rglob('*.DAE')) +
        list(folder.rglob('*.unit')) + list(folder.rglob('*.UNIT'))
    ))

    for fbx_path in model_files:
        rel = fbx_path.relative_to(folder)
        parts = list(rel.parts)
        parts[-1] = rel.stem
        resource_name = prefix + '/'.join(parts)
        resource_name = resource_name.replace('\\', '/')
        name_hash = murmur_hash64(resource_name)

        results.append((fbx_path, resource_name, name_hash))
        print(f"  [MODEL] {fbx_path.name}")
        print(f"           -> {resource_name}  (0x{name_hash:016X})")

    return results


def collect_raw_materials(folder: Path, prefix: str) -> List[Tuple[Path, str, int]]:
    """Scan for pre-built .material binary files."""
    results = []
    for mat_path in sorted(folder.rglob('*.material')):
        rel = mat_path.relative_to(folder)
        parts = list(rel.parts)
        parts[-1] = rel.stem
        resource_name = prefix + '/'.join(parts)
        resource_name = resource_name.replace('\\', '/')
        name_hash = murmur_hash64(resource_name)
        results.append((mat_path, resource_name, name_hash))
        print(f"  [RAW MAT] {mat_path.name} -> {resource_name}")
    return results


def collect_lua(folder: Path, prefix: str) -> List[Tuple[Path, str, int]]:
    """Scan for Lua scripts."""
    results = []
    for lua_path in sorted(folder.rglob('*.lua')):
        rel = lua_path.relative_to(folder)
        parts = list(rel.parts)
        parts[-1] = rel.stem
        resource_name = prefix + '/'.join(parts)
        resource_name = resource_name.replace('\\', '/')
        name_hash = murmur_hash64(resource_name)
        results.append((lua_path, resource_name, name_hash))
        print(f"  [LUA] {lua_path.name} -> {resource_name}")
    return results


# ============================================================================
# Material Auto-Generation
# ============================================================================

def generate_materials(textures: List[TextureInfo], auto_group: bool) -> List[Resource]:
    """
    Auto-generate materials from collected textures.

    If auto_group is True, textures with matching group keys get combined
    into multi-slot materials (diffuse + normal + specular).
    Otherwise, each texture gets its own single-slot material.
    """
    materials = []

    if auto_group:
        # Group textures by their base name
        groups: Dict[str, Dict[str, TextureInfo]] = {}
        for tex in textures:
            key = tex.group
            if key not in groups:
                groups[key] = {}
            groups[key][tex.role] = tex

        for group_key, slots in groups.items():
            mat_name = group_key
            mat_hash = murmur_hash64(mat_name)

            slot_list = []
            slot_idx = 1
            role_order = ['diffuse', 'normal', 'specular', 'emissive']
            role_thinhash = {
                'diffuse':  THINHASH_DIFFUSE,
                'normal':   THINHASH_NORMAL,
                'specular': THINHASH_SPECULAR,
                'emissive': THINHASH_EMISSIVE,
            }
            for role in role_order:
                if role in slots:
                    tex = slots[role]
                    slot_list.append((slot_idx, role_thinhash[role], tex.name_hash))
                    slot_idx += 1

            if slot_list:
                mat_data = build_material_multi(slot_list)
                materials.append(Resource(
                    type_hash=TYPE_MATERIAL, name=mat_name,
                    name_hash=mat_hash, data=mat_data
                ))
                tex_names = [f"{r}={slots[r].path.name}" for r in role_order if r in slots]
                print(f"  [MAT] {mat_name} ({', '.join(tex_names)})")
    else:
        # One material per texture (simple diffuse)
        for tex in textures:
            mat_name = Path(tex.resource_name).stem
            mat_hash = murmur_hash64(mat_name)
            mat_data = build_material_single(tex.name_hash)
            materials.append(Resource(
                type_hash=TYPE_MATERIAL, name=mat_name,
                name_hash=mat_hash, data=mat_data
            ))
            print(f"  [MAT] {mat_name} -> texture 0x{tex.name_hash:016X}")

    return materials


# ============================================================================
# Main Pipeline
# ============================================================================

def make_mod_bundle(input_path: str, mod_name: str = None, output_dir: str = None,
                    replace_mode: bool = False, prefix: str = "custom",
                    no_materials: bool = False, auto_group: bool = False,
                    unit_base_dep: Optional[int] = OBSERVED_NATIVE_UNIT_BASE_DEP) -> bool:
    """
    Main entry point: collect all assets, build bundle, write mod loader output.

    input_path can be a file (e.g. model.fbx) or a folder of assets.
    Output defaults to the same directory as the input.
    mod_name defaults to the file/folder stem.

    Returns True on success.
    """
    raw = Path(input_path).resolve()

    # Handle single-file input: use parent dir as scan folder,
    # but only process that one file type
    single_file = None
    if raw.is_file():
        single_file = raw
        folder = raw.parent
        if mod_name is None:
            mod_name = raw.stem
    elif raw.is_dir():
        folder = raw
        if mod_name is None:
            mod_name = folder.name
    else:
        print(f"ERROR: '{input_path}' does not exist")
        return False

    # Default output: same directory as the input
    if output_dir is None:
        out_root = folder
    else:
        out_root = Path(output_dir).resolve()

    # Package path for Lua loading
    if replace_mode:
        full_package_path = f"resource_packages/replacements/{mod_name}"
        tex_prefix = ""
    else:
        full_package_path = f"resource_packages/{prefix}/{mod_name}"
        tex_prefix = f"{prefix}/{mod_name}/"

    model_prefix = f"{prefix}/{mod_name}/"
    package_hash = murmur_hash64(full_package_path)
    bundle_hex = f"{package_hash:016x}"

    print("=" * 72)
    print(f"Gauntlet Mod Bundle Maker")
    print("=" * 72)
    if single_file:
        print(f"  Input file   : {single_file}")
    else:
        print(f"  Input folder : {folder}")
    print(f"  Mod name     : {mod_name}")
    print(f"  Package path : {full_package_path}")
    print(f"  Bundle hash  : {bundle_hex}")
    print(f"  Output       : {out_root}")
    print(f"  Mode         : {'REPLACEMENT' if replace_mode else 'NEW CONTENT'}")
    if unit_base_dep is None:
        print("  Unit base dep: disabled")
    else:
        print(f"  Unit base dep: 0x{(unit_base_dep & 0xFFFFFFFF):08X}")
    print()

    all_resources: List[Resource] = []
    unit_material_refs: Dict[int, List[str]] = {}

    # When a single file is given, only process that file type
    process_textures = single_file is None or single_file.suffix.lower() in ('.dds',)
    process_models   = single_file is None or single_file.suffix.lower() in ('.fbx', '.obj', '.gltf', '.glb', '.dae', '.unit')
    process_mats     = single_file is None
    process_lua      = single_file is None or single_file.suffix.lower() == '.lua'

    # For single-file input, create a temp folder-like view
    if single_file:
        scan_folder = single_file.parent
    else:
        scan_folder = folder

    # -- Collect textures ---------------------------------------------
    if process_textures:
        print("-- Textures --")
        textures = collect_textures(scan_folder, tex_prefix, replace_mode)
        if single_file and single_file.suffix.lower() == '.dds':
            # Keep only the single file we were asked about
            textures = [t for t in textures if t.path.resolve() == single_file]
        for tex in textures:
            all_resources.append(Resource(TYPE_TEXTURE, tex.resource_name, tex.name_hash, tex.data))
        if not textures:
            print("  (none found)")
        print()
    else:
        textures = []

    # -- Auto-generate materials --------------------------------------
    if textures and not no_materials:
        print("-- Auto-Generated Materials --")
        gen_mats = generate_materials(textures, auto_group)
        for mat in gen_mats:
            all_resources.append(mat)
        if not gen_mats:
            print("  (none generated)")
        print()

    # -- Collect pre-built materials ----------------------------------
    if process_mats:
        raw_mats = collect_raw_materials(scan_folder, model_prefix)
        if raw_mats:
            print("-- Pre-built Materials --")
            for mat_path, rname, rhash in raw_mats:
                with open(mat_path, 'rb') as f:
                    mat_data = f.read()
                all_resources.append(Resource(TYPE_MATERIAL, rname, rhash, mat_data))
            print()

    # -- Collect and process model/unit files -------------------------
    if process_models:
        if single_file and single_file.suffix.lower() in ('.fbx', '.obj', '.gltf', '.glb', '.dae', '.unit'):
            model_infos = [(single_file, model_prefix + single_file.stem,
                            murmur_hash64(model_prefix + single_file.stem))]
            print(f"  [MODEL] {single_file.name}")
            print(f"           -> {model_infos[0][1]}  (0x{model_infos[0][2]:016X})")
        else:
            model_infos = collect_fbx(scan_folder, model_prefix)
        if model_infos:
            print()
            print("-- Building Unit Resources --")
            for fbx_path, rname, rhash in model_infos:
                suffix = Path(fbx_path).suffix.lower()
                if suffix == '.unit':
                    with open(fbx_path, 'rb') as f:
                        unit_data = f.read()
                else:
                    unit_data = fbx_to_unit(str(fbx_path))
                if unit_data is not None:
                    all_resources.append(Resource(TYPE_UNIT, rname, rhash, unit_data))
                    unit_material_refs[rhash] = extract_unit_material_names(unit_data)
                    print(f"  OK: {fbx_path.name if isinstance(fbx_path, Path) else Path(fbx_path).name} -> {len(unit_data):,} bytes")
                else:
                    print(f"  FAILED: {fbx_path.name if isinstance(fbx_path, Path) else Path(fbx_path).name}")
            print()

    # -- Collect Lua scripts ------------------------------------------
    if process_lua:
        if single_file and single_file.suffix.lower() == '.lua':
            rname = model_prefix + single_file.stem
            rhash = murmur_hash64(rname)
            lua_files = [(single_file, rname, rhash)]
        else:
            lua_files = collect_lua(scan_folder, model_prefix)
        if lua_files:
            print("-- Lua Scripts --")
            for lua_path, rname, rhash in lua_files:
                with open(lua_path, 'rb') as f:
                    lua_data = f.read()
                all_resources.append(Resource(TYPE_LUA, rname, rhash, lua_data))
            print()

    # -- Ensure unit material references exist as resources ----------
    if unit_material_refs:
        existing_material_hashes = {
            r.name_hash for r in all_resources if r.type_hash == TYPE_MATERIAL
        }
        fallback_texture_hash = next(
            (r.name_hash for r in all_resources if r.type_hash == TYPE_TEXTURE),
            0,
        )

        print("-- Unit Material Resolution --")
        created_materials = 0

        for material_names in unit_material_refs.values():
            for mat_name in material_names:
                mat_hash = murmur_hash64(mat_name)
                if mat_hash in existing_material_hashes:
                    continue

                mat_data = build_material_single(fallback_texture_hash)
                all_resources.append(Resource(TYPE_MATERIAL, mat_name, mat_hash, mat_data))
                existing_material_hashes.add(mat_hash)
                created_materials += 1

                if fallback_texture_hash:
                    print(f"  [AUTO MAT] {mat_name} -> 0x{fallback_texture_hash:016X}")
                else:
                    print(f"  [AUTO MAT] {mat_name} -> 0x0000000000000000 (placeholder)")

        if created_materials == 0:
            print("  All unit material references already resolved.")
        print()

    # -- Validation ---------------------------------------------------
    if not all_resources:
        print("ERROR: No valid assets found in the input folder.")
        print("       Supported: .dds (textures), .fbx/.obj/.unit (models),")
        print("                  .material (materials), .lua (scripts)")
        return False

    # -- Build package entries with dependencies ---------------------
    package_entries: List[PackageEntry] = []
    for res in all_resources:
        deps: List[int] = []

        if res.type_hash == TYPE_UNIT:
            unit_deps: List[int] = []
            if unit_base_dep is not None:
                unit_deps.append(unit_base_dep & 0xFFFFFFFF)

            for mat_name in unit_material_refs.get(res.name_hash, []):
                mat_hash = murmur_hash64(mat_name)
                unit_deps.append(dependency_ref_from_name_hash(mat_hash))

            # Keep insertion order while removing duplicates.
            seen = set()
            for dep in unit_deps:
                if dep not in seen:
                    seen.add(dep)
                    deps.append(dep)

        package_entries.append(PackageEntry(res.type_hash, res.name_hash, deps))

    # -- Build package resource ---------------------------------------
    pkg_data = build_package_data(package_entries)
    pkg_resource = Resource(TYPE_PACKAGE, full_package_path, package_hash, pkg_data)
    all_resources.insert(0, pkg_resource)

    # -- Build and compress bundle ------------------------------------
    print("-- Building Bundle --")
    unpacked = build_bundle(all_resources)
    packed = compress_bundle(unpacked)
    ratio = (1 - len(packed) / len(unpacked)) * 100 if len(unpacked) > 0 else 0

    res_counts = {}
    for r in all_resources:
        tname = {TYPE_TEXTURE: 'texture', TYPE_MATERIAL: 'material', TYPE_UNIT: 'unit',
                 TYPE_PACKAGE: 'package', TYPE_LUA: 'lua'}.get(r.type_hash, 'other')
        res_counts[tname] = res_counts.get(tname, 0) + 1

    print(f"  Resources: {len(all_resources)} total")
    for tname, cnt in sorted(res_counts.items()):
        print(f"    {tname}: {cnt}")
    print(f"  Unpacked : {len(unpacked):,} bytes")
    print(f"  Packed   : {len(packed):,} bytes ({ratio:.1f}% reduction)")
    print()

    # -- Write output (mod loader layout) -----------------------------
    mod_dir = out_root / mod_name
    mod_dir.mkdir(parents=True, exist_ok=True)

    # Bundle file
    bundle_path = mod_dir / bundle_hex
    with open(bundle_path, 'wb') as f:
        f.write(packed)

    # Empty .stream file (engine expects it)
    stream_path = mod_dir / f"{bundle_hex}.stream"
    if not stream_path.exists():
        stream_path.touch()

    # bundle.ini for the mod loader
    ini_path = mod_dir / "bundle.ini"
    ini_content = (
        "[Bundle]\n"
        f"PackagePath={full_package_path}\n"
        f"ResourceCount={len(all_resources)}\n"
        f"HasStream=false\n"
    )
    with open(ini_path, 'w') as f:
        f.write(ini_content)

    # manifest.json
    manifest = {
        "mod_name": mod_name,
        "package_path": full_package_path,
        "bundle_hash": bundle_hex,
        "resource_count": len(all_resources),
        "package_entries": [],
        "resources": {},
        "lua_load_code": f'Game:load_package("{full_package_path}", true)',
    }
    for entry in package_entries:
        tname = {TYPE_TEXTURE: 'texture', TYPE_MATERIAL: 'material', TYPE_UNIT: 'unit',
                 TYPE_PACKAGE: 'package', TYPE_LUA: 'lua'}.get(entry.type_hash, 'other')
        manifest["package_entries"].append({
            "type": tname,
            "type_hash": f"0x{entry.type_hash:016X}",
            "name_hash": f"0x{entry.name_hash:016X}",
            "dependency_count": len(entry.dependencies),
            "dependencies": [f"0x{dep:08X}" for dep in entry.dependencies],
        })

    for r in all_resources:
        tname = {TYPE_TEXTURE: 'texture', TYPE_MATERIAL: 'material', TYPE_UNIT: 'unit',
                 TYPE_PACKAGE: 'package', TYPE_LUA: 'lua'}.get(r.type_hash, 'other')
        manifest["resources"][r.name] = {
            "type": tname,
            "hash": f"0x{r.name_hash:016X}",
            "size": len(r.data),
        }

    manifest_path = mod_dir / "manifest.json"
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    # -- Done ---------------------------------------------------------
    print("-- Output --")
    print(f"  {mod_dir}/")
    print(f"    bundle.ini         (mod loader manifest)")
    print(f"    {bundle_hex}  (bundle)")
    print(f"    {bundle_hex}.stream")
    print(f"    manifest.json      (human-readable listing)")
    print()
    print("-- Installation --")
    print(f"  Copy the '{mod_name}/' folder to your game's mods/bundles/ directory:")
    print(f"    Gauntlet/mods/bundles/{mod_name}/")
    print()
    print(f"  The mod loader (dinput8.dll) will automatically:")
    print(f"    1. Register the bundle in bundle_database.data")
    print(f"    2. Copy it to contents/")
    print(f"    3. Load it via Game:load_package()")
    print()
    print(f"  Manual Lua loading:")
    print(f'    Game:load_package("{full_package_path}", true)')
    print()

    return True


# ============================================================================
# Hash Utility
# ============================================================================

def cmd_hash(args):
    """Compute MurmurHash64 of a string."""
    for s in args.strings:
        h = murmur_hash64(s)
        print(f"  \"{s}\" -> 0x{h:016X}  ({h})")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Gauntlet Mod Bundle Maker - creates bundles for the mod loader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s /path/to/model.fbx
  %(prog)s my_textures/
  %(prog)s my_textures/ WarriorReskin
  %(prog)s my_textures/ WarriorReskin --replace
  %(prog)s assets/ CoolMod --auto-group -o output/
  %(prog)s hash "characters/avatar_warrior/warrior_diff"
        """
    )

    sub = parser.add_subparsers(dest='command')

    # -- build (default) --
    build_p = sub.add_parser('build', help='Build a mod bundle from a file or folder')
    build_p.add_argument('path', help='Input file (.fbx, .dds, etc.) or folder of assets')
    build_p.add_argument('name', nargs='?', default=None,
                         help='Mod name (default: derived from input file/folder name)')
    build_p.add_argument('-o', '--output', default=None,
                         help='Output directory (default: same directory as input)')
    build_p.add_argument('--replace', action='store_true',
                         help='Replacement mode: texture paths match originals for hash collision')
    build_p.add_argument('--prefix', default='custom',
                         help='Resource path prefix (default: "custom")')
    build_p.add_argument('--no-materials', action='store_true',
                         help='Skip auto-generating materials for textures')
    build_p.add_argument('--auto-group', action='store_true',
                         help='Group textures by base name into multi-slot materials '
                              '(diffuse + normal + specular)')
    build_p.add_argument('--no-unit-base-dep', action='store_true',
                         help='Disable the default native-style base dependency ref for unit package entries')
    build_p.add_argument('--unit-base-dep', default=None,
                         help='Override unit base dependency ref (32-bit, e.g. 0x6B1FEA56)')

    # -- hash --
    hash_p = sub.add_parser('hash', help='Compute MurmurHash64 of string(s)')
    hash_p.add_argument('strings', nargs='+', help='Strings to hash')

    # Pre-check: if the first arg isn't a known subcommand, inject 'build'
    argv = sys.argv[1:]
    known_commands = {'build', 'hash', '-h', '--help'}
    if argv and argv[0] not in known_commands:
        argv = ['build'] + argv

    args = parser.parse_args(argv)

    if args.command == 'hash':
        cmd_hash(args)
    elif args.command == 'build':
        if args.no_unit_base_dep:
            unit_base_dep = None
        elif args.unit_base_dep is not None:
            try:
                unit_base_dep = int(args.unit_base_dep, 0) & 0xFFFFFFFF
            except ValueError:
                print(f"ERROR: invalid --unit-base-dep value '{args.unit_base_dep}'")
                sys.exit(2)
        else:
            unit_base_dep = OBSERVED_NATIVE_UNIT_BASE_DEP

        success = make_mod_bundle(
            args.path, mod_name=args.name,
            output_dir=args.output,
            replace_mode=args.replace,
            prefix=args.prefix,
            no_materials=args.no_materials,
            auto_group=args.auto_group,
            unit_base_dep=unit_base_dep,
        )
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
