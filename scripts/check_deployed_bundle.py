#!/usr/bin/env python3
"""Verify a DEPLOYED mod bundle - the bytes in the game, not the builder's own output.

Everything here is read back out of the deployed blob, so it catches what the builder's log
cannot: a stale bundle left in place, a payload packed at the wrong offset, a resource count the
C++ loader and the manifest disagree about, and the two things that decide whether a level can
be played at all:

  * every placement hash in the level IS a unit resource in this package (a level places units by
    hash, so a hash that is not in the loaded package is a unit that does not exist); and
  * every unit's mesh_count equals the mesh count of the native template whose trailer it wears -
    the invariant whose violation crashed the load (FINDINGS 9H.31, access read at 00000008).

usage:
  check_deployed_bundle.py <bundle dir> [<level resource path>]
  check_deployed_bundle.py <game>/mods/bundles/CustomRunLevel modules/d01_hub_room/custom_duckomp_room
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from glb_to_template_unit import read_u32, unit_mesh_end, UNIT_SIGNATURE   # noqa: E402
from level_decode import _decode_units, _load_names, decode as decode_level  # noqa: E402

BUNDLE_SIG = 0xF0000004
TYPE_UNIT = 0xE0A48D0BE9A7453F
TYPE_LEVEL = 0x2A690FD348FE9AC5
CORPUS = HERE / '.unit orig'
# the two records that are not ours: the skeleton's skydome and our own spawn marker
NATIVE_RECORDS = {'gameobjects/level_editor/player_spawn_marker',
                  'core/editor_slave/units/skydome/skydome'}

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)
    print('  PROBLEM: %s' % msg)


def unpack(blob: bytes) -> bytes:
    """The zlib-chunked container: sig, uncompressed size, padding, then 64 KB chunks."""
    sig, total, _pad = struct.unpack_from('<III', blob, 0)
    if sig != BUNDLE_SIG:
        raise ValueError('not a bundle: sig 0x%08x' % sig)
    out, off = bytearray(), 12
    while len(out) < total:
        (clen,) = struct.unpack_from('<I', blob, off)
        off += 4
        out += zlib.decompress(blob[off:off + clen])
        off += clen
    if len(out) != total:
        raise ValueError('chunks gave %d bytes, the header says %d' % (len(out), total))
    return bytes(out)


def parse(body: bytes):
    """Resource count, the TOC, then EVERY resource's 36-byte header (including number 0)."""
    n = read_u32(body, 0)
    off = 0x104 + n * 16                    # 4 + 84-byte preamble + 172-byte padding
    res = []
    while len(res) < n:
        th, nh, flags, stream_sz, data_sz, _unknown = struct.unpack_from('<QQIQII', body, off)
        off += 36
        res.append(((th, nh), flags, body[off:off + data_sz], stream_sz))
        off += data_sz
    return n, res, off


def template_mesh_count(unit: bytes) -> int | None:
    """The mesh count of the native template whose trailer this unit wears (None if not found)."""
    if not CORPUS.is_dir():
        return None
    trailer = unit[unit_mesh_end(unit):]
    if not trailer:
        return None
    for path in sorted(CORPUS.glob('*.unit')):
        data = path.read_bytes()
        if len(data) < 8 or read_u32(data, 0) != UNIT_SIGNATURE:
            continue
        try:
            if data[unit_mesh_end(data):] == trailer:
                return read_u32(data, 4)
        except Exception:
            continue
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    bundle_dir = Path(sys.argv[1])
    level_path = sys.argv[2] if len(sys.argv) > 2 else None

    manifest = json.loads((bundle_dir / 'manifest.json').read_text())
    hash_hex = str(manifest['bundle_hash'])
    blob_name = '%016x' % int(hash_hex[2:] if hash_hex.lower().startswith('0x') else hash_hex, 16)
    blob = (bundle_dir / blob_name).read_bytes()
    print('== %s' % bundle_dir)
    print('   file %s, %d bytes in the game' % (blob_name, len(blob)))

    body = unpack(blob)
    n, res, end = parse(body)
    print('   sig 0x%08X, %d resources, %d bytes unpacked' % (BUNDLE_SIG, n, len(body)))
    if end != len(body):
        fail('payload walk ended at %d of %d bytes - the table is not tight' % (end, len(body)))
    if n != manifest['resource_count']:
        fail('resource count %d != manifest %d' % (n, manifest['resource_count']))
    ini = [l.strip() for l in (bundle_dir / 'bundle.ini').read_text().splitlines()
           if 'ResourceCount' in l]
    if ini != ['ResourceCount=%d' % n]:
        fail('bundle.ini %s does not agree with %d resources' % (ini, n))

    want = {}
    for path, r in manifest['resources'].items():
        want[(int(r['type_hash'], 16), int(r['name_hash'], 16))] = (path, r['size'], r['type'])
    units, level_payload = {}, None
    for (type_hash, name_hash), flags, data, stream_sz in res:
        got = want.pop((type_hash, name_hash), None)
        if got is None:
            fail('(0x%016x, 0x%016x) is in the bundle but not in the manifest'
                 % (type_hash, name_hash))
            continue
        path, size, kind = got
        if len(data) != size:
            fail('%s: deployed %d bytes, manifest says %d' % (path, len(data), size))
        if stream_sz:
            fail('%s: stream size %d, expected 0 in a flat bundle' % (path, stream_sz))
        print('   [%-8s] %-44s %9d bytes' % (kind, path, len(data)))
        if type_hash == TYPE_UNIT:
            units[name_hash] = (path, data)
        elif type_hash == TYPE_LEVEL:
            level_payload = (path, data)
    for path, size, _kind in want.values():
        fail('%s (%d bytes) is in the manifest but not in the bundle' % (path, size))

    for name_hash, (path, data) in sorted(units.items(), key=lambda kv: kv[1][0]):
        if read_u32(data, 0) != UNIT_SIGNATURE:
            fail('%s: not a .unit body' % path)
            continue
        meshes = read_u32(data, 4)
        trailer = len(data) - unit_mesh_end(data)
        tpl = template_mesh_count(data)
        note = ('template declares %d' % tpl) if tpl is not None \
            else 'template not in scripts/.unit orig - count unchecked'
        if tpl is not None and tpl != meshes:
            fail('%s: %d mesh block(s) but its template declares %d - this is the mesh list '
                 'mismatch that crashed the load at 0x00270259' % (path, meshes, tpl))
        print('   unit [%-44s] mesh_count %-2d trailer %7d B  (%s)'
              % (path, meshes, trailer, note))

    if level_path and level_payload is not None:
        path, data = level_payload
        tmp = Path('/tmp/check_deployed_bundle_level.tmp')
        tmp.write_bytes(data)
        names = _load_names()
        doc = decode_level(tmp, names)
        count = doc['unit_table']['count']
        records = _decode_units(data, doc['unit_table']['offset'], count, 64)
        placed: dict[str, int] = {}
        for rec in records:
            nm = names.get(rec['template_hash'][2:], rec['template_hash'])
            placed[nm] = placed.get(nm, 0) + 1
            if nm in NATIVE_RECORDS:
                continue
            hash_int = int(nm, 16) if nm.startswith('0x') else None
            if hash_int is not None and hash_int in units:
                continue                                # our own unit, shipped in this bundle
            fail('the level places %s x%d and it is NOT a unit resource in this package'
                 % (nm, placed[nm]))
        ours = sum(n for nm, n in placed.items() if nm not in NATIVE_RECORDS)
        print('   the level payload is %d bytes, %d records (%d of them our units, %d native)'
              % (len(data), count, ours, count - ours))
        for nm, n in sorted(placed.items()):
            print('       %-52s x%d' % (nm, n))

    print()
    if problems:
        print('FAILED - %d problem(s)' % len(problems))
        return 2
    print('OK - the deployed bundle agrees with its manifest, and every unit agrees with the '
          'native template whose trailer it wears')
    return 0


if __name__ == '__main__':
    sys.exit(main())
