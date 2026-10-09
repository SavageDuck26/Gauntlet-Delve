#!/usr/bin/env python3
"""Hunt the localisation vocabulary under one namespace.

`localization/game_strings` holds every display string in the game, including the
achievement names ("Skeleton Slayer", "Dragon Slayer", "Heedless").  An icon name is
such a name snake_cased, so: normalise every string every plausible way and test it
under a single namespace (default achievement_icons/).

    python3 hunt_loc_vocab.py --namespace achievement_icons
    python3 hunt_loc_vocab.py --namespace achievement_icons --suffixes _locked,_unlocked
"""
import argparse
import csv
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, '/home/<user>/Documents/Coding/Gauntlet-Reverse-Engineering/Scripting/GauntletGameDigging')
from hunt_unit_textures import murmur                                   # noqa: E402

E = pathlib.Path.home() / 'Documents/Coding/Gauntlet-Export'
STR = re.compile(rb'[ -~]{3,160}')


def normalise(s):
    """Every plausible snake_case reading of a display string."""
    s = unicodedata.normalize('NFKD', s)
    s = s.replace("'", '').replace('’', '')
    s = re.sub(r'[^A-Za-z0-9]+', ' ', s).strip().lower()
    if not s:
        return set()
    out = {'_'.join(s.split()), ''.join(s.split()), '-'.join(s.split()),
           '_'.join(s.split()).replace('_the_', '_')}
    words = s.split()
    if words and words[0] in ('the', 'a', 'an'):
        out.add('_'.join(words[1:]))
    if words and words[0] == 'you':
        out.add('_'.join(words[1:]))
    for w in ('the', 'a', 'an', 'of', 'your', 'you'):
        out.add('_'.join(x for x in words if x != w))
    out.discard('')
    out.discard('_')
    return {o.strip('_') for o in out if o}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--namespace', default='achievement_icons',
                    help='only test names under this prefix')
    ap.add_argument('--source', default='localization/game_strings',
                    help='resource to mine for vocabulary')
    ap.add_argument('--suffixes', default='_locked,_unlocked',
                    help='suffixes to try (comma separated, may be empty)')
    ap.add_argument('--filter', help='only strings matching this regex (for a readable report)')
    args = ap.parse_args()

    src = E / 'named' / (args.source + '.strings')
    if not src.exists():
        src = E / 'named' / args.source
    strings = {m.group().decode('ascii', 'ignore') for m in STR.finditer(src.read_bytes())}
    print(f"vocabulary: {len(strings):,} strings from {src.name}", flush=True)

    suffixes = [s for s in args.suffixes.split(',') if s != None]

    rows = list(csv.DictReader((E / 'index.tsv').open(newline=''), delimiter='\t'))
    unres = {r['name_hash'].lower(): r for r in rows if r['status'] == 'unresolved'}
    print(f"targets: {len(unres):,} unresolved hashes", flush=True)

    want = re.compile(args.filter, re.I) if args.filter else None
    cands = {}
    for s in strings:
        if want and not want.search(s):
            continue
        for n in normalise(s):
            for suf in suffixes:
                c = f"{args.namespace}/{n}{suf}"
                cands.setdefault(c, s)
    print(f"candidates: {len(cands):,}", flush=True)

    hits = []
    for c, s in cands.items():
        h = f"{murmur(c):016x}"
        if h in unres:
            hits.append((h, c, s, unres[h]))
    print(f"\nHITS: {len(hits)}")
    for h, c, s, r in sorted(hits, key=lambda x: x[1]):
        print(f"  {h}  {c:52s} <- \"{s[:40]}\"  ({r['type']} {r['package']} {r['size']}B)")
    if hits:
        with pathlib.Path('/tmp/loc_vocab_hits.tsv').open('w') as fh:
            fh.write('hash\tname\tsource_string\n')
            for h, c, s, _r in hits:
                fh.write(f"{h}\t{c}\t{s}\n")
        print('wrote /tmp/loc_vocab_hits.tsv')


if __name__ == '__main__':
    main()
