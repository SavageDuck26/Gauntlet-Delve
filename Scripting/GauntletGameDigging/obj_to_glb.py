#!/usr/bin/env python3
"""
Convert Gauntlet OBJ exports to GLB (glTF Binary) for Blender import.

Reads OBJ+MTL files from Exports/exported_models/ and produces .glb files
that import directly into Blender with proper material names.

Usage:
  python3 obj_to_glb.py                          # batch convert all OBJs
  python3 obj_to_glb.py <file.obj> [out.glb]     # single file
  python3 obj_to_glb.py --out Exports/glb         # custom output dir
"""
from __future__ import annotations
import json, math, os, struct, sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).parent


# ── OBJ reader ────────────────────────────────────────────────────────────────

def read_obj(path: str):
    """
    Parse an OBJ file. Returns list of meshes, each a dict with:
      name, positions, normals, uvs, faces
    faces = list of triangles, each = [(vi, ti, ni), ...]
    """
    positions, normals, uvs = [], [], []
    groups: Dict[str, list] = {}
    cur = 'default'

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            tok = line.split()
            if tok[0] == 'v':
                positions.append(tuple(float(x) for x in tok[1:4]))
            elif tok[0] == 'vn':
                normals.append(tuple(float(x) for x in tok[1:4]))
            elif tok[0] == 'vt':
                uvs.append(tuple(float(x) for x in tok[1:3]))
            elif tok[0] in ('o', 'g'):
                cur = tok[1] if len(tok) > 1 else 'default'
                if cur not in groups:
                    groups[cur] = []
            elif tok[0] == 'f':
                if cur not in groups:
                    groups[cur] = []
                verts = []
                for t in tok[1:]:
                    parts = t.split('/')
                    vi = int(parts[0]) - 1
                    ti = int(parts[1]) - 1 if len(parts) > 1 and parts[1] else -1
                    ni = int(parts[2]) - 1 if len(parts) > 2 and parts[2] else -1
                    verts.append((vi, ti, ni))
                # Fan-triangulate
                for i in range(1, len(verts) - 1):
                    groups[cur].append([verts[0], verts[i], verts[i + 1]])

    meshes = []
    for name, faces in groups.items():
        if not faces:
            continue
        meshes.append({
            'name': name,
            'positions': positions,
            'normals': normals,
            'uvs': uvs,
            'faces': faces,
        })
    return meshes


# ── GLB builder ───────────────────────────────────────────────────────────────

def _pack_f32(v: float) -> bytes:
    return struct.pack('<f', v)

def _pad4(b: bytes, pad_byte: int = 0) -> bytes:
    r = len(b) % 4
    return b if r == 0 else b + bytes([pad_byte] * (4 - r))


def build_glb(meshes: list, mtl_names: list | None = None) -> bytes:
    """Build a GLB binary from parsed mesh data."""
    accessors = []
    buffer_views = []
    bin_chunks: List[bytes] = []
    bin_offset = 0
    gltf_meshes = []
    materials = []
    mat_names: dict[str, int] = {}

    def add_buffer(data: bytes, target: int) -> int:
        nonlocal bin_offset
        padded = _pad4(data)
        bin_chunks.append(padded)
        idx = len(buffer_views)
        buffer_views.append({
            'buffer': 0,
            'byteOffset': bin_offset,
            'byteLength': len(data),
            'target': target,
        })
        bin_offset += len(padded)
        return idx

    def add_accessor(bv: int, comp_type: int, atype: str, count: int, mins=None, maxs=None) -> int:
        acc: dict = {
            'bufferView': bv,
            'componentType': comp_type,
            'count': count,
            'type': atype,
        }
        if mins is not None:
            acc['min'] = mins
            acc['max'] = maxs
        accessors.append(acc)
        return len(accessors) - 1

    ARRAY_BUFFER = 34962
    ELEMENT_ARRAY_BUFFER = 34963
    FLOAT = 5126
    UNSIGNED_SHORT = 5123
    UNSIGNED_INT = 5125

    for mesh in meshes:
        positions = mesh['positions']
        normals_src = mesh['normals']
        uvs_src = mesh['uvs']
        faces = mesh['faces']
        mesh_name = mesh['name']

        # Build unique vertex list for this group
        vert_map: dict[tuple, int] = {}
        pos_list, nor_list, uv_list = [], [], []
        idx_list = []

        for tri in faces:
            for vi, ti, ni in tri:
                p = positions[vi] if 0 <= vi < len(positions) else (0, 0, 0)
                n = normals_src[ni] if 0 <= ni < len(normals_src) else (0, 0, 1)
                u = uvs_src[ti] if 0 <= ti < len(uvs_src) else (0, 0)
                key = (vi, ti, ni)
                if key not in vert_map:
                    vert_map[key] = len(pos_list)
                    pos_list.append(p)
                    nor_list.append(n)
                    uv_list.append(u)
                idx_list.append(vert_map[key])

        if not pos_list:
            continue

        n_verts = len(pos_list)
        n_idx = len(idx_list)

        # Pack position buffer
        pos_bytes = b''.join(struct.pack('<fff', *p) for p in pos_list)
        nor_bytes = b''.join(struct.pack('<fff', *n) for n in nor_list)
        # glTF UV: V=0 at top (same as Stingray – no flip needed here, OBJ already flipped by unit_to_obj)
        uv_bytes = b''.join(struct.pack('<ff', u, v) for u, v in uv_list)

        # Min/max for positions
        px = [p[0] for p in pos_list]
        py = [p[1] for p in pos_list]
        pz = [p[2] for p in pos_list]
        pos_min = [min(px), min(py), min(pz)]
        pos_max = [max(px), max(py), max(pz)]

        bv_pos = add_buffer(pos_bytes, ARRAY_BUFFER)
        bv_nor = add_buffer(nor_bytes, ARRAY_BUFFER)
        bv_uv  = add_buffer(uv_bytes,  ARRAY_BUFFER)

        acc_pos = add_accessor(bv_pos, FLOAT, 'VEC3', n_verts, pos_min, pos_max)
        acc_nor = add_accessor(bv_nor, FLOAT, 'VEC3', n_verts)
        acc_uv  = add_accessor(bv_uv,  FLOAT, 'VEC2', n_verts)

        # Index buffer (use uint16 or uint32)
        if n_verts <= 65535:
            idx_bytes = b''.join(struct.pack('<H', i) for i in idx_list)
            idx_comp = UNSIGNED_SHORT
        else:
            idx_bytes = b''.join(struct.pack('<I', i) for i in idx_list)
            idx_comp = UNSIGNED_INT

        bv_idx = add_buffer(idx_bytes, ELEMENT_ARRAY_BUFFER)
        acc_idx = add_accessor(bv_idx, idx_comp, 'SCALAR', n_idx)

        # Material
        mat_name = mesh_name if mesh_name != 'default' else 'm_default'
        if mat_name not in mat_names:
            mat_names[mat_name] = len(materials)
            materials.append({'name': mat_name})
        mat_idx = mat_names[mat_name]

        gltf_meshes.append({
            'name': mesh_name,
            'primitives': [{
                'attributes': {
                    'POSITION': acc_pos,
                    'NORMAL':   acc_nor,
                    'TEXCOORD_0': acc_uv,
                },
                'indices': acc_idx,
                'material': mat_idx,
            }]
        })

    # Assemble glTF JSON
    bin_blob = b''.join(bin_chunks)
    gltf = {
        'asset': {'version': '2.0', 'generator': 'Gauntlet Modtools'},
        'scene': 0,
        'scenes': [{'nodes': list(range(len(gltf_meshes)))}],
        'nodes': [{'mesh': i, 'name': m['name']} for i, m in enumerate(gltf_meshes)],
        'meshes': gltf_meshes,
        'materials': materials,
        'accessors': accessors,
        'bufferViews': buffer_views,
        'buffers': [{'byteLength': len(bin_blob)}],
    }

    json_bytes = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    json_chunk = _pad4(json_bytes, ord(' '))
    bin_chunk  = _pad4(bin_blob, 0)

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    header = struct.pack('<III', 0x46546C67, 2, total)
    jchunk = struct.pack('<II', len(json_chunk), 0x4E4F534A) + json_chunk
    bchunk = struct.pack('<II', len(bin_chunk),  0x004E4942) + bin_chunk

    return header + jchunk + bchunk


def convert_obj_to_glb(obj_path: str, out_path: Optional[str] = None) -> str:
    if out_path is None:
        out_path = str(Path(obj_path).with_suffix('.glb'))
    meshes = read_obj(obj_path)
    glb = build_glb(meshes)
    with open(out_path, 'wb') as f:
        f.write(glb)
    return out_path


# ── batch conversion ──────────────────────────────────────────────────────────

def batch_convert(in_dir: str, out_dir: str, verbose: bool = False):
    in_path  = Path(in_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Use the non-_all OBJs (each shape merged into one file)
    obj_files = sorted(p for p in in_path.glob('*.obj') if '_all' not in p.name)
    print(f"Found {len(obj_files)} OBJ files → {out_path}")

    success = fail = skip = 0
    for i, obj in enumerate(obj_files, 1):
        glb = out_path / (obj.stem + '.glb')
        if glb.exists():
            skip += 1
            continue
        try:
            meshes = read_obj(str(obj))
            if not meshes:
                if verbose:
                    print(f"[{i}] EMPTY {obj.name}")
                skip += 1
                continue
            glb_data = build_glb(meshes)
            glb.write_bytes(glb_data)
            if verbose:
                print(f"[{i}] {obj.name} → {glb.name}  ({len(glb_data):,} bytes)")
            success += 1
        except Exception as e:
            print(f"[{i}] FAIL {obj.name}: {e}")
            fail += 1

    print(f"Done: {success} converted, {skip} skipped, {fail} failed → {out_path}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?',
                        default=str(HERE / 'Exports' / 'exported_models'),
                        help='OBJ file or directory (default: Exports/exported_models)')
    parser.add_argument('output', nargs='?', help='Output .glb file or directory')
    parser.add_argument('--out', help='Override output directory')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    inp = Path(args.input)
    if inp.is_dir():
        out_dir = args.out or args.output or str(HERE / 'Exports' / 'glb')
        batch_convert(str(inp), out_dir, args.verbose)
    elif inp.is_file():
        out = args.output or args.out
        result = convert_obj_to_glb(str(inp), out)
        print(f"Converted → {result}")
    else:
        print(f"Error: {inp} not found")
        sys.exit(1)
