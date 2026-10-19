#!/usr/bin/env python3
"""
level_from_glb.py - a Blender-authored level, built from the game's own units.

WHY THIS IS THE GOOD PATH
A level made by PLACING THE GAME'S OWN UNITS in Blender needs no mesh surgery at all: every
placed unit already carries its own collider, its own material and its own data.  So the
GLB's nodes map one-to-one onto a .level's 72-byte entity records, and this converter is just
a name lookup plus a transform copy.  Compare the alternative - splicing our mesh into a
donor unit - which inherits the DONOR's baked collision and therefore needs tiling to cover
anything (FINDINGS 9H.20).

WHAT IT DOES
  1. parses the GLB (names, translations, rotations, scales)
  2. normalises Blender's suffixes - `altar_01#793`, `cryptsmooth_floor_4c_4c#326.001` -
     down to the unit's own base name
  3. resolves that base name to a real resource path (preferring the families the game's own
     levels use; see PREFERRED below), and hashes it with MurmurHash64A
  4. writes one entity record per node into a DONOR level's entity table, keeping every other
     section byte-for-byte and the entity COUNT identical - the count is not negotiable,
     changing it crashes the load (FINDINGS 9H.14/9H.15)
  5. hides whatever donor entities are left over the same way the plane prototype does, by
     moving them 100 km up, so they stay counted but stop being reached

THE TRANSFORM
Blender/glTF stores a quaternion as (x, y, z, w); the engine's entity record stores the
vector part at offsets 60/64/68 and w at offset 0 NEGATED - an identity placement is
(0, 0, 0, -1) on disk (FINDINGS 9H.6, corrected and verified in 9H.18).  So the w written is
-w, which the level_tools encoder does for us when no raw `flag` is supplied.

AXIS - TWO QUESTIONS, NOT ONE
The engine is Z-up and glTF is Y-up, but "is this file Y-up" is not one question.  It is two,
and a Blender export can answer them differently:

  * where the LAYOUT is - the axis the node POSITIONS put the floors on (detect_vertical and
    detect_world_up).  Decides how a position is read.
  * where the MESHES are - the axis the unit GEOMETRY is built on, measured from the averaged
    vertex NORMALS of the flat meshes (detect_mesh_up).  Decides how a rotation is built.

The engine applies the record's rotation to ITS OWN unit mesh, so the record has to reproduce
the world orientation the node gives its mesh:  R_record = F^-1 * R_node * F', with F the
layout's frame change and F' the mesh's.  Collapsing the two into one flag is what shipped
crypt_arena01_custom, hub_custom and custom_duckomp_room with every placed unit on its side -
their layouts were engine-space (F = 1) while their meshes were Y-up (F' = R_x(+90)), so every
record needed one extra composition that the single flag never applied (FINDINGS 9H.22).

For a self-consistent export that is the conjugation it looks like: deg_mesh == -deg_pos, and
the record is F * R_node * F^-1 with F = R_x(deg_pos) the file -> engine change the POSITIONS
also get.  That form is the one to reason with - the engine's copy of a unit's mesh (native or
the author's own) is F * M_file, so reproducing the node's orientation in the ENGINE'S frame is
exactly what a record has to do - and it is what `_orientation_error` checks on every placement
before the build is allowed to write anything (FINDINGS 9H.29).

PLACING THE AUTHOR'S OWN MESHES, NOT JUST THE GAME'S
A level can only place UNITS, so a mesh authored in Blender has to ship as a unit resource:
`--own-unit BASE=PATH` (repeatable) resolves every node whose base name is BASE to that unit
instead of to a game unit, and scripts/build_own_units.py builds those units from the same
export - nodes sharing a base name (`Floor`, `Floor.001`, ...) are ONE unit placed N times,
because a node's name IS the unit.  Its mesh is spliced into a native template, so it arrives
with the template's collision, flow data and material binding (FINDINGS 9H.28).  That mesh is
already in the engine's frame - the same frame the engine's OWN meshes are in - so the SAME
deg_mesh applies to it: `--mesh-frame {auto,y-up,engine}` is there to override the measurement,
not to give our units a frame of their own.

    level_from_glb.py <level.glb> <donor.level> <out.level> [--scratch] [--skeleton sk.level]
                      [--own-unit BASE=PATH] [--mesh-frame auto|y-up|engine] [--spawn-at X,Y,Z]
                      [--reference ref.glb] [--max-entities N] [--rotation-ruler]

Example: a Blender arena of 1,000 placed units into the crypt arena's 1,570-slot table, then
ship it as an override of modules/d01_crypt/arena/crypt_arena01.  With --scratch the donor is
not read at all: the output is our entity table, our metadata and the section skeleton every
shipped level shares - see FINDINGS 9H.23.
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
for _p in (str(HERE), str(HERE / 'resource_tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mod_bundle_builder import murmur64                          # noqa: E402
from resource_tools.level_tools import (                          # noqa: E402
    ENTITY_RECORD_SIZE, TRANSFORM_LEAD_SIZE, decode_level, encode_level, _encode_entity,
    record_rotation_vector, quat_from_record_vector, set_record_rotation, shift_leads_forward,
)

# Base name -> full resource path, where a bare base name is ambiguous.  Each of these was
# chosen by checking which one the game's own levels actually use (the crypt shell places
# lights/light x130 and decals/decal x98), not by guessing.
# Base name -> full resource path, where a bare base name is ambiguous.  Each of these was
# chosen by checking which one the game's OWN levels use - the crypt shell places
# lights/light x130 and decals/decal x98 - rather than by guessing.
PREFERRED = {
    'light': 'lights/light',
    'decal': 'decals/decal',
    'torch_floor_01': 'props/d01_common/torch_floor_01',
}

# The donor's own spawn markers are the only thing that says where the player starts, so they
# are reserved rather than overwritten or hidden.
SPAWN_MARKER = 'gameobjects/level_editor/player_spawn_marker'

# WHY A LEVEL IS NOT A BLANK CANVAS (FINDINGS 9H.21).
#
# A shipped arena level is SELF-CONTAINED and SCRIPTED.  Its entity table is not scenery with
# some props in it - it is the encounter's data.  crypt_arena01 holds 102 logic entities:
# 4 spawn_field (where the encounter spawns a wave), 13 spawn_field_dormant (the waves
# themselves, woken one at a time), 9 generic_marker and 5 room_marker (the generator's
# anchors and the encounter's own bookkeeping), 7 unwalkable (nav blockers), 7
# super_jump_plate, 3 door_crypt_encounter_4c, and the 4 player_spawn_marker.
#
# The encounter script drives every one of them.  Convert a level by overwriting the first N
# slots and shoving the rest out of the world, and that script is left waiting for waves that
# can never spawn and doors that can never open - an unwinnable wait.  The game does not
# crash: it hangs, with no error, because nothing ever completes.  That is exactly what a
# first attempt at this did (92 of those 102 destroyed, 10 moved 100 km up).
#
# So the rule is the one the room mod already learned: KEEP THE LOGIC, REPLACE THE SCENERY.
# Only decoration slots are ours to overwrite, and leftovers are hidden by SCALE (the field
# edit proven safe in the room mod) rather than by moving them - a level whose entity count
# changes crashes the load outright, so they cannot be deleted either.
KEEP_PREFIXES = (
    'gameobjects/level_editor/',   # markers, player spawn markers, unwalkable nav blockers
    'gameobjects/spawn_field/',    # where the encounter spawns its waves
    'gameobjects/room_marker/',
    'gameobjects/doors/',
    'gameobjects/crests/',
    'gameobjects/spawners/',
    'gameobjects/turrets/',
    'gameobjects/traps/',
    'gameobjects/dispensers/',
)
REPLACE_PREFIXES = (
    'blocks/', 'props/', 'decals/', 'lights/',
    'gameobjects/gold/', 'gameobjects/food/', 'gameobjects/potions/',
    'gameobjects/keys/', 'gameobjects/containers/',
)
TINY = 0.0001                      # hidden, not deleted and not moved (FINDINGS 9H.20)

_PATHS: Dict[str, str] = {}


def unit_paths() -> Dict[str, str]:
    if not _PATHS:
        for fn in ('hash_database.json', 'resource_name_overlay.json'):
            p = HERE.parent / 'Data' / fn
            if p.exists():
                for k, v in json.loads(p.read_text()).items():
                    _PATHS[k.lower()] = v
    return _PATHS


def unit_of(entity: dict) -> str:
    """The resource path of an entity's template, or '' when the hash is unknown."""
    return unit_paths().get(entity['template_hash'][2:].lower(), '')


# WHAT MATERIAL DOES THE GAME ITSELF PUT ON THIS KIND OF UNIT?
#
# The level record carries a material override per entity, and the engine resolves it while
# instantiating the level: FUN_0042f120 is asked for the entry and its result is written into
# byte-for-byte (the null write at RVA 0x30224 in crash_trace.log).  So the value has to be one
# the engine can resolve FOR THAT KIND.  Copying the donor slot's value is not enough: a gold
# pickup inheriting a crypt block's swatch is a material that no shipped level ever pairs with
# that kind, and the lookup comes back NULL.
#
# The only authority on "which material goes with which kind" is the shipped corpus.  This
# scans the exported levels once, takes the most common material per kind, and caches it, so
# every placement is written the way the game writes it.  Material 0 is a legitimate answer -
# shipped levels place lights, skydomes and blackboxes with 0 - and it is kept as 0.
MATERIAL_CACHE = HERE.parent / 'Data' / 'kind_materials.json'
EXPORT_ROOTS = (
    HERE.parent / 'Gauntlet-Export' / 'named',
    HERE.parent.parent / 'Gauntlet-Export' / 'named',      # sibling of this repo
)


def shipped_material_map(rebuild: bool = False) -> Dict[str, str]:
    """kind -> the material the shipped levels use for it most often."""
    if MATERIAL_CACHE.exists() and not rebuild:
        try:
            return json.loads(MATERIAL_CACHE.read_text())
        except Exception:
            pass

    paths = unit_paths()
    counts: Dict[str, Dict[str, int]] = {}
    scanned = 0
    for root in EXPORT_ROOTS:
        if not root.is_dir():
            continue
        for p in root.rglob('*.level'):
            try:
                blob = p.read_bytes()
            except Exception:
                continue
            if len(blob) < 136:
                continue
            offset, count = struct.unpack_from('<II', blob, 0)
            if offset != 128 or not 0 < count < 20000:
                continue
            if offset + count * ENTITY_RECORD_SIZE > len(blob):
                continue
            scanned += 1
            for i in range(count):
                rec = offset + i * ENTITY_RECORD_SIZE
                template = struct.unpack_from('<Q', blob, rec + 32)[0]
                material = struct.unpack_from('<Q', blob, rec + 40)[0]
                path = paths.get('%016x' % template)
                if not path:
                    continue
                bucket = counts.setdefault(path, {})
                key = '0x%016x' % material
                bucket[key] = bucket.get(key, 0) + 1

    out = {kind: max(v.items(), key=lambda kv: kv[1])[0] for kind, v in counts.items()}
    try:
        MATERIAL_CACHE.write_text(json.dumps(out, indent=0, sort_keys=True))
    except Exception:
        pass
    print('  corpus : %d level(s) scanned -> material for %d kind(s) (%s)'
          % (scanned, len(out), MATERIAL_CACHE.name))
    return out


def classify(path: str) -> str:
    """What a unit IS as far as the encounter is concerned: keep | decor | core | other."""
    if path.startswith('core/'):
        return 'core'              # the skydome: neither logic nor ours to replace
    if path.startswith(KEEP_PREFIXES):
        return 'keep'
    if path.startswith(REPLACE_PREFIXES):
        return 'decor'
    return 'other'                 # unknown: never touched, never counted on


def entity_sig(e: dict) -> tuple:
    """Identity of a placed entity - what it is and exactly where - so that one level's logic
    can be told from another's without trusting slot order."""
    p = e['position']
    return (e['template_hash'].lower(), round(p[0], 3), round(p[1], 3), round(p[2], 3))


def hide_leftover(e: dict, mode: str) -> None:
    """Get a decoration entity out of the way WITHOUT deleting it - the entity count must not
    change, or the load fails outright (proven the hard way in the room mod).

    'move'  - what the room mod does, and the ONLY option with a proof behind it: that mod
              moved 4246 collider-bearing shell entities 100 km up and the level loaded.
    'scale' - 0.0001.  Proven for units with NO collider - gold, food, potions, keys,
              containers, room_marker.  That is exactly the list the room mod ever used it
              on.  Applied to a WALL or a FLOOR it collapses a physics shape to 1e-4, and
              the engine dies on it - which is precisely how the second attempt at shipping
              this arena crashed where the first attempt had merely hung.
    'none'  - leave the scenery exactly where it is and put our level on top of it.  For
              bisecting a failure without changing two things at once.
    """
    if mode == 'move':
        e['position'][2] += 100000.0
    elif mode == 'scale':
        e['scale'] = [TINY, TINY, TINY]


def read_glb(path: Path) -> dict:
    """The GLB's JSON chunk, with its BIN chunk stashed as `_bin`.

    `_bin` is there because the up-axis question cannot be answered from bounding boxes
    alone: a flat mesh is thin on its normal's axis whichever way that normal points, and the
    SIGN is what decides whether a rotation needs the Y-up -> Z-up change (see
    detect_mesh_up).  The vertex normals are that evidence, and they live in the BIN chunk.
    """
    raw = path.read_bytes()
    magic, _version, length = struct.unpack_from('<4sII', raw, 0)
    if magic != b'glTF':
        raise SystemExit('%s is not a GLB' % path)
    off, js, bin_chunk = 12, None, None
    while off + 8 <= length:
        clen, ctype = struct.unpack_from('<II', raw, off)
        chunk = raw[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A and js is None:
            js = json.loads(chunk.decode('utf-8').rstrip('\x00 '))
        elif ctype == 0x004E4942 and bin_chunk is None:
            bin_chunk = chunk
        off += 8 + clen
    if js is None:
        raise SystemExit('%s has no JSON chunk' % path)
    js['_bin'] = bin_chunk or b''
    return js


def accessor_vec3(js: dict, index: int) -> List[Tuple[float, float, float]]:
    """A VEC3 float accessor, read straight out of the GLB's BIN chunk."""
    acc = js['accessors'][index]
    if acc.get('type') != 'VEC3' or acc.get('componentType') != 5126 or 'bufferView' not in acc:
        return []
    bv = js['bufferViews'][acc['bufferView']]
    blob = js.get('_bin') or b''
    base = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    stride = bv.get('byteStride') or 12
    out: List[Tuple[float, float, float]] = []
    for i in range(acc['count']):
        off = base + i * stride
        if off + 12 > len(blob):
            return out
        out.append(struct.unpack_from('<3f', blob, off))
    return out


# NODES THE BUILD IGNORES BY NAME.
#
# A scene legitimately carries objects that are not part of the level: working copies, reference
# geometry, scratch parts the author is still assembling.  A node whose name contains one of these
# substrings - case-insensitively - is not placed, does not vote in the frame measurements
# (detect_vertical / detect_mesh_up / detect_world_up / world_bounds), never becomes one of our
# units (build_own_units.py imports `ignored_node`), and is reported as IGNORED rather than as an
# unresolved unit name.  `--ignore SUBSTR` adds to the list, which defaults to the author's own
# scratch marker.
IGNORE_NAME_SUBSTRINGS: List[str] = ['throwaway']


def ignored_node(name: str) -> bool:
    """True when a node's name marks it as not part of the build (see IGNORE_NAME_SUBSTRINGS)."""
    lowered = (name or '').lower()
    return any(s.lower() in lowered for s in IGNORE_NAME_SUBSTRINGS)


def base_name(node_name: str) -> str:
    """Strip Blender's suffixes.  Both can be present, in either role: `unit#326.001`."""
    name = node_name
    while True:
        before = name
        if '#' in name:
            name = name.rsplit('#', 1)[0]
        head, _, tail = name.rpartition('.')
        if tail.isdigit() and head:
            name = head
        if name == before:
            return name


def load_names() -> Dict[str, List[str]]:
    """base name -> every resource path that has that basename."""
    out: Dict[str, List[str]] = {}
    for fn in ('hash_database.json', 'resource_name_overlay.json'):
        p = HERE.parent / 'Data' / fn
        if not p.exists():
            continue
        for path in json.loads(p.read_text()).values():
            out.setdefault(path.rsplit('/', 1)[-1], []).append(path)
    return out


# OUR OWN UNITS: base name -> the unit path the author's bundle ships.  A level authored from
# custom meshes references UNITS, so those meshes have to exist as unit resources - see
# scripts/build_own_units.py and FINDINGS 9H.28.  These take priority over the game's own
# name index, because a node named `Floor` is the author's unit and not a game one.
OWN_UNITS: Dict[str, str] = {}


def resolve(base: str, by_base: Dict[str, List[str]]) -> Optional[str]:
    if base in OWN_UNITS:
        return OWN_UNITS[base]
    if base in PREFERRED:
        return PREFERRED[base]
    cands = by_base.get(base, [])
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    pref = [c for c in cands
            if c.startswith(('blocks/', 'props/', 'gameobjects/', 'lights/', 'decals/'))]
    return sorted(pref or cands)[0]


def quat_rotate(q: Tuple[float, float, float, float],
                v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    x, y, z, w = q
    vx, vy, vz = v
    return (vx * (1 - 2 * y * y - 2 * z * z) + vy * (2 * x * y - 2 * z * w) + vz * (2 * x * z + 2 * y * w),
            vx * (2 * x * y + 2 * z * w) + vy * (1 - 2 * x * x - 2 * z * z) + vz * (2 * y * z - 2 * x * w),
            vx * (2 * x * z - 2 * y * w) + vy * (2 * y * z + 2 * x * w) + vz * (1 - 2 * x * x - 2 * y * y))


def world_bounds(js: dict) -> Tuple[List[float], List[float]]:
    """Bounding box of the whole level, with every node's rotation and translation applied."""
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            continue
        t = node.get('translation', [0.0, 0.0, 0.0])
        q = tuple(node.get('rotation', [0.0, 0.0, 0.0, 1.0]))
        s = node.get('scale', [1.0, 1.0, 1.0])
        for prim in js['meshes'][node['mesh']]['primitives']:
            acc = js['accessors'][prim['attributes']['POSITION']]
            for cx in (acc['min'][0], acc['max'][0]):
                for cy in (acc['min'][1], acc['max'][1]):
                    for cz in (acc['min'][2], acc['max'][2]):
                        r = quat_rotate(q, (cx * s[0], cy * s[1], cz * s[2]))
                        for k in range(3):
                            val = r[k] + t[k]
                            lo[k] = min(lo[k], val)
                            hi[k] = max(hi[k], val)
    return lo, hi


def detect_vertical(js: dict, by_base: Dict[str, List[str]]) -> Tuple[int, str]:
    """Which axis is UP in this GLB - decided by what the FLOORS do, not by extents.

    A level is mostly floor tiles lying in one plane, so the axis whose coordinate they all
    SHARE is the vertical one.  The extent heuristic got this wrong once already: a wide, low
    level exported Y-up still has its smallest extent in Z if it happens to be a narrow strip,
    and the check happily reported "z looks like engine space".  Floors cannot lie.
    """
    groups: Dict[str, List[List[float]]] = {}
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            continue
        base = base_name(node.get('name', ''))
        if resolve(base, by_base) is None:
            continue
        groups.setdefault(base, []).append([float(v) for v in
                                            node.get('translation', [0.0, 0.0, 0.0])])
    best, best_spread = None, None
    for base, ts in groups.items():
        if len(ts) < 8:
            continue                       # too few to say anything about a plane
        spread = [max(t[i] for t in ts) - min(t[i] for t in ts) for i in range(3)]
        tight = sorted(spread)
        if tight[0] > 0.5:                 # nothing flat about this group
            continue
        # The tightest axis is the vertical if it is far tighter than the next one.
        if tight[1] < 4.0 or tight[0] * 8.0 > tight[1]:
            continue
        if best_spread is None or tight[0] < best_spread:
            best, best_spread = (spread.index(tight[0]), base), tight[0]
    if best is None:
        return 2, 'no flat group of 8+ to judge by; assuming Z-up'
    return best[0], '%d %s node(s) share one coordinate (spread %.2f) - that axis is up' % (
        len(groups[best[1]]), best[1], best_spread)


def flat_meshes(js: dict, by_base: Dict[str, List[str]]) -> List[Tuple[str, int]]:
    """(base name, mesh index) for every node whose mesh is FLAT - min extent under 5%.

    Only flat geometry answers the up question: a floor tile (or a fog volume) is a plane, so
    its normal IS the up axis.  A prop or a cube says nothing - its normals cancel out.
    """
    out: List[Tuple[str, int]] = []
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            continue
        base = base_name(node.get('name', ''))
        if resolve(base, by_base) is None:
            continue
        for prim in js['meshes'][node['mesh']]['primitives']:
            acc = js['accessors'][prim['attributes']['POSITION']]
            ext = [acc['max'][i] - acc['min'][i] for i in range(3)]
            if max(ext) <= 0.0 or min(ext) > 0.05 * max(ext):
                continue
            out.append((base, node['mesh']))
            break
    return out


# A signed axis, as an index into these tables: 0..5 -> +X -X +Y -Y +Z -Z.
AXIS_VEC = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)]
AXIS_NAME = ['+X', '-X', '+Y', '-Y', '+Z', '-Z']


def axis_of(v: Tuple[float, float, float], tol: float = 0.7) -> Optional[int]:
    """Which signed axis a unit vector is, as an index into AXIS_VEC.

    AXIS_VEC is ordered [+X, -X, +Y, -Y, +Z, -Z], so axis i is index 2*i and its negative is
    2*i+1.
    """
    best, best_v = None, tol
    for i in range(3):
        if v[i] > best_v:
            best, best_v = 2 * i, v[i]
        if -v[i] > best_v:
            best, best_v = 2 * i + 1, -v[i]
    return best


def detect_mesh_up(js: dict, by_base: Dict[str, List[str]]) -> Tuple[Optional[int], str]:
    """The SIGNED up axis of the GLB's MESH DATA, from the normals of its flat meshes.

    A floor tile's averaged vertex normal is the mesh's own up direction, and it is the one
    measurement that separates the two exports this tool has been handed:

        Base.glb (shipped crypt_arena01_custom / hub_custom / custom_duckomp_room):
            124 floor meshes, average normal (0, -1, 0)  ->  -Y
        test_arena_03.glb (the corrected export):
             48 floor meshes, average normal (0, 0, 1)   ->  +Z

    The first is Y-up geometry - the engine's own mesh turned on its side - and the second is
    engine-space geometry.  The engine applies the record's rotation to ITS OWN mesh, so the
    first needs the rotation composed with the Y-up -> Z-up change and the second does not.
    That is the whole difference between a level that stands up in game and one where every
    wall lies down and every floor stands up.
    """
    votes: Dict[int, int] = {}
    for _base, mesh in flat_meshes(js, by_base):
        for prim in js['meshes'][mesh]['primitives']:
            if 'NORMAL' not in prim['attributes']:
                continue
            ns = accessor_vec3(js, prim['attributes']['NORMAL'])
            if len(ns) < 3:
                continue
            avg = tuple(sum(v[i] for v in ns) / len(ns) for i in range(3))
            if math.sqrt(sum(c * c for c in avg)) < 0.5:
                continue                      # a box: its faces cancel, no evidence
            ax = axis_of(avg)
            if ax is not None:
                votes[ax] = votes.get(ax, 0) + 1
    if not votes:
        return None, ('no flat mesh with usable normals; assuming the meshes sit in the '
                      'same frame as the placements')
    ax = max(votes, key=lambda a: votes[a])
    return ax, ('%d flat mesh normal(s) average to %s - the MESH data is %s'
                % (votes[ax], AXIS_NAME[ax],
                   'Y-up (the engine mesh turned on its side), so the rotation needs the '
                   'change' if ax in (2, 3)
                   else 'engine-space (Z-up), so the rotation is already engine-frame'))


def detect_world_up(js: dict, by_base: Dict[str, List[str]],
                    mesh_up: Optional[int]) -> Tuple[Optional[int], str]:
    """The SIGNED up axis of the GLB's WORLD, from the same floors the vertical test uses.

    A floor's normal in world terms is R_node * (mesh up), so the node rotations plus the
    mesh up give the direction the level stands up in - which is what decides whether the
    POSITIONS need converting.  This is the half the extent-only test could not see: it knew
    the floors were flat on Y or Z, but not which way was up.
    """
    if mesh_up is None:
        return None, 'mesh up unknown'
    up = AXIS_VEC[mesh_up]
    votes: Dict[int, int] = {}
    for node in js['nodes']:
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            continue
        base = base_name(node.get('name', ''))
        if resolve(base, by_base) is None:
            continue
        for prim in js['meshes'][node['mesh']]['primitives']:
            acc = js['accessors'][prim['attributes']['POSITION']]
            ext = [acc['max'][i] - acc['min'][i] for i in range(3)]
            if max(ext) <= 0.0 or min(ext) > 0.05 * max(ext):
                continue
            q = tuple(float(v) for v in node.get('rotation', [0.0, 0.0, 0.0, 1.0]))
            ax = axis_of(quat_rotate(q, up))
            if ax is not None:
                votes[ax] = votes.get(ax, 0) + 1
            break
    if not votes:
        return None, 'no flat mesh to judge by'
    ax = max(votes, key=lambda a: votes[a])
    return ax, '%d flat mesh(es) point %s in the world' % (votes[ax], AXIS_NAME[ax])


def x_deg_for(up: int) -> int:
    """The rotation about X, in degrees, that maps the engine's +Z onto `up`."""
    return {4: 0, 3: 90, 2: -90, 5: 180}.get(up, 0)


def x_rot(deg: int, v) -> List[float]:
    """Apply a rotation about X by a multiple of 90 degrees to a 3-vector."""
    x, y, z = (float(c) for c in v)
    if deg == 0:
        return [x, y, z]
    if deg == 90:
        return [x, -z, y]
    if deg == -90:
        return [x, z, -y]
    return [x, -y, -z]


def to_engine_position(t: List[float], deg_pos: int) -> List[float]:
    """A glTF node position as the level record must hold it.

    `deg_pos` is the frame change between the file's world and the engine's, derived from the
    world up (see detect_world_up): 0 for a file already in engine space, +90 for a glTF
    Y-up file, 180 for a file whose layout is upside down.
    """
    return x_rot(deg_pos, t)


def _x_quat(deg: int) -> Tuple[float, float, float, float]:
    """The quaternion (xyzw) of a rotation about X by a multiple of 90 degrees."""
    h = math.radians(deg) / 2.0
    return (math.sin(h), 0.0, 0.0, math.cos(h))


def _qmul(a, b) -> Tuple[float, float, float, float]:
    """Hamilton product, xyzw."""
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)


# HOW FAR IS TOO FAR, when comparing a rotation against a quaternion that came out of the file.
#
# The files store float32 and this side computes in float64, so the comparison can never be
# exact: the correct build of the own-unit arena measures 0.021 degrees on its two stairs (the
# Stair node's quaternion is (-0.70710688, 0, 0, 0.70710665), whose norm is 0.99999995 - the
# rounding is the export's, not the tool's).  What the check has to separate is that noise from a
# REAL inversion, and every inversion this file has seen was at least 120 degrees out - 143.29,
# 180.00 and 120.00 on the three rotated placements of the double-branched build (9H.29).  0.5
# degrees sits between the two with a factor of 240 to spare.
ORIENT_TOL_DEG = 0.5


def _orientation_error(node_quat, deg_pos: int, q_engine) -> float:
    """How far a record's rotation is from what the NODE asks for, in the ENGINE'S frame.

    F = R_x(deg_pos) is the file -> engine frame change - the same one to_engine_position
    applies to the positions - and the engine's copy of a unit's mesh is F * M_file, which is
    true both for a native unit in a Y-up export and for an own unit built by
    scripts/build_own_units.py (see the module docstring of that script).  So the record has to
    hold F * R_node * F^-1, and this returns 0 degrees when it does.

    WHAT IT IS FOR (FINDINGS 9H.29).  The double-branched build of the first un-baked export held
    the INVERSE here: 143.3, 180.0 and 120.0 degrees out on the three placements that carried
    their own rotation, and 0 on the nine that did not - the exact signature of that bug.  This
    check is the one that catches it, because it compares the record against the NODE rather than
    against another intermediate value that shares the same mistake.
    """
    x, y, z, w = (float(v) for v in node_quat)
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n > 0.0:
        x, y, z, w = x / n, y / n, z / n, w / n
    if deg_pos:
        x, y, z, w = _qmul(_x_quat(deg_pos), _qmul((x, y, z, w), _x_quat(-deg_pos)))
    return _quat_angle_deg(q_engine, (x, y, z, w))


def to_engine_rotation(q: List[float], deg_pos: int, deg_mesh: int) -> List[float]:
    """A glTF node rotation as the level record must hold it.

    THE RULE.  The engine applies the record's rotation to ITS OWN unit mesh, which is engine
    Z-up, so the record has to reproduce the world orientation the node gives its mesh.  With
    F the frame change between the file's world and the engine's, and F' the one between the
    file's MESH frame and the engine's:

        R_record = F^-1 * R_node * F'

    `deg_pos` is F (from the world up), `deg_mesh` is F' (from the mesh up).  For a
    self-consistent export F == F' and this is the conjugation it should be.  For the export
    that shipped the tumbling custom levels they differed - the placements were engine-space
    (F = 1) while the meshes were Y-up (F' = R_x(+90)) - and q * R_x(+90) reproduces the
    corrected export's rotations exactly, 204 of 204 nodes measured.

    And the BRANCH.  Records hold only x, y, z, and the engine derives a NEGATIVE w
    (w = -sqrt(1-|xyz|^2) - that reconstruction matched the engine's own orientations
    329/329 in FINDINGS 9H.18).  q and -q are the same rotation, so the returned quaternion
    is put in the branch the engine reconstructs: w < 0.

    NEGATE ALL FOUR, NOT JUST xyz.  (x, y, z, w) and (-x, -y, -z, w) are DIFFERENT rotations -
    the second is the INVERSE of the first, -theta instead of theta; only the FULL negation is
    the same rotation.  Negating xyz alone
    still stores the right xyz for an engine that rebuilds w itself, but it leaves the RETURNED
    quaternion non-canonical, and every caller then applies the record-branch rule again
    (`_record_branch` in write_scratch, which negates all four when w > 0) - so the second
    application undid the first and put the sign back.  Measured on the un-baked arena export:
    the crane came out at -108.36 degrees instead of +108.36 (143.3 degrees out), the two
    stairs 180.0 and 120.0 degrees out, while the nine floors - whose node rotation IS the
    identity, the one case the bug cannot touch - were correct.  Every earlier build was
    BAKED and went through recovery, which branches exactly once, which is why this stayed
    invisible (FINDINGS 9H.29).

    THIS FUNCTION'S OUTPUT IS FINAL: it is already in the record's branch, and `_record_branch`
    on it is a no-op.  Do not "fix up" the sign anywhere downstream.
    """
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n > 0.0:
        x, y, z, w = x / n, y / n, z / n, w / n
    if deg_pos:
        x, y, z, w = _qmul(_x_quat(deg_pos), (x, y, z, w))
    if deg_mesh:
        x, y, z, w = _qmul((x, y, z, w), _x_quat(deg_mesh))
    if w > 0.0:
        x, y, z, w = -x, -y, -z, -w
    return [x, y, z, w]


# ---------------------------------------------------------------------------
# A LEVEL WITH NO DONOR  (FINDINGS 9H.23)
# ---------------------------------------------------------------------------
# Every custom level so far was a DONOR's body with our entities patched into its slots, so
# it arrived carrying the donor's flow, volumes and markers - the hub's light-fade callbacks
# ran on our level and the room read as "a bit messy".  The fix is a level that is only ours:
# our entity table, our metadata, and the section skeleton every shipped level shares.
#
# That skeleton is the smallest level in the corpus - 1,136 bytes, 6 units, no logic at all
# (assets/exports-samples/samples/level_24abcdf4b1fb4d4a.level, out of the game's own data).
# Everything in it that does NOT scale with the unit count is a constant:
#
#   128                 unit table (N x 72)                 u32[0]=128, u32[1]=N
#   table end + 24      four 1.0 floats then 8 zero bytes   u32[3]  identical in every level
#   + 4N                PER-UNIT pointer table, zeros      the section u32[3] NAMES
#   + metadata          count, then entries                 u32[14] ours
#   + 8                 zero bytes                          u32[4]
#   + 56                one record                          u32[5]=u32[7]
#   + 24                zero bytes                          u32[8]  zero in every level
#   + 16                zero bytes                          u32[10]=u32[12]=u32[13]
#   + 256               the render/lighting block           u32[16]=u32[18]=u32[20]
#   + 8                 {that block's offset, 253}          u32[22]
#   + 8N                per-unit array: {0, its own offset} u32[24]=u32[25]=u32[30]
#   = file size                                             u32[26]=u32[27]=u32[28]
#
# The 4N section is the one that has to be sized to the unit count, and getting it wrong is
# not a cosmetic error: FUN_00430440 walks it one 4-byte entry per unit, treats each value as a
# self-relative pointer and MEMCOPIES 4 bytes from header+value (a zero entry is skipped).
# Copying the 6-unit skeleton's 24 bytes into a 172-unit level therefore made the loader read
# its own metadata and render block as pointers and copy from a garbage address - the
# 0xC0000005 at 0x5FEA5A (FUN_005fea30 is memmove), read at a page boundary.
#
# u32[29] stays 0: no sub-level placements, which is exactly what keeps the activation pass
# out of the branch that crashed the crypt-body build (9H.22.1).
# The kinds the author reported as rotated, for --rotation-ruler.
RULER_KINDS = [
    'blocks/d01_crypt/railings/crypt_railing_straight_4c',
    'blocks/d01_crypt/borders/crypt_border_straight_4c',
    'blocks/d01_crypt/stairs/crypt_stairs_low_4c',
    'props/d01_crypt/coffin_open',
]

SCRATCH_SKELETON = HERE.parent / 'assets' / 'exports-samples' / 'samples' / \
    'level_24abcdf4b1fb4d4a.level'


def encode_metadata(entries) -> bytes:
    """The metadata list: u32 count, then per entry hashCount, hashes, type, value.

    type 1 = uint32, 2 = float32, 3 = string (u32 length INCLUDING the null, then the bytes
    padded to a 4-byte boundary).  Exactly `parseMetadataEntry` from filediver - and the
    padding rule is what a naive parse desyncs on, because the empty string is 1 byte of
    payload padded to 4 (FINDINGS 9H.16).
    """
    out = bytearray(struct.pack('<I', len(entries)))
    for h, kind, value in entries:
        out += struct.pack('<II', 1, h)
        if kind == 'float':
            out += struct.pack('<If', 2, float(value))
        else:
            raw = str(value).encode('ascii') + b'\x00'
            out += struct.pack('<II', 3, len(raw)) + raw + b'\x00' * (-len(raw) % 4)
    return bytes(out)


def scratch_sections(skeleton: Path) -> dict:
    """The skeleton's non-entity sections, keyed by the header field that names them.

    Sizes are read out of the header rather than assumed, and the layout is asserted, so a
    skeleton that is not the one this was written against fails loudly instead of producing a
    plausible wrong file.
    """
    blob = skeleton.read_bytes()
    h = list(struct.unpack_from('<32I', blob, 0))
    n = h[1]
    table_end = 128 + n * ENTITY_RECORD_SIZE
    if h[0] != 128 or h[2] != 1 or h[29] != 0 or h[24] != h[25] or h[30] != h[24]:
        raise SystemExit('%s is not the expected skeleton (header does not match)' % skeleton)
    if h[26] != len(blob) or h[27] != len(blob) or h[28] != len(blob):
        raise SystemExit('%s: u32[26..28] are not the file size' % skeleton)
    if h[24] != h[22] + 8:
        raise SystemExit('%s: the per-unit array does not follow the {offset,253} pair'
                         % skeleton)
    # The section u32[3] names starts with the 4-bytes-per-unit pointer table that
    # FUN_00430440 walks one entry per unit; a shipped level may carry more after it.
    if len(blob[h[3]:h[14]]) < 4 * n:
        raise SystemExit('%s: the section u32[3] names is %d bytes for %d units - it has to '
                         'hold 4 bytes per unit' % (skeleton, len(blob[h[3]:h[14]]), n))
    return {
        'header': h,
        'tail24': blob[table_end:h[3]],                 # four 1.0 floats + 8 zero bytes
        'zeros24': blob[h[3]:h[14]],
        'metadata': blob[h[14]:h[4]],
        'zero8': blob[h[4]:h[5]],
        'rec56': blob[h[5]:h[8]],
        'zeros24b': blob[h[8]:h[10]],
        'zeros16': blob[h[10]:h[16]],
        'render256': blob[h[16]:h[22]],
        'pair8': blob[h[22]:h[24]],
    }


def write_scratch_level(records, out: Path, skeleton: Path, metadata: bytes = None) -> bytes:
    """A complete level: our N records, the skeleton's fixed sections, nothing else.

    `records` are dicts in level_tools' decoded shape.  The only section whose size depends on
    the unit count is the per-unit array (8 bytes per unit, every entry `{0, its own offset}`
    in every shipped level - checked on the sample, the hub, the arena and the shell), so
    everything else is copied byte-for-byte and moved as a block, which keeps any
    self-relative field inside those sections valid.  The one absolute value in them is the
    {render-block offset, 253} pair, and that is rewritten.

    THE UNIT TABLE'S 24-BYTE PROLOGUE IS ZEROED.  The engine reads the four bytes at the unit
    table's own start - the prologue, NOT unit 0's data - as a COUNT, allocates that many bytes
    and writes one byte per item into the result.  A rotation like -0.7071 is 3.2 billion, the
    allocation fails, and the byte store faults at 0x430224.  All 255 shipped levels have 0 there
    (FINDINGS 9H.23.3).  It is zeroed after `shift_leads_forward`, because before the shift those
    four bytes hold unit 0's rotation w (FINDINGS 9H.36).
    """
    sk = scratch_sections(skeleton)
    meta = metadata if metadata is not None else sk['metadata']
    records = [dict(r) for r in records]
    n = len(records)
    table_end = 128 + n * ENTITY_RECORD_SIZE
    # Section offsets, laid out in the skeleton's order.  The per-unit pointer table is the
    # ONLY other section that scales with the unit count - 4 bytes per unit, all zero, which
    # the loader skips (see the note above: it is read one entry per unit and each value is
    # used as a pointer).
    tail_at = table_end
    perunit_at = tail_at + len(sk['tail24'])
    perunit = b'\x00' * (4 * n)
    meta_at = perunit_at + len(perunit)
    zero8_at = meta_at + len(meta)
    rec56_at = zero8_at + len(sk['zero8'])
    zeros24b_at = rec56_at + len(sk['rec56'])
    zeros16_at = zeros24b_at + len(sk['zeros24b'])
    render_at = zeros16_at + len(sk['zeros16'])
    pair_at = render_at + len(sk['render256'])
    array_at = pair_at + 8
    end = array_at + n * 8

    blob = bytearray(end)
    for i, v in enumerate((128, n, 1, perunit_at, zero8_at, rec56_at, 0, rec56_at,
                           zeros24b_at, 0, zeros16_at, 0, zeros16_at, zeros16_at, meta_at, 0,
                           render_at, 0, render_at, 0, render_at, 1, pair_at, 0,
                           array_at, array_at, end, end, end, 0, array_at, 0)):
        struct.pack_into('<I', blob, i * 4, v)

    for i, rec in enumerate(records):
        blob[128 + i * ENTITY_RECORD_SIZE:128 + (i + 1) * ENTITY_RECORD_SIZE] = \
            _encode_entity(rec)
    off = table_end
    for part in (sk['tail24'], perunit, meta, sk['zero8'], sk['rec56'],
                 sk['zeros24b'], sk['zeros16'], sk['render256']):
        blob[off:off + len(part)] = part
        off += len(part)
    pair = bytearray(sk['pair8'])
    struct.pack_into('<I', pair, 0, render_at)
    blob[off:off + 8] = pair
    off += 8
    for i in range(n):
        struct.pack_into('<II', blob, off + i * 8, 0, array_at)
    if off + n * 8 != end:
        raise SystemExit('internal: the level did not assemble to the size it computed')

    # EVERY UNIT'S TRANSFORM LEAD MOVES ONE RECORD ON (FINDINGS 9H.36).  `_encode_entity` writes
    # each record with its own rotation w / scale / padding in its own first 24 bytes; the engine
    # reads those 24 bytes at record+0x48/+0x4c - i.e. in the NEXT record - so they all have to
    # move, the last unit's landing in the 24 bytes reserved after the table (which the copy of
    # the skeleton's `tail24` above has just put there).  The unit table's own 24-byte prologue is
    # reset to zero: its first u32 is the COUNT the loader allocates (9H.23.3), and it is not any
    # unit's data.
    shift_leads_forward(blob, 128, n, prologue=b'\x00' * TRANSFORM_LEAD_SIZE)
    out.write_bytes(bytes(blob))
    return bytes(blob)


def rotation_ruler(placed, origin, kinds) -> List[dict]:
    """Four copies of each kind at 0/90/180/270 degrees, in a grid - the diagnostic for "it
    looks 70-80 degrees out".

    A record holds a pure yaw (0/90/180/270 is all the corpus uses for structural blocks), so
    an angle that is NOT a multiple of 90 cannot come from the record - it has to come from the
    unit's own mesh frame or from the engine composing something else.  Showing the four yaws of
    ONE kind side by side says which of them the engine draws the way it should, and the
    difference is the offset to look for.

    Laid out as one ROW per kind and one COLUMN per yaw, anchored in the layout's own -x/-y
    corner so it stands on our floor and can be walked to, and 10 units apart so an 8-unit piece
    cannot overlap its neighbour.
    """
    import math as _m
    xs = [p['t'][0] for p in placed] or [0.0]
    ys = [p['t'][1] for p in placed] or [0.0]
    x0, y0 = min(xs) + 6.0, min(ys) + 6.0
    out: List[dict] = []
    for ki, kind in enumerate(kinds):
        for ci, yaw in enumerate((0, 90, 180, 270)):
            half = _m.radians(yaw) / 2.0
            out.append({
                'unit': kind,
                't': [x0 + ci * 10.0, y0 + ki * 10.0, origin[2]],
                'q': [0.0, 0.0, _m.sin(half), _m.cos(half)],
                's': [1.0, 1.0, 1.0],
                'node': 'ruler:%s@%d' % (kind.split('/')[-1], yaw),
            })
    return out


def _scratch_id(path: str, index: int) -> int:
    """A stable unique 64-bit instance id.

    The shipped levels' ids are random 64-bit values, unique inside the file and not
    sequential, so any unique value does - this one is derived from the unit and its index so
    a rebuild reproduces the same file byte for byte.
    """
    return murmur64('%s#%d' % (path, index)) | 1


def is_floor_unit(path: str) -> bool:
    """Is this unit something the player can stand ON - a level's floor?

    WHY IT IS NOT A SUBSTRING TEST.  The spawn marker goes on our floor, and only a floor
    may nominate where that is.  `'floor' in path` would put the spawn on
    `gameobjects/deathplane/deathfloor` (a kill volume) and `'floors/' in path` alone misses
    the author's own unit, which is `units/custom/duckomp_room/floor` - the reason the spawn
    of the first own-unit build warned "no floors/ among our units" and went to the origin.

    The rule, and what it was measured against - the 280 unit kinds the shipped corpus places:
      * `floors/` anywhere in the path: the test the tool has always used, kept so that no
        shipped level's spawn alignment can move.  It covers
        `blocks/d01_crypt/floors/cryptsmooth_floor_4c_4c` and also
        `gameobjects/procedural_floors/entrance_blocker` (a substring match).
      * a path SEGMENT named `floor` or `floors`: the author's own tile,
        `units/custom/duckomp_room/floor`, which the substring test misses - which is exactly
        why the first own-unit build put the spawn at the origin;
      * a final segment STARTING WITH `floor`: `.../floor_01`.  (A prop whose name merely
        starts with `floor` - `floor_lamp` - would count too; no shipped level and no build of
        ours places one, and such a prop stands ON a floor anyway.)
    Measured: the old test and this one select the SAME 21 corpus kinds, and this one adds the
    author's own.  A plain `'floor' in path` would NOT be safe: it also catches
    `gameobjects/deathplane/deathfloor`, which is a kill volume.
    """
    low = path.lower()
    if 'floors/' in low:
        return True
    segs = [s for s in low.split('/') if s]
    if any(s in ('floor', 'floors') for s in segs):
        return True
    return bool(segs) and segs[-1].startswith('floor')


def write_scratch(placed, out: Path, skeleton: Path, shading: Optional[str] = None,
                  spawn: bool = True, skydome: bool = True,
                  ruler_kinds: Optional[List[str]] = None,
                  spawn_at: Optional[Tuple[float, float, float]] = None,
                  unit_offsets: Optional[Dict[str, list]] = None) -> int:
    """Build a level that is ONLY our content, and say what went into it."""
    paths = unit_paths()
    corpus = shipped_material_map()
    offsets = unit_offsets or {}
    records: List[dict] = []
    unknown: Dict[str, int] = {}
    floors = [p['t'] for p in placed if is_floor_unit(p['unit'])]
    # The MEDIAN tile, per axis: with an odd count that is a tile CENTRE, and with our own
    # 8-unit tiles the median z is the tiles' own surface height, so the marker lands ON the
    # floor rather than 0.18 above it (which is where the first own-unit build put it, at the
    # origin, because it only recognised the corpus' `floors/` directory).
    centre = [sorted(t[k] for t in floors)[len(floors) // 2] for k in range(3)] if floors \
        else [0.0, 0.0, 0.0]
    if spawn_at is not None:
        centre = [float(v) for v in spawn_at]

    # THE RECORD AUDIT.  Every placement's rotation is checked HERE, not in game: the record
    # holds xyz of the branch the engine rebuilds w=-|w| from, and that branch has to be the
    # SAME ROTATION the node asked for.  A single sign error in the branch is invisible in the
    # file and shows up as "the crane is facing backwards" in game (FINDINGS 9H.29), so the
    # build fails loudly instead of shipping it.
    audit = {'n': 0, 'identity': 0, 'worst': 0.0, 'kinds': {}, 'bad': []}
    collide = {'n': 0, 'worst': 0.0}

    def record(p, i):
        mat = corpus.get(p['unit'])
        if mat is None:
            mat = '0x%016x' % 0                # 0 means "no override" - never a NULL lookup
            unknown[p['unit']] = unknown.get(p['unit'], 0) + 1
        # EVERY quaternion that enters a record goes through the branch rule, whatever it came
        # from - `to_engine_rotation` and the recovery already return the branch, and the ruler
        # builds its own.  The rule is idempotent, so "already are" is exactly what it means;
        # while it was NOT (9H.29), the placements that carried their own rotation came out
        # inverted while the identity ones (floors) stayed correct - which is what hid it.
        rot = _record_branch(list(p['q']))
        # THE AUDIT CHECKS THE RECORD, NOT THE INTENT.  A record holds a rotation vector and the
        # engine builds q = normalize(vector, 1.0), so the error is measured between the authored
        # orientation and what the engine will build from the bytes this build writes - not
        # between the intent and itself, which is what it used to compare (FINDINGS 9H.33).
        q_rec = quat_from_record_vector(record_rotation_vector(rot))
        err = _quat_angle_deg(q_rec, p['q'])
        audit['n'] += 1
        audit['worst'] = max(audit['worst'], err)
        if max(abs(v) for v in rot[:3]) < 1e-6:
            audit['identity'] += 1
        else:
            key = tuple(round(v, 4) for v in rot)
            audit['kinds'][key] = audit['kinds'].get(key, 0) + 1
        if err > ORIENT_TOL_DEG:
            audit['bad'].append((p.get('node') or p['unit'], err))
        # THE COLLIDER SHIFT, UNDONE (FINDINGS 9H.41).  build_own_units.py moves a unit's mesh
        # onto the template's collider box, because the collider is anchored in the UNIT'S frame -
        # it is compiled into the template and follows the placement, so only the mesh can move.
        # The placement has to move the other way by the same vector to leave the level looking
        # exactly like Blender, and the vector has to go through the record's own rotation and
        # scale, because that is what the engine applies to the mesh before translating it.
        pos = list(p['t'])
        d = offsets.get(p['unit'])
        if d and max(abs(v) for v in d) > 1e-6:
            s = p['s']
            w = quat_rotate(q_rec, (d[0] * s[0], d[1] * s[1], d[2] * s[2]))
            pos = [float(pos[k] - w[k]) for k in range(3)]
            collide['n'] += 1
            collide['worst'] = max(collide['worst'], math.sqrt(sum(v * v for v in d)))
        return {
            'entity_id': '0x%016x' % _scratch_id(p['unit'], i),
            'template_hash': '0x%016x' % murmur64(p['unit']),
            'material_hash': mat,
            'position': pos,
            'rotation': rot,
            'scale': list(p['s']),
            '_unused': '00' * 8,
        }


    for i, p in enumerate(placed):
        records.append(record(p, i))

    # SAY WHAT THE ROTATIONS CAME OUT AS.  A level of units with no rotation at all is the
    # common case, and the one that cannot expose a branch bug - so when there ARE rotations,
    # each distinct one is listed, which is what the author needs to compare against Blender.
    rotated = audit['n'] - audit['identity']
    print('  rotation: %d placement(s): %d identity, %d rotated; the stored branch reproduces'
          % (audit['n'], audit['identity'], rotated))
    print('            the authored orientation on every one (worst %.3f deg)' % audit['worst'])
    for key, c in sorted(audit['kinds'].items(), key=lambda kv: (-kv[1], kv[0]))[:6]:
        print('            %3d x quat (%s)  = %s'
              % (c, ', '.join('%.4f' % v for v in key), _axis_angle(key)))
    if audit['bad']:
        raise SystemExit('REFUSING: %d record(s) hold a rotation that is not the authored one,'
                         ' e.g. %s by %.3f deg - the branch is being applied twice (9H.29)'
                         % (len(audit['bad']), audit['bad'][0][0], audit['bad'][0][1]))

    if collide['n']:
        print('  collider: %d placement(s) moved back by their unit\'s collider vector (worst'
              ' %.2f units), so the template\'s collider lands on the mesh while the level still'
              ' looks exactly like Blender (FINDINGS 9H.41)' % (collide['n'], collide['worst']))

    # OUR spawn marker.  A donor body inherits the donor's, which is how the previous builds
    # got a spawn at all; a level of our own has to place one, and it goes on our floor.
    if spawn:
        if not floors:
            print('  spawn  : WARNING - none of our units looks like a floor, so the spawn'
                  ' marker goes to (%.1f, %.1f, %.1f) and the player may start in the air:'
                  % tuple(centre))
            print('           place it by hand with --spawn-at X,Y,Z')
        elif spawn_at is not None:
            print('  spawn  : our own player_spawn_marker at (%.2f, %.2f, %.2f) - PLACED BY'
                  ' --spawn-at' % tuple(centre))
        else:
            print('  spawn  : our own player_spawn_marker at (%.2f, %.2f, %.2f) - the median'
                  ' floor tile\'s centre, ON the tile surface' % tuple(centre))
        records.append({
            'entity_id': '0x%016x' % _scratch_id(SPAWN_MARKER, 0),
            'template_hash': '0x%016x' % murmur64(SPAWN_MARKER),
            'material_hash': corpus.get(SPAWN_MARKER, '0x%016x' % 0),
            'position': centre,
            'rotation': [0.0, 0.0, 0.0, 1.0],
            'scale': [1.0, 1.0, 1.0],
            '_unused': '00' * 8,
        })

    # THE ROTATION RULER (diagnostic): four yaws of each kind in a row beside the spawn, so one
    # look says which of them the engine draws the way it should.
    if ruler_kinds:
        for i, p in enumerate(rotation_ruler(placed, centre, ruler_kinds)):
            records.append(record(p, len(placed) + i))
        print('  ruler  : %d test unit(s) at 0/90/180/270 deg, 24 units -x of the spawn'
              % (4 * len(ruler_kinds)))
        for k in ruler_kinds:
            print('           %s' % k)

    # The skeleton's own skydome, copied as it stands: every shipped level has one, and it is
    # the one thing in a level that is neither ours nor the encounter's.
    if skydome:
        for e in decode_level(skeleton.read_bytes())['entities']:
            if 'skydome' in (paths.get(e['template_hash'][2:].lower(), '') or ''):
                sky = dict(e)
                sky['entity_id'] = '0x%016x' % _scratch_id('skydome', 0)
                records.append(sky)
                print('  sky    : %s kept from the skeleton' % paths[sky['template_hash'][2:]])
                break

    meta = None
    if shading:
        meta = encode_metadata([(0xf01676fc, 'float', 1.0),
                                (0xfe73c7dc, 'string', shading),
                                (0xd8b27864, 'string', ''),
                                (0xfe379225, 'string', 'default')])
    blob = write_scratch_level(records, out, skeleton, meta)

    # THE AUDIT THAT WOULD HAVE CAUGHT 9H.36: read the rotation back out of the BYTES that were
    # just written, exactly where the engine reads it - four consecutive floats at record+0x3c,
    # i.e. the vector at 60/64/68 and the w at 72 (the next record's first float, moved there by
    # `shift_leads_forward`).  Comparing the intent against the intent (what this build used to
    # do) cannot see a layout error; comparing the FILE against the author's node can.
    worst = 0.0
    written_bad = []
    for i, p in enumerate(placed):
        o = 128 + i * ENTITY_RECORD_SIZE + 60
        q = [struct.unpack_from('<f', blob, o)[0],
             struct.unpack_from('<f', blob, o + 4)[0],
             struct.unpack_from('<f', blob, o + 8)[0],
             struct.unpack_from('<f', blob, o + 12)[0]]
        err = _quat_angle_deg(q, p['q'])
        worst = max(worst, err)
        if err > ORIENT_TOL_DEG:
            written_bad.append((p.get('node') or p['unit'], err))
    if written_bad:
        raise SystemExit(
            'REFUSING: %d written record(s) do not hold the authored rotation, e.g. %s by %.3f '
            'deg - the transform lead is not where the engine reads it (FINDINGS 9H.36)'
            % (len(written_bad), written_bad[0][0], written_bad[0][1]))
    print('  written: the engine\'s four floats at record+0x3c reproduce the authored rotation on'
          ' all %d placement(s) (worst %.3f deg)' % (len(placed), worst))

    kinds: Dict[str, int] = {}
    for p in placed:
        kinds[p['unit']] = kinds.get(p['unit'], 0) + 1
    print('  level  : %d record(s) = %d placement(s) + %d of ours, %d bytes'
          % (len(records), len(placed), len(records) - len(placed), len(blob)))
    print('  kinds  : %d distinct unit kind(s), %d from the shipped corpus'
          % (len(kinds), len(kinds) - len(unknown)))
    if unknown:
        print('  material: WARNING - %d kind(s) no shipped level places, written with no'
              % len(unknown))
        print('           override (0): %s' % ', '.join(sorted(unknown)[:4]))
    print('  wrote  : %s' % out)
    return 0


def baked_nodes(js: dict) -> bool:
    """True when NO node carries a transform: the exporter baked them into the meshes.

    Blender does that when the author applies scale/rotation/location (Ctrl+A).  Every node is
    then `{"name": ..., "mesh": N}` and each object's transform lives in its mesh vertices, so
    there is no per-unit rotation left to read - and the engine needs one, because it rotates
    ITS OWN unit mesh by the record's rotation (FINDINGS 9H.22.3).
    """
    mesh_nodes = [n for n in js['nodes']
                  if 'mesh' in n and not ignored_node(n.get('name', ''))]
    if not mesh_nodes:
        return False
    return not any(k in n for n in mesh_nodes
                   for k in ('translation', 'rotation', 'scale', 'matrix'))


def canonical_meshes(references) -> Dict[str, List[dict]]:
    """kind -> the reference levels' mesh parts, in each unit's OWN local frame.

    Level exports from level_to_glb are the references to use: they write each unit's mesh in
    the unit's local space and the engine's record as the node's transform, so a mesh read out
    of one is the canonical shape around the canonical origin.  SEVERAL are merged, because no
    single level carries every kind - crypt_arena01 has no crypt_railing_end, crypt_rock_01 or
    coffin_open, and those are exactly the nodes that came back unrecovered when only it was
    passed.
    """
    if isinstance(references, (str, Path)):
        references = [references]
    by = load_names()
    out: Dict[str, List[dict]] = {}
    seen = set()
    for reference in references:
        js = read_glb(Path(reference))
        for node in js['nodes']:
            if 'mesh' not in node:
                continue
            if ignored_node(node.get('name', '')):
                continue
            kind = resolve(base_name(node.get('name', '')), by)
            if kind is None:
                continue
            for prim in js['meshes'][node['mesh']]['primitives']:
                verts = accessor_vec3(js, prim['attributes']['POSITION'])
                if len(verts) < 3:
                    continue
                lo = [min(v[i] for v in verts) for i in range(3)]
                hi = [max(v[i] for v in verts) for i in range(3)]
                key = (kind, len(verts)) + tuple(round(v, 1) for v in lo + hi)
                if key in seen:
                    continue
                seen.add(key)
                out.setdefault(kind, []).append({'verts': verts, 'lo': lo, 'hi': hi})
    return out


def _kabsch(p, q):
    """The rigid (rotation, translation) taking p onto q; p and q are the SAME points in order."""
    import numpy as np
    P = np.asarray(p, dtype=np.float64)
    Q = np.asarray(q, dtype=np.float64)
    cp, cq = P.mean(axis=0), Q.mean(axis=0)
    H = (P - cp).T @ (Q - cq)
    U, _s, Vt = np.linalg.svd(H)
    D = np.eye(3)
    if np.linalg.det(Vt.T @ U.T) < 0:
        D[2, 2] = -1.0
    R = Vt.T @ D @ U.T
    return R, cq - R @ cp


def _mat_to_quat(R) -> List[float]:
    """xyzw quaternion of a rotation matrix."""
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2.0
        return [(R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s,
                (R[1][0] - R[0][1]) / s, 0.25 * s]
    i = max(range(3), key=lambda k: R[k][k])
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1.0 + R[i][i] - R[j][j] - R[k][k]) * 2.0
    q = [0.0, 0.0, 0.0, 0.0]
    q[i] = 0.25 * s
    q[j] = (R[j][i] + R[i][j]) / s
    q[k] = (R[k][i] + R[i][k]) / s
    q[3] = (R[k][j] - R[j][k]) / s
    return q


def _quat_angle_deg(a, b) -> float:
    """How far apart two unit quaternions are, as an angle in degrees (0 = the same rotation).

    Used by the record audit in write_scratch: a record stores xyz and the engine rebuilds
    w = -|w|, so the ONE thing that has to be true of every record's rotation is that the
    branch the record holds is the SAME ROTATION as the orientation the node asked for.
    `abs` on the dot product is what makes q and -q come out 0 apart, which is the whole
    point of the branch.
    """
    d = abs(sum(float(x) * float(y) for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(min(1.0, d)))


def _axis_angle(q) -> str:
    """A quaternion spelled the way a person reads it back: `108.4 deg about (0, 0, +1)`.

    The angle is reported in (0, 180] by flipping the axis into the half that gives it - a
    record holding 251.6 degrees about -Z and one holding 108.4 degrees about +Z are the same
    rotation, and only the second is what the author set in Blender, so that is the one the
    build report has to show.
    """
    x, y, z, w = (float(v) for v in q)
    ax = [-x, -y, -z] if w < 0.0 else [x, y, z]
    s = math.sqrt(ax[0] * ax[0] + ax[1] * ax[1] + ax[2] * ax[2])
    angle = math.degrees(2.0 * math.atan2(s, abs(w)))
    if s < 1e-6:
        return 'identity (0 deg)'
    return '%.1f deg about (%s)' % (angle, ', '.join(
        '%+.3f' % (v / s) for v in ax))


def _record_branch(q, enabled: bool = True) -> List[float]:
    """The branch the RECORD must hold: q and -q are the same rotation, but a record stores
    only xyz and the engine derives w = -|w|, so a quaternion with w > 0 has to be negated -
    ALL FOUR components, which is a no-op as a rotation but puts the value in the branch the
    engine rebuilds.  Negating xyz alone would be a different rotation (the inverse), which is
    the mirror bug 9H.23.5 chased on the recovered path and which the double application of
    this rule re-introduced on the un-baked path (FINDINGS 9H.29).

    IDEMPOTENT BY CONSTRUCTION - the output always has w < 0, so applying it again cannot
    change anything.  That is what makes it safe to call on EVERY quaternion that enters a
    record, whatever produced it: `to_engine_rotation` already returns the branch, the
    recovery returns the branch, and the rotation ruler builds its own - and all three are
    handed the same treatment.  It was NOT idempotent while `to_engine_rotation` negated only
    xyz and left w positive: the rule read that as un-branched and flipped it back.

    `enabled=False` is the diagnostic that tells the two apart in one build: with the rule the
    walls came out right and the coffins/railings did not, and without it the reverse - so a
    build of each says which set the rule is for.
    """
    x, y, z, w = q
    if enabled and w > 0.0:
        return [-x, -y, -z, -w]
    return [x, y, z, w]


def _bbox_err_lo_hi(lo, hi, R, ext) -> float:
    """How far a box (given by its own lo/hi), rotated by R, is from the baked extents.

    The union of a kind's parts is what a baked node's box should be compared with: a unit can
    be several parts, and comparing one part's box against the whole node's extents is what made
    the box route blind to a tilt for the multi-part kinds.
    """
    import numpy as np
    plo, phi = np.array(lo), np.array(hi)
    corners = np.array([[plo[0] if (m >> 0) & 1 else phi[0],
                         plo[1] if (m >> 1) & 1 else phi[1],
                         plo[2] if (m >> 2) & 1 else phi[2]] for m in range(8)])
    rc = corners @ R.T
    return float(np.abs((rc.max(axis=0) - rc.min(axis=0)) - ext).sum())


def _bbox_err(part, R, ext) -> float:
    """How far a canonical part's box, rotated by R, is from the baked box's extents."""
    import numpy as np
    plo, phi = np.array(part['lo']), np.array(part['hi'])
    corners = np.array([[plo[0] if (m >> 0) & 1 else phi[0],
                         plo[1] if (m >> 1) & 1 else phi[1],
                         plo[2] if (m >> 2) & 1 else phi[2]] for m in range(8)])
    rc = corners @ R.T
    return float(np.abs((rc.max(axis=0) - rc.min(axis=0)) - ext).sum())


def recover_baked(js: dict, by_base, deg_pos: int, reference, branch: bool = True):
    """Rebuild (position, rotation) per node from the baked meshes, against a reference.

    Two routes, and which one ran is counted so the report can say so:

      EXACT  the baked mesh has the same vertex count as a reference part, so the two are the
             same mesh rigidly moved and a Kabsch fit gives the rotation and the position
             exactly - the correspondence is by vertex index, which is what makes it exact
             rather than a guess.
      BOX    the counts differ (a proxy, or an exporter that de-duplicated differently), so
             the fit falls back to bounding boxes: the canonical box under each of the
             axis-aligned orientations is compared with the baked box and the best wins.  A box
             is symmetric, so its yaw comes back only up to that symmetry - which is as much as
             the engine's own mesh can tell apart.
    """
    import numpy as np
    ref = canonical_meshes(reference)
    if not ref:
        raise SystemExit('%s yielded no canonical meshes - is it a level export?'
                         % reference)
    # THE 24 PROPER ROTATIONS OF A CUBE, NOT THE 10 THE AXIS LOOP GIVES.
    # This used to be `for axis in x,y,z: for angle in 0,90,180,270`, which produces only 10
    # distinct matrices: the identity, the 90/270 about the three face axes (6) and the 180
    # about the three face axes (3).  The cube's proper rotation group has 24 - the other 14
    # are the 120/240 about the four body diagonals (8) and the 180 about the six edge axes
    # (6) - and a level that uses them (the author's symmetric test arena does) then gets the
    # wrong orientation for every unit whose true rotation is one of the missing ones.  The
    # symptom is exact and recognisable: the recovered rotation is a 120 or 180 degree flip of
    # the engine's own value, which is what "everything is scattered" measured (FINDINGS 9H.26).
    import itertools
    rots = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            M = np.zeros((3, 3))
            for row, (col, sign) in enumerate(zip(perm, signs)):
                M[row][col] = sign
            if round(float(np.linalg.det(M))) > 0:          # det +1 = a proper rotation
                rots.append(M)
    out: Dict[int, Tuple[list, list]] = {}
    stats = {'exact': 0, 'box': 0, 'nokind': 0, 'unmatched': [], 'box_kinds': {},
             'proxy_kinds': {}, 'exact_idx': set()}
    for idx, node in enumerate(js['nodes']):
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            continue
        kind = resolve(base_name(node.get('name', '')), by_base)
        parts = ref.get(kind) if kind else None
        if not parts:
            stats['nokind'] += 1
            continue
        verts: List[Tuple[float, float, float]] = []
        for prim in js['meshes'][node['mesh']]['primitives']:
            verts += accessor_vec3(js, prim['attributes']['POSITION'])
        if len(verts) < 3:
            stats['nokind'] += 1
            continue
        # The baked vertices are in the FILE's frame; the reference's are engine-space.
        V = np.array([x_rot(deg_pos, v) for v in verts], dtype=np.float64)
        lo, hi = V.min(axis=0), V.max(axis=0)
        centre, ext = (lo + hi) / 2.0, hi - lo
        part = next((p for p in parts if len(p['verts']) == len(verts)), None)
        if part is not None:
            R, t = _kabsch(part['verts'], V)
            out[idx] = (list(t), _record_branch(_mat_to_quat(R), branch))
            stats['exact'] += 1
            stats['exact_idx'].add(idx)
            continue
        # IS THIS NODE EVEN THE GAME'S UNIT?  A baked export has no transforms, so the recovery
        # fits the REFERENCE mesh to the node's geometry.  That is exact when the node IS the
        # game's unit, and meaningless when it is not - and a level authored with simple proxy
        # plates named after game units is exactly that case: a "railing" that is 0.45 x 0.02 x
        # 0.45 cannot be fitted to the game's 8.34-long railing, so the box ties on cube
        # symmetries and the rotations come out flipped by 120 or 180 degrees (FINDINGS 9H.27).
        # Nothing here can fix that - only an UN-BAKED export can, because then the node's own
        # transform is read instead of recovered.  So count it and say it.
        allv0 = np.array([v for part in parts for v in part['verts']], dtype=np.float64)
        gext = np.sort(allv0.max(axis=0) - allv0.min(axis=0))
        bext = np.sort(np.array(ext))
        if any(abs(bext[i] - gext[i]) > 0.25 * max(gext[i], 0.01) for i in range(3)):
            stats['proxy_kinds'][kind] = stats['proxy_kinds'].get(kind, 0) + 1

        # THE UNIT'S WHOLE CLOUD, NOT ONE PART OF IT.  A kind can be several parts - a railing
        # is two coincident parts, a skeleton a dozen - and the vertex check below used to run
        # per PART while the baked node carries all of them, so for exactly those kinds it
        # scored noise and the BOX decided.  A box cannot see a tilt, so the unit came back
        # flipped by 120 or 180 degrees (the author's symmetric test arena is built from the
        # cube's rotations, and the box route only knew 10 of the 24 - FINDINGS 9H.26).  Union
        # the kind's parts once, and use the union for both the box error and the vertices.
        allv = np.array([v for part in parts for v in part['verts']], dtype=np.float64)
        ulo, uhi = allv.min(axis=0), allv.max(axis=0)
        # Subsample: the distance below is O(|cloud|^2), and 256 points per cloud discriminates
        # the candidates just as well as thousands.
        if len(allv) > 256:
            allv_s = allv[::max(1, len(allv) // 256)]
        else:
            allv_s = allv
        V_s = V[::max(1, len(V) // 256)] if len(V) > 256 else V
        best, best_err = None, None
        for R in rots:
            err = _bbox_err_lo_hi(ulo, uhi, R, ext)
            if best_err is None or err < best_err:
                best_err, best = err, R
        if best is None:
            stats['unmatched'].append(kind)
            continue
        # THE VERTICES DECIDE, over the WHOLE candidate set.  The box only shortlists - and with
        # a real box many candidates tie on extents, so a shortlist that cuts the list early can
        # drop the author's orientation before the geometry ever sees it.
        vmean = V.mean(axis=0)
        pick = None
        for R in rots:
            t = vmean - R @ allv.mean(axis=0)
            d = float(np.abs((allv_s @ R.T + t)[None, :, :] - V_s[:, None, :]).sum(axis=2)
                      .min(axis=0).mean())
            if pick is None or d < pick[0]:
                pick = (d, R, t)
        R, t = pick[1], pick[2]
        out[idx] = (list(t), _record_branch(_mat_to_quat(R), branch))
        stats['box'] += 1
        stats['box_kinds'][kind] = stats['box_kinds'].get(kind, 0) + 1
    return out, stats


def build(glb: Path, donor: Path, out: Path, max_entities: Optional[int],
          z_offset: Optional[float], body: Optional[Path] = None,
          keep_from: Optional[Path] = None, allow_logic: bool = False,
          hide: str = 'move', align: str = 'none',
          offset: Optional[Tuple[float, float, float]] = None, fit: bool = False,
          verbatim: bool = False, keep_slot_transform: bool = False,
          scratch: bool = False, skeleton: Optional[Path] = None,
          shading: Optional[str] = None, spawn: bool = True,
          with_skydome: bool = True, reference: Optional[Path] = None,
          branch: bool = True, ruler: bool = False,
          mesh_frame: str = 'auto',
          spawn_at: Optional[Tuple[float, float, float]] = None,
          unit_offsets: Optional[Dict[str, list]] = None,
          spawn_at_node: Optional[str] = None) -> int:
    js = read_glb(glb)
    by_base = load_names()

    # WHICH WAY IS UP?  Two questions, and they are NOT the same one:
    #
    #   PLACEMENTS (detect_vertical + detect_world_up)  the frame the layout is in.  Decides
    #       how POSITIONS are read.
    #   MESHES     (detect_mesh_up)                     the frame the unit geometry is in.
    #       Decides how the RECORD'S ROTATION is built.
    #
    # Reading the placements as if they answered the mesh question is what shipped three
    # levels with every placed unit on its side: a Blender export can lay an engine-space
    # layout out with Y-up geometry, and then only the rotation needs converting.
    axis, why = detect_vertical(js, by_base)
    mesh_up, mesh_why = detect_mesh_up(js, by_base)
    world_up, world_why = detect_world_up(js, by_base, mesh_up)
    if world_up is None:
        # No floor to measure: fall back to the axis the placements are flat on, assuming the
        # level stands up in the positive direction of it (the old behaviour).
        world_up = 2 * axis
        world_why = '%s; assuming +%s is up' % (why, 'XYZ'[axis])
    deg_pos = -x_deg_for(world_up) if world_up is not None else 0
    # The meshes live in the file's world frame unless the normals say otherwise - that is
    # the self-consistent case, and it is the conjugation.
    deg_mesh = x_deg_for(mesh_up) if mesh_up is not None else -deg_pos
    if mesh_frame != 'auto':
        # THE OVERRIDE, AND WHY IT IS NOT PER-UNIT.  It is tempting to think the author's own
        # units need F' = 0 ("their mesh is already engine-space, so the rotation is already in
        # the engine's frame") - but a native unit in the same file is in the SAME frame as
        # theirs: the engine's own mesh is Z-up, and both the file's copy of it and the copy
        # build_own_units.py writes carry the same file -> engine change.  Giving the author's
        # units a different F' would tilt them 90 degrees against the placement and turn every
        # floor into a wall (the nine identity records ARE the proof: they are only identity
        # because deg_mesh = -90 cancels the layout's +90).  So this knob is for the case the
        # measurement cannot answer - no flat mesh, or normals the exporter dropped - and it
        # says what the WHOLE file's mesh data is, not what one unit is.
        deg_mesh = {'y-up': -90, 'engine': 0}[mesh_frame]
        mesh_why = ('FORCED by --mesh-frame %s: the mesh data is %s' % (
            mesh_frame, 'Y-up in the file (a normal Blender +Y-up export)'
            if mesh_frame == 'y-up' else 'already engine-space (Z-up)'))
    # Which coordinate the level stands up on IN THE FILE (for the extent sanity note below).
    up_axis = {4: 2, 5: 2, 2: 1, 3: 1}.get(world_up, 0)
    print('GLB      : %s' % glb.name)
    print('  up     : placements: %s' % world_why)
    print('           -> positions %s' % (
        'are read as-is (the layout is already engine-space)' if deg_pos == 0
        else 'rotated %+d degrees about X into engine Z-up' % deg_pos))
    print('  up     : meshes    : %s' % mesh_why)
    print('           -> rotations %s' % (
        'are read as-is (the geometry is already engine-space)' if deg_mesh == 0
        else 'are composed with a %+d degree X rotation (F^-1 * R_node * F\')' % deg_mesh))
    if deg_mesh != -deg_pos:
        # F (the layout's frame change) is R_x(-deg_pos) and F' is R_x(deg_mesh); a
        # self-consistent export has them EQUAL, i.e. deg_mesh == -deg_pos.  A plain Y-up
        # file is +90/-90 and perfectly consistent - comparing the two degrees directly
        # would flag every one of them.
        print('  *** MIXED EXPORT: the layout is %+d degrees from engine space but the MESHES'
              % deg_pos)
        print('      are %+d, i.e. a different frame - so the record needs BOTH changes, and'
              % deg_mesh)
        print('      getting the pair wrong is what shipped crypt_arena01_custom / hub_custom')
        print('      / custom_duckomp_room tumbled.  If a build looks wrong in game, this line')
        print('      is the first thing to re-check.')

    # A BAKED EXPORT HAS NO PER-NODE TRANSFORM (FINDINGS 9H.22.3).  Reading one as if it had
    # TRS puts every unit at the origin, which is why this is checked before anything else:
    # either the transforms are recovered from the meshes against a reference, or the build
    # stops and says why.
    recovered: Dict[int, Tuple[list, list]] = {}
    baked = baked_nodes(js)
    if baked:
        print('  baked  : *** NO NODE HAS A TRANSFORM - this export applied them into the'
              ' meshes')
        if reference is None:
            raise SystemExit(
                'REFUSING: every node in %s is `{"name": ..., "mesh": N}` - the exporter baked\n'
                'scale/rotation/location into the mesh vertices, so there is no per-unit\n'
                'rotation left to read and every unit would be written at the origin.\n'
                '\n'
                'Two ways forward:\n'
                '  1. Re-export from Blender WITHOUT applying the transforms (do not use\n'
                '     Ctrl+A on the objects): the tool then converts positions and rotations\n'
                '     from the export\'s own frame, which is the path everything is verified\n'
                '     on.  This is the one to prefer.\n'
                '  2. Pass --reference <a level export .glb> and the transforms are recovered\n'
                '     from the meshes instead: exact where the mesh is the game\'s own (a\n'
                '     vertex-for-vertex fit), and from bounding boxes - so yaw only, up to the\n'
                '     mesh\'s own symmetry - where it is not.' % glb)
        recovered, stats = recover_baked(js, by_base, deg_pos, reference, branch)
        refs = [reference] if isinstance(reference, (str, Path)) else list(reference)
        print('  baked  : recovered %d of %d mesh node(s) against %d reference(s): %s'
              % (len(recovered), len([n for n in js['nodes'] if 'mesh' in n]), len(refs),
                 ', '.join(Path(r).name for r in refs[:3])
                 + (' (+%d)' % (len(refs) - 3) if len(refs) > 3 else '')))
        print('           %d exact (vertex-for-vertex), %d from bounding boxes, %d unknown'
              ' kind, %d unmatched'
              % (stats['exact'], stats['box'], stats['nokind'], len(stats['unmatched'])))
        if stats['unmatched']:
            print('           unmatched kinds: %s'
                  % ', '.join(sorted(set(stats['unmatched']))[:4]))
        if stats['box_kinds']:
            print('           yaw-only (a box cannot say more): %s'
                  % ', '.join('%s x%d' % (k.split('/')[-1], v)
                              for k, v in sorted(stats['box_kinds'].items(),
                                                 key=lambda kv: -kv[1])[:6]))
        if stats['proxy_kinds']:
            tot = sum(stats['proxy_kinds'].values())
            print('  baked  : *** %d node(s) ARE NOT THE GAME UNIT ***' % tot)
            print('           their geometry does not match the unit their name resolves to: %s'
                  % ', '.join('%s x%d' % (k.split('/')[-1], v)
                              for k, v in sorted(stats['proxy_kinds'].items(),
                                                 key=lambda kv: -kv[1])[:6]))
            print('           a baked export has no node transforms, so the fit above had to')
            print('           guess - and a shape that is not the unit cannot be fitted to it.')
            print('           RE-EXPORT WITHOUT APPLYING THE TRANSFORMS (do not Ctrl+A): the')
            print('           node transforms are then read instead of recovered, and the')
            print('           geometry only has to exist, not match.')
        # A node with no recovery must NOT fall through to the TRS path: there is no TRS in
        # this file, so it would be written at the origin - the exact silent failure this
        # whole check exists to prevent.  It is dropped and counted instead.
        dropped = [n.get('name', '') for i, n in enumerate(js['nodes'])
                   if 'mesh' in n and i not in recovered]
        if dropped:
            print('  baked  : *** %d node(s) could NOT be recovered and are DROPPED, not'
                  ' placed at the origin: %s' % (len(dropped), ', '.join(dropped[:4])))
        # ONE ENTITY PER UNIT, not one per MESH PART.  An exported unit arrives as one node per
        # mesh part (a coffin is a body and a lid, a brazier is two pieces), and the engine's
        # unit already contains all of them - so placing every part would put two complete
        # units on the same spot, and with baked geometry the two fits can disagree and face
        # different ways.  Parts of one unit sit within a fraction of a unit of each other, so
        # they are merged, preferring a part that was recovered exactly.
        by_kind: Dict[str, List[int]] = {}
        for i in recovered:
            kind = resolve(base_name(js['nodes'][i].get('name', '')), by_base)
            by_kind.setdefault(kind or '', []).append(i)
        merged = 0
        for kind, idxs in by_kind.items():
            groups: List[List[int]] = []
            for i in idxs:
                t = recovered[i][0]
                for g in groups:
                    tg = recovered[g[0]][0]
                    if all(abs(t[k] - tg[k]) <= 1.0 for k in range(3)):
                        g.append(i)
                        break
                else:
                    groups.append([i])
            for g in groups:
                if len(g) < 2:
                    continue
                keep = next((i for i in g if i in stats['exact_idx']), g[0])
                for i in g:
                    if i != keep:
                        recovered.pop(i)
                        merged += 1
        if merged:
            print('  baked  : %d node(s) merged away: they are the other MESH PARTS of a unit'
                  ' whose entity is already placed' % merged)

    placed: List[dict] = []
    unresolved: Dict[str, int] = {}
    # NODES THE AUTHOR MARKED AS NOT PART OF THE BUILD (an object whose name carries one of
    # IGNORE_NAME_SUBSTRINGS - working copies, scratch parts).  They are skipped everywhere and
    # reported as IGNORED, not as an unresolved unit name: the difference matters, because an
    # unresolved name is a build error to fix while an ignored one is a decision already made.
    ignored_names: List[str] = []

    # THE ORIENTATION CHECK (FINDINGS 9H.29).  A record's rotation must reproduce the orientation
    # the node gives its mesh in the ENGINE'S frame: F * R_node * F^-1, F being the file -> engine
    # change the positions get.  It is checked for every placement that is COMPUTED from a node
    # transform (the recovered path is already in the engine's frame, and only applies when an
    # export is baked), and a mismatch REFUSES the build rather than shipping a level whose crane
    # faces backwards - which is what the double-branched build did, invisibly, because only the
    # placements that carried their own rotation were affected.
    orient = {'n': 0, 'worst': 0.0, 'bad': [], 'skipped': 0}
    for idx, node in enumerate(js['nodes']):
        if 'mesh' not in node:
            continue
        if ignored_node(node.get('name', '')):
            ignored_names.append(node.get('name', ''))
            continue
        base = base_name(node.get('name', ''))
        path = resolve(base, by_base)
        if path is None:
            unresolved[base] = unresolved.get(base, 0) + 1
            continue
        if baked and idx not in recovered:
            continue                  # no transform exists for it: dropped, and said so above
        if idx in recovered:
            # A BAKED export: no node transform exists, so (position, rotation) came from the
            # meshes themselves and is already in the engine's frame - converting it again
            # would double-apply the frame change.
            t, q = recovered[idx]
            s = [float(v) for v in node.get('scale', [1.0, 1.0, 1.0])]
            placed.append({'unit': path, 't': t, 'q': q, 's': s, 'node': node.get('name', '')})
            orient['skipped'] += 1
            continue
        if verbatim:
            # VERBATIM: no alignment, no normalisation, no quaternion-branch rewriting - but
            # the axis changes the export needs.  Positions follow the WORLD frame, the
            # rotation follows BOTH frames (see to_engine_rotation).  The quaternion is
            # stored WHOLE (see the placement loop), so the engine can keep whichever half of
            # it it actually reads.
            t = to_engine_position(node.get('translation', [0.0, 0.0, 0.0]), deg_pos)
            q = to_engine_rotation(node.get('rotation', [0.0, 0.0, 0.0, 1.0]), deg_pos,
                                   deg_mesh)
            # THE RECORD'S OFFSET-0 FIELD IS ALWAYS <= 0 in every shipped level (corpus:
            # -1.0 at 0 degrees, -0.7071 at 90, 0.0 at 180).  Storing a POSITIVE w there -
            # which the raw glTF gives for 918 of these 1000 nodes - is a value the engine
            # never sees from its own data, and every crashing build wrote either that or a
            # zeroed material.  q and -q are the same rotation, so put it in the branch the
            # engine's own records use before storing it.
            if q[3] > 0.0:
                q = [-q[0], -q[1], -q[2], -q[3]]
        else:
            t = to_engine_position(node.get('translation', [0.0, 0.0, 0.0]), deg_pos)
            q = to_engine_rotation(node.get('rotation', [0.0, 0.0, 0.0, 1.0]), deg_pos,
                                   deg_mesh)
        if deg_mesh == -deg_pos:
            # The self-consistent export: the meshes sit in the same frame as the layout, which
            # is the case F * R_node * F^-1 describes.  A MIXED export (9H.22) is the one where
            # the mesh frame genuinely differs, so it is reported instead of judged.
            # Measured against what the ENGINE will build from the record's three floats - the
            # record holds a rotation vector, q = normalize(vector, 1.0) - so this is the error
            # the author would see in game (FINDINGS 9H.33).
            err = _orientation_error(node.get('rotation', [0.0, 0.0, 0.0, 1.0]), deg_pos,
                                     quat_from_record_vector(record_rotation_vector(q)))
            orient['n'] += 1
            orient['worst'] = max(orient['worst'], err)
            if err > ORIENT_TOL_DEG:
                orient['bad'].append((node.get('name', ''), err))
        else:
            orient['skipped'] += 1
        s = [float(v) for v in node.get('scale', [1.0, 1.0, 1.0])]
        placed.append({'unit': path, 't': t, 'q': q, 's': s})

    if orient['n']:
        print('  orient : %d placement(s) checked against their node: every record reproduces'
              ' F * R_node * F^-1' % orient['n'])
        print('           (worst %.3f deg)' % orient['worst'])
    if orient['skipped']:
        print('  orient : %d placement(s) NOT checked - recovered from geometry, or the export'
              ' is mixed' % orient['skipped'])
    if orient['bad']:
        raise SystemExit(
            'REFUSING: %d placement(s) hold a rotation that is NOT the orientation their node '
            'asks for in the engine\'s frame, e.g. %r by %.3f deg.\n'
            'An INVERSE record is the double-branch bug of FINDINGS 9H.29: to_engine_rotation '
            'has to negate ALL FOUR quaternion components when w > 0, not just xyz, or the '
            'record-branch rule applied later undoes it.'
            % (len(orient['bad']), orient['bad'][0][0], orient['bad'][0][1]))

    lo, hi = world_bounds(js)
    extent = [hi[i] - lo[i] for i in range(3)]
    vertical = extent.index(min(extent))
    print('  nodes  : %d with a mesh (%d placed, %d dropped%s)' % (
        sum(1 for n in js['nodes'] if 'mesh' in n), len(placed),
        sum(unresolved.values()),
        (', %d ignored' % len(ignored_names)) if ignored_names else ''))
    if ignored_names:
        shown = ', '.join(sorted(ignored_names)[:4]) + (' ...' if len(ignored_names) > 4 else '')
        print('  ignored: %d node(s) whose name carries %s - NOT placed, and excluded from the'
              ' up-axis measurements: %s'
              % (len(ignored_names), '/'.join(repr(s) for s in IGNORE_NAME_SUBSTRINGS), shown))
    if unresolved:
        print('  UNRESOLVED unit names (dropped - fix these before shipping):')
        for b, c in sorted(unresolved.items(), key=lambda kv: -kv[1]):
            print('     %4d  %s' % (c, b))
    print('  extent : %.1f x %.1f x %.1f   (GLB space: x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f)'
          % (extent[0], extent[1], extent[2], lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))
    if vertical != up_axis:
        print('  *** NOTE: the smallest extent is on %s while the floors say the level stands'
              % 'XYZ'[vertical])
        print('      up on %s.  The floors win (a level is mostly floor tiles lying in one'
              % 'XYZ'[up_axis])
        print('      plane), and the extent test is known to be fooled by a wide, low level.  If')
        print('      the level is still wrong in game, this disagreement is the first thing to')
        print('      re-check.')

    scales = sorted({tuple(round(v, 4) for v in p['s']) for p in placed})
    if scales != [(1.0, 1.0, 1.0)]:
        print('  scales : %d distinct, e.g. %s' % (len(scales), scales[:3]))
        print('           NOTE: a unit collider follows the entity scale downward, so a'
              ' scaled placement gets a SMALLER collider.')

    # ---- A LEVEL OF OUR OWN ---------------------------------------------------------
    # No donor body, so none of the donor's flow, volumes, markers or leftover scenery comes
    # with it - which is the whole point (FINDINGS 9H.23).  The only shared thing is the
    # section skeleton, which every shipped level has and none of it is content.
    if scratch:
        if spawn_at_node:
            # READ THE SPAWN OFF THE SCENE.  The author's own marker object is the intent, and a
            # coordinate on a command line goes stale the moment it is moved - so resolve it here,
            # where the axis this build detected (deg_pos) is known.
            want = base_name(spawn_at_node)
            matches = [n for n in js.get('nodes', []) if base_name(n.get('name', '')) == want]
            if not matches:
                raise SystemExit('--spawn-at-node %s: no node of that name in %s'
                                 % (spawn_at_node, glb.name))
            if len(matches) > 1:
                print('  spawn  : %d node(s) match %s - using the first (%s)'
                      % (len(matches), spawn_at_node, matches[0].get('name')))
            t = matches[0].get('translation', [0.0, 0.0, 0.0])
            spawn_at = tuple(to_engine_position(t, deg_pos))
            print('  spawn  : --spawn-at-node %s -> engine (%.3f, %.3f, %.3f) from glTF %s'
                  % (spawn_at_node, spawn_at[0], spawn_at[1], spawn_at[2],
                     [round(float(v), 3) for v in t]))
        if z_offset:
            for p in placed:
                p['t'][2] += z_offset
            print('  align  : applied %+.2f to all %d placements' % (z_offset, len(placed)))
        return write_scratch(placed, out, skeleton or SCRATCH_SKELETON, shading,
                             spawn=spawn, skydome=with_skydome,
                             ruler_kinds=RULER_KINDS if ruler else None,
                             spawn_at=spawn_at, unit_offsets=unit_offsets)

    data = decode_level((body or donor).read_bytes())
    before = data['entity_count']
    ents = data['entities']

    # ---- OUR PLACEMENTS: hand back what the GENERATOR owns, then cap if asked ---------
    ours_logic = [p for p in placed if classify(p['unit']) == 'keep']
    if ours_logic and not allow_logic:
        placed = [p for p in placed if classify(p['unit']) != 'keep']
        kinds: Dict[str, int] = {}
        for p in ours_logic:
            kinds[p['unit']] = kinds.get(p['unit'], 0) + 1
        print('  ours   : %d generator-managed unit(s) left OUT - the arena already has'
              % len(ours_logic))
        print('           its own and two sets fight each other: %s'
              % ', '.join('%d x %s' % (c, u) for u, c in sorted(kinds.items())))
        print('           --allow-logic places them anyway')
    # NO SCALE WRITES.  This is the one rule the evidence is unambiguous about, and it is not
    # a preference:
    #
    #   --hide move  (positions only)          -> the level LOADS
    #   --hide scale (decor scale 0.0001)      -> crash_trace.log: 0xC0000005 write at 0,
    #   --fit        (our units scale 0.174)      RVA 0x30224, "MOV byte ptr [ESI+ECX-1],AL"
    #                                             - a byte store into a buffer FUN_0042f120
    #                                             returned NULL
    #
    # Three crashing builds wrote an entity's scale (or zeroed its material); the one that
    # loaded wrote neither.  So the converter refuses to write a scale other than 1.0 rather
    # than producing a level that takes the game down at load.
    if hide == 'scale':
        raise SystemExit(
            'REFUSING --hide scale: collapsing a unit writes its scale field, which is one of\n'
            'the two things every crashing build had in common (the other is a zeroed\n'
            'material).  The engine fault is a byte store into a NULL buffer at RVA 0x30224.\n'
            'Use --hide move, which only moves positions and is the variant that loads.')
    if fit:
        raise SystemExit(
            'REFUSING --fit: fitting a layout to the module means scaling its units, and that\n'
            'is exactly the write that crashes the load (RVA 0x30224, NULL buffer).  A level\n'
            'cannot be shrunk - the game never scales a placed unit with geometry behind it.\n'
            'Author inside the module footprint instead, or use a larger canvas.')

    if max_entities is not None and len(placed) > max_entities:
        want = len(placed)
        # Keep ARCHITECTURE first when the body is tight.  Keeping the rarest kinds (the old
        # rule) would drop floors and walls and keep urns - which is the wrong way round: a
        # level is what can be walked on and what stands up.  Floors, then blocks (walls,
        # borders, pillars, rocks, railings, stairs), then props, then what is only seen.
        def rank(p: dict) -> int:
            u = p['unit']
            if 'floor' in u or 'stairs' in u:
                return 0
            if u.startswith('blocks/') or 'wall' in u or 'pillar' in u or 'border' in u \
               or 'railing' in u or 'rock' in u:
                return 1
            if u.startswith(('lights/', 'decals/')):
                return 3
            return 2
        count: Dict[str, int] = {}
        for p in placed:
            count[p['unit']] = count.get(p['unit'], 0) + 1
        placed = sorted(placed, key=lambda p: (rank(p), count[p['unit']], p['unit']))[:max_entities]
        print('  cap    : %d placements, this body has room for %d - dropped %d, keeping floors'
              % (want, max_entities, want - len(placed)))
        print('           and walls (the shape of the level) and dropping decoration last')

    # ---- WHAT SURVIVES, AND WHAT IS OURS TO REPLACE -----------------------------------
    keep_data = data if keep_from is None else decode_level(keep_from.read_bytes())
    keep_sig = {entity_sig(e) for e in keep_data['entities']
                if classify(unit_of(e)) in ('keep', 'core')}

    # WHAT MATERIAL DOES THE ARENA ITSELF USE FOR THIS KIND OF UNIT?  Ask the body.  For every
    # kind it places, it also fixes the swatch that kind needs - and the crypt's blocks/ units
    # are SWATCH-BASED, so the level has to name one (381 of this arena's entities carry
    # blocks/d01_crypt/d01_crypt_swatch).  Writing 0 instead leaves the swatch unresolved, and
    # the engine's unit-instantiation pass - FUN_0042f3a0, reached from the World.load_level
    # delegate and called with the level it has just built - then writes through the null.
    # crash_trace.log caught exactly that: 0xC0000005, "access write at 00000000", in
    # FUN_0042f3a0, the moment the generator asked for arena/crypt_arena01.
    # For a kind the arena does not place, fall back to its block swatch, and otherwise to the
    # value the slot itself had (a prop's own material is always valid for that slot).
    mat_by_kind: Dict[str, str] = {}
    block_mats: Dict[str, int] = {}
    for e in ents:
        u = unit_of(e)
        if not u:
            continue
        mat_by_kind.setdefault(u, e['material_hash'])
        if u.startswith('blocks/') and int(e['material_hash'], 16):
            block_mats[e['material_hash']] = block_mats.get(e['material_hash'], 0) + 1
    block_swatch = max(block_mats, key=block_mats.get) if block_mats else None
    corpus_mat = shipped_material_map()
    print('  material: %d kind(s) the arena itself places; its block swatch is %s'
          % (len(mat_by_kind), block_swatch))

    # HOW MANY OF EACH KIND DOES THIS LEVEL ACTUALLY HAVE?  A kind that appears exactly ONCE is
    # not decoration - it is the level's one exit trigger, its one interactable, its one gate.
    # Those are the entities the loader looks UP by kind and then indexes: crash_trace.log
    # caught that exactly - a lookup returning -1 followed by `MOV EAX,[ESI+0x184]` then
    # `PUSH [EAX+ECX*4]` with the vector empty, i.e. reading element -1 of nothing (access
    # 0xFFFFFFFC = null-4), immediately after the hub's tutorial layout was read.  So anything
    # the level has only one of is kept, whatever prefix it has.
    kind_count: Dict[str, int] = {}
    for e in ents:
        u = unit_of(e)
        if u:
            kind_count[u] = kind_count.get(u, 0) + 1
    unique_kinds = {u: c for u, c in kind_count.items() if c == 1}
    if unique_kinds:
        print('  unique : %d kind(s) this level has exactly one of - all KEPT, not replaced:'
              % len(unique_kinds))
        print('           %s%s' % (', '.join(sorted(unique_kinds)[:4]),
                                   ' ...' if len(unique_kinds) > 4 else ''))

    keep_slots: List[int] = []
    foreign_slots: List[int] = []
    decor_slots: List[int] = []
    other_slots: List[int] = []
    for i, e in enumerate(ents):
        k = classify(unit_of(e))
        if k in ('keep', 'core') and entity_sig(e) in keep_sig:
            keep_slots.append(i)          # the encounter's own data: left bit-for-bit alone
        elif k == 'keep':
            foreign_slots.append(i)       # ANOTHER level's logic: replaced, and replaced FIRST
        elif k == 'decor' and kind_count.get(unit_of(e), 0) > 1:
            decor_slots.append(i)
        elif k == 'decor':
            # The ONLY one of its kind in this level: that is the exit trigger / interactable /
            # gate the loader looks up and then indexes.  Never replace it.
            keep_slots.append(i)
        else:
            other_slots.append(i)         # unknown unit: never touched (fail safe)

    # Logic this body does not have but the level we keep from does: place it, verbatim.
    have = {entity_sig(ents[i]) for i in keep_slots}
    inject = [e for e in keep_data['entities']
              if classify(unit_of(e)) in ('keep', 'core') and entity_sig(e) not in have]
    order = foreign_slots + decor_slots
    if len(inject) + len(placed) > len(order):
        raise SystemExit('need %d replaceable slots; this body offers %d'
                         % (len(inject) + len(placed), len(order)))
    print('  body   : %s, %d slots | logic kept from %s'
          % ((body or donor).name, before, (keep_from or donor).name))
    print('  logic  : %d kept in place, %d injected, %d unit(s) of unknown kind untouched'
          % (len(keep_slots), len(inject), len(other_slots)))

    # ---- WHERE THE PLAYER STARTS, AND THE VERTICAL ALIGNMENT --------------------------
    marker_hash = '0x%016x' % murmur64(SPAWN_MARKER)
    markers = [ents[i]['position'] for i in keep_slots
               if ents[i]['template_hash'].lower() == marker_hash]
    markers += [e['position'] for e in inject if e['template_hash'].lower() == marker_hash]
    if markers:
        print('  spawn  : %d player_spawn_marker(s) preserved, e.g. %s'
              % (len(markers), [round(v, 2) for v in markers[0]]))
    # The ARENA's own frame, for reference.  This is the frame a level authored for this
    # module has to sit in - everything the encounter needs is already in it.
    dfx = [e['position'][0] for e in ents if 'floors/' in unit_of(e)]
    dfy = [e['position'][1] for e in ents if 'floors/' in unit_of(e)]
    if dfx:
        print('  arena  : its own floor centred (%.1f, %.1f); markers %s'
              % (sum(dfx) / len(dfx), sum(dfy) / len(dfy),
                 ', '.join('(%.0f,%.0f)' % (m[0], m[1]) for m in markers[:4])))
    else:
        print('  spawn  : WARNING - no player_spawn_marker survives; the engine will fall')
        print('           back to its own position and the player may start elsewhere')

    # A level authored in Blender sits wherever the author put it - ours has its floor at
    # 12.69 where the arena's own floor is at 0.00.  Left alone, the spawn raycast starts at
    # marker_z + 5 and reaches 10 down, so it never touches a floor 12.69 above it: the
    # player is placed at the fallback and drops.  Measure the offset from a marker that has
    # one of our floors under it.
    if verbatim and markers:
        mx, my, mz = markers[0]
        near = sorted(p['t'][2] for p in placed
                      if 'floors/' in p['unit']
                      and abs(p['t'][0] - mx) < 8 and abs(p['t'][1] - my) < 8)
        print('  align  : VERBATIM - no vertical alignment applied.  Marker at z=%.2f, our'
              % mz)
        print('           nearest floor at z=%s.  If the player spawns in the air, that is why.'
              % ('%.2f' % near[len(near) // 2] if near else 'none within 8 units'))
    if markers and z_offset is None and not verbatim:
        for mx, my, mz in markers:
            near = sorted(p['t'][2] for p in placed
                          if 'floors/' in p['unit']
                          and abs(p['t'][0] - mx) < 8 and abs(p['t'][1] - my) < 8)
            if near:
                z_offset = mz - near[len(near) // 2]
                print('  align  : marker (%.1f, %.1f, %.2f) has our floor at z=%.2f -> %+.2f'
                      % (mx, my, mz, near[len(near) // 2], z_offset))
                break
        else:
            print('  align  : no marker has one of our floors within 8 units; NOT offsetting')
    if z_offset:
        for p in placed:
            p['t'][2] += z_offset
        print('  align  : applied %+.2f to all %d placements' % (z_offset, len(placed)))

    # HORIZONTAL FRAME.  The engine does not move a level's content around: a module level is
    # authored in the module's OWN frame, and the generator places the whole thing at the
    # room's grid cell and yaws it by room.rotation * 90 degrees (dungeon_generator.lua:296).
    # The frame to author in is therefore the ARENA's frame - everything else in the arena
    # (its spawn fields, its room/generic markers, its unwalkable volumes, the encounter's
    # spawn positions) lives in it and cannot be moved.  A scene authored in a different
    # Blender frame arrives offset from all of that, which looks exactly like "the level is
    # out of place and the native stuff spawns somewhere else".
    #
    # Both frames do have one thing in common: a floor.  Put ours where the arena's is, by
    # the markers the player spawns on.  --align none keeps the authored coordinates,
    # --offset shifts by hand.
    # SIZE.  A module level is placed in a reserved grid cell - this arena's is about 10 x 10
    # cells of 8 units.  Content that reaches past the module's own footprint spills into the
    # neighbouring rooms, and the shell, the exits and the encounter's spawn positions all stay
    # where the cell is.  That is what "the level is out of place" looks like from inside.
    if placed:
        px = [p['t'][0] for p in placed]
        py = [p['t'][1] for p in placed]
        ax = [e['position'][0] for e in ents if 'floors/' in unit_of(e)]
        ay = [e['position'][1] for e in ents if 'floors/' in unit_of(e)]
        print('  frame  : ours x %.0f..%.0f y %.0f..%.0f (%d x %d units)'
              % (min(px), max(px), min(py), max(py), max(px) - min(px), max(py) - min(py)))
        if ax:
            print('           the arena\'s own footprint is x %.0f..%.0f y %.0f..%.0f'
                  % (min(ax), max(ax), min(ay), max(ay)))
            over = (max(px) - min(px)) > (max(ax) - min(ax)) * 1.5
            print('           %s' % ('*** OURS IS MUCH LARGER - it will reach into the rooms '
                                     'around it.  Author inside the cell.' if over
                                     else 'size looks compatible with the module'))
    if align == 'markers' and markers:
        fxs = [p['t'][0] for p in placed if 'floors/' in p['unit']]
        fys = [p['t'][1] for p in placed if 'floors/' in p['unit']]
        if fxs and fys:
            dx = sum(m[0] for m in markers) / len(markers) - sum(fxs) / len(fxs)
            dy = sum(m[1] for m in markers) / len(markers) - sum(fys) / len(fys)
            for p in placed:
                p['t'][0] += dx
                p['t'][1] += dy
            print('  frame  : our floor centred at (%.1f, %.1f), the spawn markers at'
                  % (sum(fxs) / len(fxs), sum(fys) / len(fys)))
            print('           (%.1f, %.1f) -> shifted x %+.1f y %+.1f so the level is'
                  % (sum(m[0] for m in markers) / len(markers),
                     sum(m[1] for m in markers) / len(markers), dx, dy))
            print('           authored in the ARENA\'s frame, not the export\'s')
        else:
            print('  frame  : no floors/ among our units; NOT aligning horizontally')
    if fit and placed:
        px = [p['t'][0] for p in placed]
        py = [p['t'][1] for p in placed]
        ax = [e['position'][0] for e in ents if 'floors/' in unit_of(e)]
        ay = [e['position'][1] for e in ents if 'floors/' in unit_of(e)]
        if ax and ay:
            w = max(px) - min(px)
            h = max(py) - min(py)
            s = min((max(ax) - min(ax)) / w if w > 1e-6 else 1.0,
                    (max(ay) - min(ay)) / h if h > 1e-6 else 1.0)
            cx, cy = (min(px) + max(px)) / 2.0, (min(py) + max(py)) / 2.0
            tx, ty = (min(ax) + max(ax)) / 2.0, (min(ay) + max(ay)) / 2.0
            for p in placed:
                p['t'][0] = tx + (p['t'][0] - cx) * s
                p['t'][1] = ty + (p['t'][1] - cy) * s
                p['t'][2] *= s                      # the floor sits at ~0 after the z align
                p['s'] = [v * s for v in p['s']]    # unit scale too: colliders follow it down
            print('  fit    : scaled %.3f about the floor centre and centred on the arena, so the'
                  % s)
            print('           whole layout sits inside the module cell instead of the rooms next'
                  ' to it')
    if offset:
        for p in placed:
            for k in range(3):
                p['t'][k] += offset[k]
        print('  frame  : applied manual offset %s' % (offset,))

    # Place: injected logic first (into the foreign slots), then our units, then hide the rest.
    for slot, e in zip(order[:len(inject)], inject):
        n = dict(e)
        n['entity_id'] = ents[slot]['entity_id']      # the per-slot id stays the body's
        n['_unused'] = ents[slot].get('_unused', n.get('_unused', '00' * 8))
        ents[slot] = n
    for slot, p in zip(order[len(inject):len(inject) + len(placed)], placed):
        e = dict(ents[slot])
        e['template_hash'] = '0x%016x' % murmur64(p['unit'])
        # Material: the CORPUS wins (the material the game itself pairs with this kind),
        # then the arena's own value for the kind, then the block swatch / the slot's value.
        # See shipped_material_map() - a donor slot's material belongs to a different kind
        # and the engine's lookup for ours then comes back NULL (crash at RVA 0x30224).
        m = corpus_mat.get(p['unit']) or mat_by_kind.get(p['unit'])
        if not m:
            m = block_swatch if (p['unit'].startswith('blocks/') and block_swatch) \
                             else e['material_hash']
        e['material_hash'] = m
        if keep_slot_transform:
            # BISECT, one variable at a time: change ONLY which unit sits in the slot and leave
            # its transform and its offset-0 field exactly as the shipped level had them.  If
            # this crashes, the crash is about replacing the unit; if it loads, the transforms
            # are the culprit.
            pass
        else:
            e['position'] = list(p['t'])
            # THE WHOLE QUATERNION, and the record's cached vector cleared with it: the encoder
            # prefers `rotation_vector` (kept for a byte-exact round trip), so writing only
            # `rotation` left the slot's ORIGINAL xyz in place and the placement came out rotated
            # by the donor's unit - a second, independent way the rotations were wrong.
            set_record_rotation(e, p['q'])
            e['scale'] = list(p['s'])
        if keep_slot_transform:
            pass
        elif verbatim:
            # Store the quaternion WHOLE: w goes into the record's offset-0 field instead of
            # being dropped so the encoder can re-derive -sqrt(1-|xyz|^2).  If the engine
            # reads that field rather than deriving it, this is the difference between the
            # authored rotation and 360-minus-it - which is the whole question.
            e['flag'] = float(p['q'][3])
        else:
            e.pop('flag', None)    # let the encoder write the negative-branch w
        ents[slot] = e
    used = order[:len(inject) + len(placed)]
    for slot in order[len(used):]:
        # Out of the way, but still counted, and by MOVE by default: the room mod proved mov-
        # ing collider-bearing units is safe, and that scale-collapsing one is not.
        hide_leftover(ents[slot], hide)
    stray = [s for s in order[len(used):] if classify(unit_of(ents[s])) != 'decor']
    if stray:
        raise SystemExit('REFUSING: %d non-decoration slot(s) would be hidden, first %d (%s)'
                         % (len(stray), stray[0], unit_of(ents[stray[0]])))
    print('  ours   : %d placed | %d decoration unit(s) put aside (%s)'
          % (len(placed), len(order) - len(used), hide))
    assert data['entity_count'] == before

    # THE UNIT TABLE'S PROLOGUE'S FIRST u32 MUST BE 0 - see write_scratch_level and 9H.23.3.  The
    # engine reads the four bytes at the unit table's own start as a COUNT and allocates from it;
    # a rotation there (e.g. -0.7071 = 3.2 billion) fails that allocation and the byte store
    # faults at 0x430224.  All 255 shipped levels have 0 there.
    #
    # THOSE FOUR BYTES ARE THE TABLE'S PROLOGUE, NOT UNIT 0's W (FINDINGS 9H.36).  Zeroing
    # `ents[0]['flag']` - what this used to do - no longer touches the prologue at all: it zeroes
    # unit 0's rotation w, which the encoder now writes one record further on.  The prologue is
    # pinned instead, and a decoded donor already carries it (`_lead_prologue`).
    pro = bytearray.fromhex(data.get('_lead_prologue') or ('00' * TRANSFORM_LEAD_SIZE))
    if len(pro) < TRANSFORM_LEAD_SIZE:
        pro = bytearray(TRANSFORM_LEAD_SIZE)
    was, = struct.unpack_from('<I', pro, 0)
    struct.pack_into('<I', pro, 0, 0)
    data['_lead_prologue'] = bytes(pro).hex()
    if was:
        print('  flag   : unit table prologue %d -> 0 (the engine reads it as a byte count)' % was)

    blob = bytearray(encode_level(data))
    original = (body or donor).read_bytes()
    if len(blob) != len(original):
        raise SystemExit('level changed size: %d -> %d' % (len(original), len(blob)))
    table_end = 128 + before * ENTITY_RECORD_SIZE
    diff = [i for i in range(128, table_end) if blob[i] != original[i]]
    outside = [i for i in range(0, len(original))
               if blob[i] != original[i] and not (128 <= i < table_end)]
    # THE ENCOUNTER'S OWN DATA MUST COME THROUGH UNTOUCHED, byte for byte.  This is the
    # check that matters: if a spawn field or a marker moved by so much as a float, the
    # encounter can be left waiting for a wave that never comes.
    for s in keep_slots:
        a = original[128 + s * ENTITY_RECORD_SIZE:128 + (s + 1) * ENTITY_RECORD_SIZE]
        b = bytes(blob[128 + s * ENTITY_RECORD_SIZE:128 + (s + 1) * ENTITY_RECORD_SIZE])
        if a != b:
            raise SystemExit('REFUSING: kept logic slot %d changed (%s at %s)'
                             % (s, unit_of(ents[s]), [round(v, 2) for v in ents[s]['position']]))
    print('  final  : %d entity records, %d bytes changed inside the table, %d OUTSIDE'
          % (before, len(diff), len(outside)))
    if outside:
        raise SystemExit('something outside the entity table changed - refusing to write')
    out.write_bytes(bytes(blob))
    print('  wrote  : %s (%d bytes)' % (out, len(blob)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('glb')
    ap.add_argument('donor')
    ap.add_argument('out')
    ap.add_argument('--max-entities', type=int, default=None)
    ap.add_argument('--z-offset', type=float, default=None,
                    help='shift every placement vertically; default is to align our floor '
                         'at the donor spawn with the donor spawn marker height')
    ap.add_argument('--body', type=Path, default=None,
                    help='level whose slots and non-entity sections to reuse.  Any shipped '
                         'level works, because the result is shipped at the target path and '
                         'a level is just a container.  Default: the donor')
    ap.add_argument('--keep-from', type=Path, default=None,
                    help='level whose LOGIC entities (spawn fields, markers, doors, nav '
                         'blockers) must survive.  Default: the donor')
    ap.add_argument('--allow-logic', action='store_true',
                    help='also place our own generator-managed units (doors, spawn fields, '
                         'markers).  Off by default: the arena already has its own set and '
                         'a second one fights it')
    ap.add_argument('--hide', choices=('move', 'scale', 'none'), default='move',
                    help='how to put leftover scenery out of the way.  move (default) is the '
                         'proven one - the room mod moved 4246 collider-bearing entities and '
                         'the level loaded; scale 0.0001 is only proven on units with no '
                         'collider and crashes the engine on walls and floors')
    ap.add_argument('--align', choices=('markers', 'none'), default='none',
                    help="none (default) places the level exactly where you authored it, which "
                         "is the whole point: the engine only puts the level at the module's "
                         "grid cell and yaws it by a multiple of 90, it does not move content.  "
                         "markers instead shifts our floor onto the arena's spawn markers")
    ap.add_argument('--offset', default=None,
                    help='manual DX,DY,DZ shift, applied after --align')
    ap.add_argument('--fit', action='store_true',
                    help='scale the whole layout down and centre it on the arena floor, so a '
                         'level authored much larger than the module cell still lands inside it '
                         '(unit scale is scaled with it, and colliders follow unit scale down)')
    ap.add_argument('--verbatim', action='store_true',
                    help='take the GLB transform exactly as it stands: raw positions, the '
                         'quaternion stored whole (w in the record rather than re-derived), no '
                         'axis conversion, no vertical alignment, no normalisation.  For a file '
                         'exported in the orientation it was imported in.')
    ap.add_argument('--keep-slot-transform', action='store_true',
                    help='BISECT: place our units but keep each slot\'s own transform and '
                         'offset-0 field, so only the unit identity changes.  Separates "the '
                         'crash is about replacing the unit" from "the crash is the transforms".')
    ap.add_argument('--scratch', action='store_true',
                    help='build a level that is ONLY ours: our entity table, our metadata and '
                         'the section skeleton every shipped level shares - no donor body, so '
                         'none of the donor\'s flow, volumes, markers or leftover scenery comes '
                         'with it.  The donor argument is then only used for its frame report '
                         'and is not read into the output.  See FINDINGS 9H.23.')
    ap.add_argument('--skeleton', type=Path, default=None,
                    help='the level whose non-entity sections --scratch reuses.  Default: the '
                         'smallest level in the corpus, 1,136 bytes with 6 units and no logic '
                         '(assets/exports-samples/samples/level_24abcdf4b1fb4d4a.level)')
    ap.add_argument('--shading', default=None,
                    help='with --scratch: the shading-environment resource the level metadata '
                         'names, e.g. modules/d01_hub_room/shading_environment.  Default: the '
                         'skeleton\'s own (core/rendering/default_outdoor)')
    ap.add_argument('--no-spawn', action='store_true',
                    help='with --scratch: do not add our own player_spawn_marker.  Off by '
                         'default because a donor body supplies one and a level of our own has '
                         'to place its own, on our floor')
    ap.add_argument('--no-skydome', action='store_true',
                    help='with --scratch: do not carry the skeleton\'s skydome over')
    ap.add_argument('--reference', type=Path, action='append', default=None,
                    help='a level export (.glb from level_to_glb) whose meshes are the '
                         'canonical ones.  Needed only for a BAKED export - one with no node '
                         'transforms at all, which happens when Blender applied '
                         'scale/rotation/location into the meshes.  Repeat it to merge several '
                         'exports: no single level carries every kind, and a kind with no '
                         'reference mesh cannot be recovered.  Without this the build refuses '
                         'rather than putting every unit at the origin (FINDINGS 9H.22.3)')
    ap.add_argument('--no-branch', action='store_true',
                    help='DIAGNOSTIC: do not normalise a recovered quaternion into the branch '
                         'the record needs (q and -q are the same rotation, but a record stores '
                         'xyz only and the engine derives w = -|w|).  With the rule the walls '
                         'came out right and the coffins/railings did not; without it the '
                         'reverse - so building both says which set the rule is for (FINDINGS '
                         '9H.23.5)')
    ap.add_argument('--own-unit', action='append', default=None, metavar='BASE=PATH',
                    help='a unit the author ships themselves: a node whose base name is BASE '
                         'resolves to this unit path instead of a game unit.  Repeatable.  See '
                         'scripts/build_own_units.py (FINDINGS 9H.28).')
    ap.add_argument('--ignore', action='append', default=None, metavar='SUBSTR',
                    help='a node whose NAME contains SUBSTR (case-insensitive) is not part of '
                         'this build: it is not placed, does not vote on the up axis, and never '
                         'becomes one of our units.  Repeatable; the default list is %r (the '
                         'author\'s scratch marker).  build_own_units.py honours the same list.'
                         % (IGNORE_NAME_SUBSTRINGS,))
    ap.add_argument('--mesh-frame', choices=('auto', 'y-up', 'engine'), default='auto',
                    help='which frame the MESH DATA of the export is in, OVERRIDING what the '
                         'flat meshes\' own normals say.  auto (the default) measures it, and '
                         'it is right whenever the file has a flat mesh with usable normals.  '
                         'y-up = the mesh normals point +Y in the file (a normal Blender '
                         '+Y-up export); engine = the mesh data is already engine-space (Z-up).  '
                         'Use it only when there is nothing to measure.  It is NOT a per-unit '
                         'switch: an own unit built from this export is in the SAME mesh frame '
                         'as a native unit in it, because build_own_units.py applies the same '
                         'file -> engine change the engine\'s own meshes already carry.')
    ap.add_argument('--spawn-at', default=None, metavar='X,Y,Z',
                    help='with --scratch: put the player_spawn_marker exactly at these engine '
                         'coordinates instead of at the centre of the median floor tile.  '
                         'Coordinates are the ones the tool reports and the decoder dumps.')
    ap.add_argument('--spawn-at-node', default=None, metavar='NODE',
                    help='with --scratch: the same thing, read off a GLB node - the scene\'s own '
                         'spawn marker object.  Its engine position is (x, -z, y) of the glTF '
                         'translation, converted with the axis this build detected, so it cannot '
                         'go stale when the author moves the marker; the name is matched as a base '
                         'name and the first match wins.')
    ap.add_argument('--unit-offsets', type=Path, default=None, metavar='FILE',
                    help='a JSON map of unit path -> the vector build_own_units.py moved that '
                         'unit\'s mesh by, so its template\'s collider (which sits on the '
                         'TEMPLATE\'s mesh box, not ours) lands on the mesh.  Every placement of '
                         'such a unit is moved back by the same vector, rotated and scaled into '
                         'the placement\'s own frame, so the level still looks exactly like '
                         'Blender (FINDINGS 9H.41).  build_own_units.py writes it with --offsets '
                         'and build_level_mod.py passes it through.')
    ap.add_argument('--rotation-ruler', action='store_true',
                    help='DIAGNOSTIC: add four copies of the units reported as rotated (crypt_railing_straight_4c, crypt_border_straight_4c, crypt_stairs_low_4c, coffin_open) at 0/90/180/270 degrees in a row beside the spawn, so one look says which yaw the engine draws correctly')
    a = ap.parse_args()
    offset = None
    if a.offset:
        offset = tuple(float(v) for v in a.offset.replace(' ', '').split(','))
        if len(offset) != 3:
            raise SystemExit('--offset wants DX,DY,DZ')
    spawn_at = None
    if a.spawn_at:
        spawn_at = tuple(float(v) for v in a.spawn_at.replace(' ', '').split(','))
        if len(spawn_at) != 3:
            raise SystemExit('--spawn-at wants X,Y,Z')
    for spec in (a.ignore or []):
        if spec.strip() and spec.strip().lower() not in [s.lower() for s in IGNORE_NAME_SUBSTRINGS]:
            IGNORE_NAME_SUBSTRINGS.append(spec.strip())
    if IGNORE_NAME_SUBSTRINGS:
        print('ignoring nodes whose name contains: %s'
              % ', '.join(repr(s) for s in IGNORE_NAME_SUBSTRINGS))
    for spec in (a.own_unit or []):
        if '=' not in spec:
            raise SystemExit('--own-unit wants BASE=PATH, got %r' % spec)
        base, path = spec.split('=', 1)
        OWN_UNITS[base.strip()] = path.strip()
    if OWN_UNITS:
        print('own units: %s' % ', '.join('%s -> %s' % kv for kv in sorted(OWN_UNITS.items())))
    unit_offsets = None
    if a.unit_offsets:
        if not a.unit_offsets.exists():
            raise SystemExit('--unit-offsets %s does not exist' % a.unit_offsets)
        unit_offsets = json.loads(a.unit_offsets.read_text())
        if isinstance(unit_offsets, dict) and 'units' in unit_offsets:
            unit_offsets = unit_offsets['units']     # the file is sectioned; a flat map is fine too
        if not isinstance(unit_offsets, dict):
            raise SystemExit('--unit-offsets %s is not a map of unit path -> vector' % a.unit_offsets)
        kinds = sorted(unit_offsets)
        print('collider offsets: %d unit kind(s) from %s%s - each placement of those is moved back '
              'by its own vector so the template\'s collider lands on the mesh (FINDINGS 9H.41)'
              % (len(kinds), a.unit_offsets.name,
                 ' (e.g. %s)' % ', '.join('%s %s' % (k.split('/')[-1],
                                                     unit_offsets[k]) for k in kinds[:3])
                 if kinds else ''))
    elif OWN_UNITS:
        print('WARNING: own units are in play but no --unit-offsets file was given.  If they were '
              'built by build_own_units.py their meshes were moved onto their template\'s collider '
              'box, and without this file the whole level sits displaced by those vectors '
              '(FINDINGS 9H.41).')
    return build(Path(a.glb), Path(a.donor), Path(a.out), a.max_entities, a.z_offset,
                 a.body, a.keep_from, a.allow_logic, a.hide, a.align, offset, a.fit,
                 a.verbatim, a.keep_slot_transform,
                 a.scratch, a.skeleton, a.shading, not a.no_spawn, not a.no_skydome,
                 a.reference, not a.no_branch, a.rotation_ruler,
                 a.mesh_frame, spawn_at, unit_offsets, spawn_at_node=a.spawn_at_node)


if __name__ == '__main__':
    raise SystemExit(main())
