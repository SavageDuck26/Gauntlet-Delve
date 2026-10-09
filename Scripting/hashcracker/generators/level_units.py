#!/usr/bin/env python3
"""Candidate generator for the unresolved level-`unit` rows (FINDINGS 60.11).

Those 57 resources are unique mesh-bearing units inside the level modules.  They
carry no name strings and their content is not duplicated anywhere, so the only
way in is the naming convention.  This builds candidates from four angles:

  A  numbered tile props          props/d01_<env>/tile_NN            (we hold tile_03/tile_04)
  B  sibling completion           mutate the tokens of names already KNOWN in the
                                  same directories along the axes the vocabulary
                                  uses (rock / part / shape / size / number)
  C  referenced-material stems    the units' bodies reference e.g.
                                  `lavarock_floor_01_norm`, so the tile that uses
                                  it is named from that stem
  D  directory moves              a known name with its category dir added/removed

Writes the candidate list to stdout (one per line) and a summary to stderr.

`--prefab-vocab DIR` instead writes the four slot lists the prefab pattern sweep
needs (`prefab_words.txt`, `prefab_words_small.txt`, `prefab_cats.txt`,
`prefab_envs.txt`, `prefab_suffix.txt`) into DIR, so that run is reproducible:

    python3 generators/level_units.py --prefab-vocab data/vocab
    tools/hc.sh crack --gpu --targets data/vocab/unresolved_targets.txt \
        --list e=data/vocab/prefab_envs.txt --list c=data/vocab/prefab_cats.txt \
        --list a=data/vocab/prefab_words.txt --list b=data/vocab/prefab_words.txt \
        --list d=data/vocab/prefab_suffix.txt \
        --pattern 'modules/d01_%e/prefabs/%c/prefab_%e_%a_%b_%d' \
        --pattern 'modules/d01_%e/prefabs/prefab_%e_%a_%b_%d' --matches matches.tsv
"""
import collections
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
GD = HERE.parent / 'GauntletGameDigging'

SMALL_WORDS = """floor floors wall walls detail details pit round square raised altar gate
exit door doors spawner spawners sarcophagus lit special room rooms temple pillar pillars
corner corners stairs stair rock rocks rockpile ceiling ceilings column skull ornament
ornaments pit_round pit_square crypt lava caves cavestruct lavastruct lavarock caverock
cryptsmooth stone trap traps key doorway bridge cover broken rubble bones bone coffin urn
brazier pool water fountain statue idol shrine arch beam rail railing pipes machine cage
chain chains plate platform step steps ramp ledge column_base base top bottom left right
north south east west center corner_inner corner_outer""".split()

CATS = ['door_walls', 'floor_details', 'gate_exit', 'spawners', 'special_rooms',
        'wall_details', 'ceilings', 'corners', 'floors', 'walls', 'tiles', 'props',
        'details', 'rooms', 'ambient', 'encounters', 'treasure', 'traps', 'doors',
        'decor', 'cutscenes']
ENVS = ['crypt', 'lava', 'caves', 'hub', 'menu', 'common', 'arcade', 'swamp',
        'colosseum', 'arena']


def write_prefab_vocab(outdir):
    """Write the prefab pattern-slot lists (see the module docstring)."""
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    ov = json.loads((GD / 'resource_name_overlay.json').read_text())
    rows = list(csv.DictReader((GD / 'bundle_manifest/04_bundle_resources.csv').open(
        newline='', encoding='utf-8', errors='replace')))
    toks = collections.Counter()
    for r in rows:
        n = r.get('name') or ov.get(r['name_hash'].lower())
        if not n or not re.match(r'^(props|blocks|modules|gameobjects|decals|characters|effects)/', n):
            continue
        for t in re.split(r'[/_]', n):
            if t and not re.fullmatch(r'(d01|\d+|\d+c\d*|diff|norm|spec|var\d+)', t):
                toks[t] += 1
    (out / 'prefab_words.txt').write_text('\n'.join(t for t, _ in toks.most_common(4000)) + '\n')
    (out / 'prefab_words_small.txt').write_text('\n'.join(SMALL_WORDS) + '\n')
    (out / 'prefab_cats.txt').write_text('\n'.join(CATS) + '\n')
    (out / 'prefab_envs.txt').write_text('\n'.join(ENVS) + '\n')
    sufs = ([f'{i:02d}' for i in range(1, 41)] + [f'{i:02d}c' for i in range(1, 41)] +
            [f'{i}c' for i in range(1, 41)] + [f'{i}c_{i}c' for i in range(1, 21)] +
            ['var01', 'var02', 'var03', '01_var01', '02_var01'])
    (out / 'prefab_suffix.txt').write_text('\n'.join(sufs) + '\n')
    sys.stderr.write(f'wrote prefab vocab to {out}: words {len(toks)} / small '
                     f'{len(SMALL_WORDS)} / cats {len(CATS)} / envs {len(ENVS)} / '
                     f'suffix {len(sufs)}\n')


if __name__ == '__main__' and '--prefab-vocab' in sys.argv:
    write_prefab_vocab(sys.argv[sys.argv.index('--prefab-vocab') + 1])
    sys.exit(0)
ov = json.loads((GD / 'resource_name_overlay.json').read_text())
rows = list(csv.DictReader((GD / 'bundle_manifest/04_bundle_resources.csv').open(
    newline='', encoding='utf-8', errors='replace')))
named = {}
for r in rows:
    n = r.get('name') or ov.get(r['name_hash'].lower())
    if n:
        named[n] = r['type']

ENVS = ['d01_caves', 'd01_lava', 'd01_crypt', 'd01_common', 'd01_hub_room', 'menu']
CATS = ['floors', 'walls', 'borders', 'rocks', 'pillars', 'stairs', 'railings', 'water', 'ceilings']
AXES = {
    'rock': ['lavarock', 'caverock', 'cavestruct', 'lavastruct', 'cryptsmooth', 'swamp',
             'corruption', 'caves', 'lava', 'crypt', 'lavaflow', 'cryptbrick'],
    'part': ['floor', 'floors', 'wall', 'walls', 'border', 'borders', 'rock', 'rocks',
             'pillar', 'pillars', 'stairs', 'stair', 'railing', 'railings', 'water',
             'ceiling', 'edge', 'drain', 'base', 'deck'],
    'shape': ['convex', 'concave', 'straight', 'corner', 'low', 'high', 'outer', 'inner',
              'end', 'start', 'turn', 'cross', 'tee', 'g', 'u', 'w', 'c', 'd', 'dw', 'ww'],
    'size': ['1c', '2c', '4c', '8c', '16c', '4c2', '2c2', '1c2', '8c2'],
    'num': [f'{i:02d}' for i in range(1, 41)] + [f'{i}' for i in range(1, 25)],
}
AXIS_OF = {tok: ax for ax, toks in AXES.items() for tok in toks}
SUFFIXES = ['', '_var01', '_var02', '_var03', '_diff', '_norm', '_spec', '_01', '_02', '_03']

# --- seeds: names we already know whose dir looks like where the units live ---
seeds = [n for n in named
         if n.startswith('props/d01_') or n.startswith('blocks/d01_')]
sys.stderr.write(f'seeds (props/blocks): {len(seeds)}\n')

out = set()


def add(x):
    if len(x) < 120:
        out.add(x)


# A. numbered tile props
for e in ENVS:
    for i in range(1, 41):
        for s in ('', '_var01', '_var02', '_diff', '_norm', '_spec'):
            add(f'props/{e}/tile_{i:02d}{s}')
            add(f'blocks/{e}/tile_{i:02d}{s}')
            add(f'props/{e}/tiles/tile_{i:02d}{s}')

# B + D. sibling completion / directory moves
for n in seeds:
    d, _, leaf = n.rpartition('/')
    if not leaf:
        continue
    toks = leaf.split('_')
    axes = [i for i, t in enumerate(toks) if t in AXIS_OF]
    # one-axis substitutions
    for i in axes:
        ax = AXIS_OF[toks[i]]
        for v in AXES[ax]:
            if v == toks[i]:
                continue
            cand = toks[:i] + [v] + toks[i + 1:]
            add('/'.join([d] + cand))
            for s in ('', '_var01'):
                add('/'.join([d] + cand) + s)
    # two-axis substitutions on the most valuable pairs
    for a in range(len(axes)):
        for b in range(a + 1, len(axes)):
            ia, ib = axes[a], axes[b]
            if AXIS_OF[toks[ia]] == AXIS_OF[toks[ib]]:
                continue
            for va in AXES[AXIS_OF[toks[ia]]]:
                for vb in AXES[AXIS_OF[toks[ib]]]:
                    if va == toks[ia] or vb == toks[ib]:
                        continue
                    cand = list(toks)
                    cand[ia], cand[ib] = va, vb
                    add('/'.join([d] + cand))
    # D. directory moves: flat <-> category dir, and cross-level
    for e in ENVS:
        for c in CATS:
            add(f'blocks/{e}/{c}/{leaf}')
            add(f'blocks/{e}/{c}/{leaf}_4c')
            add(f'props/{e}/{leaf}')
            add(f'props/{e}/tiles/{leaf}')

# C. referenced-material stems
REFSTEMS = ['lavarock_floor_01', 'lavarock_rock_01', 'lavarock_wall_01',
            'lavarock_floor_border_01', 'lava_geyser', 'lavastruct_stairs',
            'lavastruct_borders_01', 'caves_water_01', 'caverock', 'caverock_wall',
            'swamp_rock', 'lavarock_floor', 'lavarock_wall']
for stem in REFSTEMS:
    for e in ENVS:
        for d in (f'blocks/{e}', f'props/{e}', f'blocks/{e}/floors', f'blocks/{e}/walls',
                  f'blocks/{e}/borders', f'blocks/{e}/rocks', f'modules/{e}/dungeon_tiles'):
            for c in CATS + AXES['shape'] + ['']:
                for sz in ('', '_2c', '_4c', '_8c', '_4c2', '_16c'):
                    base = f'{stem}_{c}' if c else stem
                    add(f'{d}/{base}{sz}')
                    add(f'{d}/{stem}{sz}')

print('\n'.join(sorted(out)))
sys.stderr.write(f'candidates: {len(out):,}\n')
