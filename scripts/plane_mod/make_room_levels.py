#!/usr/bin/env python3
"""
make_room_levels.py - put our plane into the crypt adventure room, safely.

Two levels come out of this:

  our_level.level      a level containing our plane (entity 0) with the donor shell's COUNT
                       PRESERVED - the other 4246 entities are moved 100 km up rather than
                       deleted, because a level whose entity count changes crashes the load.
  room_retarget.level  the crypt room with its sub-level PLACEMENT records retargeted
                       instead of blanked: the shell slot points at our level, the
                       door-wall slots are shrunk to nothing.

Why retarget rather than blank: the placement table is 56-byte records on an exact stride
and nothing before them looks like a count, so a blanked record is still counted and the
engine then tries to load a sub-level named 0x0000000000000000.  That crashed the load
twice.  Rewriting a record's name hash and transform is the same class of edit as changing
an entity's template hash - the class that already loads.

Nothing here touches room_crypt_floor_01_adventure_template: modifying the shell itself
crashed every time it was tried.
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
for p in (str(SCRIPTS), str(SCRIPTS / 'resource_tools')):
    if p not in sys.path:
        sys.path.insert(0, p)

from mod_bundle_builder import murmur64                                  # noqa: E402
from resource_tools.level_tools import (decode_level, encode_level,      # noqa: E402
                                        set_record_rotation)

# The exported (game-derived) level tree this script reads; kept out of the repo on purpose.
# Written with expanduser so the tool carries no machine specifics (see .clinerules); override
# with GAUNTLET_EXPORT for a tree somewhere else.
EXPORT = Path(os.environ.get('GAUNTLET_EXPORT')
              or os.path.expanduser('~/Documents/Coding/Gauntlet-Export/named/modules/d01_crypt'))

SHELL = 'modules/d01_crypt/room_crypt_floor_01_adventure_template'
ROOM = 'modules/d01_crypt/room_crypt_floor_01_adventure'
OUR_LEVEL = 'modules/custom/test_level/flat_plane'
OUR_UNIT = 'units/custom/test_plane/plane'

DOOR_WALLS = ['modules/d01_crypt/prefabs/door_walls/prefab_crypt_door_wall_%s' % s
              for s in ('10c', '16c', '6c', '8c')]
PREFABS = ['modules/d01_crypt/prefabs/floor_details/prefab_crypt_floor_detail_pit_round_01',
           'modules/d01_crypt/prefabs/gate_exit/prefab_crypt_gate_exit_02']

PLACEMENT_SIZE = 56
TINY = 0.0001                 # shrunk, not blanked: a null record is still counted

# THE FLOOR IS TILED, because the collider is not our mesh.
#
# ActorProbe mapped the collider in game (a 5x5 grid of floor-filtered raycasts over +/-10
# around the unit) and found it spanning only x,y in [0,+8) at the unit's own ORIGIN - i.e.
# the donor block's baked 8x8 patch, carried over verbatim in the trailer, and NOT scaled by
# the entity (at entity scale 10 a scaling collider would have spanned +/-40 and the whole
# grid would have hit).  The player could stand only within ~8 units of the spawn, then fell
# off - which is exactly what was reported.
#
# The crypt's own floor works because it is TILED: hundreds of 8x8 blocks side by side, each
# contributing its own 8x8 patch.  So place a grid of our plane, one tile per 8 units, and
# make the VISIBLE mesh match the patch: the GLB is authored corner-origin (0..40, via
# make_plane_glb.py --center 20,20,0) and scaled by 0.2 so it occupies 0..8 - the same square
# as the collider.
TILE_SPACING = 8.0            # the donor patch is 8x8, so tiles must be 8 apart
TILE_SCALE = 1.0              # *** 1.0, and the mesh is authored at 8 units ***
                              # Measured: the collider follows the entity scale DOWNWARD.  At
                              # entity scale 0.2 the footprint collapsed to a single point
                              # (~1.6 units = 8 * 0.2) and the player fell through everywhere,
                              # because tiles 8 apart with 1.6-unit patches leave gaps.  At
                              # scale 10 it read ~8 units.  So do what the real floor does:
                              # author the tile at 8 units corner-origin (0..8, exactly the
                              # donor's own vertices) and place it at scale 1.
TILE_GRID_SPAN = 25           # 25x25 = 625 tiles, reaching +/-96 around the spawn

PLANE_SCALE = 10.0            # kept for the single-plane variants; the tiled level uses
                              # TILE_SCALE, because a 400 m visible quad with an 8x8 collider
                              # was the whole problem
PLANE_AT = (0.0, -42.0, 8.0)  # *** ONE METRE BELOW THE SPAWN ***, on purpose.
                              # At z=9 (the spawn marker's own height) the player "sort of
                              # glitched through": the game's spawn probe is a downward
                              # raycast and the player's ORIGIN is set to the hit point, so
                              # their capsule straddles the surface of a slab only ~5 cm
                              # thick (ActorProbe measures the surface at unit_z + 0.025,
                              # normal (0,0,1)) - deep initial penetration, and the solver
                              # pushes them out the way they came.  A metre of clearance means
                              # they fall and land instead of starting inside it.
                              #
                              # The room carries four `gameobjects/level_editor/player_spawn_marker`
                              # entities at (0,-43,9) (1.5,-42,9) (0,-41,9) (-1.5,-42,9) - a
                              # four-player spawn rig centred on (0,-42,9).  The plane used to
                              # sit at the room origin, ~42 m away in Y, and its collider is
                              # only as big as the donor block's baked shape, not our 400 m
                              # quad, so it could never reach the player at all.

# Hide the decoration, keep the logic.  Everything the encounter needs - doors, spawn
# fields, entrance blockers, markers, the jump plate - stays exactly as it is.  The props
# the player actually SEES are shrunk to nothing.  Scale is a field edit, which is the safe
# class: no count changes, no blanking.
HIDE_PREFIXES = ('gameobjects/gold/',
                 'gameobjects/food/',
                 'gameobjects/potions/',
                 'gameobjects/keys/',
                 'gameobjects/containers/',
                 'gameobjects/room_marker/')


def placement_offsets(buf: bytes, names) -> list:
    """(offset, name) for every occurrence of a known level name hash."""
    out = []
    for nm in names:
        needle = struct.pack('<Q', murmur64(nm))
        start = 0
        while True:
            i = buf.find(needle, start)
            if i < 0:
                break
            out.append((i, nm))
            start = i + 1
    return sorted(out)


def build_our_level() -> bytes:
    """A GRID of our plane as the first entities, every other entity hidden, count kept.

    One plane cannot cover the room: the collider is the donor's baked 8x8 patch at the
    unit's origin, and it does not scale with the entity (FINDINGS 9H.20).  So tile it, the
    way the crypt tiles its own floor - 625 tiles at 8-unit spacing, each carrying its own
    8x8 patch, with the visible mesh scaled to the same 8x8 square.
    """
    donor = (EXPORT / (SHELL.split('/')[-1] + '.level')).read_bytes()
    data = decode_level(donor)
    before = data['entity_count']

    ents = data['entities']
    if before < TILE_GRID_SPAN * TILE_GRID_SPAN:
        raise SystemExit('donor has only %d entities; need %d tiles'
                         % (before, TILE_GRID_SPAN * TILE_GRID_SPAN))

    half = TILE_GRID_SPAN // 2
    tiles = 0
    for gy in range(-half, half + 1):
        for gx in range(-half, half + 1):
            e = dict(ents[tiles])
            e['template_hash'] = '0x%016x' % murmur64(OUR_UNIT)
            e['material_hash'] = '0x%016x' % 0
            e['position'] = [gx * TILE_SPACING, gy * TILE_SPACING, 0.0]
            # set_record_rotation drops the record's cached `rotation_vector` too - without that
            # the encoder writes the DONOR's vector and the tile keeps its old orientation
            # (FINDINGS 9H.36).
            set_record_rotation(e, [0.0, 0.0, 0.0, -1.0])
            e['scale'] = [TILE_SCALE] * 3
            ents[tiles] = e
            tiles += 1
    print('  placed %d tiles (%dx%d at %g spacing, scale %g -> %g x %g each)'
          % (tiles, TILE_GRID_SPAN, TILE_GRID_SPAN, TILE_SPACING, TILE_SCALE,
             TILE_SPACING, TILE_SPACING))

    for e in ents[tiles:]:
        e['position'][2] += 100000.0           # hidden; deleting them changes the count
    assert data['entity_count'] == before

    out = bytearray(encode_level(data))
    for off, _nm in placement_offsets(bytes(out), [SHELL] + DOOR_WALLS + PREFABS):
        struct.pack_into('<3f', out, off + 36, TINY, TINY, TINY)
    assert len(out) == len(donor), 'our level changed size'
    return bytes(out)


def build_room() -> bytes:
    """The room: entity table untouched, placement records retargeted or shrunk."""
    donor = (EXPORT / (ROOM.split('/')[-1] + '.level')).read_bytes()
    room = bytearray(donor)

    for off, nm in placement_offsets(bytes(room), [SHELL] + DOOR_WALLS + PREFABS):
        if nm == SHELL:
            struct.pack_into('<Q', room, off, murmur64(OUR_LEVEL))
            struct.pack_into('<3f', room, off + 8, *PLANE_AT)              # position
            struct.pack_into('<4f', room, off + 20, 0.0, 0.0, 0.0, -1.0)   # unit rotation
            struct.pack_into('<3f', room, off + 36, 1.0, 1.0, 1.0)         # scale
            print('  shell slot  @0x%06X -> %s at %s' % (off, OUR_LEVEL, PLANE_AT))
        else:
            struct.pack_into('<3f', room, off + 36, TINY, TINY, TINY)
            print('  shrink slot @0x%06X (%s)' % (off, nm.split('/')[-1]))

    ent_off, ent_count = decode_level(donor)['header'][0]

    # Hide the visible props.  Scale only - the safe class of edit: the entities stay,
    # counted, in place; they just stop being visible.
    db = json.loads((SCRIPTS / '..' / 'Data' / 'hash_database.json').resolve().read_text())
    hidden = 0
    for i, e in enumerate(decode_level(donor)['entities']):
        if db.get(e['template_hash'][2:], '').startswith(HIDE_PREFIXES):
            struct.pack_into('<3f', room, ent_off + i * 72 + 4, TINY, TINY, TINY)
            hidden += 1
    print('  hid %d visible props (scale -> %g)' % (hidden, TINY))
    table_end = ent_off + ent_count * 72
    # Verification.  Same size, same entity count, and the ONLY bytes allowed to differ are
    # inside the entity table (the hidden props) and inside the placement records we
    # retargeted or shrank.  Everything else must be untouched.
    if len(room) != len(donor):
        raise SystemExit('REFUSING: size changed')
    if room[4:8] != donor[4:8]:
        raise SystemExit('REFUSING: the entity count changed')
    table_end = ent_off + ent_count * 72
    allowed = set(range(ent_off, table_end))
    for off, _nm in placement_offsets(donor, [SHELL] + DOOR_WALLS + PREFABS):
        allowed.update(range(off, off + PLACEMENT_SIZE))
    stray = [i for i in range(len(donor)) if i not in allowed and donor[i] != room[i]]
    if stray:
        raise SystemExit('REFUSING: %d bytes changed outside the entity table and the '
                         'placement records (first at 0x%X)' % (len(stray), stray[0]))
    print('  size %d, count unchanged, entity table + placement records are the only edits'
          % len(room))
    return bytes(room)


def main() -> int:
    our = HERE / 'our_level.level'
    room = HERE / 'room_retarget.level'
    our.write_bytes(build_our_level())
    print('wrote %s (%d bytes, %d entities)'
          % (our.name, our.stat().st_size, decode_level(our.read_bytes())['entity_count']))
    room.write_bytes(build_room())
    print('wrote %s (%d bytes, %d entities)'
          % (room.name, room.stat().st_size, decode_level(room.read_bytes())['entity_count']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
