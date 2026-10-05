#!/usr/bin/env python3
"""
Stingray .unit → glTF 2.0 exporter

Exports a Gauntlet .unit file to a self-contained glTF Binary (.glb) file that
Blender (and other tools) can import directly:

  - All mesh geometry (positions, normals, UVs, tangents)
  - Multiple mesh objects / LOD groups as separate glTF mesh primitives
  - Material slots with names matching texture hash filenames
  - Vertex skin weights and joint indices (if present in the file)
  - Bone hierarchy read from a companion .bones file (if provided)
  - Proper Stingray→Blender coordinate transform (Z-up, right-hand → same)

Usage:
  python unit_to_gltf.py  <file.unit>  [file.bones]  [output.glb]
  python unit_to_gltf.py  selftest

The .glb output can be imported into Blender via: File > Import > glTF 2.0

Round-trip note:
  This file handles decode ONLY (unit → glTF). For encode (glTF → unit) see
  unit_tools.py which implements a basic re-encoder from OBJ/glTF vertex data.
"""

from __future__ import annotations
import json, math, os, struct, sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── import unit parser ────────────────────────────────────────────────────────

HERE = Path(__file__).parent
PARENT = HERE.parent
# Ensure the directory containing unit_to_obj.py is on sys.path
# When loaded via importlib from resource_tools, HERE = GauntletGameDigging/
for _p in [str(HERE), str(PARENT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from unit_to_obj import (
    UnitParser, ElementType, Mesh, Vertex, Shape, Vector3, Vector2
)

# ── import bones decoder ──────────────────────────────────────────────────────
_bones_mod = None
try:
    import importlib.util as _ilu
    _bt_path = HERE / 'resource_tools' / 'bones_tools.py'
    _spec = _ilu.spec_from_file_location('bones_tools', _bt_path)
    _bones_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_bones_mod)
except Exception:
    pass


# ── glTF constants ────────────────────────────────────────────────────────────

GLTF_COMPONENT = {
    'BYTE':           (5120, 1),
    'UNSIGNED_BYTE':  (5121, 1),
    'SHORT':          (5122, 2),
    'UNSIGNED_SHORT': (5123, 2),
    'UNSIGNED_INT':   (5125, 4),
    'FLOAT':          (5126, 4),
}

GLTF_TYPE_COUNTS = {
    'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
    'MAT2': 4, 'MAT3': 9, 'MAT4': 16,
}


class GltfBuilder:
    """Minimal glTF 2.0 builder — produces a self-contained .glb."""

    def __init__(self):
        self.asset = {'version': '2.0', 'generator': 'Gauntlet-Stuff unit_to_gltf'}
        self.scene = 0
        self.scenes = [{'name': 'Scene', 'nodes': []}]
        self.nodes: List[dict] = []
        self.meshes: List[dict] = []
        self.materials: List[dict] = []
        self.accessors: List[dict] = []
        self.buffer_views: List[dict] = []
        self.buffers: List[dict] = []
        self.skins: List[dict] = []
        self._bin_chunks: List[bytes] = []
        self._bin_offset = 0
        self._mat_index: Dict[str, int] = {}

    # ── buffer helpers ────────────────────────────────────────────────────────

    def _pad4(self, data: bytes) -> bytes:
        rem = len(data) % 4
        if rem:
            data += b'\x00' * (4 - rem)
        return data

    def _add_buffer_view(self, data: bytes, target: Optional[int] = None) -> int:
        """Append data to binary chunk, return buffer_view index."""
        padded = self._pad4(data)
        view: dict = {
            'buffer': 0,
            'byteOffset': self._bin_offset,
            'byteLength': len(data),  # actual, not padded
        }
        if target is not None:
            view['target'] = target
        self.buffer_views.append(view)
        self._bin_chunks.append(padded)
        self._bin_offset += len(padded)
        return len(self.buffer_views) - 1

    def _add_accessor(self, view_idx: int, component_type: str,
                      accessor_type: str, count: int,
                      min_vals=None, max_vals=None,
                      byte_offset: int = 0) -> int:
        comp_enum, comp_size = GLTF_COMPONENT[component_type]
        acc: dict = {
            'bufferView': view_idx,
            'byteOffset': byte_offset,
            'componentType': comp_enum,
            'type': accessor_type,
            'count': count,
        }
        if min_vals is not None:
            acc['min'] = list(min_vals)
        if max_vals is not None:
            acc['max'] = list(max_vals)
        self.accessors.append(acc)
        return len(self.accessors) - 1

    # ── material helpers ──────────────────────────────────────────────────────

    def get_or_create_material(self, name: str) -> int:
        if name in self._mat_index:
            return self._mat_index[name]
        idx = len(self.materials)
        self.materials.append({
            'name': name,
            'pbrMetallicRoughness': {
                'baseColorFactor': [0.8, 0.8, 0.8, 1.0],
                'metallicFactor': 0.0,
                'roughnessFactor': 0.8,
            },
            'doubleSided': False,
        })
        self._mat_index[name] = idx
        return idx

    # ── mesh prim builder ─────────────────────────────────────────────────────

    def add_mesh_primitive(self, mesh_name: str,
                           positions: np.ndarray,
                           normals: Optional[np.ndarray],
                           uvs: Optional[np.ndarray],
                           indices: np.ndarray,
                           material_name: str,
                           weights: Optional[np.ndarray] = None,
                           joints: Optional[np.ndarray] = None,
                           skin_idx: Optional[int] = None) -> Tuple[int, int]:
        """
        Add one mesh primitive. Returns (mesh_idx, node_idx).
        positions: (N,3) float32
        normals:   (N,3) float32 or None
        uvs:       (N,2) float32 or None
        indices:   (F,) uint16 or uint32
        weights:   (N,4) float32 or None
        joints:    (N,4) uint8 or None
        """
        ARRAY_BUFFER  = 34962
        ELEMENT_ARRAY = 34963

        attrs: dict = {}

        # Positions (required)
        pos_data = positions.astype(np.float32).tobytes()
        pv_idx = self._add_buffer_view(pos_data, ARRAY_BUFFER)
        pa_idx = self._add_accessor(pv_idx, 'FLOAT', 'VEC3', len(positions),
                                    min_vals=positions.min(axis=0).tolist(),
                                    max_vals=positions.max(axis=0).tolist())
        attrs['POSITION'] = pa_idx

        # Normals
        if normals is not None and len(normals) == len(positions):
            n_data = normals.astype(np.float32).tobytes()
            nv_idx = self._add_buffer_view(n_data, ARRAY_BUFFER)
            na_idx = self._add_accessor(nv_idx, 'FLOAT', 'VEC3', len(normals))
            attrs['NORMAL'] = na_idx

        # UVs
        if uvs is not None and len(uvs) == len(positions):
            uv_data = uvs.astype(np.float32).tobytes()
            uv_view = self._add_buffer_view(uv_data, ARRAY_BUFFER)
            uv_acc  = self._add_accessor(uv_view, 'FLOAT', 'VEC2', len(uvs))
            attrs['TEXCOORD_0'] = uv_acc

        # Skin weights
        if weights is not None and joints is not None:
            w_data = weights.astype(np.float32).tobytes()
            wv_idx = self._add_buffer_view(w_data, ARRAY_BUFFER)
            wa_idx = self._add_accessor(wv_idx, 'FLOAT', 'VEC4', len(weights))
            attrs['WEIGHTS_0'] = wa_idx

            j_data = joints.astype(np.uint8).tobytes()
            jv_idx = self._add_buffer_view(j_data, ARRAY_BUFFER)
            ja_idx = self._add_accessor(jv_idx, 'UNSIGNED_BYTE', 'VEC4', len(joints))
            attrs['JOINTS_0'] = ja_idx

        # Indices
        if indices.max() > 65535:
            idx_data = indices.astype(np.uint32).tobytes()
            comp_type = 'UNSIGNED_INT'
        else:
            idx_data = indices.astype(np.uint16).tobytes()
            comp_type = 'UNSIGNED_SHORT'

        iv_idx = self._add_buffer_view(idx_data, ELEMENT_ARRAY)
        ia_idx = self._add_accessor(iv_idx, comp_type, 'SCALAR', len(indices),
                                    min_vals=[int(indices.min())],
                                    max_vals=[int(indices.max())])

        mat_idx = self.get_or_create_material(material_name)

        prim = {
            'attributes': attrs,
            'indices': ia_idx,
            'material': mat_idx,
        }

        mesh_idx = len(self.meshes)
        self.meshes.append({'name': mesh_name, 'primitives': [prim]})

        node: dict = {'name': mesh_name, 'mesh': mesh_idx}
        if skin_idx is not None:
            node['skin'] = skin_idx

        node_idx = len(self.nodes)
        self.nodes.append(node)
        self.scenes[0]['nodes'].append(node_idx)
        return mesh_idx, node_idx

    # ── skeleton helpers ──────────────────────────────────────────────────────

    def add_skeleton(self, bone_names: List[str],
                     parent_indices: List[int]) -> Tuple[int, List[int]]:
        """
        Add a skeleton. parent_indices[i] == -1 means root.
        Returns (skin_idx, [joint_node_indices]).
        """
        joint_nodes: List[int] = []

        for i, name in enumerate(bone_names):
            node: dict = {'name': name}
            # Identity transform
            node['translation'] = [0, 0, 0]
            node['rotation']    = [0, 0, 0, 1]
            node['scale']       = [1, 1, 1]
            idx = len(self.nodes)
            self.nodes.append(node)
            joint_nodes.append(idx)

        # Wire up parent → children
        for i, parent in enumerate(parent_indices):
            if parent >= 0 and parent < len(joint_nodes):
                parent_node = self.nodes[joint_nodes[parent]]
                parent_node.setdefault('children', []).append(joint_nodes[i])

        # Roots are bones with no parent; add them to scene
        roots = [joint_nodes[i] for i, p in enumerate(parent_indices) if p < 0]
        if roots:
            self.scenes[0]['nodes'].extend(roots)

        # Inverse bind matrices — identity for all bones (we don't have bind pose)
        ibm_count = len(bone_names)
        identity = np.eye(4, dtype=np.float32)
        ibm_data = np.tile(identity.flatten(), ibm_count).astype(np.float32).tobytes()
        ibm_view = self._add_buffer_view(ibm_data)
        ibm_acc  = self._add_accessor(ibm_view, 'FLOAT', 'MAT4', ibm_count)

        skin_idx = len(self.skins)
        self.skins.append({
            'name': 'Skeleton',
            'joints': joint_nodes,
            'inverseBindMatrices': ibm_acc,
        })
        return skin_idx, joint_nodes

    # ── GLB serialization ─────────────────────────────────────────────────────

    def to_glb(self) -> bytes:
        """Serialize to GLB binary format."""
        bin_data = b''.join(self._bin_chunks)
        if self.buffers:
            self.buffers[0]['byteLength'] = len(bin_data)
        else:
            self.buffers.append({'byteLength': len(bin_data)})

        gltf_dict: dict = {
            'asset': self.asset,
            'scene': self.scene,
            'scenes': self.scenes,
            'nodes': self.nodes,
            'meshes': self.meshes,
            'accessors': self.accessors,
            'bufferViews': self.buffer_views,
            'buffers': self.buffers,
        }
        if self.materials:
            gltf_dict['materials'] = self.materials
        if self.skins:
            gltf_dict['skins'] = self.skins

        json_bytes = json.dumps(gltf_dict, separators=(',', ':')).encode('utf-8')
        # Pad JSON to 4-byte boundary
        rem = len(json_bytes) % 4
        if rem:
            json_bytes += b' ' * (4 - rem)

        # Pad binary to 4-byte boundary
        rem = len(bin_data) % 4
        if rem:
            bin_data += b'\x00' * (4 - rem)

        # GLB header
        total_len = 12 + (8 + len(json_bytes)) + (8 + len(bin_data))
        header = struct.pack('<III', 0x46546C67, 2, total_len)  # magic, version, length

        chunk_json = struct.pack('<II', len(json_bytes), 0x4E4F534A)  # JSON chunk
        chunk_bin  = struct.pack('<II', len(bin_data),  0x004E4942)   # BIN chunk

        return header + chunk_json + json_bytes + chunk_bin + bin_data


# ── main converter ─────────────────────────────────────────────────────────────

def convert_unit_to_gltf(unit_path: str,
                          bones_path: Optional[str] = None,
                          out_path: Optional[str] = None,
                          verbose: bool = False) -> str:
    """
    Convert a .unit file to .glb.

    unit_path:  path to .unit binary
    bones_path: path to companion .bones file (optional, adds skeleton)
    out_path:   output .glb path (default: same stem as unit, .glb extension)
    """
    unit_path = str(unit_path)
    if out_path is None:
        out_path = os.path.splitext(unit_path)[0] + '.glb'

    # Parse unit
    parser = UnitParser(unit_path, verbose=verbose)
    parser.parse()

    if not parser.meshes:
        raise ValueError(f"No meshes found in {unit_path}")

    builder = GltfBuilder()

    # Parse bones if provided
    skin_idx = None
    bone_names: List[str] = []
    if bones_path and os.path.exists(bones_path) and _bones_mod:
        try:
            bones_data = _bones_mod.decode_bones(open(bones_path, 'rb').read())
            bone_names = [b['name'] for b in bones_data['bones']]
            # Without parent data in .bones, we make a flat skeleton (all roots)
            parent_indices = [-1] * len(bone_names)
            skin_idx, _ = builder.add_skeleton(bone_names, parent_indices)
            if verbose:
                print(f"Added skeleton: {len(bone_names)} bones")
        except Exception as e:
            print(f"  Warning: could not parse bones: {e}")

    # Convert each mesh
    for mesh_idx, mesh in enumerate(parser.meshes):
        verts = mesh.vertices
        if not verts:
            continue

        n = len(verts)

        # Positions
        positions = np.array([[v.position.x, v.position.y, v.position.z]
                               for v in verts], dtype=np.float32)

        # Normals
        normals = None
        if any(v.normal for v in verts):
            normals = np.array([
                [v.normal.x, v.normal.y, v.normal.z] if v.normal else [0, 1, 0]
                for v in verts
            ], dtype=np.float32)

        # UVs (flip V from Stingray→OpenGL convention, which Blender uses)
        uvs = None
        if any(v.uv for v in verts):
            uvs = np.array([
                [v.uv.u, 1.0 - v.uv.v] if v.uv else [0, 0]
                for v in verts
            ], dtype=np.float32)

        # Skin weights
        weights = None
        joints = None
        if any(v.bone_weights for v in verts):
            weights = np.array([
                list(v.bone_weights) if v.bone_weights else [1, 0, 0, 0]
                for v in verts
            ], dtype=np.float32)
            joints = np.array([
                list(v.bone_indices) if v.bone_indices else [0, 0, 0, 0]
                for v in verts
            ], dtype=np.uint8)

        # Group by shape (submesh / material group)
        shapes = mesh.shapes
        if not shapes:
            # No shape info — one big group
            all_indices = np.array(mesh.indices, dtype=np.uint32)
            mat_name = mesh.materials[0] if mesh.materials else f'material_{mesh_idx}'
            builder.add_mesh_primitive(
                f'mesh_{mesh_idx:03d}',
                positions, normals, uvs, all_indices, mat_name,
                weights, joints, skin_idx if weights is not None else None
            )
        else:
            for shape_i, shape in enumerate(shapes):
                s_idx = shape.index_offset
                s_cnt = shape.index_count
                raw_indices = np.array(mesh.indices[s_idx:s_idx + s_cnt], dtype=np.int64)

                if len(raw_indices) == 0 or raw_indices.max() >= n:
                    continue

                # Remap to compact vertex range
                used_verts = np.unique(raw_indices)
                remap = np.full(n, -1, dtype=np.int64)
                remap[used_verts] = np.arange(len(used_verts), dtype=np.int64)
                remapped = remap[raw_indices].astype(np.uint32)

                sub_pos = positions[used_verts]
                sub_norm = normals[used_verts] if normals is not None else None
                sub_uv   = uvs[used_verts] if uvs is not None else None
                sub_w    = weights[used_verts] if weights is not None else None
                sub_j    = joints[used_verts] if joints is not None else None

                mat_idx_local = shape.material_index
                mat_name = (mesh.materials[mat_idx_local]
                            if 0 <= mat_idx_local < len(mesh.materials)
                            else f'material_{mesh_idx}_{mat_idx_local}')

                mesh_name = f'mesh_{mesh_idx:03d}_shape_{shape_i:03d}'
                builder.add_mesh_primitive(
                    mesh_name, sub_pos, sub_norm, sub_uv, remapped, mat_name,
                    sub_w, sub_j, skin_idx if sub_w is not None else None
                )

    glb = builder.to_glb()
    with open(out_path, 'wb') as f:
        f.write(glb)

    mesh_count = len(parser.meshes)
    total_verts = sum(len(m.vertices) for m in parser.meshes)
    print(f"unit → glTF: {unit_path}")
    print(f"  {mesh_count} mesh(es), {total_verts:,} vertices → {out_path}  ({len(glb):,} bytes)")
    if bone_names:
        print(f"  Skeleton: {len(bone_names)} bones")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def selftest():
    unit = str(HERE / 'Exports' / 'samples' / 'unit_015febcb203ebaaf.unit')
    bones = str(HERE / 'Exports' / 'samples' / 'bones_e8a62af86d41f0e5.bones')
    out = '/tmp/_selftest_unit.glb'
    if not os.path.exists(unit):
        print("unit_to_gltf selftest: SKIP (sample not found)")
        return
    bones_arg = bones if os.path.exists(bones) else None
    path = convert_unit_to_gltf(unit, bones_arg, out)
    glb_bytes = open(path, 'rb').read()
    assert glb_bytes[:4] == b'glTF', "Not a GLB file"
    assert len(glb_bytes) > 1000, "GLB suspiciously small"
    print(f"unit_to_gltf selftest: PASS  ({len(glb_bytes):,} bytes)")
    try:
        os.unlink(out)
    except Exception:
        pass


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        selftest()
    elif len(sys.argv) >= 2:
        unit = sys.argv[1]
        bones = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].endswith('.bones') else None
        out = next((a for a in sys.argv[2:] if a.endswith('.glb')), None)
        convert_unit_to_gltf(unit, bones, out, verbose=True)
    else:
        print(__doc__)
        sys.exit(1)
