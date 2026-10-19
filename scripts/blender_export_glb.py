#!/usr/bin/env python3
"""Export a .blend scene to .glb, with the settings this pipeline needs and no others.

    blender --background <scene.blend> --python scripts/blender_export_glb.py -- <out.glb>

WHY EACH SETTING MATTERS (this is the one step where a wrong flag silently ruins the level):

  export_yup=True     glTF is Y-up.  The engine is Z-up, so our tools convert positions with
                      R_x(+90) and rotations with R_x(+90) . R . R_x(-90).  Exporting Z-up
                      instead ("export_yup=False") bakes different coordinates and every
                      placement comes out on its side.
  export_apply=False  Do NOT apply modifiers: a level's node transform IS the authored placement,
                      and applying modifiers can move geometry between objects.
  export_animations=False, export_skins=False, export_morph=False
                      A level has no animation.  The exporter's animation sampling adds nodes and
                      bakes transforms into them, which the level builder would then place as
                      extra units.
  export_extras=False, export_cameras=False, export_lights=False
                      Keep the node list exactly the mesh objects the author placed.
  export_materials='EXPORT'
                      Material slots come along (the unit builder still takes the mesh only).
  use_selection=False The level IS the scene.

After writing, it re-reads the file it produced and prints every mesh node's name, translation and
rotation, so the export can be checked against Blender's own N-panel before anything is built.
"""
import json
import math
import struct
import sys

import bpy

WANT = {
    'export_format': 'GLB',
    'use_selection': False,
    'export_yup': True,
    'export_apply': False,
    'export_animations': False,
    'export_skins': False,
    'export_morph': False,
    'export_extras': False,
    'export_cameras': False,
    'export_lights': False,
    'export_materials': 'EXPORT',
    'export_texcoords': True,
    'export_normals': True,
    'export_tangents': False,
    'export_draco_mesh_compression_enable': False,
}


def log(m):
    print('[export] %s' % m)


def read_glb(path):
    raw = open(path, 'rb').read()
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


def main():
    argv = sys.argv
    out = argv[argv.index('--') + 1] if '--' in argv else 'export.glb'
    props = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
    kwargs = {k: v for k, v in WANT.items() if k in props}
    dropped = sorted(set(WANT) - set(kwargs))
    if dropped:
        log('this Blender does not know: %s' % ', '.join(dropped))
    for obj in bpy.data.objects:
        obj.select_set(False)
    log('scene: %d objects, %d with meshes'
        % (len(bpy.data.objects), sum(1 for o in bpy.data.objects if o.type == 'MESH')))
    bpy.ops.export_scene.gltf(filepath=out, **kwargs)
    log('wrote %s' % out)

    js, _bin = read_glb(out)
    log('nodes in the file (name, translation, rotation, scale):')
    for i, node in enumerate(js.get('nodes', [])):
        if 'mesh' not in node:
            log('  %2d %-20s NO MESH' % (i, node.get('name', '')))
            continue
        t = node.get('translation', [0, 0, 0])
        q = node.get('rotation', [0, 0, 0, 1])
        s = node.get('scale', [1, 1, 1])
        # what our converter will store: the axis and angle of this rotation
        w = max(-1.0, min(1.0, q[3]))
        angle = 2.0 * math.degrees(math.acos(abs(w)))
        log('  %2d %-20s t=(%8.4f,%8.4f,%8.4f)  q=(%+.4f,%+.4f,%+.4f,%+.4f)  %7.2f deg'
            % (i, node.get('name', ''), t[0], t[1], t[2], q[0], q[1], q[2], q[3], angle))
        if any(abs(v - 1.0) > 1e-6 for v in s):
            log('      scale = %s' % [round(v, 4) for v in s])


main()
