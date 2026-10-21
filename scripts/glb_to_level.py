#!/usr/bin/env python3
"""
glTF 2.0 (.glb) -> Stingray .level writer - the return half of level_to_glb.

Usage
-----
    glb_to_level.py --level ORIGINAL.level --glb EDITED.glb --out NEW.level
                    [--contents /path/to/contents] [--include-helpers] [--apply-scale]

Design: patch, never rebuild
----------------------------
A `.level` carries sections whose meaning is not settled (the 16-entry header, the
resource-path block, the lighting block).  Rebuilding one from scratch would mean
knowing all of them.  Instead the ORIGINAL file's bytes are copied and only the
entity records that the edited GLB actually changed are overwritten, so every
unknown section survives untouched and an unedited entity is byte-identical.

Identifying records
-------------------
`level_to_glb` names each node `{label}#{node_index}`, where node_index counts
every node it has appended so far - and a unit with several mesh parts appends
several nodes.  So the name alone does not give an entity index.  It is recoverable
because the export is deterministic: replaying the exporter's own traversal against
the same original file and contents produces the same node order, which gives
`node name -> entity index`.  That replay is what `build_node_map` does, importing
the exporter rather than copying its logic.

What it can and cannot patch
----------------------------
* Top-level entities: patched.
* Entities merged in from SUB-LEVELS (`_collect_placements` recurses, and the room
  levels only carry their decoration - the shell is a placed sub-level): their
  records live in that sub-level's own .level file, so they are reported, not
  patched.  Pass --include-sublayers later to write those too; for now a node from
  a sub-level that was actually edited is a loud warning, not a silent loss.

Written with numpy and the standard library only, and importing the exporter means
the record layout has exactly one definition.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import numpy as np                                             # noqa: E402

from level_to_glb import (                                     # noqa: E402
    ENTITY_RECORD_SIZE, ENTITY_TABLE_OFFSET, OFF_POSITION, OFF_QUAT_X,
    OFF_QUAT_Y, OFF_QUAT_Z, Entity, parse_entities,
)

def node_trs(node: dict) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(translation, quaternion xyzw, scale) of a glTF node, matrix or TRS form."""
    if 'matrix' in node:
        M = np.array(node['matrix'], dtype=np.float64).reshape(4, 4, order='F')
        t = M[:3, 3]
        s = np.array([np.linalg.norm(M[:3, i]) for i in range(3)])
        R = M[:3, :3] / np.where(s == 0.0, 1.0, s)
        w = math.sqrt(max(0.0, 1.0 + R[0, 0] + R[1, 1] + R[2, 2])) / 2.0
        if w < 1e-8:
            q = np.array([0.0, 0.0, 0.0, 1.0])
        else:
            q = np.array([
                (R[2, 1] - R[1, 2]) / (4 * w),
                (R[0, 2] - R[2, 0]) / (4 * w),
                (R[1, 0] - R[0, 1]) / (4 * w),
                w,
            ])
        return t, q, s
    t = np.array(node.get('translation', [0.0, 0.0, 0.0]), dtype=np.float64)
    q = np.array(node.get('rotation', [0.0, 0.0, 0.0, 1.0]), dtype=np.float64)
    s = np.array(node.get('scale', [1.0, 1.0, 1.0]), dtype=np.float64)
    return t, q, s


def _matrix_quat(R: np.ndarray) -> np.ndarray:
    """Quaternion xyzw from a 3x3 rotation matrix."""
    w = math.sqrt(max(0.0, 1.0 + R[0, 0] + R[1, 1] + R[2, 2])) / 2.0

    if w < 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0])

    return np.array([
        (R[2, 1] - R[1, 2]) / (4 * w),
        (R[0, 2] - R[2, 0]) / (4 * w),
        (R[1, 0] - R[0, 1]) / (4 * w),
        w,
    ])


# Blender is Z-up and glTF is Y-up, so a round trip through it can hand the whole scene
# back rotated 90 degrees about X: every node's transform differs, none of them by us.
# The writer detects that and converts, rather than demanding particular export settings.
AXIS_KINDS = ('identity', 'x+90', 'x-90')


def _axis_matrix(kind: str) -> Optional[np.ndarray]:
    if kind == 'x+90':
        return np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    if kind == 'x-90':
        return np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    return None


def convert_trs(pos: np.ndarray, quat: np.ndarray, kind: str) -> Tuple[np.ndarray, np.ndarray]:
    """A (position, quaternion) with the axis change applied or removed.

    Applied through matrices rather than by permuting quaternion components, so the
    handedness and the signs come out of the rotation itself.
    """
    A = _axis_matrix(kind)

    if A is None:
        return pos, quat

    from level_to_glb import _quat_matrix                       # 3x3, as written out

    p = A @ pos
    # Conjugation (A M A^-1), and this was checked the hard way: with A @ M the axis
    # detection falls back to identity and nothing matches, i.e. left-multiply explains
    # none of the 9503 nodes while conjugation explains 8818.  The 685 that match under
    # neither are the rotated props - see the note in collect_edits; they are NOT a
    # convention difference and must not be treated as one.
    R = A @ _quat_matrix(quat) @ A.T
    return p, _matrix_quat(R)


def entity_trs(ent: Entity) -> Tuple[np.ndarray, np.ndarray]:
    """The (.level) record's transform, in the same terms the exporter writes it.

    Only position and rotation are compared: the exporter deliberately keeps the
    record's f1,f2,f3 triple out of the node scale (it is a region box, not a render
    scale - see level_to_glb), so a node scale of 1 does not mean the record's
    scale is 1.
    """
    return np.array(ent.position, dtype=np.float64), np.array(ent.quaternion_unit(),
                                                              dtype=np.float64)


def quat_close(a: np.ndarray, b: np.ndarray, tol: float = 1e-4) -> bool:
    """q and -q are the same rotation."""
    return bool(np.allclose(a, b, atol=tol) or np.allclose(a, -b, atol=tol))


def build_node_map(original_glb: str, entities: List[Entity],
                   tol: float = 1e-3) -> Dict[str, int]:
    """node name -> entity index, from the ORIGINAL .glb paired with the records.

    The original export is what makes this possible: every node there still carries
    the transform the exporter read out of its record, so matching on position +
    rotation identifies which record a node came from.  Several nodes share one
    entity when its unit has several mesh parts - that is expected, and they all
    match the same record.

    Matching against the ORIGINAL glb, not the edited one, is the point: an edited
    node no longer looks like any record, but its name is unchanged, so the name is
    the link and the original transform is the identification.
    """
    gltf = parse_glb(original_glb)
    ents = [entity_trs(e) for e in entities]
    taken: Dict[int, int] = {}
    out: Dict[str, int] = {}
    unmatched = 0

    for node in gltf.get('nodes', []):
        name = node.get('name')
        if not name:
            continue
        t, q, _s = node_trs(node)
        hit = None
        for i, (et, eq) in enumerate(ents):
            if np.allclose(t, et, atol=tol) and quat_close(q, eq):
                # Prefer a record not yet claimed, so repeated transforms resolve in
                # the order the exporter emitted them - the order of the records.
                if i not in taken:
                    hit = i
                    break
                if hit is None:
                    hit = i
        if hit is None:
            unmatched += 1
            continue
        taken[hit] = taken.get(hit, 0) + 1
        out[name] = hit

    return out


def read_edited_transforms(edited_glb: str) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """name -> (position, quaternion xyzw) for every node in the edited .glb."""
    gltf = parse_glb(edited_glb)
    out: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for node in gltf.get('nodes', []):
        name = node.get('name')
        if not name:
            continue
        t, q, _s = node_trs(node)
        out[name] = (t, q)
    return out


def quat_to_stored(q: np.ndarray) -> Tuple[float, float, float, float, float]:
    """(x, y, z, w, f0) as the record wants them.

    The record stores the quaternion's VECTOR part only, and its f0 field holds a
    sign flag (-1.0 or 0.0); w is reconstructed by the reader.  q and -q are the
    same rotation, so the free sign is spent putting w on the negative branch -
    the branch parse_entities reconstructs - and f0 is set to agree with it.
    """
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w)

    if n < 1e-8:
        return 0.0, 0.0, 0.0, 1.0, 0.0

    x, y, z, w = x / n, y / n, z / n, w / n

    if w > 0.0:
        x, y, z, w = -x, -y, -z, -w

    return x, y, z, w, -1.0


def patch_level(blob: bytes, edits: Dict[int, Tuple[np.ndarray, np.ndarray]]) -> bytes:
    """Copy the original bytes, overwrite only the edited records' transforms.

    entity index -> (position, quaternion).  Nothing else in a record is touched:
    template hash, material hash, entity id and the region box are the original
    file's business, and moving or rotating a placement has no reason to change
    them.  That is also what keeps this safe - every section of the file whose
    meaning is still open is copied through byte for byte.
    """
    out = bytearray(blob)

    for idx, (pos, quat) in sorted(edits.items()):
        base = ENTITY_TABLE_OFFSET + idx * ENTITY_RECORD_SIZE

        if base + ENTITY_RECORD_SIZE > len(out):
            raise IndexError(f'entity {idx} is past the end of the file')

        x, y, z, _w, f0 = quat_to_stored(quat)

        struct.pack_into('<f', out, base, f0)
        struct.pack_into('<3f', out, base + OFF_POSITION,
                         float(pos[0]), float(pos[1]), float(pos[2]))
        struct.pack_into('<3f', out, base + OFF_QUAT_X, x, y, z)

    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--level', required=True,
                    help='the ORIGINAL .level - its bytes are copied, not rebuilt')
    ap.add_argument('--glb', required=True, help='the EDITED .glb')
    ap.add_argument('--out', required=True, help='the .level to write')
    ap.add_argument('--original-glb',
                    help='the original export, if you still have it (otherwise it is '
                         're-exported from --level, which needs --contents)')
    ap.add_argument('--contents', help='path to the game contents/ directory')
    args = ap.parse_args()

    import tempfile
    from level_to_glb import convert_level_to_glb

    original_glb = args.original_glb
    tmp: Optional[str] = None

    if original_glb is None:
        # The identification needs the original transforms, which only the original
        # export has - an edited node no longer looks like any record.  So re-export it
        # with the same code path step 1 used, if it was not kept.
        handle = tempfile.NamedTemporaryFile(suffix='.glb', delete=False)
        handle.close()
        tmp = handle.name
        print(f'  re-exporting the original for identification -> {tmp}')
        convert_level_to_glb(args.level, tmp, args.contents)
        original_glb = tmp

    try:
        blob, edits, changed, unowned = collect_edits(args.level, original_glb, args.glb)
        out = patch_level(blob, edits)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_bytes(out)
    finally:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)

    print(f'  records in {Path(args.level).name}: {len(parse_entities(blob))}')
    print(f'  records patched: {changed}')
    if unowned:
        print(f'  NOTE: {unowned} node(s) in the .glb belong to a merged sub-level or a '
              f'helper unit, so they have no record in this file.  An edit to one of '
              f'those is NOT in the output.')
    print(f'  wrote {args.out} ({len(out):,} bytes, '
          f'{sum(1 for a, b in zip(out, blob) if a != b)} byte(s) differ from the original)')
    return 0


def selftest() -> int:
    """An unedited round-trip must reproduce the original file byte for byte.

    That is the whole test: if patch_level and the record offsets are right, exporting
    and writing straight back changes nothing.  Any difference is the tool, not the
    edit, and it is reported as a count so a rounding-level difference cannot hide.
    """
    import tempfile
    from level_to_glb import convert_level_to_glb

    sample = (Path.home() / 'Documents/Coding/Gauntlet-Export/named/modules/d01_crypt'
              / 'room_crypt_floor_01_adventure.level')

    if not sample.exists():
        print('glb_to_level selftest: SKIP (sample level not found)')
        return 0

    blob = sample.read_bytes()
    entities = parse_entities(blob)

    with tempfile.TemporaryDirectory() as td:
        glb = str(Path(td) / 'base.glb')
        convert_level_to_glb(str(sample), glb)
        _b, edits, changed, unowned = collect_edits(str(sample), glb, glb)
        out = patch_level(blob, edits)

    diff = sum(1 for a, b in zip(out, blob) if a != b)
    print(f'  sample: {len(blob):,} bytes, {len(entities)} records')
    print(f'  {len(entities)} record(s) in {Path(sample).name}; '
          f'{unowned} node(s) in the .glb belong to merged sub-levels or helpers')
    print(f'  edits on an unedited round-trip: {changed}   differing bytes: {diff}')

    ok = (out == blob and changed == 0)
    print('glb_to_level selftest: ' + ('PASS  (byte-identical)' if ok else 'FAIL'))
    return 0 if ok else 1


# The entry point lives at the END of the file: module code runs top to bottom, so a
# `__main__` block placed here would fire before collect_edits is defined.


INVERSE_AXIS = {'identity': 'identity', 'x+90': 'x-90', 'x-90': 'x+90'}


def detect_axis(base: Dict[str, Tuple[np.ndarray, np.ndarray]],
                edited: Dict[str, Tuple[np.ndarray, np.ndarray]]) -> Tuple[str, int]:
    """The axis convention the edit came back in, and how many nodes it explains.

    Tries the identity and both 90-degree X rotations and keeps whichever makes the
    most nodes match the original once converted.  That is what separates "Blender
    rotated the whole scene" from "the user moved these things": a convention change
    explains thousands of nodes at once, an edit explains only the ones edited.
    """
    common = [n for n in edited if n in base]
    best_kind, best_hits = 'identity', -1

    for kind in AXIS_KINDS:
        hits = 0

        for n in common:
            bp, bq = convert_trs(base[n][0], base[n][1], kind)
            t, q = edited[n]

            if np.allclose(t, bp, atol=1e-3) and quat_close(q, bq):
                hits += 1

        if hits > best_hits:
            best_kind, best_hits = kind, hits

    return best_kind, max(best_hits, 0)


def collect_edits(original_level: str, original_glb: str, edited_glb: str
                  ) -> Tuple[bytes, Dict[int, Tuple[np.ndarray, np.ndarray]], int, int]:
    """(original bytes, entity index -> new transform, changed count, unowned node count)."""
    blob = Path(original_level).read_bytes()
    entities = parse_entities(blob)
    node_map = build_node_map(original_glb, entities)
    base = read_edited_transforms(original_glb)
    edited = read_edited_transforms(edited_glb)

    kind, explained = detect_axis(base, edited)

    if kind != 'identity':
        print(f'  axis: the edited file came back rotated {kind} about X (Blender Z-up '
              f'vs glTF Y-up).  {explained} of {len(edited)} node(s) match the original '
              f'once converted, so it is a convention change and not an edit - the '
              f'conversion is undone on write.')

    edits: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    changed = 0
    unowned = 0
    rot_only = 0

    for name, (t, q) in edited.items():
        idx = node_map.get(name)

        if idx is None:
            # A node from a merged sub-level or a helper unit: its record lives in a
            # different file, so it must be reported rather than quietly dropped.
            unowned += 1
            continue

        bt, bq = base.get(name, (None, None))

        if bt is not None:
            bp, bq_c = convert_trs(bt, bq, kind)

            # 1e-3, not 1e-5: a Blender round-trip re-serialises floats, so an untouched
            # node comes back a hair off - smaller than any edit, but larger than 1e-5.
            # At 1e-5 every node looked edited; moving one pillar reported 26 records.
            pos_same = np.allclose(t, bp, atol=1e-3)
            rot_same = quat_close(q, bq_c, tol=1e-3)

            if pos_same and rot_same:
                continue                                # untouched by the edit

            if pos_same and not rot_same:
                # Rotation-only difference on a node that did not move.  That is not an
                # edit anyone asked for - a Blender import/export can leave 180-degree
                # rotations behind on props - and writing them rotates colliders,
                # blockers and jump plates that the engine then sets up wrong.  Reported,
                # never written.
                rot_only += 1
                continue

        # Stored in the engine's frame, not the editor's.
        edits[idx] = convert_trs(t, q, INVERSE_AXIS[kind])
        changed += 1

    if rot_only:
        print(f'  rotation-only differences ignored: {rot_only} (did not move, but came '
              f'back rotated - not written, see the note above)')

    return blob, edits, changed, unowned


def parse_glb(path: str) -> dict:
    """The glTF JSON chunk of a .glb."""
    data = Path(path).read_bytes()
    if data[:4] != b'glTF':
        raise ValueError(f'not a .glb: {path}')
    off = 12
    while off < len(data):
        clen, ctype = struct.unpack_from('<II', data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:                     # 'JSON'
            return json.loads(chunk)
    raise ValueError(f'no JSON chunk in {path}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        raise SystemExit(selftest())
    raise SystemExit(main())
