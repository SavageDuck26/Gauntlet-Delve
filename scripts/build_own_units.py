#!/usr/bin/env python3
"""
Build the author's OWN units from a Blender export, the way the engine packs them.

WHY THIS EXISTS (FINDINGS 9H.28).  A level places UNITS by hash; it cannot carry geometry.  So a
level authored from custom meshes only works if those meshes ship as unit resources - which is
what the game itself does, and what Data/CUSTOM_ASSET_LOADING_FINDINGS.md #10 proved in game.

The grouping rule is the one the author asked for, and it is the engine's own: A NODE'S NAME IS
THE UNIT.  Nodes whose names share a base name (`Floor`, `Floor.001`, `Floor.002`) are the same
unit placed several times, so they become ONE unit resource and N placements.  Blender's `.001`
and `#123` suffixes are stripped, exactly as level_from_glb resolves game unit names.

The mesh is spliced into a NATIVE TEMPLATE with glb_to_template_unit's own trick: keep the
template's trailer (collision actors, flow data, the 32-byte footer whose material hash is the
binding) and replace only its mesh section.  That is why the template choice matters - it
decides the physics and the material - and why a floor tile should be built from a floor tile.

AND THE MESH COUNT HAS TO MATCH (FINDINGS 9H.31).  A native unit's trailer is serialized for the
template's OWN mesh list, so the body must declare the same number of mesh blocks: splicing a
1-mesh body into a 2-mesh or 5-mesh template (crypt_pillar_01 has 2, crypt_stairs_low_4c has 5)
makes the engine build a mesh list with a non-zero size and a NULL array, and the first pass
that dereferences it crashes the load - `access read at 00000008`, RVA 0x00270259.  So the
generated mesh block is replicated to the template's mesh count (each block is self-contained:
its own vertex/element/index/shape/material tables).  `--no-duplicate-meshes` refuses instead,
which forces a template whose count is already 1.

The vertices are rotated into the ENGINE'S frame, because a unit's mesh is stored in engine space:
the record's rotation is applied to it at run time, and the game's own units are Z-up.  WHICH
rotation is MEASURED, not assumed: the averaged vertex normals say which way the export's mesh
data faces, and the change is the one that takes that up-direction onto the engine's +Z.  A
normal Blender +Y-up export (floors whose normals average to +Y) gets +90 about X, exactly as
before; a file exported with Z up, or one whose mesh data is already engine-space, gets 0 - and
assuming +90 there would have tilted every unit 90 degrees.  `--mesh-frame auto|y-up|engine`
overrides the measurement when there is nothing to measure.

Usage:
  build_own_units.py <export.glb> <template.unit> <base_name>=<unit/path> [...] --out <dir>
  build_own_units.py <export.glb> <template.unit> Floor=units/custom/x/floor --out=dir --mesh-frame=engine
"""
import json
import numpy as np
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gltf_to_unit import encode_unit                       # noqa: E402
from glb_to_template_unit import (read_u32, splice_into_template,   # noqa: E402
                                  unit_mesh_end, UNIT_SIGNATURE)
# The SAME name filter the level converter uses (level_from_glb.IGNORE_NAME_SUBSTRINGS /
# ignored_node): a node the author marked as scratch must not be placed AND must not become one
# of our units, or the package would ship a unit nothing references.
from level_from_glb import IGNORE_NAME_SUBSTRINGS, ignored_node     # noqa: E402

# The rotation about X, in degrees, that maps the export's mesh up onto the engine's +Z - i.e.
# exactly the inverse of the level tool's `deg_mesh` (level_from_glb.detect_mesh_up), which is
# what keeps a placed unit and the placement's record in the same frame.
UP_TO_DEG = {'+Y': 90, '-Y': -90, '+Z': 0, '-Z': 180}


def read_glb(path: Path):
    raw = path.read_bytes()
    total = struct.unpack_from('<I', raw, 8)[0]
    off, js, bin0 = 12, None, b''
    while off < total:
        clen, _ctype = struct.unpack_from('<II', raw, off)
        kind = raw[off + 4:off + 8]
        if kind == b'JSON':
            js = json.loads(raw[off + 8:off + 8 + clen].decode('utf-8'))
        elif kind == b'BIN\x00' and not bin0:
            bin0 = raw[off + 8:off + 8 + clen]
        off += 8 + clen + ((-clen) % 4)
    return js, bin0


def accessor(js, bin0, index, kind):
    a = js['accessors'][index]
    bv = js['bufferViews'][a['bufferView']]
    comps = {'VEC3': 3, 'VEC2': 2, 'SCALAR': 1}[a['type']]
    fmt = {5126: 'f', 5125: 'I', 5123: 'H', 5121: 'B'}[a['componentType']]
    size = struct.calcsize(fmt)
    start = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride') or comps * size
    out = []
    for i in range(a['count']):
        base = start + i * stride
        out.append(struct.unpack_from('<' + fmt * comps, bin0, base))
    return out


def base_name(name: str) -> str:
    """`Floor.001`, `Stair#12`, `Floor.003#7` all reduce to the unit's base name."""
    for sep in ('#', '.'):
        if sep in name:
            head, tail = name.split(sep, 1)
            if sep == '.' and not tail[:1].isdigit():
                continue
            name = head
    return name.strip()


def rotate_x(verts, deg):
    """Rotate vertices about X by a multiple of 90 degrees: the file's mesh frame -> engine.

    The four cases, and what each one means:
        +90   (x, y, z) -> (x, -z, y)     the export is Y-up: every normalised Blender
                                          export, and what every unit built so far used
        -90   (x, y, z) -> (x, z, -y)     Y-up but upside down (the old Base.glb's floor
                                          normals averaged to (0, -1, 0))
        0     unchanged                   the mesh data is ALREADY engine-space (Z-up)
        180   (x, y, z) -> (x, -y, -z)    engine-space but upside down
    """
    if deg == 0:
        return [(v[0], v[1], v[2]) for v in verts]
    if deg == 90:
        return [(v[0], -v[2], v[1]) for v in verts]
    if deg == -90:
        return [(v[0], v[2], -v[1]) for v in verts]
    return [(v[0], -v[1], -v[2]) for v in verts]


def mesh_up(js, bin0):
    """Which way the export's MESH DATA faces, from the averaged vertex normals.

    Returns (a signed axis name, an explanation).  A floor tile's averaged normal IS the mesh's
    up direction, and it is the one measurement that says which of the four rotations above the
    file needs - the same measurement level_from_glb makes for the record's rotation, so the
    unit and its placement cannot disagree.

    Only FLAT geometry votes.  A prop's normals cancel out (the crane's average to (0, 0.014,
    0.002), a stair's to (-0.004, -0.253, 0.264)) - so the votes come from the floors, which is
    exactly the geometry that answers the question.
    """
    votes = {}
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        for prim in js['meshes'][node['mesh']]['primitives']:
            if 'NORMAL' not in prim['attributes']:
                continue
            acc = js['accessors'][prim['attributes']['POSITION']]
            ext = [acc['max'][i] - acc['min'][i] for i in range(3)]
            if max(ext) <= 0.0 or min(ext) > 0.05 * max(ext):
                continue                       # a prop or a cube: no evidence about up
            ns = accessor(js, bin0, prim['attributes']['NORMAL'], 'VEC3')
            if len(ns) < 3:
                continue
            avg = [sum(v[i] for v in ns) / len(ns) for i in range(3)]
            if math.sqrt(sum(c * c for c in avg)) < 0.5:
                continue
            best, best_v = None, 0.7
            for i, name in enumerate(('+X', '-X', '+Y', '-Y', '+Z', '-Z')):
                sign = -1.0 if i % 2 else 1.0
                if sign * avg[i // 2] > best_v:
                    best, best_v = name, sign * avg[i // 2]
            if best:
                votes[best] = votes.get(best, 0) + 1
    if not votes:
        return None, ('no flat mesh with usable normals - nothing to measure, so the meshes are '
                      'assumed to be in the same frame as a normal Blender +Y-up export')
    top = max(votes, key=lambda k: votes[k])
    return top, ('%d flat mesh normal(s) average to %s - the MESH data is %s'
                 % (votes[top], top,
                    'engine-space (Z-up) already' if top in ('+Z', '-Z')
                    else 'Y-up, so the vertices need rotating into the engine\'s frame'))


def main():
    argv = sys.argv[1:]
    if len(argv) < 4:
        print(__doc__)
        return 1
    glb, template = Path(argv[0]), Path(argv[1])
    mapping, out_dir, frame, duplicate_meshes = {}, None, 'auto', True
    for a in argv[2:]:
        if a == '--out':
            continue
        if a.startswith('--out='):
            out_dir = Path(a.split('=', 1)[1])
        elif a == '--no-duplicate-meshes':
            duplicate_meshes = False
        elif a.startswith('--mesh-frame='):
            frame = a.split('=', 1)[1]
            if frame not in ('auto', 'y-up', 'engine'):
                raise SystemExit('--mesh-frame wants auto, y-up or engine')
        elif '=' in a:
            name, path = a.split('=', 1)
            mapping[base_name(name)] = path
        elif out_dir is None and '/' in a:
            out_dir = Path(a)
    if not mapping or out_dir is None:
        print('need <base>=<unit/path> pairs and --out <dir>')
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    js, bin0 = read_glb(glb)
    if frame == 'auto':
        up, why = mesh_up(js, bin0)
    else:
        up, why = {'y-up': '+Y', 'engine': '+Z'}[frame], \
            'FORCED by --mesh-frame %s' % frame
    deg = UP_TO_DEG.get(up or '+Y', 90)
    if up is None:
        deg = 90                               # the historical behaviour, and it is stated
    elif up in ('+X', '-X'):
        print('WARNING: the flat meshes face %s, which no rotation about X can turn into the'
              ' engine\'s +Z - building them as if they were Y-up (+90).  Re-export the level'
              ' with its up axis on Y or Z.' % up)
        deg = 90
    groups = {}
    ignored = []
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            ignored.append(node.get('name', ''))
            continue
        b = base_name(node.get('name', ''))
        if b in mapping:
            groups.setdefault(b, []).append(node)

    tpl = template.read_bytes()
    if read_u32(tpl, 0) != UNIT_SIGNATURE:
        raise SystemExit('%s is not a unit file' % template)
    tpl_meshes = read_u32(tpl, 4)      # the mesh count the trailer was serialized against

    print('export   : %s (%d nodes)' % (glb.name, len(js['nodes'])))
    print('mesh up  : %s' % why)
    print('           -> vertices rotated %+d degrees about X into engine Z-up%s'
          % (deg, '' if deg else ' (already engine-space, no rotation)'))
    if ignored:
        print('ignored  : %d node(s) whose name carries %s - no unit is built from them'
              % (len(ignored), '/'.join(repr(s) for s in IGNORE_NAME_SUBSTRINGS)))
    print('template : %s (%d bytes, %d mesh(es), trailer %d bytes)'
          % (template.name, len(tpl), tpl_meshes, len(tpl) - unit_mesh_end(tpl)))
    print()
    for base, nodes in sorted(groups.items()):
        # EVERY PRIMITIVE, not just the first.  A glTF mesh with N primitives is N material
        # groups over one surface (the stair's mesh is 2: 106 verts + 60 verts, two materials),
        # and the engine's unit model is one material group per mesh block - so dropping the
        # later primitives drops geometry the author authored.  They are merged into the block
        # with the mesh's first material name.
        src = js['meshes'][nodes[0]['mesh']]
        pos, nrm, uv, idx = [], [], [], []
        prim_sizes = []
        for prim in src['primitives']:
            p = accessor(js, bin0, prim['attributes']['POSITION'], 'VEC3')
            n = accessor(js, bin0, prim['attributes']['NORMAL'], 'VEC3') \
                if 'NORMAL' in prim['attributes'] else [(0.0, 0.0, 1.0)] * len(p)
            u = accessor(js, bin0, prim['attributes']['TEXCOORD_0'], 'VEC2') \
                if 'TEXCOORD_0' in prim['attributes'] else [(0.0, 0.0)] * len(p)
            i = [v[0] for v in accessor(js, bin0, prim['indices'], 'SCALAR')]
            off = len(pos)
            pos += [tuple(v) for v in p]
            nrm += [tuple(v) for v in n]
            uv += [tuple(v) for v in u]
            idx += [k + off for k in i]
            prim_sizes.append('%d+%d' % (len(p), len(i) // 3))
        mesh = {
            'name': 'm_%s' % base.lower().replace(' ', '_'),
            'positions': np.array(rotate_x(pos, deg), dtype=np.float32),
            'normals': np.array(rotate_x(nrm, deg), dtype=np.float32),
            'uvs': np.array(uv, dtype=np.float32),
            'indices': np.array(idx, dtype=np.int64),
        }
        generated = encode_unit([mesh])
        try:
            unit, _tpl_meshes, written = splice_into_template(
                generated, tpl, allow_duplicate=duplicate_meshes)
        except ValueError as exc:
            raise SystemExit('%s: %s' % (base, exc))
        unit_path = mapping[base]
        fname = out_dir / (unit_path.replace('/', '_') + '.unit')
        fname.write_bytes(unit)
        print('%-16s -> %-44s %2d placement(s)  %d verts  %d tris  %d bytes  '
              '(%d mesh block(s), %d primitive(s): %s)'
              % (base, unit_path, len(nodes), len(pos), len(idx) // 3, len(unit), written,
                 len(prim_sizes), ' '.join(prim_sizes)))
    print()
    print('unit paths (hash these into the level):')
    for base, path in sorted(mapping.items()):
        print('   %-16s %s' % (base, path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
