#!/usr/bin/env python3
"""Does the DEPLOYED level reproduce the author's GLB, computed with the ENGINE'S OWN formula?

Everything here comes from the code, not from intuition (RULE ZERO):

  * the placement matrix is FUN_0042d7f0's arithmetic - a NORMALISED four-float quaternion
    (x, y, z, w) turned into a matrix, k = 2/|q|^2 (FINDINGS 9H.34);
  * a record's quaternion is (f60, f64, f68, f0) and its position is at 48;
  * the engine frame is the Blender frame, so the authored world orientation is
    R_x(+90) . R_node . R_x(-90) and our unit's mesh is R_x(+90) . v_file.

So: for every placement, does the rotation the engine will build from the deployed record equal
the authored one, and does every deployed unit's mesh equal the GLB's mesh in the engine frame?
If both hold to float precision, then the game renders the .blend for this content and any
remaining difference is not in the pipeline.

ONE THING IS DELIBERATELY NOT EQUAL (FINDINGS 9H.41): a unit whose mesh build_own_units.py moved
onto its template's collider box.  The move is undone on the placement, so pass
`--unit-offsets <the build's unit_offsets.json>` and both halves are measured with it - the record
plus the vector the engine applies has to land on the authored node, and the unit's mesh minus it
has to equal the GLB's mesh.  Without the file a shifted level reports a mismatch of exactly that
vector, which is the tool telling the truth.

usage: check_deployed_placement.py <deployed level> <glb> [<unit file>=<base name> ...]
                                   [--unit-offsets <unit_offsets.json>]
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from resource_tools.level_tools import quat_from_record_vector       # noqa: E402
from level_from_glb import base_name, quat_rotate                    # noqa: E402


def read_glb(path: Path):
    raw = path.read_bytes()
    total = struct.unpack_from('<I', raw, 8)[0]
    off, js, bin0 = 12, None, b''
    while off < total:
        clen, _t = struct.unpack_from('<II', raw, off)
        kind = raw[off + 4:off + 8]
        if kind == b'JSON':
            js = json.loads(raw[off + 8:off + 8 + clen].decode('utf-8'))
        elif kind == b'BIN\x00' and not bin0:
            bin0 = raw[off + 8:off + 8 + clen]
        off += 8 + clen + ((-clen) % 4)
    return js, bin0


def accessor(js, bin0, index, comps):
    a = js['accessors'][index]
    bv = js['bufferViews'][a['bufferView']]
    fmt = {5126: 'f', 5125: 'I', 5123: 'H', 5121: 'B'}[a['componentType']]
    size = struct.calcsize(fmt)
    stride = bv.get('byteStride') or size * comps
    start = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    return [struct.unpack_from('<' + fmt * comps, bin0, start + i * stride)
            for i in range(a['count'])]


def quat_mat(q):
    """FUN_0042d7f0's arithmetic, verbatim: normalised quaternion -> 3x3 rotation."""
    x, y, z, w = q
    d = x * x + y * y + z * z + w * w
    if d <= 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    k = 2.0 / d
    return [[1 - k * (y * y + z * z), k * (x * y + w * z), k * (x * z - w * y)],
            [k * (x * y - w * z), 1 - k * (x * x + z * z), k * (y * z + w * x)],
            [k * (x * z + w * y), k * (y * z - w * x), 1 - k * (x * x + y * y)]]


def mat_of_quat_gltf(q):
    """The glTF node's rotation as a matrix ((x,y,z,w), unit or not)."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def apply(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


RX90 = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]        # file -> engine (Z-up)
RX90T = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]       # engine -> file


def quat_angle_deg(a, b):
    """Angle between two rotations given as (x, y, z, w).  q and -q are the same rotation."""
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))


def conj_by_rx90(q):
    """The authored quaternion in the ENGINE frame: R_x(+90) . R_node . R_x(-90), as (x,y,z,w).

    The engine's matrices and the glTF matrices are written in opposite conventions
    (FUN_0042d7f0 has m01 = k(xy+wz), m10 = k(xy-wz) - a transpose of the glTF form), so
    comparing matrices across the two is meaningless.  Comparing the ROTATIONS as quaternions
    is convention-free, which is what this does.
    """
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    # conjugate by R_x(+90): (x, -z, y) for the vector, w unchanged
    return [x, -z, y, w]


def unit_mesh_vertices(path: Path):
    """The vertices of a .unit's first mesh block (the layout build_own_units writes)."""
    d = path.read_bytes()
    count = struct.unpack_from('<I', d, 4)[0]
    vbuf = struct.unpack_from('<I', d, 8)[0]
    o = 12 + vbuf + 8
    vc, stride, _ec = struct.unpack_from('<III', d, o)
    verts = [struct.unpack_from('<3f', d, 12 + i * stride) for i in range(vc)]
    return count, vc, stride, verts


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    level = Path(sys.argv[1])
    glb = Path(sys.argv[2])
    rest = sys.argv[3:]
    offsets_file = None
    if '--unit-offsets' in rest:
        i = rest.index('--unit-offsets')
        if i + 1 >= len(rest):
            print('--unit-offsets wants a file')
            return 1
        offsets_file = Path(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    own = [a.split('=') for a in rest]                  # <unit file>=<base name>
    offsets = {}
    if offsets_file:
        raw = json.loads(offsets_file.read_text())
        offsets = (raw.get('bases') or {}) if isinstance(raw, dict) else {}
        print('collider shift: %d unit kind(s) from %s - the level moved those placements back by '
              'the same vector, so it is added here before comparing (FINDINGS 9H.41)'
              % (len(offsets), offsets_file.name))

    js, bin0 = read_glb(glb)
    nodes = {}
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        base = base_name(node.get('name', ''))
        nodes.setdefault(base, []).append((node.get('name'),
                                           node.get('translation', [0, 0, 0]),
                                           node.get('rotation', [0, 0, 0, 1]),
                                           node.get('scale', [1, 1, 1])))

    # ---- 1. placements: the engine's matrix vs the authored one -----------------
    blob = level.read_bytes()
    n = struct.unpack_from('<I', blob, 4)[0]
    print('1. PLACEMENTS - the engine\'s matrix (FUN_0042d7f0) vs the GLB node')
    print('   the record holds FOUR consecutive floats at +0x3c (9H.36): the vector at 60/64/68')
    print('   and the w at 72, i.e. the NEXT record\'s offset 0.')
    worst = 0.0
    for i in range(n):
        o = 128 + i * 72
        pos = struct.unpack_from('<3f', blob, o + 48)
        q4 = struct.unpack_from('<4f', blob, o + 60)
        q_engine = quat_from_record_vector(list(q4[:3]), q4[3])
        best, best_d = None, 1e9
        for group in nodes.values():
            for name, t, nq, s in group:
                pt = apply(RX90, t)
                d = offsets.get(base_name(name))
                if d:
                    # the placement was moved back by this vector; the engine applies the record's
                    # rotation and the placement's scale to it, so the authored node is the record
                    # PLUS it - subtract to bring the authored point into the file's frame
                    w = quat_rotate(q_engine, (d[0] * s[0], d[1] * s[1], d[2] * s[2]))
                    pt = [pt[k] - w[k] for k in range(3)]
                d_ = sum((pt[k] - pos[k]) ** 2 for k in range(3)) ** 0.5
                if d_ < best_d:
                    best, best_d = (name, t, nq, s), d_
        if best is None or best_d > 0.05:
            print('   rec %2d  no GLB node at %s (closest %.4f)' % (i, pos, best_d))
            continue
        name, t, nq, s = best
        err = quat_angle_deg(q_engine, conj_by_rx90(nq))
        worst = max(worst, err)
        print('   rec %2d  %-20s engine-from-record vs authored: %8.4f deg%s'
              % (i, name, err, '   *** MISMATCH' if err > 0.05 else ''))
    print('   worst placement error: %.4f deg' % worst)

    # ---- 2. units: the deployed mesh vs R_x(90) . (the GLB mesh) ----------------
    print()
    print('2. UNITS - the .unit\'s mesh vs the GLB mesh rotated into the engine frame')
    for spec in own:
        upath, base = Path(spec[0]), spec[1]
        if not upath.exists():
            print('   %s is missing' % upath)
            continue
        count, vc, stride, verts = unit_mesh_vertices(upath)
        if base not in nodes:
            print('   %-16s no GLB node named %s' % (base, base))
            continue
        name = nodes[base][0][0]
        node = [nd for nd in js['nodes'] if nd.get('name') == name][0]
        prim = js['meshes'][node['mesh']]['primitives'][0]
        src = accessor(js, bin0, prim['attributes']['POSITION'], 3)
        worst_v = 0.0
        d = offsets.get(base, [0.0, 0.0, 0.0])
        for i in range(min(len(src), vc)):
            want = apply(RX90, src[i])
            want = [want[k] + d[k] for k in range(3)]      # the collider shift (9H.41)
            got = verts[i]
            worst_v = max(worst_v, max(abs(want[k] - got[k]) for k in range(3)))
        print('   %-16s %5d verts, stride %d : worst vertex error %.6f%s%s'
              % (base, vc, stride, worst_v, '   *** MISMATCH' if worst_v > 1e-4 else '',
                 '' if not any(d) else '   (unit shifted by %s)'
                 % ', '.join('%+.2f' % v for v in d)))

    print()
    print('Both halves are the code\'s own arithmetic.  If they pass, the game renders the .blend'
          ' for this content and any difference left is NOT in the pipeline.')
    return 0


if __name__ == '__main__':
    sys.exit(main())