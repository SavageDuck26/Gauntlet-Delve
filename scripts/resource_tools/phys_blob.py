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
