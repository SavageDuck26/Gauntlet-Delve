#!/usr/bin/env python3
"""The `m_` namespace, harvested from unit bodies, as candidate resource names.

Unit bodies carry their material slots as `m_<name>` strings (`m_tutorial_platform`,
`m_caverock_stalagmites_01`), and the runtime capture shows `m_potion` being hashed by
the engine - so `m_*` is a real naming convention, not noise.  Two ways it could name a
resource: the name *is* `m_x` (prefix included), or the name is `x` with the prefix
stripped.  Both were untested: the segment sweeps used catalogue-derived segments only,
so `props/tutorial_platform` could never be generated.
"""
import collections
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hunt_unit_textures import murmur                                   # noqa: E402

E = pathlib.Path.home() / 'Documents/Coding/Gauntlet-Export'
STR = re.compile(rb'[A-Za-z_][A-Za-z0-9_]{3,60}')


def main():
    rows = list(csv.DictReader((E / 'index.tsv').open(newline=''), delimiter='\t'))
    unres = {r['name_hash'].lower(): r for r in rows if r['status'] == 'unresolved'}
    named = {r['name'] for r in rows if r['status'] == 'named'}

    m_names = collections.Counter()
    for area in ('named', 'unresolved'):
        for p in (E / area).rglob('*.unit'):
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            for m in STR.finditer(raw):
                s = m.group().decode('ascii', 'ignore')
                if s.startswith('m_') and len(s) > 3:
                    m_names[s] += 1
    # plus anything the engine hashed that looks the same
    cap = pathlib.Path.home() / '.local/share/Steam/steamapps/common/Gauntlet/binaries/runtime_names.tsv'
    if cap.exists():
        for line in cap.read_text(errors='replace').splitlines():
            for s in re.findall(r'\bm_[a-z0-9_]{3,40}', line):
                m_names[s] += 1
    print(f"distinct m_* names: {len(m_names):,}", flush=True)
    print("  samples:", ', '.join(list(m_names)[:12]))

    dirs = sorted({'/'.join(n.split('/')[:-1]) for n in named if '/' in n})
    cands = {}
    for s in m_names:
        stem = s[2:]
        variants = {s, stem, s + '_01', stem + '_01', s + '_a', stem + '_a'}
        for v in variants:
            cands.setdefault(v, f"m-name {s}")
        for d in dirs:
            for v in variants:
                cands.setdefault(f"{d}/{v}", f"m-name {s} in {d}")
    print(f"candidates: {len(cands):,}", flush=True)

    hits = []
    for c, why in cands.items():
        h = f"{murmur(c):016x}"
        if h in unres:
            hits.append((h, c, why, unres[h]))
    print(f"\nHITS: {len(hits)}")
    for h, c, why, r in sorted(hits, key=lambda x: x[1]):
        print(f"  {h}  {c:52s} ({r['type']} {r['package']} {r['size']}B)")
    if hits:
        with pathlib.Path('/tmp/m_namespace_hits.tsv').open('w') as fh:
            fh.write('hash\tname\tsource\n')
            for h, c, why, _r in hits:
                fh.write(f"{h}\t{c}\t{why}\n")
        print('wrote /tmp/m_namespace_hits.tsv')


if __name__ == '__main__':
    main()
