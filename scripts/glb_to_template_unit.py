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


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


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
    generated_mesh_end = unit_mesh_end(generated)

    out = generated[:generated_mesh_end] + template_trailer
    output_path.write_bytes(out)

    mn = mesh['positions'].min(axis=0)
    mx = mesh['positions'].max(axis=0)
    size = mx - mn
    print(f'mesh: verts={len(mesh["positions"]):,} tris={len(mesh["indices"]) // 3:,}')
    print(f'bbox size: x={size[0]:.4f} y={size[1]:.4f} z={size[2]:.4f}')


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5, 6):
        print('usage: glb_to_template_unit.py <template.unit> <source.glb> <output.unit> [scale] [material_name]')
        sys.exit(1)

    scale = float(sys.argv[4]) if len(sys.argv) == 5 else 1.0
    material_name = sys.argv[5] if len(sys.argv) == 6 else DEFAULT_MATERIAL_NAME
    glb_to_template_unit(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), scale, material_name)
    print(f'Wrote {sys.argv[3]}')
