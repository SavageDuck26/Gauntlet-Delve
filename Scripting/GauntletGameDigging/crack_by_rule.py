#!/usr/bin/env python3
"""Guess names by *rule* rather than vocabulary.

Two rules the earlier sweeps never used properly:

  state variants  the HUD stylesheet (gui/hud_css.lua) names four states - bg_img,
                  bg_img_hover, bg_img_pressed, bg_img_selected - but every sweep so
                  far only tried _over/_normal/_active/_disabled/_locked.  So: add
                  every state word to every known name, and strip every state word off
                  every known name (the missing base of a *_over pair).

  numbered gaps   families are numbered (eq_warrior_head_set04, cape_s03_r01, *_01).
                  If a number is missing from a range we hold, the gap is a candidate.
                  Numbers are tried 0..40, zero-padded and not.
"""
import csv
import pathlib
import re
import sys

sys.path.insert(0, '/home/<user>/Documents/Coding/Gauntlet-Reverse-Engineering/Scripting/GauntletGameDigging')
from hunt_unit_textures import murmur                                   # noqa: E402

E = pathlib.Path.home() / 'Documents/Coding/Gauntlet-Export'

STATES = ['_hover', '_pressed', '_selected', '_active', '_over', '_normal', '_down',
          '_up', '_disabled', '_locked', '_unlocked', '_highlight', '_glow', '_dim',
          '_off', '_on', '_grey', '_gray', '_empty', '_full', '_new', '_checked',
          '_default', '_open', '_closed', '_inactive', '_clicked', '_pushed']

NUM_TAIL = re.compile(r'^(.*?)(?:_?(set|tier|level|lvl|var|ver|v))?(\d{1,2})$')


def main():
    rows = list(csv.DictReader((E / 'index.tsv').open(newline=''), delimiter='\t'))
    named = sorted({r['name'] for r in rows if r['status'] == 'named'})
    unres = {r['name_hash'].lower(): r for r in rows if r['status'] == 'unresolved'}
    print(f"named: {len(named):,}   unresolved: {len(unres):,}", flush=True)

    cands = {}
    for n in named:
        for s in STATES:
            cands.setdefault(n + s, f"state+ {n}")
            if n.endswith(s):
                cands.setdefault(n[:-len(s)], f"state- {n}")
        m = NUM_TAIL.match(n)
        if m:
            head, word, num = m.group(1), m.group(2) or '', m.group(3)
            for k in range(0, 41):
                for fmt in (f"{k}", f"{k:02d}"):
                    cands.setdefault(f"{head}{('_' + word) if word else ''}{fmt}",
                                     f"number {n}")
    print(f"rule candidates: {len(cands):,}", flush=True)

    hits = []
    for c, why in cands.items():
        h = f"{murmur(c):016x}"
        if h in unres:
            hits.append((h, c, why, unres[h]))
    print(f"\nHITS: {len(hits)}")
    for h, c, why, r in sorted(hits, key=lambda x: x[1]):
        print(f"  {h}  {c:50s} ({why})  {r['type']} {r['package']} {r['size']}B")


if __name__ == '__main__':
    main()
