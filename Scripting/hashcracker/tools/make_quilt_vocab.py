#!/usr/bin/env python3
"""
Shape-conditioned vocabularies for the quilt family.

A quilt name is

    modules/d01_<env>/<sub>/<env>_quilt_<shape>__<u>_<r>_<d>_<l>__<nn>[_<mods>]

and the <shape> does not merely label the piece - it *constrains* both the cell
rows and their side lengths.  Measured over the resolved names:

    largeroom    9 codes   sides only (3,3,3,3)
    mediumroom   9         (3,2,3,2) and (3,3,3,3)
    turn         6         (1,1,1,1) and (1,2,1,2)
    straight     4         (1,1,1,1), (2,1,2,1), (1,2,1,2)
    smallroom    5         (2,2,2,2), (1,1,1,1)
    entrance 3 / exit 4 / encounter 2 / saferoom 1 / blackbox 1

So the unknown quilts are reachable by *expanding each shape's own repertoire* -
its group alphabet per side length (plus one-character neighbours) under its own
side-length profile - instead of guessing cell codes globally (4^5 per side,
which is what made the earlier exhaustive tiers unusable when crossed with mods)
or re-using only the 42 codes we have.

    python3 tools/make_quilt_vocab.py [--out data/vocab/quilt] [--cap N]

Writes, for `hc.sh crack --pattern 'modules/d01_%e/%s/%e_quilt_%p__%n'` style use:
    env.txt     caves crypt lava
    sub.txt     quilts/base, quilts/encounters, ... (as seen, plus bare "")
    pair.txt    `<shape>__<cells>` - ONE slot, so shape and cells can never
                mismatch (this is the whole trick)
    nn.txt      01..24 plus start/end as seen
    mod_<env>.txt  that environment's mod vocabulary (observed + themes +
                creature groups + `<mod>_<nn>_<part>` forms)
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
CELLS = "xeio"
NN = [f"{i:02d}" for i in range(1, 25)]
PARTS = [str(i) for i in range(1, 9)]
SECOND = ["sand", "slaves", "skeleton", "temple", "fancy", "mixed", "lobbers",
          "spawner", "queen", "endless", "rocks", "statues", "juggernauts",
          "cultists", "demons", "spiders"]

QUILT = re.compile(r"^modules/d01_([a-z_]+)/((?:[a-z0-9]+/)*)"
                   r"([a-z0-9_]+)_quilt_([a-z]+)__([a-z_]+)__(.+)$")


def known_names():
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return sorted(n for n in names if n)


def prop_tokens():
    """
    Mod tokens mined from the game's prop vocabulary.

    A quilt's mod tail names what it contains (`..._05_gold`, `..._02_spiketraps`)
    and the resources it then references are `props/.../spiketraps_*`.  So the
    prop/gameobject catalogue is the *authoritative* mod vocabulary - crucially
    including tokens like `chains` and `shield` that appear only in quilts we
    have not named yet, which is exactly what recombining resolved names missed.
    """
    names = set()
    if CATALOGUE.exists():
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if r.get("name"):
                names.add(r["name"])
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    out = set()
    for n in names:
        if not (n.startswith(("props/", "gameobjects/", "blocks/"))):
            continue
        for t in re.split(r"[^a-z]+", n.rsplit("/", 1)[-1]):
            if len(t) > 2 and t not in ("var", "props", "gameobjects"):
                out.add(t)
    return out


def prop_phrases(max_len=3):
    """
    Mod candidates as *contiguous phrases* from a prop name.

    `props/d01_common/chains_wall_bend_2c_01` yields `chains`, `chains_wall`,
    `chains_wall_bend`, `wall_bend_2c`, ... - a quilt mod names what it contains,
    so the phrase the prop name itself uses is the strongest candidate.  This is
    what single-token mining missed.
    """
    names = set()
    if CATALOGUE.exists():
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if r.get("name"):
                names.add(r["name"])
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    out = set()
    for n in names:
        if not (n.startswith(("props/", "gameobjects/", "blocks/"))):
            continue
        toks = [t for t in re.split(r"[^a-z0-9]+", n.rsplit("/", 1)[-1]) if t]
        toks = [t for t in toks if t not in ("var",)
                and not re.fullmatch(r"\d+", t)]
        for i in range(len(toks)):
            for j in range(i + 1, min(len(toks), i + max_len) + 1):
                out.add("_".join(toks[i:j]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "quilt"))
    ap.add_argument("--full", action="store_true",
                    help="cross every mutated group (8.9M pairs) instead of the targeted repertoire")
    ap.add_argument("--cap", type=int, default=60000,
                    help="max cells codes per shape")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    groups = collections.defaultdict(lambda: collections.defaultdict(set))
    profiles = collections.defaultdict(set)
    envs, subs, nns = set(), set(), set()
    mods = collections.defaultdict(set)
    for n in known_names():
        m = QUILT.match(n)
        if not m:
            continue
        env, sub, _base, shape, cells, tail = m.groups()
        envs.add(env)
        if sub:
            subs.add(sub.rstrip("/"))
        p = cells.split("_")
        if len(p) != 4:
            continue
        profiles[shape].add(tuple(len(x) for x in p))
        for x in p:
            groups[shape][len(x)].add(x)
        t = tail.split("_")
        nns.add(t[0])
        if len(t) > 1:
            mods[env].add("_".join(t[1:]))
            mods[env].add(t[1])

    # expand each shape's repertoire: observed groups + one-character neighbours
    for shape in groups:
        for ln, vals in list(groups[shape].items()):
            mut = set(vals)
            for g in vals:
                for i, ch in enumerate(g):
                    for alt in CELLS:
                        if alt != ch:
                            mut.add(g[:i] + alt + g[i + 1:])
            groups[shape][ln] = mut

    # Each shape's code repertoire, three ways (the middle one is the default):
    #   observed codes  +  one-character neighbours  +  one group swapped for
    #   another observed group of the same length; `--full` instead crosses every
    #   mutated group (8.9 M pairs - a dedicated long run, not a sweep tier).
    obs = collections.defaultdict(set)
    for n in known_names():
        m = QUILT.match(n)
        if m:
            p = m.group(5).split("_")
            if len(p) == 4:
                obs[m.group(4)].add(m.group(5))
    plain = collections.defaultdict(lambda: collections.defaultdict(set))
    for n in known_names():
        m = QUILT.match(n)
        if not m:
            continue
        p = m.group(5).split("_")
        if len(p) == 4:
            for x in p:
                plain[m.group(4)][len(x)].add(x)

    pairs = set()
    for shape in profiles:
        for lu, lr, ld, ll in profiles[shape]:
            lens = (lu, lr, ld, ll)
            for base in obs[shape]:
                b = base.split("_")
                if tuple(len(x) for x in b) != lens:
                    continue
                pairs.add(f"{shape}__{base}")
                for i, g in enumerate(b):                    # one-character
                    for j, ch in enumerate(g):
                        for alt in CELLS:
                            if alt != ch:
                                b2 = list(b)
                                b2[i] = g[:j] + alt + g[j + 1:]
                                pairs.add(f"{shape}__{'_'.join(b2)}")
                    for alt in plain[shape][len(g)]:         # one group swapped
                        if alt != g:
                            b3 = list(b)
                            b3[i] = alt
                            pairs.add(f"{shape}__{'_'.join(b3)}")
                if args.full:                                # everything legal
                    for combo in itertools.product(
                            *[sorted(groups[shape][k]) for k in lens]):
                        pairs.add(f"{shape}__{'_'.join(combo)}")
    if len(pairs) > args.cap * len(profiles):
        pairs = set(sorted(pairs)[:args.cap * len(profiles)])

    all_mod = set().union(*mods.values()) if mods else set()

    def w(name, vals):
        vals = sorted(v for v in vals if v)
        (out / name).write_text("\n".join(vals) + ("\n" if vals else ""))
        print(f"  {name:18s} {len(vals):>7}")

    print("quilt vocabularies:")
    w("env.txt", envs)
    w("sub.txt", subs)
    w("pair.txt", pairs)
    w("pair_seen.txt", {f"{s}__{c}" for s, cs in obs.items() for c in cs})
    w("nn.txt", nns | set(NN) | {"start", "end"})
    for env in sorted(envs):
        w(f"mod_seen_{env}.txt", mods[env])
    # The mod tail of a quilt is a *sequence* of 1-3 tokens drawn from the
    # game's own vocabulary - `gold`, `gold_sand`, `sarcophagus_chain`,
    # `bridge_fancy_02` - so enumerate token n-grams rather than recombining
    # whole observed tails (which is what missed `sarcophagus_chain`).
    toks = sorted({t for m in all_mod for t in m.split("_") if not t.isdigit()})
    props = sorted(prop_tokens())
    generated = set(toks) | set(props)
    generated |= {f"{a}_{b}" for a in toks for b in toks}
    generated |= {f"{t}_{p}" for t in toks for p in props}
    generated |= {f"{p}_{t}" for p in props for t in toks}
    generated |= {f"{a}_{b}_{c}" for a in toks for b in toks[:12]
                  for c in toks[:8]}
    generated = set(sorted(generated)[:40000])
    for env in sorted(envs):
        w(f"mod_{env}.txt",
          mods[env] | set(generated)
          | {f"{m}_{k}" for m in mods[env] for k in NN})
    # a bounded list for crossing with the *whole* shape/cells pair space
    phrases = prop_phrases()
    for env in sorted(envs):
        small = set(mods[env]) | set(toks) | set(props) | phrases
        small |= {f"{t}_{p}" for t in toks for p in props}
        small = set(sorted(small)[:6000])
        w(f"mod_small_{env}.txt", small)
        w(f"mod_tiny_{env}.txt", set(mods[env]) | phrases | set(toks))
    print(f"  tokens         {len(toks)} quilt + {len(props)} prop "
          f"-> {len(generated)} mod forms")

    print(f"shapes {len(profiles)}  pairs {len(pairs)}  "
          f"space(no mods) {len(envs) * (len(subs) + 1) * len(pairs) * (len(nns) + 25):,}")


if __name__ == "__main__":
    main()
