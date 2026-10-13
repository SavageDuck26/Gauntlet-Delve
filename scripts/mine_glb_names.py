#!/usr/bin/env python3
"""Mine material names out of the converted GLBs and use them as name vocabulary.

`view/glb/**` holds one GLB per unit, and each carries the unit's material slots as
JSON: `"materials":[{"name":"m_tutorial_platform"}, ...]`.  That is the same vocabulary
that recovered `blocks/d01_caves/rocks/caverock_stalagmites_01b`, but read from clean
JSON instead of by scanning binary bodies - and it covers units whose bodies scan badly.

    python3 mine_glb_names.py            # report hits
    python3 mine_glb_names.py --dump     # just list the vocabulary
"""
import argparse
import csv
import json
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hunt_unit_textures import murmur                                   # noqa: E402

E = pathlib.Path.home() / 'Documents/Coding/Gauntlet-Export'
FRAG = ['', '_01', '_02', '_03', '_1', '_2', '_a', '_b', '_c', '_d', '_e', '_l',
        '_m', '_ml', '_hm', '_h', '_r', '_s', '_t', '_left', '_right', '_mid',
        '_middle', '_top', '_bottom', '_hi', '_lo', '_h1', '_h2', '_h3', '_h4',
        '_horizontal', '_vertical', '_broken', '_damaged', '_parts', '_piece',
        '_pieces', '_start', '_end', '_open', '_closed', '_static', '_dynamic',
        '_p01', '_p02', '_p03', '_01b', '_02b', '_b01', '_e01', '_e02', '_s01']


def glb_material_names(p):
    """Names from the JSON chunk of a .glb."""
    try:
        raw = p.read_bytes()
    except OSError:
        return []
    if raw[:4] != b'glTF':
        return []
    try:
        _magic, _ver, _len = struct.unpack_from('<III', raw, 0)
        clen, ctype = struct.unpack_from('<II', raw, 12)
        if ctype != 0x4E4F534A:                      # 'JSON'
            return []
        doc = json.loads(raw[20:20 + clen].decode('utf-8', 'replace'))
    except Exception:
        return []
    out = []
    for m in doc.get('materials', []) or []:
        n = (m or {}).get('name')
        if n and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{2,60}', n):
            out.append(n)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', action='store_true')
    args = ap.parse_args()

    files = sorted((E / 'view/glb').rglob('*.glb'))
    vocab = {}
    for p in files:
        for n in glb_material_names(p):
            vocab.setdefault(n, str(p.relative_to(E / 'view/glb')))
    print(f"GLBs: {len(files):,}   distinct material names: {len(vocab):,}", flush=True)
    stems = set()
    for n in vocab:
        stems.add(n)
        if n.startswith('m_'):
            stems.add(n[2:])
    if args.dump:
        for s in sorted(stems):
            print(f"  {s}")
        return

    rows = list(csv.DictReader((E / 'index.tsv').open(newline=''), delimiter='\t'))
    unres = {r['name_hash'].lower(): r for r in rows if r['status'] == 'unresolved'}
    named = {r['name'] for r in rows if r['status'] == 'named'}
    dirs = sorted({'/'.join(n.split('/')[:-1]) for n in named if '/' in n})
    print(f"unresolved: {len(unres):,}   dirs: {len(dirs):,}   stems: {len(stems):,}", flush=True)

    hits = []
    for s in stems:
        forms = {s} | {s + f for f in FRAG} | {('m_' + s) for f in FRAG}
        for f in forms:
            for d in [''] + dirs:
                c = f"{d}/{f}" if d else f
                h = f"{murmur(c):016x}"
                if h in unres:
                    hits.append((h, c, s, unres[h]))
    print(f"\nHITS: {len(hits)}")
    for h, c, s, r in sorted(hits, key=lambda x: x[1]):
        print(f"  {h}  {c:52s} ({r['type']} {r['package']} {r['size']}B)  from {s}")
    if hits:
        with pathlib.Path('/tmp/glb_name_hits.tsv').open('w') as fh:
            fh.write('hash\tname\tsource\n')
            for h, c, s, _r in hits:
                fh.write(f"{h}\t{c}\t{s}\n")
        print('wrote /tmp/glb_name_hits.tsv')


if __name__ == '__main__':
    main()
