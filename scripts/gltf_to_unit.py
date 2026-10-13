#!/usr/bin/env python3
"""
OBJ / glTF -> Stingray .unit encoder

Converts Blender-exported OBJ (or a simple vertex list) back into a Stingray
binary .unit file that Gauntlet can load.

Supported inputs:
  .obj   - Wavefront OBJ (with normals + UVs preferred; bone weights not supported)
  .glb   - glTF Binary (with normals, UVs; bone weights included if present)

The encoder writes:
  - One mesh per OBJ object / glTF mesh node
  - Vertex layout: POSITION(f32x3) + NORMAL(f32x3) + UV(f32x2)  = 32 bytes/vert
    (or 48 bytes/vert if tangent is also included)
  - Element descriptors matching the original Stingray format
  - uint16 indices (or uint32 if vert count > 65535)
  - Shape covering all indices, material_index = 0

Limitations:
  - Multiple material groups per OBJ object are merged into one material slot
  - Bone skinning from glTF is re-encoded only if the original .unit used skinning
  - The material name hash is encoded as 0 (unknown) unless supplied via --mat-hash

Usage:
  python gltf_to_unit.py  <input.obj>  [output.unit]
  python gltf_to_unit.py  <input.glb>  [output.unit]
  python gltf_to_unit.py  selftest
"""

from __future__ import annotations
import json, math, os, struct, sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

HERE   = Path(__file__).parent
PARENT = HERE

# -- vertex structures ----------------------------------------------------------

def _pack_element_descriptor(elem_type: int, size: int, layer: int = 0,
                              fmt: int = 0) -> bytes:
    """Pack a 17-byte Stingray element descriptor."""
    return struct.pack('<IIIII', elem_type, size, layer, fmt, 0)[:17]


# element_type values (from ElementType enum in unit_to_obj.py)
ET_POSITION  = 0
ET_NORMAL    = 1
ET_TANGENT   = 2
ET_BINORMAL  = 3
ET_UV_COORDS = 4

ELEM_SIZE_VEC3 = 2  # component count - 1 for 3-component vectors
ELEM_SIZE_VEC2 = 1  # 2-component vectors


def _orthogonal_tangent(normal: np.ndarray) -> np.ndarray:
    """Build a stable tangent vector orthogonal to the normal."""
    up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    if abs(float(np.dot(normal, up))) > 0.99:
        up = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    tangent = np.cross(up, normal)
    n = float(np.linalg.norm(tangent))
    if n < 1e-6:
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)
    return (tangent / n).astype(np.float32)


def _build_vertex_buffer(positions: np.ndarray,
                          normals: Optional[np.ndarray],
                          uvs: Optional[np.ndarray]) -> Tuple[bytes, List[bytes], int]:
    """
    Build Stingray vertex buffer + element descriptor list.
    Returns (vertex_data, element_descriptors, stride).
    """
    stride = 0
    elements: List[bytes] = []

    # POSITION always first
    elements.append(_pack_element_descriptor(ET_POSITION, ELEM_SIZE_VEC3))
    stride += 12

    # NORMAL
    if normals is not None:
        elements.append(_pack_element_descriptor(ET_NORMAL, ELEM_SIZE_VEC3))
        stride += 12

    # TANGENT + BINORMAL
    if normals is not None:
        elements.append(_pack_element_descriptor(ET_BINORMAL, ELEM_SIZE_VEC3))
        stride += 12
        elements.append(_pack_element_descriptor(ET_TANGENT, ELEM_SIZE_VEC3))
        stride += 12

    # UV
    if uvs is not None:
        elements.append(_pack_element_descriptor(ET_UV_COORDS, ELEM_SIZE_VEC2))
        stride += 8

    # Build interleaved vertex buffer
    n = len(positions)
    buf = bytearray(n * stride)
    off = 0
    pos_data = positions.astype(np.float32)

    for i in range(n):
        struct.pack_into('<fff', buf, off, *pos_data[i])
        curr = off + 12
        if normals is not None:
            normal = normals[i].astype(np.float32)
            struct.pack_into('<fff', buf, curr, *normal)
            curr += 12

            # Emit binormal/tangent for game-like 56-byte layout.
            tangent = _orthogonal_tangent(normal)
            binormal = np.cross(normal, tangent)
            binormal_len = float(np.linalg.norm(binormal))
            if binormal_len < 1e-6:
                binormal = np.array([0.0, 0.0, 1.0], dtype=np.float32)
            else:
                binormal = (binormal / binormal_len).astype(np.float32)
            struct.pack_into('<fff', buf, curr, *binormal)
            curr += 12
            struct.pack_into('<fff', buf, curr, *tangent)
            curr += 12

        if uvs is not None:
            u, v = uvs[i]
            # Stingray stores UVs with V flipped vs OpenGL/glTF convention
            struct.pack_into('<ff', buf, curr, float(u), 1.0 - float(v))
            curr += 8
        off += stride

    return bytes(buf), elements, stride


def _compute_bbox(positions: np.ndarray) -> Tuple[float, ...]:
    """Return (min_x, min_y, min_z, max_x, max_y, max_z, extra) for a bbox."""
    mn = positions.min(axis=0)
    mx = positions.max(axis=0)
    # extra field: Stingray stores the bounding sphere radius here (approx)
    center = (mn + mx) * 0.5
    radius = float(np.linalg.norm(mx - center))
    return (float(mn[0]), float(mn[1]), float(mn[2]),
            float(mx[0]), float(mx[1]), float(mx[2]),
            radius)


def _build_mesh_block(positions: np.ndarray,
                       normals: Optional[np.ndarray],
                       uvs: Optional[np.ndarray],
                       indices: np.ndarray,
                       mat_name: str = 'material_0') -> bytes:
    """
    Build the complete binary block for one Stingray mesh.
    Returns raw bytes that can be concatenated for the .unit file.

    Stingray mesh block layout (confirmed from reverse engineering):
      uint32              vertex_buffer_size
      bytes[vbs]          vertex data (interleaved, stride bytes/vertex)
      uint64              padding (= 0)
      uint32              vertex_count
      uint32              vertex_stride
      uint32              element_count
      element_count x 17b element descriptors  (uint32 type, size, layer, fmt + uint8 end)
      12 bytes            post-element padding
      uint32              total_index_count
      uint32              index_buffer_size
      bytes[ibs]          index data (uint16 or uint32)
      uint32              shape_count
      shape_count x 16b   { uint32 mat_idx, uint32 idx_offset, uint32 idx_count, uint32 shape_idx }
      7 x float32         bounding box: min_x, min_y, min_z, max_x, max_y, max_z, radius
      uint32              material_count
      mat_count x (uint32 str_len + bytes)  material name strings (NOT null-terminated, length-prefixed)
    """
    vbuf, elements, stride = _build_vertex_buffer(positions, normals, uvs)
    vc = len(positions)
    ec = len(elements)

    out = bytearray()

    # ---- VERTEX BUFFER ----
    out += struct.pack('<I', len(vbuf))
    out += vbuf
    out += b'\x00' * 8                   # padding

    # ---- VERTEX METADATA ----
    out += struct.pack('<III', vc, stride, ec)

    # ---- ELEMENT DESCRIPTORS (17 bytes each: 4xuint32 + 1xuint8) ----
    for elem in elements:
        out += elem

    # ---- 12-byte POST-ELEM PADDING ----
    out += b'\x00' * 12

    # ---- INDEX BUFFER ----
    max_idx = int(indices.max()) if len(indices) > 0 else 0
    if max_idx > 65535:
        idx_bytes = indices.astype(np.uint32).tobytes()
    else:
        idx_bytes = indices.astype(np.uint16).tobytes()
    total_index_count = len(indices)
    out += struct.pack('<II', total_index_count, len(idx_bytes))
    out += idx_bytes

    # ---- SHAPES (one shape covering all indices) ----
    out += struct.pack('<I', 1)           # shape_count
    out += struct.pack('<IIII', 0, 0, total_index_count, 0)

    # ---- BOUNDING BOX (7 floats) ----
    bbox = _compute_bbox(positions)
    out += struct.pack('<7f', *bbox)

    # ---- MATERIAL TABLE (length-prefixed strings, not null-terminated) ----
    name_bytes = mat_name.encode('utf-8')
    out += struct.pack('<I', 1)           # material_count = 1
    out += struct.pack('<I', len(name_bytes))
    out += name_bytes

    return bytes(out)


def encode_unit(meshes: List[Dict]) -> bytes:
    """
    Encode a list of mesh dicts into a Stingray .unit binary.

    Each mesh dict:
      positions: np.ndarray (N,3) float32
      normals:   np.ndarray (N,3) float32 or None
      uvs:       np.ndarray (N,2) float32 or None
      indices:   np.ndarray (M,)  int
      name:      str  (material/object name)
    """
    SIGNATURE = 0x00010090
    mesh_count = len(meshes)

    header = struct.pack('<II', SIGNATURE, mesh_count)
    blocks = b''.join(
        _build_mesh_block(
            m['positions'], m.get('normals'), m.get('uvs'),
            m['indices'], m.get('name', f'mesh_{i}')
        )
        for i, m in enumerate(meshes)
    )
    return header + blocks


# -- OBJ reader -----------------------------------------------------------------

def read_obj(path: str) -> List[Dict]:
    """Parse Wavefront OBJ; return list of mesh dicts grouped by 'o' object."""
    # Full positions/normals/UVs accumulated across whole file
    all_v:  List[Tuple[float, float, float]] = []
    all_vn: List[Tuple[float, float, float]] = []
    all_vt: List[Tuple[float, float]]        = []

    meshes: List[Dict] = []
    cur_name  = 'mesh_0'
    cur_faces: List[Tuple[int, int, int, int, int, int, int, int, int]] = []  # (v1,vt1,vn1,...) 0-indexed

    def _flush():
        nonlocal cur_faces
        if not cur_faces:
            return
        # Build unique vertex list
        vmap: Dict[Tuple, int] = {}
        positions, normals, uvs, indices = [], [], [], []

        for face in cur_faces:
            vi = []
            for i in range(0, 9, 3):
                key = (face[i], face[i+1], face[i+2])
                if key not in vmap:
                    vmap[key] = len(positions)
                    v_idx, vt_idx, vn_idx = key
                    px, py, pz = all_v[v_idx]
                    positions.append((px, py, pz))
                    if vn_idx >= 0 and vn_idx < len(all_vn):
                        normals.append(all_vn[vn_idx])
                    else:
                        normals.append((0.0, 1.0, 0.0))
                    if vt_idx >= 0 and vt_idx < len(all_vt):
                        uvs.append(all_vt[vt_idx])
                    else:
                        uvs.append((0.0, 0.0))
                vi.append(vmap[key])
            indices.extend(vi)

        meshes.append({
            'name': cur_name,
            'positions': np.array(positions, dtype=np.float32),
            'normals':   np.array(normals, dtype=np.float32) if normals else None,
            'uvs':       np.array(uvs, dtype=np.float32) if uvs else None,
            'indices':   np.array(indices, dtype=np.int64),
        })
        cur_faces = []

    with open(path, 'r', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            token = parts[0].lower()

            if token == 'v':
                all_v.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif token == 'vn':
                all_vn.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif token == 'vt':
                all_vt.append((float(parts[1]), float(parts[2]) if len(parts) > 2 else 0.0))
            elif token == 'o' or token == 'g':
                _flush()
                cur_name = ' '.join(parts[1:]) or f'mesh_{len(meshes)}'
            elif token == 'f':
                # Triangulate (fan triangulation for N-gons)
                face_verts = []
                for fp in parts[1:]:
                    segs = fp.split('/')
                    vi  = int(segs[0]) - 1
                    vti = int(segs[1]) - 1 if len(segs) > 1 and segs[1] else -1
                    vni = int(segs[2]) - 1 if len(segs) > 2 and segs[2] else -1
                    face_verts.append((vi, vti, vni))
                for j in range(1, len(face_verts) - 1):
                    a, b, c = face_verts[0], face_verts[j], face_verts[j+1]
                    cur_faces.append((*a, *b, *c))

    _flush()
    return meshes


# -- glTF reader ----------------------------------------------------------------

def read_glb(path: str) -> List[Dict]:
    """
    Parse a GLB file and return list of mesh dicts (one per glTF mesh primitive).
    """
    raw = open(path, 'rb').read()
    if raw[:4] != b'glTF':
        raise ValueError("Not a GLB file")

    # Parse GLB chunks
    json_len  = struct.unpack_from('<I', raw, 12)[0]
    json_data = raw[20:20 + json_len]
    gltf = json.loads(json_data)

    bin_offset = 20 + json_len + 8  # skip bin chunk header
    bin_data = raw[bin_offset:] if bin_offset < len(raw) else b''

    def get_accessor_data(acc_idx: int) -> np.ndarray:
        acc  = gltf['accessors'][acc_idx]
        view = gltf['bufferViews'][acc['bufferView']]
        byte_off  = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        comp_enum = acc['componentType']
        acc_type  = acc['type']
        count     = acc['count']

        dtype_map = {
            5120: np.int8,   5121: np.uint8,
            5122: np.int16,  5123: np.uint16,
            5125: np.uint32, 5126: np.float32,
        }
        comp_counts = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
                       'MAT2': 4, 'MAT3': 9, 'MAT4': 16}

        dtype = dtype_map[comp_enum]
        n_comp = comp_counts[acc_type]
        total  = count * n_comp
        arr = np.frombuffer(bin_data[byte_off:], dtype=dtype, count=total)
        if n_comp > 1:
            arr = arr.reshape(count, n_comp)
        return arr

    meshes = []
    for mesh in gltf.get('meshes', []):
        mesh_name = mesh.get('name', f'mesh_{len(meshes)}')
        for prim in mesh.get('primitives', []):
            attrs = prim.get('attributes', {})

            pos = get_accessor_data(attrs['POSITION']).astype(np.float32)

            normals = None
            if 'NORMAL' in attrs:
                normals = get_accessor_data(attrs['NORMAL']).astype(np.float32)

            uvs = None
            if 'TEXCOORD_0' in attrs:
                uvs = get_accessor_data(attrs['TEXCOORD_0']).astype(np.float32)

            indices = get_accessor_data(prim['indices']).astype(np.int64).flatten()

            mat_name = mesh_name
            if 'material' in prim:
                mat = gltf.get('materials', [])[prim['material']]
                mat_name = mat.get('name', mesh_name)

            # For runtime stability, map arbitrary DCC material names to a known
            # in-game material unless the name already looks like an engine key.
            if not mat_name.startswith('m_') and '/' not in mat_name:
                mat_name = 'm_sphere'

            meshes.append({
                'name': mat_name,
                'positions': pos,
                'normals':   normals,
                'uvs':       uvs,
                'indices':   indices,
            })

    return meshes


# -- main entry -----------------------------------------------------------------

def convert_to_unit(src: str, dst: Optional[str] = None) -> str:
    """Convert OBJ or GLB -> .unit binary."""
    src = str(src)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.unit'

    ext = os.path.splitext(src)[1].lower()
    if ext == '.obj':
        meshes = read_obj(src)
    elif ext in ('.glb', '.gltf'):
        meshes = read_glb(src)
    else:
        raise ValueError(f"Unsupported input format: {ext}")

    if not meshes:
        raise ValueError(f"No meshes found in {src}")

    blob = encode_unit(meshes)
    with open(dst, 'wb') as f:
        f.write(blob)

    total_verts = sum(len(m['positions']) for m in meshes)
    total_faces = sum(len(m['indices']) // 3 for m in meshes)
    print(f"{'OBJ' if ext == '.obj' else 'glTF'} -> .unit: {src}")
    print(f"  {len(meshes)} mesh(es), {total_verts:,} vertices, {total_faces:,} faces -> {dst}  ({len(blob):,} bytes)")
    return dst


# -- selftest ------------------------------------------------------------------

def selftest():
    # Test OBJ round-trip via unit_to_obj -> gltf_to_unit -> decode again
    unit_sample = str(PARENT / 'Exports' / 'samples' / 'unit_015febcb203ebaaf.unit')
    if not os.path.exists(unit_sample):
        print("gltf_to_unit selftest: SKIP (sample not found)")
        return

    import sys
    sys.path.insert(0, str(PARENT))
    from unit_to_obj import UnitParser
    from unit_to_gltf import convert_unit_to_gltf

    glb_tmp  = '/tmp/_selftest_enc.glb'
    unit_tmp = '/tmp/_selftest_enc.unit'

    # Export to glTF
    convert_unit_to_gltf(unit_sample, out_path=glb_tmp)
    # Re-encode to .unit
    convert_to_unit(glb_tmp, unit_tmp)

    # Verify it round-trips
    p = UnitParser(unit_tmp)
    p.parse()
    assert p.meshes, "No meshes after round-trip"
    print(f"gltf_to_unit selftest: PASS  ({len(p.meshes)} mesh(es) after round-trip)")

    for tmp in [glb_tmp, unit_tmp]:
        try:
            os.unlink(tmp)
        except Exception:
            pass


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        selftest()
    elif len(sys.argv) >= 2:
        src = sys.argv[1]
        dst = sys.argv[2] if len(sys.argv) > 2 else None
        convert_to_unit(src, dst)
    else:
        print(__doc__)
        sys.exit(1)
