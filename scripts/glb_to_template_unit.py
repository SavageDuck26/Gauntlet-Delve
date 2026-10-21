#!/usr/bin/env python3
from __future__ import annotations

import math
import numpy as np
import struct
import sys
from pathlib import Path

# Reuse the existing GLB parser/encoder used by the current toolchain.
sys.path.insert(0, str(Path(__file__).parent))
from gltf_to_unit import encode_unit, read_glb  # type: ignore


DEFAULT_MATERIAL_NAME = 'm_ham'

# Every .unit body starts with this signature and then the MESH COUNT.  The count is not
# decoration: a native unit's trailing sections (collision actors, flow data, the 32-byte footer
# whose material hash is the binding) are serialized FOR ITS OWN MESH LIST, so the trailer can
# only be reused by a body that declares the same number of mesh blocks.  Splicing a 1-mesh body
# into a template that has 2 or more meshes makes the loader build a mesh list whose size is
# non-zero while its array stays NULL - and the next pass dereferences it (FINDINGS 9H.31:
# `access read at 00000008`, RVA 0x00270259).
UNIT_SIGNATURE = 0x00010090


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


def splice_into_template(generated: bytes, template: bytes,
                         allow_duplicate: bool = True) -> tuple[bytes, int, int]:
    """Bolt a generated mesh section onto a native template's trailer, mesh counts kept equal.

    Returns (unit_bytes, template_mesh_count, mesh_blocks_written).  The generated body's single
    mesh block is replicated to the template's mesh count when they differ, because a mesh block
    is self-contained (its own vertex/element/index/shape/material tables), so N identical copies
    parse exactly like one - and they are what the trailer was serialized against.
    """
    if read_u32(generated, 0) != UNIT_SIGNATURE:
        raise ValueError('generated body is not a unit')
    if read_u32(template, 0) != UNIT_SIGNATURE:
        raise ValueError('template is not a unit')

    tpl_meshes = read_u32(template, 4)
    if not 1 <= tpl_meshes <= 64:
        raise ValueError('template declares an implausible mesh count: %d' % tpl_meshes)

    trailer = template[unit_mesh_end(template):]
    if not trailer:
        raise ValueError('template has no trailer to preserve')

    gen_meshes = read_u32(generated, 4)
    gen_end = unit_mesh_end(generated)

    if gen_meshes == tpl_meshes:
        return generated[:gen_end] + trailer, tpl_meshes, gen_meshes
    if not allow_duplicate:
        raise ValueError('template has %d mesh(es) but the generated body has %d - pick a template '
                         'with %d (or allow duplication)' % (tpl_meshes, gen_meshes, gen_meshes))
    if gen_meshes != 1:
        raise ValueError('cannot reconcile %d generated mesh(es) with a %d-mesh template'
                         % (gen_meshes, tpl_meshes))

    block = generated[8:gen_end]                       # everything after sig + mesh count
    body = struct.pack('<II', UNIT_SIGNATURE, tpl_meshes) + block * tpl_meshes
    return body + trailer, tpl_meshes, tpl_meshes


def normalize(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = vec
    ln = math.sqrt(x * x + y * y + z * z)
    if ln < 1e-6:
        return (0.0, 0.0, 1.0)
    return (x / ln, y / ln, z / ln)


def parse_single_mesh_offsets(data: bytes) -> dict[str, int]:
    if read_u32(data, 0) != 0x00010090:
        raise ValueError('unsupported unit signature')
    mesh_count = read_u32(data, 4)
    if mesh_count != 1:
        raise ValueError(f'expected 1 mesh template, found {mesh_count}')

    offset = 8
    vbuf_size = read_u32(data, offset)
    offset += 4
    vbuf_start = offset
    offset += vbuf_size
    offset += 8
    vertex_count = read_u32(data, offset)
    offset += 4
    vertex_stride = read_u32(data, offset)
    offset += 4
    element_count = read_u32(data, offset)
    offset += 4
    offset += element_count * 17
    offset += 12
    total_index_count = read_u32(data, offset)
    offset += 4
    index_buffer_size = read_u32(data, offset)
    offset += 4
    index_buffer_start = offset
    offset += index_buffer_size
    shape_count = read_u32(data, offset)
    offset += 4 + shape_count * 16
    bbox_offset = offset

    return {
        'vbuf_start': vbuf_start,
        'vertex_count': vertex_count,
        'vertex_stride': vertex_stride,
        'bbox_offset': bbox_offset,
        'total_index_count': total_index_count,
        'index_buffer_start': index_buffer_start,
        'index_buffer_size': index_buffer_size,
    }


def unit_mesh_end(data: bytes) -> int:
    if len(data) < 8:
        raise ValueError('unit too small')
    sig = read_u32(data, 0)
    if sig != 0x00010090:
        raise ValueError('unsupported unit signature')

    mesh_count = read_u32(data, 4)
    if mesh_count <= 0 or mesh_count > 1024:
        raise ValueError(f'invalid mesh count: {mesh_count}')

    offset = 8
    for _ in range(mesh_count):
        if offset + 4 > len(data):
            raise ValueError('truncated vertex buffer size')
        vertex_buffer_size = read_u32(data, offset)
        offset += 4 + vertex_buffer_size
        offset += 8
        if offset + 12 > len(data):
            raise ValueError('truncated vertex metadata')
        element_count = read_u32(data, offset + 8)
        offset += 12 + element_count * 17 + 12
        if offset + 8 > len(data):
            raise ValueError('truncated index metadata')
        index_buffer_size = read_u32(data, offset + 4)
        offset += 8 + index_buffer_size
        if offset + 4 > len(data):
            raise ValueError('truncated shape count')
        shape_count = read_u32(data, offset)
        offset += 4 + shape_count * 16 + 28
        if offset + 4 > len(data):
            raise ValueError('truncated material count')
        material_count = read_u32(data, offset)
        offset += 4
        for _ in range(material_count):
            if offset + 4 > len(data):
                raise ValueError('truncated material name length')
            name_len = read_u32(data, offset)
            offset += 4 + name_len

    if offset > len(data):
        raise ValueError('mesh parse overran input size')
    return offset


def gather_glb_geometry(glb_path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float]], list[int]]:
    meshes = read_glb(str(glb_path))
    if not meshes:
        raise ValueError(f'no meshes in {glb_path}')

    pos: list[tuple[float, float, float]] = []
    nrm: list[tuple[float, float, float]] = []
    uv0: list[tuple[float, float]] = []
    idx: list[int] = []

    v_off = 0
    for mesh in meshes:
        positions = mesh['positions']
        normals = mesh.get('normals')
        uvs = mesh.get('uvs')
        indices = mesh['indices']

        for i in range(len(positions)):
            p = positions[i]
            pos.append((float(p[0]), float(p[1]), float(p[2])))

            if normals is not None and len(normals) > i:
                n = normals[i]
                nrm.append(normalize((float(n[0]), float(n[1]), float(n[2]))))
            else:
                nrm.append((0.0, 0.0, 1.0))

            if uvs is not None and len(uvs) > i:
                t = uvs[i]
                uv0.append((float(t[0]), float(t[1])))
            else:
                uv0.append((0.0, 0.0))

        for i in range(len(indices)):
            idx.append(int(indices[i]) + v_off)

        v_off += len(positions)

    return pos, nrm, uv0, idx


def _build_combined_single_mesh(glb_path: Path, scale: float, material_name: str) -> dict[str, np.ndarray]:
    src_pos, src_nrm, src_uv, src_idx = gather_glb_geometry(glb_path)
    if not src_pos:
        raise ValueError('source geometry has no vertices')

    pos = np.array(src_pos, dtype=np.float32)
    if scale != 1.0:
        pos *= float(scale)

    nrm = np.array(src_nrm, dtype=np.float32)
    uv = np.array(src_uv, dtype=np.float32)
    idx = np.array(src_idx, dtype=np.int64)

    return {
        'name': material_name,
        'positions': pos,
        'normals': nrm,
        'uvs': uv,
        'indices': idx,
    }


def glb_to_template_unit(
    template_path: Path,
    glb_path: Path,
    output_path: Path,
    scale: float = 1.0,
    material_name: str = DEFAULT_MATERIAL_NAME,
) -> None:
    template_data = template_path.read_bytes()
    template_mesh_end = unit_mesh_end(template_data)
    template_trailer = template_data[template_mesh_end:]
    if not template_trailer:
        raise ValueError('template has no trailer to preserve')

    mesh = _build_combined_single_mesh(glb_path, scale, material_name)
    generated = encode_unit([mesh])
    out, tpl_meshes, written = splice_into_template(generated, template_data)
    output_path.write_bytes(out)

    mn = mesh['positions'].min(axis=0)
    mx = mesh['positions'].max(axis=0)
    size = mx - mn
    print(f'mesh: verts={len(mesh["positions"]):,} tris={len(mesh["indices"]) // 3:,}')
    print(f'bbox size: x={size[0]:.4f} y={size[1]:.4f} z={size[2]:.4f}')
    print(f'meshes: template declares {tpl_meshes}, body carries {written}')


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5, 6):
        print('usage: glb_to_template_unit.py <template.unit> <source.glb> <output.unit> [scale] [material_name]')
        sys.exit(1)

    scale = float(sys.argv[4]) if len(sys.argv) == 5 else 1.0
    material_name = sys.argv[5] if len(sys.argv) == 6 else DEFAULT_MATERIAL_NAME
    glb_to_template_unit(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), scale, material_name)
    print(f'Wrote {sys.argv[3]}')
