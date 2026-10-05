#!/usr/bin/env python3
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path


def murmur64(key: str, seed: int = 0) -> int:
    m = 0xC6A4A7935BD1E995
    r = 47
    kb = key.lower().encode('utf-8')
    ln = len(kb)
    h = (seed ^ ((ln * m) & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF

    for i in range(ln // 8):
        k = struct.unpack_from('<Q', kb, i * 8)[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    tail = kb[ln & ~7:]
    if len(tail) >= 7:
        h ^= tail[6] << 48
    if len(tail) >= 6:
        h ^= tail[5] << 40
    if len(tail) >= 5:
        h ^= tail[4] << 32
    if len(tail) >= 4:
        h ^= tail[3] << 24
    if len(tail) >= 3:
        h ^= tail[2] << 16
    if len(tail) >= 2:
        h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    h ^= h >> r
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> r
    return h


def template_hash_from_filename(path: Path) -> int | None:
    stem = path.stem.lower()
    if stem.startswith('0x'):
        stem = stem[2:]
    if len(stem) == 16:
        try:
            return int(stem, 16)
        except ValueError:
            return None
    return None


def replace_all_u64(buf: bytearray, old_val: int, new_val: int) -> int:
    old_b = old_val.to_bytes(8, 'little')
    new_b = new_val.to_bytes(8, 'little')
    count = 0
    i = 0
    while True:
        idx = buf.find(old_b, i)
        if idx < 0:
            break
        buf[idx:idx + 8] = new_b
        count += 1
        i = idx + 8
    return count


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


def write_vec3(buf: bytearray, offset: int, xyz: tuple[float, float, float]) -> None:
    struct.pack_into('<fff', buf, offset, *xyz)


def normalize(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = vec
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-6:
        return (0.0, 0.0, 1.0)
    return (x / length, y / length, z / length)


def orthogonal_basis(normal: tuple[float, float, float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    nx, ny, nz = normal
    if abs(ny) < 0.99:
        tangent = normalize((-nz, 0.0, nx))
    else:
        tangent = normalize((1.0, 0.0, 0.0))
    tx, ty, tz = tangent
    binormal = normalize((ny * tz - nz * ty, nz * tx - nx * tz, nx * ty - ny * tx))
    return tangent, binormal


def parse_single_mesh_offsets(data: bytes) -> dict[str, int]:
    if read_u32(data, 0) != 0x00010090:
        raise ValueError('unsupported unit signature')
    mesh_count = read_u32(data, 4)
    if mesh_count != 1:
        raise ValueError(f'expected 1 mesh, found {mesh_count}')

    offset = 8
    vbuf_size = read_u32(data, offset)
    offset += 4
    vbuf_start = offset
    offset += vbuf_size
    offset += 8  # pad
    vertex_count = read_u32(data, offset)
    offset += 4
    vertex_stride = read_u32(data, offset)
    offset += 4
    element_count = read_u32(data, offset)
    offset += 4
    offset += element_count * 17
    offset += 12  # post-elem pad
    total_index_count = read_u32(data, offset)
    offset += 4
    index_buffer_size = read_u32(data, offset)
    offset += 4
    index_buffer_start = offset
    offset += index_buffer_size
    shape_count = read_u32(data, offset)
    offset += 4 + shape_count * 16
    bbox_offset = offset
    offset += 28
    material_count_offset = offset
    material_table_start = material_count_offset + 4
    return {
        'vbuf_start': vbuf_start,
        'vbuf_size': vbuf_size,
        'vertex_count': vertex_count,
        'vertex_stride': vertex_stride,
        'bbox_offset': bbox_offset,
        'material_count_offset': material_count_offset,
        'material_table_start': material_table_start,
        'total_index_count': total_index_count,
        'index_buffer_start': index_buffer_start,
        'index_buffer_size': index_buffer_size,
    }


def build_cube_triangle_indices(corner_to_vertex: dict[tuple[float, float, float], int], tri_count: int) -> list[int]:
    # Corner keys use +/-1 signs.
    c = {
        'n_n_n': (-1.0, -1.0, -1.0),
        'p_n_n': (1.0, -1.0, -1.0),
        'p_p_n': (1.0, 1.0, -1.0),
        'n_p_n': (-1.0, 1.0, -1.0),
        'n_n_p': (-1.0, -1.0, 1.0),
        'p_n_p': (1.0, -1.0, 1.0),
        'p_p_p': (1.0, 1.0, 1.0),
        'n_p_p': (-1.0, 1.0, 1.0),
    }

    # 12 triangles, then mirrored winding to make faces robust against culling.
    tris = [
        (c['n_n_n'], c['p_n_n'], c['p_p_n']), (c['n_n_n'], c['p_p_n'], c['n_p_n']),
        (c['n_n_p'], c['p_p_p'], c['p_n_p']), (c['n_n_p'], c['n_p_p'], c['p_p_p']),
        (c['n_n_n'], c['p_n_p'], c['p_n_n']), (c['n_n_n'], c['n_n_p'], c['p_n_p']),
        (c['n_p_n'], c['p_p_n'], c['p_p_p']), (c['n_p_n'], c['p_p_p'], c['n_p_p']),
        (c['n_n_n'], c['n_p_n'], c['n_p_p']), (c['n_n_n'], c['n_p_p'], c['n_n_p']),
        (c['p_n_n'], c['p_n_p'], c['p_p_p']), (c['p_n_n'], c['p_p_p'], c['p_p_n']),
    ]
    tris += [(a, c1, b) for (a, b, c1) in tris]

    index_stream: list[int] = []
    for a, b, c1 in tris:
        index_stream.extend([
            corner_to_vertex[a],
            corner_to_vertex[b],
            corner_to_vertex[c1],
        ])

    needed_indices = tri_count * 3
    out: list[int] = []
    while len(out) < needed_indices:
        out.extend(index_stream)
    return out[:needed_indices]


def cubify_template(template_path: Path, output_path: Path, unit_resource_path: str | None = None, half_extent: float = 0.5) -> None:
    data = bytearray(template_path.read_bytes())
    info = parse_single_mesh_offsets(data)

    stride = info['vertex_stride']
    if stride < 56:
        raise ValueError(f'expected at least 56-byte vertex stride, got {stride}')

    positions = []
    for vertex_index in range(info['vertex_count']):
        base = info['vbuf_start'] + vertex_index * stride
        positions.append(struct.unpack_from('<fff', data, base))

    min_x = min(p[0] for p in positions)
    min_y = min(p[1] for p in positions)
    min_z = min(p[2] for p in positions)
    max_x = max(p[0] for p in positions)
    max_y = max(p[1] for p in positions)
    max_z = max(p[2] for p in positions)
    center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
    extents = (
        max((max_x - min_x) * 0.5, 1e-6),
        max((max_y - min_y) * 0.5, 1e-6),
        max((max_z - min_z) * 0.5, 1e-6),
    )

    corner_to_vertex: dict[tuple[float, float, float], int] = {}

    for vertex_index in range(info['vertex_count']):
        base = info['vbuf_start'] + vertex_index * stride
        px, py, pz = struct.unpack_from('<fff', data, base)
        nx = (px - center[0]) / extents[0]
        ny = (py - center[1]) / extents[1]
        nz = (pz - center[2]) / extents[2]

        # Force vertices to true cube corners (8-corner topology coordinates).
        snapped = [
            1.0 if nx >= 0.0 else -1.0,
            1.0 if ny >= 0.0 else -1.0,
            1.0 if nz >= 0.0 else -1.0,
        ]

        key = (snapped[0], snapped[1], snapped[2])
        if key not in corner_to_vertex:
            corner_to_vertex[key] = vertex_index

        new_pos = (snapped[0] * half_extent, snapped[1] * half_extent, snapped[2] * half_extent)
        write_vec3(data, base, new_pos)

        normal = normalize(tuple(snapped))
        tangent, binormal = orthogonal_basis(normal)

        write_vec3(data, base + 12, normal)
        write_vec3(data, base + 24, binormal)
        write_vec3(data, base + 36, tangent)

    radius = math.sqrt(3.0 * (half_extent ** 2))
    struct.pack_into('<7f', data, info['bbox_offset'], -half_extent, -half_extent, -half_extent, half_extent, half_extent, half_extent, radius)

    if len(corner_to_vertex) == 8:
        total_index_count = info['total_index_count']
        index_buffer_start = info['index_buffer_start']
        index_buffer_size = info['index_buffer_size']
        index_stride = index_buffer_size // max(total_index_count, 1)
        if index_stride == 2:
            idx_values = build_cube_triangle_indices(corner_to_vertex, total_index_count // 3)
            for i, idx in enumerate(idx_values):
                struct.pack_into('<H', data, index_buffer_start + i * 2, idx)
        elif index_stride == 4:
            idx_values = build_cube_triangle_indices(corner_to_vertex, total_index_count // 3)
            for i, idx in enumerate(idx_values):
                struct.pack_into('<I', data, index_buffer_start + i * 4, idx)
        else:
            print(f'warning: unsupported index stride {index_stride}; kept original indices')
    else:
        print(f'warning: expected 8 corners, found {len(corner_to_vertex)}; kept original indices')

    if unit_resource_path:
        old_hash = template_hash_from_filename(template_path)
        new_hash = murmur64(unit_resource_path)
        if old_hash is not None:
            replaced = replace_all_u64(data, old_hash, new_hash)
            print(f'replaced template hash occurrences: {replaced}')
        else:
            print('warning: template hash could not be inferred from filename; skipped hash rewrite')

    output_path.write_bytes(data)


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        print('usage: cubify_unit_template.py <template.unit> <output.unit> [unit/resource/path]')
        sys.exit(1)
    resource_path = sys.argv[3] if len(sys.argv) == 4 else None
    cubify_template(Path(sys.argv[1]), Path(sys.argv[2]), resource_path)
