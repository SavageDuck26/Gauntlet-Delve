#!/usr/bin/env python3
"""A unit's physics blob: the compiled collision the engine reads (FINDINGS 9H.19/9H.38/9H.45).

A unit's trailer is [16 bytes: {0, physics_size, 0, count}][physics blob][data table][32-byte footer],
and the blob is the whole collision: the actors with their planes, triangles, spheres and convex
masks.  Everything a unit collides with today comes from here verbatim, which is why a walkable tile
whose faces the author deleted still presents the template's full 8x8 patch.

WHAT IS PROVEN, AND FROM WHERE:

  * the FIELD ORDER and each field's STRIDE, from the engine's own actor serialiser (FUN_006f2fe0,
    which declares name/size/offset per field and is the debug/text dumper - hence its %g values):

        CollisionSpheres        4 B    |  CollisionSpherePairs  18 B
        CollisionPlanes        16 B    |  CollisionConvexMasks  18 B
        CollisionTriangles     36 B    |  SelfCollisionIndices  18 B

  * the SPACE FORMULA, verbatim from the allocator call that precedes those declarations:

        bytes = 4 * (9*triangles + convex_masks + 4*(spheres + planes) + 2*sphere_pairs)

    and it solves the shipped corpus exactly: the 80 B walkable is 2 triangles + 2 masks (a quad is
    two triangles), the 108 B variant is 3 triangles, the 192 B "floor" blocks are 2 triangles + 6
    masks + 6 planes - a solid six-plane box, which is why they are a wall to walk into rather than a
    patch to walk on.

  * the element strides as the engine walks them, from the codecs themselves:

        FUN_006f3e40(p, i) = p + i*0x10   16 B   planes and spheres
        FUN_006f3df0(p, i) = p + i*0x04    4 B   masks, pairs, self-collision
        FUN_006f3e50(p, i) = p + i*0x24   36 B   triangles

  * a TRIANGLE is three vertices as plain floats (FUN_006f3b40 emits a vec3 at +0, +0xc and +0x18),
    and a PLANE is a vec3 normal at +0 plus a float distance at +0xc (FUN_006f3ab0).

BEING DECODED NOW: the binary layout inside the blob (which fields the header carries, and how the
engine's reader walks them).  Nothing in this module is trusted until `roundtrip()` reproduces the
shipped blobs byte for byte - the same discipline the level work used, and the reason it is a test
that must be able to fail.
"""
from __future__ import annotations

import struct
from typing import Dict, List, Tuple

# The trailer's 16-byte header, then the blob, then the table and the footer.
TRAILER_HEADER = 16
FOOTER = 32

FIELD_STRIDES: Dict[str, int] = {
    'CollisionSpheres': 4,
    'CollisionSpherePairs': 18,
    'CollisionPlanes': 16,
    'CollisionConvexMasks': 18,
    'CollisionTriangles': 36,
    'SelfCollisionIndices': 18,
}


def blob_size(triangles: int, masks: int, spheres: int, planes: int, pairs: int) -> int:
    """The size the engine allocates for a blob with these counts (the formula, verbatim).

    Kept as its own function because it is the one piece of the format that is PROVEN by arithmetic
    rather than by reading bytes: it predicts the shipped corpus's 80/108/164/192/220-byte blobs
    exactly, so any encoder can compute its own answer before writing anything.
    """
    return 4 * (9 * triangles + masks + 4 * (spheres + planes) + 2 * pairs)


# ---------------------------------------------------------------------------------------------------
# READING A BLOB'S WORDS (2026-10-20, measured in game - FINDINGS 9H.46)
#
# ActorProbe was pointed at our own units and each one's shape was read back out of the engine.  Our
# floor tile - the 80-byte blob below - reports:
#
#     shape type 3    half_extents = Vector3(4.0250001, 4.0250001, 0.0250000004)
#
# and the blob's own words, as signed 16-bit, line up with exactly that:
#
#     +0x00  [f32 0.9667][u32 80][u32 0][u32 1]      <- header: the same float in every blob
#     +0x10   32767  32767   2051  -32736  32767  32767  32767   2051
#     +0x20  -32736 -16384      0    2051 -32736 -16368    966   2051
#     +0x30  -32736 -32768      0   32767  32767  32767 -32752    966
#     +0x40   32767  32767  32767      3      1      0      0      0   <- tail
#
# read at I16_UNIT (1/32768): normals land on +/-1.0, the tile's half-extent on -0.5 x 8 = -4.0 (the
# tile IS 8 units), the small runs on 0.0625, and 966 = 0.0295 - the only value near the engine's
# measured 0.025 SKIN, which is added to the box after the normalised extent is scaled.  The 4th word
# of the tail is 3, and 3 is precisely the shape type the probe measured on this blob.
#
# A unit with TWO meshes reported TWO shapes with two types (3 and 4), one blob each - so the shape
# type is per-mesh and lives in the blob, NOT in the template.  SHAPE_BOX = 3 is measured; the other
# type seen in game is 4, and what 4 means is what the `_fc` route needs to pin down.
#
# THE EDITS BELOW KEEP THE BLOB'S LENGTH.  That is not a detail: the data table and the 32-byte
# footer sit immediately after the blob, so removing or adding bytes moves them, and the one strip:
# crash (FINDINGS 9H.38.1.1) is exactly that.  Same length means the only thing that changes is the
# collision - which is also why these edits are the safe half of the work.
# ---------------------------------------------------------------------------------------------------
I16_UNIT = 32768.0        # 0x8000: the geometry words are signed 16-bit fixed point, this is 1.0
BLOB_HEADER = 16          # float, u32 size (the blob's own length), two u32s
BLOB_TAIL = 16            # ..., shape type, 1, 0, 0, 0
SHAPE_BOX = 3             # measured in game: the floor's -0x...3 - blob reports type 3

# Words that are never a distance: unit normals (the +/-1.0 and +/-0.9990 family), zero, the
# quantiser's own repeated flags (0.0625 reads 2051 and appears in every plane; 966 reads 0.0295 and
# is the engine's skin, measured as 0.025), and the small counts (1, 3).  What is left in the floor's
# body is exactly two words - -16384 and -16368, the -0.5 and -0.4995 family - so scaling a blob moves
# its EXTENTS and nothing else, and one measurement reads the units straight off.  Read off the
# shipped blobs, not assumed: see the dump in FINDINGS 9H.46.
STRUCTURAL_ABS = 32720
STRUCTURAL_WORDS = (0, 1, 3, 966, 2051)


def blob_words(blob: bytes) -> List[int]:
    """The blob as signed 16-bit words (its geometry is fixed point; see I16_UNIT)."""
    if len(blob) % 2:
        raise ValueError('a blob is an even number of bytes, got %d' % len(blob))
    return list(struct.unpack('<%dh' % (len(blob) // 2), blob))


def shape_type(blob: bytes) -> int:
    """The shape type the engine reports for this blob (measured: 3 = the fitted box)."""
    words = blob_words(blob)
    if len(words) < (BLOB_HEADER + BLOB_TAIL) // 2:
        raise ValueError('blob too short for a header and a tail: %d B' % len(blob))
    return words[-(BLOB_TAIL // 2) + 3]


def set_shape_type(blob: bytes, shape: int) -> bytes:
    """The same blob with its shape type replaced - the `_fc` lever, and length-preserving.

    The engine reads the type per mesh block, so a unit whose blob says 4 collides as whatever 4 is
    even though the template it was spliced into says 3.  That is the whole experiment: one word.
    """
    if not 0 <= shape <= 8:
        raise ValueError('refusing to call %r a shape type' % shape)
    out = bytearray(blob)
    struct.pack_into('<h', out, len(blob) - BLOB_TAIL + 6, shape)
    return bytes(out)


def scale_sizes(blob: bytes, k: float, mask: str = 'lo') -> bytes:
    """The same blob with the words `mask` selects multiplied by k - a box's size knob, length-keeping.

    `mask` says WHICH words, because the first attempt at this (9H.47) scaled the obvious candidates
    and the collider did not move: the words that read -0.5/-0.4995 in the floor are not the extents.
    What is left is the +/-1.0 family (the unit normals), which 9H.48 has to test by construction:

        'lo'   the small words - whatever is not a normal, a flag or a count.  This is what the first
               calibration run scaled, and the answer was NO.
        'hi'   the +/-1.0 and +/-0.9990 family (|w| >= 32000).  If halving THESE halves the box, the
               extents live here and a box of any size is arithmetic.
        'all'  both, i.e. every word that is not 0, 1, 3 or the 2051 flag.

    Normals and flags are never touched by 'lo', and 'hi' touches nothing else, so one run with both
    masks on different kinds reads off which family carries the extents.
    """
    words = blob_words(blob)
    first, last = BLOB_HEADER // 2, len(words) - BLOB_TAIL // 2
    out = list(words)
    for i in range(first, last):
        w = words[i]
        if w == 0 or w in STRUCTURAL_WORDS:
            continue                      # a flag or a count - never a distance
        if abs(w) >= STRUCTURAL_ABS:
            if mask not in ('hi', 'all'):
                continue                  # the +/-1.0 family: 'lo' leaves it alone
        elif mask not in ('lo', 'all'):
            continue
        out[i] = max(-32768, min(32767, int(round(w * k))))
    return struct.pack('<%dh' % len(out), *out)


def edit_blob(blob: bytes, scale: float = 1.0, shape: int = None, mask: str = 'lo') -> bytes:
    """Both edits, in place: `scale` resizes the box, `shape` re-types the mesh block.

    This is the single entry point build_own_units.py calls (--collider-edit=KIND=scale:0.5,type:4),
    and the reason a collider can be changed without any of the byte surgery that crashes the loader.
    """
    out = blob
    if scale != 1.0:
        out = scale_sizes(out, scale, mask=mask)
    if shape is not None:
        out = set_shape_type(out, shape)
    if len(out) != len(blob):
        raise AssertionError('an edit changed the blob length (%d -> %d)' % (len(blob), len(out)))
    return out


def describe(blob: bytes) -> str:
    """A human-readable dump: the words, what they read as, and the tail's shape type."""
    words = blob_words(blob)
    lines = ['blob %d B, shape type %d (header float %.4f, declared size %d)'
             % (len(blob), shape_type(blob), struct.unpack_from('<f', blob, 0)[0],
                struct.unpack_from('<I', blob, 4)[0])]
    for i in range(0, len(words), 8):
        chunk = words[i:i + 8]
        lines.append('  +0x%02x  i16 %-42s = %s'
                     % (i * 2, ' '.join('%6d' % w for w in chunk),
                        ' '.join('%8.4f' % (w / I16_UNIT) for w in chunk)))
    return '\n'.join(lines)


def split_trailer(unit_bytes: bytes) -> Tuple[bytes, int, bytes, bytes]:
    """(header, physics_size, blob, rest) of a .unit's trailer.

    `rest` is the data table plus the 32-byte footer; the nav type the build reports lives in it, and
    strip_physics in build_own_units.py already relies on this shape.
    """
    from glb_to_template_unit import unit_mesh_end
    end = unit_mesh_end(unit_bytes)
    tr = unit_bytes[end:]
    if len(tr) < TRAILER_HEADER:
        raise ValueError('no trailer: the body is the whole file')
    size, = struct.unpack_from('<I', tr, 4)
    if TRAILER_HEADER + size > len(tr):
        raise ValueError('the trailer claims %d bytes of physics and has %d'
                         % (size, len(tr) - TRAILER_HEADER))
    return tr[:TRAILER_HEADER], size, tr[TRAILER_HEADER:TRAILER_HEADER + size], tr[TRAILER_HEADER + size:]
