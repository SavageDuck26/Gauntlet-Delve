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

THE MESH IS MOVED ONTO THE TEMPLATE'S COLLIDER BOX (FINDINGS 9H.41), and the level builder puts the
placement back so nothing visible moves.  A splice's collider is the TEMPLATE's, and in game it sits
on the TEMPLATE's own geometry: the splash plane spliced into cryptsmooth_floor_4c_4c came out with
an 8x8 patch spanning x,y in [0,+8) at the unit's origin (9H.20, read with ActorProbe) and that
template's mesh box is exactly (0,0,0)->(8,8,0).  The author's tiles are centred on their origin
(-4..+4), so a tile built that way has its collider four units away in x and y: three quarters of
the visible tile has nothing under it and the player walks or falls straight through.  So the
generated mesh is moved by `template_box_min - mesh_box_min` in x and y, and the vector is written
to --offsets for level_from_glb.py to subtract from every placement - which leaves the level looking
exactly like Blender while the collider lands on the mesh.  `--no-collider-shift` builds the old way.
"""
import json
import numpy as np
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'resource_tools'))

from phys_blob import edit_blob                                    # noqa: E402

from gltf_to_unit import encode_unit                       # noqa: E402
from glb_to_template_unit import (read_u32, splice_into_template,   # noqa: E402
                                  unit_mesh_end, UNIT_SIGNATURE)
# The SAME rules the level converter uses, IMPORTED rather than copied: the name filter
# (IGNORE_NAME_SUBSTRINGS / ignored_node), so a node the author marked as scratch is neither placed
# nor turned into a unit, and base_name, because these two tools disagreeing about what a node is
# called is exactly how a unit gets built under one name and resolved under another (9H.40).  That
# function also carries the author's LIB_ master convention now (9H.43).
from level_from_glb import (IGNORE_NAME_SUBSTRINGS, base_name,       # noqa: E402
                            ignored_node)

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


# base_name LIVES IN level_from_glb NOW (imported above).  It was duplicated here once and the two
# copies drifted: this one stripped any tail starting with a digit, so `Spiral Road.002safdasdf` and
# its siblings collapsed into one unit built from the first piece's mesh (FINDINGS 9H.40).  That
# function also carries the author's LIB_ master convention (9H.43) - one rule in one place, so the
# level converter and this builder cannot disagree again.


# PHYSICS BY NAME  (the author's request: `_walkable` / `_collision` in an object's name, and
# nothing means walk-through).  THE BUILDER CANNOT INVENT A COLLIDER - a unit's physics IS its
# template's trailer, carried over verbatim - so a role selects WHICH TEMPLATE the mesh is
# spliced into, and the template's own trailer decides the collider, the nav type and the
# material binding (FINDINGS 9H.19, 9H.20, 9H.31).  Measured on shipped units, the trailer's
# SECOND WORD is the physics blob's size and 0 means "no physics":
#
#     cryptsmooth_floor_4c_4c   80 B   nav 'floor'     a walkable patch (9H.20 mapped it)
#     crypt_wall_2c            136 B   nav 'blocker'   solid
#     crypt_pillar_01          164 B   nav 'blocker'   solid
#     crypt_stairs_low_4c      220 B   nav 'slope'     walkable slope
#     decals/decal, fog_volume  80 B   nav 'ignore'    (a name rule forces 'ignore')
#     lights/light, skydome      0 B   no nav string   NO PHYSICS - walk-through
#
# So `--physics-template=walkable=<unit>` and friends point at templates whose trailers carry the
# physics wanted, and `_walkable`/`_collision` in a name pick between them.
PHYSICS_ROLES = ('walkable', 'collision', 'none')
NAME_ROLES = (('_walkable', 'walkable'), ('_collision', 'collision'))

# HOW MANY VERTICES ONE MESH BLOCK MAY HOLD (FINDINGS 9H.39).  Sixteen-bit indices are what the
# engine's own data uses, and it never goes past them: across 1,242 mesh blocks in 582 shipped
# units EVERY index is 2 bytes and the largest mesh the game ships is 15,972 verts.  This toolkit
# used to write 32-bit indices past 65,535 - and the only two meshes that ever needed it (the
# 157,180-vert spiral road and the 74,536-vert chains) are the two that render corrupted, the road
# going wrong from about 65,536/157,180 = 42% in.  So a node that exports past this is REFUSED here
# rather than written: split the object in Blender (each piece becomes its own unit, which is how
# the game's own content is built) so every piece is comfortably under the limit.  NOTE the
# exporter inflates the count - the spiral road is 62,368 verts in Blender and 157,180 in the GLB -
# so judge it by what the build prints, not by Blender's counter.
MAX_VERTS_PER_MESH = 65535


def role_of(base: str, per_base: dict) -> str:
    """Which physics role a base name asks for: the name flag, then the config, then 'none'."""
    low = base.lower()
    for needle, role in NAME_ROLES:
        if needle in low:
            return role
    return per_base.get(base, 'none')


def physics_of(unit_bytes: bytes) -> str:
    """What physics a built unit wears, read back out of its own trailer.

    Reported so a build says what each unit actually got instead of what was intended: the
    physics blob's size (the trailer's second word) and the nav type string.  See PHYSICS_ROLES
    for the measured reference values.
    """
    try:
        tr = unit_bytes[unit_mesh_end(unit_bytes):]
        size, = struct.unpack_from('<I', tr, 4)
        nav = next((w.decode() for w in (b'floor', b'blocker', b'slope', b'ignore') if w in tr),
                   None)
        return 'physics %4d B, nav %s' % (size, ('%r' % nav) if nav else '(none)')
    except Exception as exc:                                     # noqa: BLE001
        return 'physics UNREADABLE (%s)' % exc


def strip_physics(tpl_bytes: bytes) -> bytes:
    """A copy of a template with its physics section removed: `--physics-template=none=strip:PATH`.

    WHY.  The three shipped units whose trailer declares no physics at all (skydome, light,
    light_proxies) all have a footer that names the unit itself instead of a MATERIAL SWATCH, so a
    mesh wearing one loses its material binding - and `lights/light` drags light flow in as well
    (measured: the trailer carries 'FlowCallbacks' and 'light').  Stripping keeps everything the
    template had - the swatch, the flow, the nav data - and removes only the collider, which is what
    "no collision" means.

    WHY NOTHING IS REMOVED ANY MORE (2026-10-20, FINDINGS 9H.49).  The two earlier attempts REMOVED
    the blob and zeroed the trailer's size and count; both crashed on package load at the same
    instruction (FUN_00402e10+0x3C, a container resize - 9H.38.1, 9H.38.1.1, 9H.38.1.2).  What those
    runs could not see, and 9H.46-9H.48 now show, is that the physics blob is an opaque block whose
    LENGTH is what tells the loader where the data table, the nav string and the 32-byte footer begin:
    shorten it and everything the loader reads next is misaligned.

    Zeroing keeps every offset exactly where it was, so the only thing that changes is what the blob
    says - no planes, no triangles, no actors.  The blob's own header is left alone (its format float
    and its size word) so the block still parses as the same block, and the trailer's 16 bytes are
    untouched for the same reason.  The nav type becomes "ignore", the value the game's own builder
    writes for a unit that collides with nothing (9H.19).  WHETHER THE ENGINE ACCEPTS IT IS THE TEST:
    ActorProbe reports Unit.num_actors and Actor.shapes per unit, so a stripped unit must read back as
    zero actors - that is the check, not this docstring.
    """
    end = unit_mesh_end(tpl_bytes)
    body, tr = tpl_bytes[:end], tpl_bytes[end:]
    if len(tr) < 16:
        return tpl_bytes                       # no trailer at all: there is no physics to strip
    size, = struct.unpack_from('<I', tr, 4)
    if size == 0:
        return tpl_bytes                       # already no physics
    if 16 + size > len(tr):
        raise SystemExit('cannot strip physics: the trailer claims %d bytes and has %d'
                         % (size, len(tr)))
    blob = bytearray(tr[16:16 + size])
    cleared = 0
    for i in range(8, len(blob)):              # keep the format float and the size word: only the rest
        if blob[i]:
            cleared += 1
        blob[i] = 0
    print('   strip   : blob zeroed in place (%d B, %d bytes cleared, length kept)' % (size, cleared))
    # THE COUNT, AND THIS IS WHAT THE 11:16 CRASH ACTUALLY NAMED (FINDINGS 9H.50).  Zeroing the blob's
    # body while the trailer still said count=2 kept the level load dying at FUN_00402e10+0x3C - the
    # same instruction as both earlier strip: crashes, and with the length PRESERVED - which retires
    # the byte-removal theory for good.  The trailer is {0, size, 0, count} and the loader sizes its
    # actor containers from `count`, so an empty blob with count 2 asks for actors that have no data
    # and the resize write at +0x4 faults.  `size` stays: it is what locates the table, the nav string
    # and the footer, and moving those is what 9H.38.1.1/9H.38.1.2 did on top of the count change.
    header = bytearray(tr[:16])
    struct.pack_into('<I', header, 12, 0)
    print('   strip   : trailer count -> 0 (was %d), size left at %d' % (
        struct.unpack_from('<I', tr, 12)[0], size))
    rest = bytearray(tr[16 + size:])
    # The nav type is GENERATED metadata - the game's own builder writes "ignore" when a unit
    # collides with nothing (FINDINGS 9H.19) - so a stripped unit claims walkable AI nav no more.
    # The value is an 8-byte padded field, which is why the match includes its NULs (a material
    # name like m_cryptsmooth_floor_01 must not match).
    for word, padded in (('floor', b'floor\x00\x00\x00'), ('slope', b'slope\x00\x00\x00'),
                         ('blocker', b'blocker\x00')):
        at = rest.find(padded)
        if at >= 0:
            rest[at:at + 8] = b'ignore\x00\x00'
            print('   strip   : nav %s -> ignore' % word)
            break
    return body + bytes(header) + bytes(blob) + bytes(rest)


def apply_collider_edits(unit_bytes: bytes, ops: dict) -> bytes:
    """Rewrite the spliced template's physics blob IN PLACE - `scale` resizes, `type` re-types.

    WHY THIS IS THE SAFE HALF (FINDINGS 9H.46).  A unit's collider is the template's blob, spliced in
    verbatim, so a walkable tile whose faces the author deleted still presents the template's full
    8x8 patch - the overextension this work exists to fix.  The blob is quantised geometry (signed
    16-bit at 1/32768) ending in a shape-type word, and both edits change WORDS, never lengths, so the
    u32 table and the 32-byte footer after the blob stay exactly where the engine expects them.  The
    one route that failed, `strip:`, removed bytes and moved the trailer - that is the difference.

    Built for calibration first: the same floor blob on two kinds, one scaled by 0.5 and one by 2.0,
    reads back from ActorProbe as their half_extents, and the ratio between them IS the unit.
    """
    scale = float(ops.get('scale', 1.0))
    shape = None if ops.get('type') is None else int(ops['type'])
    mask = str(ops.get('mask', 'lo'))      # WHICH words scale: the +/-1.0 family, the small ones, both
    end = unit_mesh_end(unit_bytes)
    trailer = unit_bytes[end:]
    if len(trailer) < 16:
        raise SystemExit('collider edit: the unit has no trailer')
    size, = struct.unpack_from('<I', trailer, 4)
    if size == 0:
        raise SystemExit('collider edit: this unit declares no physics to edit (0 B)')
    if 16 + size > len(trailer):
        raise SystemExit('collider edit: the trailer claims %d bytes of physics and has %d'
                         % (size, len(trailer) - 16))
    edited = edit_blob(trailer[16:16 + size], scale=scale, shape=shape, mask=mask)
    return unit_bytes[:end] + trailer[:16] + edited + trailer[16 + size:]


def load_template(spec: Path) -> bytes:
    """A role's template bytes.  `strip:PATH` means "that template with its physics removed"."""
    text = str(spec)
    if text.startswith('strip:'):
        inner = Path(text.split(':', 1)[1])
        data = strip_physics(inner.read_bytes())
        if read_u32(data, 0) != UNIT_SIGNATURE:
            raise SystemExit('%s is not a unit file' % inner)
        return data
    data = spec.read_bytes()
    if read_u32(data, 0) != UNIT_SIGNATURE:
        raise SystemExit('%s is not a unit file' % spec)
    return data


def template_mesh_bbox(data: bytes):
    """min/max of every vertex of a native unit - the box a splice's collider is built around.

    FINDINGS 9H.41.  A splice's collider is the TEMPLATE's, compiled into its trailer, and in game
    it sits ON THE TEMPLATE'S OWN GEOMETRY: the splash plane spliced into cryptsmooth_floor_4c_4c
    came out with an 8x8 collider patch spanning x,y in [0,+8) at the unit's origin (9H.20, read
    with ActorProbe), and this template's mesh box is exactly (0,0,0) -> (8,8,0).  So the template's
    box is where a splice has to put its own geometry, and that is what collider_shift returns.
    """
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    off = 8
    for _ in range(read_u32(data, 4)):
        vbuf = read_u32(data, off)
        start = off + 4
        # A mesh block is [size][vertex bytes][8][count][stride][element_count][elements*17][12]
        # [index_count][index_size][indices][shape_count][shapes*16][28][materials].  Each
        # vertex's POSITION is its first 12 bytes (a normal and a UV follow it).
        count = read_u32(data, start + vbuf + 8)
        stride = read_u32(data, start + vbuf + 12)
        for i in range(count):
            p = struct.unpack_from('<3f', data, start + i * stride)
            for k in range(3):
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
        off = start + vbuf + 8
        off += 12 + read_u32(data, off + 8) * 17 + 12          # vertex elements
        off += 8 + read_u32(data, off + 4)                     # the index buffer
        off += 4 + read_u32(data, off) * 16 + 28               # shapes, and their 28-byte tail
        material_count = read_u32(data, off)
        off += 4
        for _ in range(material_count):
            off += 4 + read_u32(data, off)
    return lo, hi


def collider_shift(tpl: bytes, positions) -> list:
    """How far a generated mesh has to move for the template's collider to land on it.

    X and Y only, and that is deliberate: the collider of every template this toolkit uses is a
    HORIZONTAL patch (the floor's is 8x8 at z = 0), so x,y decide whether there is anything under
    the player, while z is the height that patch sits at - which the author already controls with
    the object's own z.  Aligning z as well would sink a walkable patch to the underside of a thick
    slab and raise a prop off the floor.
    """
    lo, _hi = template_mesh_bbox(tpl)
    gen = positions.min(axis=0)
    return [float(lo[0] - gen[0]), float(lo[1] - gen[1]), 0.0]


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
    templates, physics_by_base, templates_by_base = {}, {}, {}
    collider_edits = {}                    # BASE -> {'scale': k, 'type': n}, --collider-edit (9H.46)
    offsets_out, collider_shift_on = None, True
    for a in argv[2:]:
        if a == '--out':
            continue
        if a.startswith('--out='):
            out_dir = Path(a.split('=', 1)[1])
        elif a == '--no-duplicate-meshes':
            duplicate_meshes = False
        elif a == '--no-collider-shift':
            collider_shift_on = False
        elif a.startswith('--offsets='):
            offsets_out = Path(a.split('=', 1)[1])
        elif a.startswith('--mesh-frame='):
            frame = a.split('=', 1)[1]
            if frame not in ('auto', 'y-up', 'engine'):
                raise SystemExit('--mesh-frame wants auto, y-up or engine')
        elif a.startswith('--template='):
            # A PER-KIND TEMPLATE OVERRIDE: the same lever as a role's template, but for ONE kind.
            # A role chooses the collider for everything that falls in it, so today a solid prop and
            # a flat tile share one template - and the game ships both kinds of collider (a flat
            # patch is 2-3 pieces, a box is 6, see FINDINGS 9H.45).  Until a blob can be WRITTEN,
            # this is how a kind gets the closest collider the game already has.
            spec = a.split('=', 1)[1]
            if '=' not in spec:
                raise SystemExit('--template wants BASE=SPEC, got %r' % spec)
            name, spec_path = spec.split('=', 1)
            templates_by_base[base_name(name)] = spec_path
        elif a.startswith('--collider-edit='):
            # EDIT A TEMPLATE'S PHYSICS BLOB IN PLACE (FINDINGS 9H.46): BASE=scale:0.5,type:4.
            # `scale` multiplies the blob's distance words, `type` replaces its shape word - both
            # length-preserving, which is what makes them safe where removing bytes crashed the load.
            spec = a.split('=', 1)[1]
            if '=' not in spec:
                raise SystemExit('--collider-edit wants BASE=OPS, got %r' % spec)
            name, ops_text = spec.split('=', 1)
            ops = {}
            for field in ops_text.split(','):
                if ':' not in field:
                    raise SystemExit('--collider-edit op wants field:value, got %r' % field)
                fname2, value = field.split(':', 1)
                if fname2 not in ('scale', 'type', 'mask'):
                    raise SystemExit('--collider-edit field must be scale, type or mask, got %r'
                                     % fname2)
                if fname2 == 'scale':
                    ops[fname2] = float(value)
                elif fname2 == 'type':
                    ops[fname2] = int(value)
                else:
                    ops[fname2] = value        # mask: hi | lo | all - WHICH words scale (9H.48)
            collider_edits[base_name(name)] = ops
        elif a.startswith('--physics-template='):
            # which native unit to splice into for a physics role: the template's trailer IS the
            # collider, so this is the only lever the builder has (see PHYSICS_ROLES)
            spec = a.split('=', 1)[1]
            if '=' not in spec:
                raise SystemExit('--physics-template wants ROLE=PATH, got %r' % spec)
            role, path = spec.split('=', 1)
            if role not in PHYSICS_ROLES:
                raise SystemExit('--physics-template role must be one of %s'
                                 % ', '.join(PHYSICS_ROLES))
            templates[role] = Path(path)
        elif a.startswith('--physics='):
            spec = a.split('=', 1)[1]           # BASE=ROLE, the fallback for a name with no flag
            if '=' not in spec:
                raise SystemExit('--physics wants BASE=ROLE, got %r' % spec)
            name, role = spec.split('=', 1)
            if role not in PHYSICS_ROLES:
                raise SystemExit('--physics role must be one of %s' % ', '.join(PHYSICS_ROLES))
            physics_by_base[base_name(name)] = role
        elif '=' in a:
            name, path = a.split('=', 1)
            mapping[base_name(name)] = path
        elif out_dir is None and '/' in a:
            out_dir = Path(a)
    if templates and set(templates) != set(PHYSICS_ROLES):
        raise SystemExit('--physics-template must give all of %s (missing: %s)'
                         % (', '.join(PHYSICS_ROLES),
                            ', '.join(r for r in PHYSICS_ROLES if r not in templates)))
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

    tpl_bytes: dict = {}
    shifts: dict = {}          # unit path -> the vector its mesh was moved by (see 9H.41)

    def template_for(role: str) -> Path:
        return templates[role] if templates else template

    if not templates:
        tpl = load_template(template)
        tpl_bytes[template] = tpl

    print('export   : %s (%d nodes)' % (glb.name, len(js['nodes'])))
    print('mesh up  : %s' % why)
    print('           -> vertices rotated %+d degrees about X into engine Z-up%s'
          % (deg, '' if deg else ' (already engine-space, no rotation)'))
    if templates:
        print('physics  : by name, from the TEMPLATE each role points at (a trailer carries the'
              ' collider)')
        for role in PHYSICS_ROLES:
            tp = template_for(role)
            tb = tpl_bytes.get(tp) or load_template(tp)
            print('           %-9s -> %-44s %s' % (role, tp.name, physics_of(tb)))
    else:
        print('template : %s (%d bytes, %d mesh(es), trailer %d bytes, %s)'
              % (template.name, len(tpl), read_u32(tpl, 4), len(tpl) - unit_mesh_end(tpl),
                 physics_of(tpl)))
    if ignored:
        print('ignored  : %d node(s) whose name carries %s - no unit is built from them'
              % (len(ignored), '/'.join(repr(s) for s in IGNORE_NAME_SUBSTRINGS)))
    print()
    for base, nodes in sorted(groups.items()):
        role = role_of(base, physics_by_base)
        # a per-kind override wins over the role's template (see --template)
        tp = Path(templates_by_base[base]) if base in templates_by_base else template_for(role)
        if tp not in tpl_bytes:
            tpl_bytes[tp] = load_template(tp)
        tpl = tpl_bytes[tp]
        tpl_meshes = read_u32(tpl, 4)   # the mesh count the trailer was serialized against
        # EVERY PRIMITIVE, not just the first.  A glTF mesh with N primitives is N material
        # groups over one surface (the stair's mesh is 2: 106 verts + 60 verts, two materials),
        # and the engine's unit model is one material group per mesh block - so dropping the
        # later primitives drops geometry the author authored.  They are merged into the block
        # with the mesh's first material name.
        # WHICH NODE SUPPLIES THE MESH.  The author's `LIB_` master when the kind has one (FINDINGS
        # 9H.43): the other nodes are Blender instances of it, so normally their mesh data is the
        # same - but when it is NOT (a stale copy, a one-off variant) the master is the shape the
        # author means, and this is said out loud instead of the first node silently winning.
        libs = [n for n in nodes if n.get('name', '')[:4].upper() == 'LIB_']
        if len(libs) > 1:
            print('%-16s    %d LIB_ node(s) for this kind (%s) - the first one supplies the mesh'
                  % ('', len(libs), ', '.join(n.get('name', '') for n in libs[:4])))
        src_node = libs[0] if libs else nodes[0]
        src = js['meshes'][src_node['mesh']]
        # A UNIT IS ONE MESH, AND NOT EVERY NODE OF A KIND IS REALLY AN INSTANCE OF IT (2026-10-20).
        # Nodes that carry a DIFFERENT mesh than the one this unit is built from will be drawn with
        # this unit's geometry in game, at their own transform - so a variant with the same shape
        # but a moved origin (0..5.81 vs -2.9..2.9 is how it showed up) lands units away from where
        # Blender has it.  Nothing about the bytes says so; only a comparison of mesh indices does.
        others = [n for n in nodes if n['mesh'] != src_node['mesh']]
        if others:
            print('%-16s    WARNING: %d of %d node(s) use a DIFFERENT mesh than this unit is built'
                  ' from (%s vs %s) - they will be drawn as this unit, not as their own geometry'
                  % ('', len(others), len(nodes), ', '.join('mesh %s' % n['mesh'] for n in others[:3]),
                     'mesh %s' % src_node['mesh']))
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
        # PUT THE MESH WHERE THE TEMPLATE'S COLLIDER IS (9H.41).  The collider is anchored in the
        # UNIT'S own frame - it is compiled into the template and follows the placement, not the
        # mesh - so moving the mesh is the only way to make it land on our geometry.  The level
        # builder subtracts the same vector from every placement (--unit-offsets), which cancels
        # out: the level still looks exactly like Blender, and the collider now covers the mesh.
        shift = collider_shift(tpl, mesh['positions']) if collider_shift_on else [0.0, 0.0, 0.0]
        if max(abs(v) for v in shift) > 1e-4:
            mesh['positions'] = mesh['positions'] + np.array(shift, dtype=np.float32)
            shifts[mapping[base]] = shift
        if len(pos) > MAX_VERTS_PER_MESH:
            raise SystemExit(
                '%s: the mesh exports %d verts, over the %d a single mesh block may hold.\n'
                '  Sixteen-bit indices are what every one of the game\'s 1,242 shipped mesh blocks\n'
                '  uses and its largest mesh is 15,972 verts (FINDINGS 9H.39); writing 32-bit indices\n'
                '  instead is what corrupted the spiral road from about 42%% in.  Split this object in\n'
                '  Blender into pieces that each export well under the limit - each piece becomes its\n'
                '  own unit and placement, which is how the game\'s own content is built.  Watch the\n'
                '  count this tool prints: the exporter inflates it, so compare this number with what\n'
                '  Blender shows rather than trusting Blender\'s vertex counter.'
                % (base, len(pos), MAX_VERTS_PER_MESH))
        generated = encode_unit([mesh])
        try:
            unit, _tpl_meshes, written = splice_into_template(
                generated, tpl, allow_duplicate=duplicate_meshes)
        except ValueError as exc:
            raise SystemExit('%s: %s' % (base, exc))
        unit_path = mapping[base]
        fname = out_dir / (unit_path.replace('/', '_') + '.unit')
        # THE BLOB EDIT (FINDINGS 9H.46): the spliced template's collider, rewritten in place.  The
        # config asks for it per kind (--collider-edit=BASE=scale:0.5,type:4) and the blob keeps its
        # length, so this cannot disturb the trailer the strip: route proved fragile.
        ops = collider_edits.get(base) or collider_edits.get(base_name(base))
        if ops:
            before = len(unit)
            unit = apply_collider_edits(unit, ops)
            assert len(unit) == before, 'a collider edit changed the unit length'
            print('%-16s    collider: %s  (blob edited in place, unit still %d B)'
                  % (base, ', '.join('%s=%s' % kv for kv in sorted(ops.items())), len(unit)))
        fname.write_bytes(unit)
        print('%-16s -> %-44s %2d placement(s)  %d verts  %d tris  %d bytes  '
              '(%d mesh block(s), %d primitive(s): %s)'
              % (base, unit_path, len(nodes), len(pos), len(idx) // 3, len(unit), written,
                 len(prim_sizes), ' '.join(prim_sizes)))
        print('%-16s    mesh from %s%s'
              % ('', src_node.get('name', ''), '  (the LIB_ master)' if libs else ''))
        csh = shifts.get(mapping[base])
        if csh is not None:
            print('%-16s    collider shift (%+.2f, %+.2f, %+.2f): the template\'s collider sits on'
                  ' ITS mesh box (FINDINGS 9H.41), so the mesh is moved onto it and the placement'
                  ' is moved back by the same vector - nothing visible moves.'
                  % ('', csh[0], csh[1], csh[2]))
        if len(pos) > 15972:
            print('%-16s    %d verts is larger than any mesh the game ships (15,972) - fine, but it\n'
                  '%-16s    is %d%% of the 65,535 block limit, where 32-bit indices start'
                  % ('', len(pos), '', 100 * len(pos) // MAX_VERTS_PER_MESH))
        print('%-16s    role %-9s  %s  <- read back from the built file'
              % ('', role, physics_of(unit)))
    if shifts and offsets_out is None:
        print('WARNING: %d unit kind(s) had their mesh moved onto their template\'s collider, but'
              ' --offsets was not given - the level builder cannot move the placements back, so the'
              ' level would sit displaced by those vectors.  Pass --offsets=<file>;'
              ' build_level_mod.py does.' % len(shifts))
    if offsets_out is not None:
        old = json.loads(offsets_out.read_text()) if offsets_out.exists() else {}
        units_map = (old.get('units') or {}) if isinstance(old, dict) else {}
        bases_map = (old.get('bases') or {}) if isinstance(old, dict) else {}
        for base_, path_ in mapping.items():
            d = shifts.get(path_)
            if d is None:
                continue
            units_map[path_] = [round(float(v), 6) for v in d]
            bases_map[base_] = [round(float(v), 6) for v in d]
        offsets_out.parent.mkdir(parents=True, exist_ok=True)
        offsets_out.write_text(json.dumps({
            '_comment': 'FINDINGS 9H.41.  The vector build_own_units.py moved a unit\'s mesh by, in '
                        'the unit\'s own frame (x and y only).  "units" is keyed by the unit PATH - '
                        'level_from_glb.py subtracts it, rotated and scaled into the record\'s '
                        'frame, from every placement of that unit - and "bases" by the GLB node '
                        'base name, which is what the offline checkers key on.',
            'units': dict(sorted(units_map.items())),
            'bases': dict(sorted(bases_map.items())),
        }, indent=2) + '\n')
        print()
        print('collider offsets: %s (%d unit kind(s), %d from this run)'
              % (offsets_out, len(units_map), len(shifts)))
    print()
    print('unit paths (hash these into the level):')
    for base, path in sorted(mapping.items()):
        print('   %-16s %s' % (base, path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
