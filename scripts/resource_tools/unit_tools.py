"""
Stingray .unit resource tools - full Blender round-trip.

The .unit format contains geometry, materials, bone skinning, and LOD info.

Blender-compatible exports:
  .unit -> .glb  (glTF 2.0, direct Blender import)
  .unit -> .obj  (Wavefront OBJ, no skinning)
  .glb  -> .unit (re-encode from Blender export)
  .obj  -> .unit (re-encode from OBJ)

Usage:
  python unit_tools.py selftest
  python unit_tools.py gltf   <file.unit>  [file.bones]  [out.glb]
  python unit_tools.py obj    <file.unit>  [out_dir]
  python unit_tools.py encode <input.glb|.obj>  [out.unit]
"""
from __future__ import annotations
import importlib.util as _ilu, json, os, struct, sys
from typing import Any, Dict, Optional

HERE   = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)


def _load_module(name: str, path: str):
    spec = _ilu.spec_from_file_location(name, path)
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def decode_unit_to_gltf(unit_path: str,
                         bones_path: Optional[str] = None,
                         out_path: Optional[str] = None) -> str:
    """Export .unit -> glTF (.glb) for Blender import."""
    mod = _load_module('unit_to_gltf', os.path.join(PARENT, 'unit_to_gltf.py'))
    return mod.convert_unit_to_gltf(unit_path, bones_path, out_path)


def decode_unit_to_obj(unit_path: str, out_dir: Optional[str] = None) -> str:
    """Export .unit -> OBJ/MTL (no skinning)."""
    if PARENT not in sys.path:
        sys.path.insert(0, PARENT)
    mod = _load_module('unit_to_obj', os.path.join(PARENT, 'unit_to_obj.py'))
    out_dir = out_dir or os.path.dirname(unit_path) or '.'
    base = os.path.splitext(os.path.basename(unit_path))[0]
    obj_path = os.path.join(out_dir, base + '.obj')
    mod.convert_unit(unit_path, obj_path)
    return obj_path


def encode_unit_from_gltf(glb_path: str, out_path: Optional[str] = None) -> str:
    """Import from .glb -> .unit binary."""
    mod = _load_module('gltf_to_unit', os.path.join(PARENT, 'gltf_to_unit.py'))
    return mod.convert_to_unit(glb_path, out_path)


def encode_unit_from_obj(obj_path: str, out_path: Optional[str] = None) -> str:
    """Import from .obj -> .unit binary."""
    mod = _load_module('gltf_to_unit', os.path.join(PARENT, 'gltf_to_unit.py'))
    return mod.convert_to_unit(obj_path, out_path)


def decode_unit_header(blob: bytes) -> Dict[str, Any]:
    """Decode the .unit header metadata."""
    if len(blob) < 8:
        raise ValueError("blob too short")
    sig = struct.unpack_from('<I', blob, 0)[0]
    mesh_count = struct.unpack_from('<I', blob, 4)[0]
    return {
        'signature': f'0x{sig:08X}',
        'mesh_count': mesh_count,
        'file_size': len(blob),
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'selftest':
        sample = os.path.join(PARENT, 'Exports', 'samples',
                               'unit_015febcb203ebaaf.unit')
        bones  = os.path.join(PARENT, 'Exports', 'samples',
                               'bones_e8a62af86d41f0e5.bones')
        if not os.path.exists(sample):
            print("unit_tools selftest: SKIP (sample not found)")
        else:
            blob = open(sample, 'rb').read()
            meta = decode_unit_header(blob)
            print(f"unit_tools: sig={meta['signature']} meshes={meta['mesh_count']}")
            glb = decode_unit_to_gltf(sample,
                                       bones if os.path.exists(bones) else None,
                                       '/tmp/_unit_tools_test.glb')
            unit = encode_unit_from_gltf(glb, '/tmp/_unit_tools_test.unit')
            for p in ['/tmp/_unit_tools_test.glb', '/tmp/_unit_tools_test.unit']:
                try: os.unlink(p)
                except: pass
            print("unit_tools selftest: PASS")

    elif cmd in ('gltf', 'glb'):
        unit = sys.argv[2]
        bones = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].endswith('.bones') else None
        out   = next((a for a in sys.argv[3:] if a.endswith('.glb')), None)
        decode_unit_to_gltf(unit, bones, out)

    elif cmd == 'obj':
        unit = sys.argv[2]
        out_dir = sys.argv[3] if len(sys.argv) > 3 else None
        decode_unit_to_obj(unit, out_dir)

    elif cmd == 'encode':
        src = sys.argv[2]
        dst = sys.argv[3] if len(sys.argv) > 3 else None
        if src.endswith('.glb'):
            encode_unit_from_gltf(src, dst)
        else:
            encode_unit_from_obj(src, dst)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
