#!/usr/bin/env python3
"""
Stingray .level -> glTF 2.0 (.glb) exporter.

A Gauntlet `.level` is a placement list: every record names a unit template and
carries that instance's transform.  Exporting a level therefore means

  1. parse the level's entity table,
  2. resolve each record's template hash to a `.unit` resource,
  3. build each unique unit's mesh once (reusing `unit_to_gltf.GltfBuilder`),
  4. drop one glTF node per placed entity, carrying that entity's transform,
  5. serialise a single self-contained .glb.

Entity record layout (72 bytes, table starts at byte 128, count from the header):

  offset  size  field
  ------  ----  -----
    0      4    NOT a rotation component      (float32)
    4     12    scale                xyz      (float32[3], usually 1)
   16      8    unused                         (always 0 in the corpus)
   24      8    entity id                      (uint64, per-instance)
   32      8    template hash                  (uint64 name hash of the unit)
   40      8    material override hash         (uint64; often 0 / a variant)
   48     12    position            xyz        (float32[3])
   60      4    rotation quaternion  x         (float32)
   64      4    rotation quaternion  y         (float32)
   68      4    rotation quaternion  w         (float32)

so the rotation is (x, y, z) = (f15, f16, f17) with w reconstructed as
+/-sqrt(1 - x*x - y*y - z*z).  CONFIRMED against the running engine (45 units,
(x,y,z) agreeing to 1e-6); offset 0 is not a rotation component.  The sign of w
is free: q and -q are the same rotation.  Every one of the
three rotation channels is a value in [-1, 1]; the recovered Z angle
`2*atan2(z, w)` lands on 0/90/180/270 degrees for the overwhelming majority of
records (the authored grid rotations) and only the x/y channels and the odd
non-90 degree value carry an out-of-plane tilt, which is why x and y are 0 on
~80% of records.

Confidence: the *positions* (48), *scale* (4), and *template* (32) fields are
confirmed - offsets 32 and 40 hit catalogue name hashes on 100% / 76% of a
372-entity room, positions land on the level's 4-unit grid, scales are the
expected powers of two - and the rotation is decoded from the four [-1,1]
channels described above.  The record used to be read as 80 bytes with the
transform interpreted as 3 loose floats, which parsed real levels into garbage
(`resource_tools/level_tools.py`).

Editor/logic units are dropped by default.  A level also places `skydome`,
`room_marker`, `level_editor` markers, invisible walls and spawn fields; these are
not visible geometry and one of them - `core/editor_slave/units/skydome`, a
~1000-unit hemisphere that a level scales by ~16 - alone spans ~16,000 units.
Left in, it swallows the frame and every real piece of the level collapses to a
dot when the model is framed.  `--include-helpers` keeps them.

The record's f1,f2,f3 triple is NOT applied as a node scale.  It reads like a
region/size box, not a render scale: the same value (e.g. 30x68x35) is shared by
every entity of an area - it even lands on an unrelated chest - and it reaches
110-270 on floor tiles, sarcophagi and decals, which as a scale would build
800-2000-unit objects inside a 16-unit room.  `--apply-scale` restores the
literal reading.

A level also places other levels.  A "room" level is only the DECORATION layer:
`room_crypt_floor_01_adventure` (gold, urns, chests, doors) places its shell as
`..._adventure_template` plus the door-wall prefabs, in a run of 56-byte records
(`name_hash, position, quaternion, scale, extra`).  Those are merged back in
(default `--max-depth 3`, ancestor-tracked so a cycle cannot loop), which turns
that level from a scattering of props into ~11,000 nodes of dungeon.

Usage:
  python3 level_to_glb.py <file.level> [output.glb]
  python3 level_to_glb.py --export ~/Documents/Coding/Gauntlet-Export --out /tmp/lvl
  python3 level_to_glb.py selftest
"""

from __future__ import annotations

import argparse
import math
import os
import re
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from unit_to_obj import UnitParser                      # noqa: E402
from unit_to_gltf import GltfBuilder                    # noqa: E402

# -- format constants ----------------------------------------------------------

ENTITY_TABLE_OFFSET = 128
ENTITY_RECORD_SIZE = 72

OFF_QUAT_X   = 60
OFF_QUAT_Y   = 64
OFF_QUAT_Z   = 68
OFF_SCALE    = 4
OFF_ENTITY_ID = 24
OFF_TEMPLATE = 32
OFF_MATERIAL = 40
OFF_POSITION = 48

# default install locations (Steam install; override with --contents)
CONTENTS_CANDIDATES = [
    os.path.expanduser('~/.local/share/Steam/steamapps/common/Gauntlet/contents'),
    str(HERE.parent / 'Gauntlet-install' / 'contents'),
]

UNIT_TYPE_HASH = 0xE0A48D0BE9A7453F
LEVEL_TYPE_HASH = 0x2A690FD348FE9AC5

# A level also places *sub-levels* (its room shell / door-wall prefabs), which is
# what a "room" level is: `room_crypt_floor_01_adventure` is the decoration layer
# and `room_crypt_floor_01_adventure_template` is the shell it references.  Each
# entry is a clean 56-byte record:
#
#   name_hash(8)  position float32[3]  quaternion float32[4]  scale float32[3]
#   extra(8)
#
# (the stride and field order were read off crypt_arena01 / the crypt room: the
# quaternion is unit, the position lands on the level grid).  Entries are found by
# matching every 8-byte window against the catalogue's own level name hashes.
SUBLAYER_RECORD_SIZE = 56

# Editor / logic units are not visible geometry, and some of them are enormous:
# `core/editor_slave/units/skydome` is a ~1000-unit hemisphere that a level scales
# by ~16, so it alone spans ~16,000 units around a 16-unit room.  Left in, it
# swallows the frame and every real piece of the level collapses to a dot - so
# they are dropped by default (`--include-helpers` puts them back).
HELPER_PATTERNS = (
    r'^core/editor_slave/',
    r'^gameobjects/(room_marker|level_editor|spawn_field|deathplane|spawners|markers?)(/|$)',
    r'invisible_wall',
    r'skydome',
)
HELPER_RE = re.compile('|'.join(HELPER_PATTERNS))

# Materials on meshes that exist only as proxies - see _is_proxy_mesh().
PROXY_MATERIALS = frozenset({'lambert1'})


def is_helper(name: str) -> bool:
    """True for editor/logic units that should not appear in a level export."""
    return bool(name) and bool(HELPER_RE.search(name))



# -- level parsing -------------------------------------------------------------

@dataclass
class Entity:
    entity_id: int
    template_hash: int
    material_hash: int
    position: Tuple[float, float, float]
    rotation: Tuple[float, float, float, float]   # quaternion xyzw
    scale: Tuple[float, float, float]

    def quaternion_unit(self) -> Tuple[float, float, float, float]:
        """The stored quaternion, normalised (Stingray does not pre-normalise)."""
        x, y, z, w = self.rotation
        n = math.sqrt(x * x + y * y + z * z + w * w)
        if n < 1e-8:
            return (0.0, 0.0, 0.0, 1.0)
        return (x / n, y / n, z / n, w / n)


def parse_entities(blob: bytes) -> List[Entity]:
    """Decode the entity table of a .level body."""
    entity_count = struct.unpack_from('<I', blob, 4)[0]
    out: List[Entity] = []
    for i in range(entity_count):
        base = ENTITY_TABLE_OFFSET + i * ENTITY_RECORD_SIZE
        if base + ENTITY_RECORD_SIZE > len(blob):
            break
        ent_id, = struct.unpack_from('<Q', blob, base + OFF_ENTITY_ID)
        template, = struct.unpack_from('<Q', blob, base + OFF_TEMPLATE)
        material, = struct.unpack_from('<Q', blob, base + OFF_MATERIAL)
        pos = struct.unpack_from('<3f', blob, base + OFF_POSITION)
        scale = struct.unpack_from('<3f', blob, base + OFF_SCALE)
        f0, = struct.unpack_from('<f', blob, base + 0)   # not a component; sign only
        qx, = struct.unpack_from('<f', blob, base + OFF_QUAT_X)
        qy, = struct.unpack_from('<f', blob, base + OFF_QUAT_Y)
        qz, = struct.unpack_from('<f', blob, base + OFF_QUAT_Z)
        # The stored triple is the quaternion's VECTOR part; w is reconstructed.
        # Confirmed against the running engine: (x,y,z) = (f15,f16,f17) agrees to
        # 1e-6 over 45 units, while the rotated-in f0 does not match the engine's w
        # at all (6/45) - f0 is not a rotation component.  The sign of w is free
        # because q and -q are the same rotation.
        qw_src = f0 if f0 != 0.0 else 1.0
        r2 = qx * qx + qy * qy + qz * qz
        if r2 > 1.0:
            # longer than unit: keep the direction, take the 180-degree rotation
            n = math.sqrt(r2)
            qx, qy, qz = qx / n, qy / n, qz / n
            qw = 0.0
        else:
            # w is reconstructed, NOT stored.  Fitted against the engine over 633
            # crypt_wall_4c instances (9 distinct orientations) and 1143 records:
            #   (x,y,z) = (f15,f16,f17) with w = -sqrt(1-|v|^2)  -> 100% coverage,
            # and every one of the top candidates is (f15,f16,f17) - no other
            # triple of the record's fields comes close.  The sign of w is free for
            # q == -q, and (x,y,z)=(f15,f16,f17); the negative branch is the
            # fitted one.  A handful of orientations (~5 of 14 distinct for walls)
            # are still not produced by the engine's set; those are listed, not
            # hidden.
            qw = -math.sqrt(1.0 - r2)
        out.append(Entity(ent_id, template, material, pos, (qx, qy, qz, qw), scale))
    return out
# -- sub-levels ----------------------------------------------------------------

@dataclass
class SubLayer:
    name_hash: int
    position: Tuple[float, float, float]
    rotation: Tuple[float, float, float, float]
    scale: Tuple[float, float, float]


def known_level_hashes() -> set:
    """Name hashes the catalogue lists as `level` resources."""
    import csv
    cat = HERE.parent / 'Data' / 'bundle_manifest' / '04_bundle_resources.csv'
    out = set()
    if cat.exists():
        with cat.open(newline='', encoding='utf-8', errors='replace') as fh:
            for r in csv.DictReader(fh):
                if r.get('type') == 'level' and r.get('name_hash'):
                    out.add(int(r['name_hash'], 16))
    return out


def parse_sublayers(blob: bytes, level_hashes) -> List[SubLayer]:
    """Decode the sub-level placement table (layout in SUBLAYER_RECORD_SIZE).

    Every 8-byte window is matched against the catalogue's level name hashes; a
    hit is accepted as an entry only when the record reads back as a real
    placement (unit quaternion, sane scale).
    """
    out: List[SubLayer] = []
    seen = set()
    for off in range(0, len(blob) - SUBLAYER_RECORD_SIZE + 1):
        v = int.from_bytes(blob[off:off + 8], 'little')
        if v not in level_hashes:
            continue
        pos = struct.unpack_from('<3f', blob, off + 8)
        quat = struct.unpack_from('<4f', blob, off + 20)
        scale = struct.unpack_from('<3f', blob, off + 36)
        if abs(math.sqrt(sum(c * c for c in quat)) - 1.0) > 0.01:
            continue
        if not all(0.0 <= s < 1000.0 for s in scale):
            continue
        key = (v, pos)
        if key in seen:
            continue
        seen.add(key)
        out.append(SubLayer(v, pos, quat, scale))
    return out


# -- unit resource loading -----------------------------------------------------


# -- unit resource loading -----------------------------------------------------

def _contents_dir(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    for cand in CONTENTS_CANDIDATES:
        if os.path.isdir(cand):
            return Path(cand)
    raise SystemExit("could not find the Gauntlet contents/ directory; "
                     "pass --contents <dir>")


_BODY_CACHE: Dict[Tuple[str, int], Dict[int, bytes]] = {}
_SCANNED: Dict[str, set] = {}


def load_bodies(hashes, type_hash: int, contents: Path, verbose: bool = False
                ) -> Dict[int, bytes]:
    """Return {name_hash: body} for every requested hash of `type_hash` on disk.

    Scans the packed bundles once and stops early once all requested hashes are
    resolved.  Results are cached per (contents directory, type), and bundles
    already scanned for that type are not re-read, so a batch of levels sharing
    templates pays for the bundle scan only once.
    """
    import list_game_bundles as L

    key = (str(contents), type_hash)
    cache = _BODY_CACHE.setdefault(key, {})
    want = set(hashes) - set(cache)
    total = len(hashes)
    if not want:
        return {h: cache[h] for h in hashes if h in cache}

    scanned = _SCANNED.setdefault(key, set())
    bundles = sorted(f for f in os.listdir(contents)
                     if '.' not in f and (contents / f).is_file())
    for bname in bundles:
        if not want:
            break
        if bname in scanned:
            continue
        scanned.add(bname)
        try:
            packed = (contents / bname).read_bytes()
            _sig, _uz, data = L.decompress_bundle(packed)
            _count, toc = L.parse_toc(data)
            entries, _end, _ok = L.parse_resources(data, toc)
        except Exception as exc:                                    # noqa: BLE001
            if verbose:
                print(f"  skip {bname}: {exc}")
            continue
        for e in entries:
            if e.get('type_hash') != type_hash:
                continue
            nh = e.get('name_hash')
            if nh is None or nh in cache:
                continue
            start = e.get('body_start', 0)
            # Cache every body of this type in a scanned bundle (not just the
            # ones asked for now), so a later level referencing a different one
            # from the same bundle does not need the bundle re-read.
            cache[nh] = data[start:start + e.get('body_size', 0)]
            want.discard(nh)
        if verbose:
            print(f"  {bname}: {len(hashes) - len(want)}/{total} found")
    return {h: cache[h] for h in hashes if h in cache}


def load_unit_bodies(hashes, contents: Path, verbose: bool = False
                     ) -> Dict[int, bytes]:
    """Unit bodies, by name hash (see load_bodies)."""
    return load_bodies(hashes, UNIT_TYPE_HASH, contents, verbose)


def load_level_bodies(hashes, contents: Path, verbose: bool = False
                      ) -> Dict[int, bytes]:
    """Level bodies, by name hash (sub-levels referenced by a level)."""
    return load_bodies(hashes, LEVEL_TYPE_HASH, contents, verbose)
    return {h: cache[h] for h in hashes if h in cache}


# -- mesh building -------------------------------------------------------------

def _mesh_attributes(mesh):
    verts = mesh.vertices
    positions = np.array([[v.position.x, v.position.y, v.position.z] for v in verts],
                         dtype=np.float32)
    normals = None
    if any(v.normal for v in verts):
        normals = np.array([[v.normal.x, v.normal.y, v.normal.z] if v.normal else (0, 1, 0)
                            for v in verts], dtype=np.float32)
    uvs = None
    if any(v.uv for v in verts):
        uvs = np.array([[v.uv.u, 1.0 - v.uv.v] if v.uv else (0, 0)
                        for v in verts], dtype=np.float32)
    return positions, normals, uvs


def _is_proxy_mesh(mesh) -> bool:
    """True for the Maya-default `lambert1` meshes a unit carries.

    Those are not render geometry: `crypt_wall_4c` ships an exact copy of its
    wall mesh under `lambert1`, `crypt_entrance_sand_01` ships twelve 24-vertex
    boxes (collision volumes) under it, and `caverock_stalagmites_01` duplicates
    the whole rock.  Rendering them is what makes a level look full of
    duplicates and stray boxes.
    """
    mats = [m for m in (mesh.materials or []) if m]
    return bool(mats) and all(m.lower() in PROXY_MATERIALS for m in mats)


def build_unit_meshes(builder: GltfBuilder, parser: UnitParser,
                      label: str) -> List[int]:
    """Add one glTF mesh per (mesh, shape) of a parsed unit; return mesh indices.

    No scene nodes are created - the caller instances these meshes once per
    placed entity.
    """
    ARRAY_BUFFER, ELEMENT_ARRAY = 34962, 34963
    mesh_indices: List[int] = []

    usable = [m for m in parser.meshes if m.vertices and not _is_proxy_mesh(m)]
    if not usable:                       # a handful of units are lambert1-only
        usable = [m for m in parser.meshes if m.vertices]

    for mi, mesh in enumerate(usable):
        if not mesh.vertices:
            continue
        positions, normals, uvs = _mesh_attributes(mesh)
        n = len(positions)

        if not mesh.shapes:
            ranges = [(0, len(mesh.indices), 0)]
        else:
            ranges = [(s.index_offset, s.index_count, s.material_index) for s in mesh.shapes]

        for si, (idx_off, idx_cnt, local_mat) in enumerate(ranges):
            raw = np.array(mesh.indices[idx_off:idx_off + idx_cnt], dtype=np.int64)
            if len(raw) == 0 or raw.max() >= n:
                continue
            used = np.unique(raw)
            remap = np.full(n, -1, dtype=np.int64)
            remap[used] = np.arange(len(used), dtype=np.int64)
            idx = remap[raw].astype(np.uint32)
            sub_pos = positions[used]
            sub_nrm = normals[used] if normals is not None else None
            sub_uv = uvs[used] if uvs is not None else None

            mat_name = (mesh.materials[local_mat]
                        if 0 <= local_mat < len(mesh.materials)
                        else f'material_{mi}_{si}')

            attrs: dict = {}
            pv = builder._add_buffer_view(sub_pos.tobytes(), ARRAY_BUFFER)
            attrs['POSITION'] = builder._add_accessor(
                pv, 'FLOAT', 'VEC3', len(sub_pos),
                min_vals=sub_pos.min(axis=0).tolist(),
                max_vals=sub_pos.max(axis=0).tolist())
            if sub_nrm is not None and len(sub_nrm) == len(sub_pos):
                nv = builder._add_buffer_view(sub_nrm.astype(np.float32).tobytes(),
                                              ARRAY_BUFFER)
                attrs['NORMAL'] = builder._add_accessor(nv, 'FLOAT', 'VEC3', len(sub_nrm))
            if sub_uv is not None and len(sub_uv) == len(sub_pos):
                uv = builder._add_buffer_view(sub_uv.astype(np.float32).tobytes(),
                                              ARRAY_BUFFER)
                attrs['TEXCOORD_0'] = builder._add_accessor(uv, 'FLOAT', 'VEC2', len(sub_uv))

            if idx.max() > 65535:
                comp, idx_data = 'UNSIGNED_INT', idx.astype(np.uint32).tobytes()
            else:
                comp, idx_data = 'UNSIGNED_SHORT', idx.astype(np.uint16).tobytes()
            iv = builder._add_buffer_view(idx_data, ELEMENT_ARRAY)
            ia = builder._add_accessor(iv, comp, 'SCALAR', len(idx),
                                       min_vals=[int(idx.min())],
                                       max_vals=[int(idx.max())])

            mesh_idx = len(builder.meshes)
            builder.meshes.append({
                'name': f'{label}_mesh{mi}_shape{si}',
                'primitives': [{'attributes': attrs, 'indices': ia,
                                'material': builder.get_or_create_material(mat_name)}],
            })
            mesh_indices.append(mesh_idx)
    return mesh_indices


def _quat_matrix(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def _trs_matrix(pos, quat, scale=(1.0, 1.0, 1.0)) -> np.ndarray:
    M = np.eye(4)
    M[:3, :3] = _quat_matrix(quat) * np.asarray(scale, dtype=np.float64)[None, :]
    M[:3, 3] = pos
    return M


def _add_instance(builder: GltfBuilder, mesh_indices: List[int], ent: Entity,
                  label: str, apply_scale: bool = False,
                  parent: Optional[np.ndarray] = None,
                  pivot: Optional[Tuple[float, float, float]] = None,
                  snap: float = 0.0, yaw_scale: float = 1.0,
                  yaw_offset: float = 0.0, swap_zw: bool = False) -> None:
    qx, qy, qz, qw = ent.quaternion_unit()
    if swap_zw:
        # f17 is the quaternion's Z and f0 its W (the reverse of the first guess)
        qz, qw = qw, qz
    if yaw_scale != 1.0 or yaw_offset:
        yaw = 2.0 * math.atan2(qz, qw) * yaw_scale + math.radians(yaw_offset)
        qz, qw = math.sin(yaw / 2.0), math.cos(yaw / 2.0)
        qx = qy = 0.0
    if snap:
        # The level's own valid (unit-quaternion) records put the yaw on exact
        # 45-degree multiples; the records that store a non-unit f0/f17 pair
        # decode a few degrees off those, so snapping recovers the intended set.
        yaw = math.atan2(qz, qw)
        step = math.radians(snap)
        yaw = round(yaw / step) * step
        qz, qw = math.sin(yaw), math.cos(yaw)
        qx = qy = 0.0
        n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
        qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    # NOTE: the record's f1,f2,f3 triple is *not* a render scale - it is a
    # region/size box.  Evidence: it is identical (e.g. 30x68x35) across every
    # entity of an area and lands on unrelated props (a chest carries the room's
    # box), and it reaches 110-270 on floor tiles, sarcophagi and decals, which
    # as a scale would build 800-2000-unit objects inside a 16-unit room.  So it
    # is left out of the transform (`--apply-scale` restores the literal reading).
    scale = (1.0, 1.0, 1.0) if not apply_scale else ent.scale
    for mesh_idx in mesh_indices:
        node: dict = {'name': f'{label}#{len(builder.nodes)}', 'mesh': mesh_idx}
        if pivot is None and parent is None:
            # glTF composes TRS as T*R*S, which is exactly what an unparented
            # entity needs; keep it readable.
            node['translation'] = [float(ent.position[0]), float(ent.position[1]),
                                   float(ent.position[2])]
            node['rotation'] = [qx, qy, qz, qw]
            node['scale'] = [float(scale[0]), float(scale[1]), float(scale[2])]
        else:
            local = _trs_matrix(ent.position, (qx, qy, qz, qw), scale)
            if pivot is not None:
                # rotate about the unit's own centre rather than its mesh origin
                P = np.eye(4)
                P[:3, 3] = -np.asarray(pivot, dtype=np.float64)
                local = local @ P
            world = local if parent is None else parent @ local
            node['matrix'] = [float(v) for v in world.flatten(order='F')]
        builder.nodes.append(node)
        builder.scenes[0]['nodes'].append(len(builder.nodes) - 1)



# -- name lookup ---------------------------------------------------------------

def _name_table() -> Dict[int, str]:
    """hash -> name from the catalogue + overlay (best effort, may be empty)."""
    import csv
    import json
    table: Dict[int, str] = {}
    cat = HERE.parent / 'Data' / 'bundle_manifest' / '04_bundle_resources.csv'
    ov = HERE.parent / 'Data' / 'resource_name_overlay.json'
    if cat.exists():
        with cat.open(newline='', encoding='utf-8', errors='replace') as fh:
            for r in csv.DictReader(fh):
                if r.get('name'):
                    table[int(r['name_hash'], 16)] = r['name']
    if ov.exists():
        for h, n in json.loads(ov.read_text()).items():
            table.setdefault(int(h, 16), n)
    return table


# -- converter -----------------------------------------------------------------

def _collect_placements(blob, level_hashes, sub_bodies, contents_dir, verbose,
                        max_depth, parent, ancestors, depth, out):
    """Append (entity, parent_matrix) for this level *and* every sub-level it places.

    A room level only carries its decoration; its shell is a placed sub-level
    (`..._adventure` -> `..._adventure_template`), so the composition has to be
    walked or the export shows a handful of props floating in the dark.
    """
    for e in parse_entities(blob):
        if e.template_hash:
            out.append((e, parent))
    if depth >= max_depth:
        return
    subs = parse_sublayers(blob, level_hashes)
    want = [s.name_hash for s in subs if s.name_hash not in sub_bodies]
    if want:
        sub_bodies.update(load_level_bodies(want, contents_dir, verbose=verbose))
    for s in subs:
        if s.name_hash in ancestors:
            continue
        body = sub_bodies.get(s.name_hash)
        if body is None:
            continue
        M = _trs_matrix(s.position, s.rotation, s.scale)
        world = M if parent is None else parent @ M
        _collect_placements(body, level_hashes, sub_bodies, contents_dir, verbose,
                            max_depth, world, ancestors | {s.name_hash},
                            depth + 1, out)


def convert_level_to_glb(level_path: str, out_path: Optional[str] = None,
                         contents: Optional[str] = None,
                         verbose: bool = False,
                         include_helpers: bool = False,
                         apply_scale: bool = False,
                         max_depth: int = 3,
                         pivot: str = 'origin',
                         rot_snap: float = 0.0,
                         yaw_scale: float = 1.0,
                         yaw_offset: float = 0.0,
                         swap_zw: bool = False) -> str:
    level_path = str(level_path)
    if out_path is None:
        out_path = os.path.splitext(level_path)[0] + '.glb'

    blob = Path(level_path).read_bytes()
    if not parse_entities(blob):
        raise ValueError(f"no entities decoded from {level_path}")

    contents_dir = _contents_dir(contents)
    names = _name_table()

    # walk the level and every sub-level it places
    level_hashes = known_level_hashes()
    sub_bodies: Dict[int, bytes] = {}
    placements: List[Tuple[Entity, Optional[np.ndarray]]] = []
    _collect_placements(blob, level_hashes, sub_bodies, contents_dir, verbose,
                        max_depth, None, frozenset(), 0, placements)

    templates = sorted({e.template_hash for e, _ in placements if e.template_hash})
    bodies = load_unit_bodies(templates, contents_dir, verbose=verbose)

    builder = GltfBuilder()
    builder.asset = {'version': '2.0', 'generator': 'Gauntlet-Stuff level_to_glb'}

    mesh_cache: Dict[int, List[int]] = {}
    center_cache: Dict[int, Tuple[float, float, float]] = {}
    placed = skipped = helper = 0
    tmpdir = tempfile.mkdtemp(prefix='gauntlet_level_')
    try:
        for e, parent in placements:
            th = e.template_hash
            name = names.get(th, '')
            if not include_helpers and is_helper(name):
                # editor/sky/logic unit - not visible geometry (see above)
                helper += 1
                continue
            if th not in mesh_cache:
                if th not in bodies:
                    skipped += 1
                    continue
                tmp_unit = os.path.join(tmpdir, f'{th:016x}.unit')
                with open(tmp_unit, 'wb') as fh:
                    fh.write(bodies[th])
                try:
                    parser = UnitParser(tmp_unit)
                    parser.parse()
                    label = (name.rsplit('/', 1)[-1] or f'{th:016x}')
                    mesh_cache[th] = build_unit_meshes(builder, parser, label)
                    if pivot in ('center', 'center_xy'):
                        vs = [v.position for m in parser.meshes for v in m.vertices]
                        if vs:
                            cz = 0.0 if pivot == 'center_xy' else (
                                min(v.z for v in vs) + max(v.z for v in vs)) / 2.0
                            center_cache[th] = (
                                (min(v.x for v in vs) + max(v.x for v in vs)) / 2.0,
                                (min(v.y for v in vs) + max(v.y for v in vs)) / 2.0,
                                cz,
                            )
                except Exception as exc:                            # noqa: BLE001
                    if verbose:
                        print(f"  unit {th:016x} failed: {exc}")
                    mesh_cache[th] = []
            if mesh_cache.get(th):
                label = (names.get(th, f'{th:016x}').rsplit('/', 1)[-1] or f'{th:016x}')
                _add_instance(builder, mesh_cache[th], e, label, apply_scale, parent,
                              center_cache.get(th), rot_snap, yaw_scale, yaw_offset, swap_zw)
                placed += 1
    finally:
        for f in os.listdir(tmpdir):
            try:
                os.unlink(os.path.join(tmpdir, f))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

    glb = builder.to_glb()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'wb') as fh:
        fh.write(glb)

    print(f"level -> glTF: {level_path}")
    print(f"  {len(placements)} entities ({len(sub_bodies)} sub-level(s) merged), "
          f"{len(templates)} unique templates "
          f"({placed} placed, {helper} helper entities skipped, "
          f"{skipped} with no unit on disk)")
    print(f"  {len([m for m in mesh_cache.values() if m])} template meshes, "
          f"{len(builder.nodes)} nodes -> {out_path}  ({len(glb):,} bytes)")
    return out_path


# -- CLI -----------------------------------------------------------------------

def _iter_levels(path: Path) -> List[Path]:
    if path.is_dir():
        return sorted(path.rglob('*.level'))
    return [path]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', nargs='?', help='a .level file or a directory of them')
    ap.add_argument('output', nargs='?', help='output .glb (single file input)')
    ap.add_argument('--export', help='export root; converts every named/**/*.level')
    ap.add_argument('--out', help='output directory when converting many levels')
    ap.add_argument('--contents', help='path to the game contents/ directory')
    ap.add_argument('--include-helpers', action='store_true',
                    help='keep editor/logic units (skydome, room_marker, markers, '
                         'invisible walls, spawn fields).  Off by default: the '
                         'skydome alone is ~16,000 units wide and swallows the level')
    ap.add_argument('--apply-scale', action='store_true',
                    help='apply the record f1,f2,f3 triple as a node scale.  Off by '
                         'default: that field is a region/size box, not a render '
                         'scale (see the module docstring), so applying it inflates '
                         'props by up to 270x')
    ap.add_argument('--max-depth', type=int, default=3,
                    help='how deep to follow placed sub-levels (default 3).  0 '
                         'exports only the level itself, which for a room level is '
                         'just its decoration layer')
    ap.add_argument('--pivot', choices=['origin', 'center', 'center_xy'], default='origin',
                    help='rotate each unit about its mesh origin (default) or about '
                         'its own centre.  The level places blocks on cell centres, '
                         'so a corner-origin block rotated about its origin slides '
                         'off its cell')
    ap.add_argument('--rotation-snap', type=float, default=0.0, metavar='DEG',
                    help='snap the decoded yaw to a multiple of DEG (45 or 90).  '
                         'The records that store a non-unit f0/f17 pair decode a few '
                         'degrees off the level\'s 45-degree grid')
    ap.add_argument('--swap-zw', action='store_true',
                    help='read f17 as the quaternion Z and f0 as W (the reverse of '
                         'the original guess); fixes the 180-degree flips')
    ap.add_argument('--yaw-offset', type=float, default=0.0, metavar='DEG',
                    help='add a constant yaw offset in degrees to every placed unit')
    ap.add_argument('--yaw-scale', type=float, default=1.0, metavar='K',
                    help='multiply the decoded yaw by K; 0.5 treats f0/f17 as '
                         '(sin,cos) of the yaw itself instead of of the half-angle')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    if args.input == 'selftest':
        sys.exit(selftest())

    if args.export:
        targets = sorted((Path(args.export).expanduser() / 'named').rglob('*.level'))
    elif args.input:
        targets = _iter_levels(Path(args.input).expanduser())
    else:
        ap.error('give a .level file, a directory, --export, or selftest')

    out_root = Path(args.out).expanduser() if args.out else None
    ok = 0
    for src in targets:
        dst = None
        if out_root is not None:
            dst = str(out_root / (src.stem + '.glb'))
        elif len(targets) == 1 and args.output:
            dst = args.output
        try:
            convert_level_to_glb(str(src), dst, args.contents, args.verbose,
                                 args.include_helpers, args.apply_scale,
                                 args.max_depth, args.pivot, args.rotation_snap, args.yaw_scale,
                                 args.yaw_offset, args.swap_zw)
            ok += 1
        except Exception as exc:                                    # noqa: BLE001
            print(f"FAIL {src}: {exc}")
    print(f"\nDone: {ok}/{len(targets)} levels exported")


def _glb_world_size(path: str) -> List[float]:
    """Rough world-space size of a GLB (per-accessor bounds, may over-estimate)."""
    import json as _json
    data = Path(path).read_bytes()
    off, gltf = 12, None
    while off < len(data):
        clen, ctype = struct.unpack_from('<II', data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            gltf = _json.loads(chunk)
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for node in gltf['nodes']:
        if 'mesh' not in node:
            continue
        if 'matrix' in node:
            # column-major per the spec
            M = np.array(node['matrix'], dtype=np.float64).reshape(4, 4).T
        else:
            t = node.get('translation', [0, 0, 0])
            s = node.get('scale', [1, 1, 1])
            M = _trs_matrix(t, node.get('rotation', [0, 0, 0, 1]), s)
        for prim in gltf['meshes'][node['mesh']]['primitives']:
            acc = gltf['accessors'][prim['attributes']['POSITION']]
            for corner in (acc['min'], acc['max']):
                p = M @ np.array([corner[0], corner[1], corner[2], 1.0])
                for k in range(3):
                    lo[k] = min(lo[k], p[k])
                    hi[k] = max(hi[k], p[k])
    return [hi[k] - lo[k] for k in range(3)]


def selftest() -> int:
    sample = (Path.home() / 'Documents/Coding/Gauntlet-Export/named/modules/d01_crypt'
              / 'room_crypt_floor_01_adventure.level')
    if not sample.exists():
        print("level_to_glb selftest: SKIP (sample not found)")
        return 0
    blob = sample.read_bytes()
    ents = parse_entities(blob)
    assert len(ents) == 371, f"expected 371 entities, got {len(ents)}"
    assert all(e.template_hash for e in ents), "every sample entity names a template"
    assert any(e.position != (0.0, 0.0, 0.0) for e in ents), "positions decoded"
    out = '/tmp/_selftest_level.glb'
    convert_level_to_glb(str(sample), out)
    data = open(out, 'rb').read()
    assert data[:4] == b'glTF' and len(data) > 1000
    # The room must not be swallowed by the skydome: its real content spans a few
    # hundred units, not the ~16,000 the helper units would add.
    size = _glb_world_size(out)
    assert max(size) < 1000, f"level world size {size} - helper units leaked in?"
    print(f"level_to_glb selftest: PASS  ({len(data):,} bytes, "
          f"world {size[0]:.0f}x{size[1]:.0f}x{size[2]:.0f})")
    os.unlink(out)
    return 0


if __name__ == '__main__':
    main()

