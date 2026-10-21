#!/usr/bin/env python3
"""
make_plane_glb.py - a flat quad as GLB, authored in the level's own space.

Gauntlet's levels are Z-up, and glb_to_template_unit.py copies GLB vertex positions
straight into the unit's vertex buffer with no axis change.  So a floor plane must be
authored HERE in the XY plane with a +Z normal: the same plane exported from Blender
arrives standing on edge, because Blender writes Z-up as Y-up on export.

The output feeds glb_to_template_unit.py, which splices the mesh into a native unit and
preserves that unit's trailing sections - the thing whose absence loads fine and then
crashes at the engine's resolve stage (CUSTOM_ASSET_LOADING_FINDINGS 10.2).

    make_plane_glb.py --out plane.glb --size 40
    make_plane_glb.py --out plane.glb --size 40 --center 45,40,9 --uv-scale 0.1
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import List, Sequence, Tuple

GLB_MAGIC = b'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
FLOAT = 5126
UINT32 = 5125


def build_glb(positions: Sequence[Sequence[float]],
              normals: Sequence[Sequence[float]],
              uvs: Sequence[Sequence[float]],
              indices: Sequence[int],
              name: str = 'plane') -> bytes:
    """One mesh, one primitive, POSITION + NORMAL + TEXCOORD_0, uint32 indices."""
    bin_parts: List[bytes] = []
    views: List[dict] = []
    offset = 0

    def add_view(payload: bytes, target: int) -> int:
        nonlocal offset
        pad = (-offset) % 4
        if pad:
            bin_parts.append(b'\x00' * pad)
            offset += pad
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(payload),
                      'target': target})
        bin_parts.append(payload)
        offset += len(payload)
        return len(views) - 1

    def pack(fmt: str, rows: Sequence[Sequence[float]]) -> bytes:
        return b''.join(struct.pack(fmt, *r) for r in rows)

    pv = add_view(pack('<3f', positions), 34962)
    nv = add_view(pack('<3f', normals), 34962)
    uv = add_view(pack('<2f', uvs), 34962)
    iv = add_view(pack('<I', [(i,) for i in indices]), 34963)

    accessors = [
        {'bufferView': pv, 'componentType': FLOAT, 'count': len(positions), 'type': 'VEC3',
         'min': [min(p[i] for p in positions) for i in range(3)],
         'max': [max(p[i] for p in positions) for i in range(3)]},
        {'bufferView': nv, 'componentType': FLOAT, 'count': len(normals), 'type': 'VEC3'},
        {'bufferView': uv, 'componentType': FLOAT, 'count': len(uvs), 'type': 'VEC2'},
        {'bufferView': iv, 'componentType': UINT32, 'count': len(indices), 'type': 'SCALAR'},
    ]
    gltf = {
        'asset': {'version': '2.0', 'generator': 'make_plane_glb.py'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0, 'name': name}],
        'meshes': [{'name': name, 'primitives': [
            {'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2},
             'indices': 3, 'mode': 4}]}],
        'accessors': accessors,
        'bufferViews': views,
        'buffers': [{'byteLength': offset}],
    }

    binary = b''.join(bin_parts)
    binary += b'\x00' * ((-len(binary)) % 4)
    json_bytes = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    json_bytes += b' ' * ((-len(json_bytes)) % 4)

    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    out = bytearray()
    out += GLB_MAGIC + struct.pack('<II', 2, total)
    out += struct.pack('<II', len(json_bytes), CHUNK_JSON) + json_bytes
    out += struct.pack('<II', len(binary), CHUNK_BIN) + binary
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True)
    ap.add_argument('--size', type=float, default=40.0, help='edge length, metres')
    ap.add_argument('--center', default='0,0,0', help='x,y,z of the plane centre')
    ap.add_argument('--uv-scale', type=float, default=0.25,
                    help='UVs per metre; native props tend to tile rather than stretch')
    ap.add_argument('--grid', type=int, default=1,
                    help='subdivisions per axis.  1 = a single quad (4 verts / 2 triangles); '
                         '3 = a 3x3 grid of 9 verts / 8 triangles, which is EXACTLY what the '
                         'native floor block blocks/d01_crypt/floors/cryptsmooth_floor_4c_4c '
                         'uses.  If a collider is generated from the mesh, this is the knob '
                         'that makes ours structurally identical to a floor that works.')
    a = ap.parse_args()

    cx, cy, cz = (float(v) for v in a.center.split(','))
    h = a.size / 2.0
    u = a.size * a.uv_scale
    n = max(1, a.grid)

    positions: List[Tuple[float, float, float]] = []
    normals: List[Tuple[float, float, float]] = []
    uvs: List[Tuple[float, float]] = []
    for iy in range(n + 1):
        for ix in range(n + 1):
            fx = ix / float(n)
            fy = iy / float(n)
            positions.append((cx - h + fx * a.size, cy - h + fy * a.size, cz))
            normals.append((0.0, 0.0, 1.0))
            uvs.append((fx * u, fy * u))

    indices: List[int] = []
    for iy in range(n):
        for ix in range(n):
            v0 = iy * (n + 1) + ix
            v1 = v0 + 1
            v2 = v0 + (n + 1)
            v3 = v2 + 1
            indices += [v0, v1, v3, v0, v3, v2]

    data = build_glb(positions, normals, uvs, indices)
    Path(a.out).write_bytes(data)
    print('%s: %d bytes, %.1f m %dx%d grid (%d verts, %d triangles), centred (%g, %g, %g), '
          '+Z normal' % (a.out, len(data), a.size, n, n, len(positions), len(indices) // 3,
                         cx, cy, cz))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
