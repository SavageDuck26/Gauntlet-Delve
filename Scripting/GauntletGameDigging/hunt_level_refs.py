#!/usr/bin/env python3
"""
Classify unresolved `.level` resources by what they reference (section 43).

The catalogue's `index` column is hash-shuffled, so TOC neighbours say nothing.
A resource's body, however, does: a `.level` carries the 64-bit hashes of the
materials, units and sub-levels it uses.  Reading the body out of the depot and
matching every 8-byte window against the bundle's own TOC (the technique from
`hunt_unit_textures.py`) therefore tells us what family an unnamed level belongs
to - a tile references one rock material, a quilt room references a room's worth
of props, a colosseum references its arenas - and which vocabulary it uses.

    python3 hunt_level_refs.py [--limit N] [--depot DIR] [--all-types]
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import list_game_bundles as L                      # noqa: E402
from bundle_tools import murmur_hash64             # noqa: E402
from hunt_unit_textures import (CATALOGUE, OVERLAY, bundle_toc,  # noqa: E402
                                find_body, known_resources, type_map)

DEFAULT_DEPOT = REPO / "Gauntlet-PreSlayer-2015-08-11" / "depot_258972" / "contents"


def unresolved_rows(level_only=True):
    ov = set(json.loads(OVERLAY.read_text())) if OVERLAY.exists() else set()
    rows = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("name") or r.get("name_hash") in ov:
            continue
        if level_only and r.get("type") != "level":
            continue
        rows.append(r)
    return rows


def signature(body, hashes):
    """The set of resources a body references (its 8-byte windows ∩ the TOC)."""
    out = set()
    for off in range(0, max(0, len(body) - 7)):
        v = int.from_bytes(body[off:off + 8], "little")
        if v in hashes:
            out.add(v)
    return out


def known_level_hashes(bundle):
    """name hashes of *resolved* levels the catalogue places in this bundle."""
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("bundle") != bundle or r.get("type") != "level":
            continue
        name = r.get("name") or ov.get(r.get("name_hash"))
        if name:
            out[int(r["name_hash"], 16)] = name
    return out


QUILT_FULL = re.compile(
    r"^(?:modules/d01_(?P<env>[a-z_]+)/(?:(?P<sub>[a-z0-9/]+)/)?)?"
    r"(?P<base>[a-z0-9_]+)_quilt_(?P<shape>[a-z]+)__(?P<cells>[a-z_]+)__"
    r"(?P<num>[a-z0-9]+)(?:_(?P<mod>.+))?$")


def quilt_parts(name):
    m = QUILT_FULL.match(name)
    return m.groupdict() if m else None


def observed_quilt_index():
    """env -> (pairs by shape, mods, subs, numbers, env dirs) from resolved names."""
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    pairs, mods, subs, nums = (collections.defaultdict(set) for _ in range(4))
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("type") != "level" or not r.get("name"):
            continue
        p = quilt_parts(r["name"])
        if not p or not p["env"]:
            continue
        env, shape = p["env"], p["shape"]
        pairs[(env, shape)].add(f"{shape}__{p['cells']}")
        pairs[(env, None)].add(f"{shape}__{p['cells']}")
        if p["mod"]:
            mods[env].update(t for t in p["mod"].split("_") if not t.isdigit())
        if p["sub"]:
            subs[env].add(p["sub"])
        nums[env].add(p["num"])
    return pairs, mods, subs, nums


def token_hints(prop_names):
    """Mod tokens suggested by the props this target has and its twin lacks."""
    out = set()
    for n in prop_names:
        leaf = n.rsplit("/", 1)[-1]
        for t in re.split(r"[^a-z]+", leaf):
            if len(t) > 2 and not t.isdigit() and t not in ("var", "wall",
                                                            "bend", "props"):
                out.add(t)
                if t.endswith("s"):
                    out.add(t[:-1])
                else:
                    out.add(t + "s")
    return out


SIZE_INDEX = None


def size_seeds(body_size, env=None, window=96, top=3):
    """
    Resolved level names whose body size is closest to this one.

    A level body's size is very nearly a function of its name, so the exact-size
    neighbours are the structural twins: for target 1 the 4,880 B neighbours are
    `crypt_quilt_turn__*__02`, which the *reference* twin (a `straight`) missed.
    """
    global SIZE_INDEX
    if SIZE_INDEX is None:
        ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
        rows = []
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if r.get("type") != "level":
                continue
            n = r.get("name") or ov.get(r.get("name_hash"))
            if n:
                rows.append((int(r["body_size"]), n))
        rows.sort()
        SIZE_INDEX = rows
    try:
        sz = int(body_size)
    except (TypeError, ValueError):
        return []
    import bisect
    i = bisect.bisect_left(SIZE_INDEX, (sz, ""))
    cands = collections.defaultdict(list)
    for j in range(max(0, i - 16), min(len(SIZE_INDEX), i + 16)):
        d = abs(SIZE_INDEX[j][0] - sz)
        if d <= window:
            n = SIZE_INDEX[j][1]
            if env is None or f"d01_{env}" in n:
                cands[d].append(n)
    out = []
    for d in sorted(cands):
        out.extend(cands[d])
        if len(out) >= top:
            break
    return out[:top]


def guess_from_seed(target_hash_str, twin_name, hints, index, extra_nums):
    p = quilt_parts(twin_name)
    if not p or not p["env"]:
        return []
    pairs, mods, subs, nums = index
    env = p["env"]
    token_pool = sorted(hints | mods.get(env, set()) | {"chains", "shield",
                                                       "shields", "chain"})
    token_pool = token_pool[:60]
    mod_cands = set()
    for t in token_pool:
        mod_cands.add(t)
        for u in token_pool:
            mod_cands.add(f"{t}_{u}")
    if p["mod"]:
        for t in token_pool:
            mod_cands.add(f"{p['mod']}_{t}")
            mod_cands.add(f"{t}_{p['mod']}")
    mod_cands = sorted(mod_cands)[:400]
    num_cands = sorted({p["num"]} | set(extra_nums))
    sub_cands = sorted({p["sub"]} | subs.get(env, set()) | {"base", "encounters",
                                                            "entrances", "exits",
                                                            "saferooms"})
    sub_cands = [s for s in sub_cands if s]
    pair_cands = sorted(pairs.get((env, p["shape"]), set()))[:80]
    if not pair_cands and p["cells"]:
        pair_cands = [f"{p['shape']}__{p['cells']}"]

    cands = []
    for sub in sub_cands:
        head = f"modules/d01_{env}/quilts/{sub}/{env}_quilt_"
        for num in num_cands:
            for mod in mod_cands:
                cands.append(f"{head}{p['shape']}__{p['cells']}__{num}_{mod}")
            cands.append(f"{head}{p['shape']}__{p['cells']}__{num}")
            for pair in pair_cands:
                for mod in mod_cands[:24]:
                    cands.append(f"{head}{pair}__{num}_{mod}")
                cands.append(f"{head}{pair}__{num}")
    # bare form (no sub directory)
    for num in num_cands:
        for mod in mod_cands[:24]:
            cands.append(f"modules/d01_{env}/{env}_quilt_{p['shape']}__"
                         f"{p['cells']}__{num}_{mod}")
    want = int(target_hash_str, 16)
    out = []
    for c in cands:
        if murmur_hash64(c) == want:
            out.append(c)
    return out


def twins(data, toc_hashes, target_sig, known_sigs, top=5):
    scored = []
    for h, (name, sig) in known_sigs.items():
        if not sig or not target_sig:
            continue
        inter = len(target_sig & sig)
        if inter:
            scored.append((inter / len(target_sig | sig), inter, name, sig))
    scored.sort(reverse=True)
    # the caller only wants (sim, inter, name); keep sigs for --diff
    return scored[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depot", default=str(DEFAULT_DEPOT))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all-types", action="store_true",
                    help="include unresolved non-level resources")
    ap.add_argument("--depth", type=int, default=8,
                    help="how many referenced names to show per target")
    ap.add_argument("--twin", action="store_true",
                    help="find the nearest *resolved* level by reference-set similarity")
    ap.add_argument("--diff", action="store_true",
                    help="also show which references differ from the best twin")
    ap.add_argument("--guess", action="store_true",
                    help="derive mod tokens from the props the target has and its "
                         "twin lacks, then hash the implied quilt names")
    ap.add_argument("--write", action="store_true",
                    help="append verified guesses to matches.tsv")
    args = ap.parse_args()
    depot = pathlib.Path(args.depot)
    index = observed_quilt_index()
    extra_nums = [f"{i:02d}" for i in range(1, 25)] + ["start", "end"]
    guessed = []

    known = known_resources()
    tmap = type_map()
    rows = unresolved_rows(not args.all_types)
    if args.limit:
        rows = rows[:args.limit]
    by_bundle = collections.defaultdict(list)
    for r in rows:
        by_bundle[r["bundle"]].append(r)
    print(f"unresolved rows {len(rows)} in {len(by_bundle)} bundles  depot {depot}")

    fam_count = collections.Counter()
    for bundle, rs in sorted(by_bundle.items()):
        path = depot / bundle
        if not path.exists():
            print(f"  !! bundle {bundle} not in depot")
            continue
        packed = path.read_bytes()
        _sig, _unzipped, data = L.decompress_bundle(packed)
        toc = bundle_toc(data, tmap)
        hashes = set(toc)
        klh = known_level_hashes(bundle)
        known_sigs = {}
        if args.twin or args.diff or args.guess:
            for h, name in klh.items():
                _i, _e, b = find_body(data, h)
                if b:
                    known_sigs[h] = (name, signature(b, hashes))
        print(f"\n=== bundle {bundle}  ({len(rs)} targets, toc {len(toc)} entries, "
              f"{len(known_sigs)} resolved level bodies)")
        for r in rs:
            h = int(r["name_hash"], 16)
            _i, _e, body = find_body(data, h)
            if body is None:
                print(f"  {r['name_hash']}  body not found")
                continue
            sig = signature(body, hashes)
            refs = collections.Counter()
            for off in range(0, max(0, len(body) - 7)):
                v = int.from_bytes(body[off:off + 8], "little")
                if v in hashes:
                    refs[v] += 1
            named = [(n, t) for v in refs for n, t in [known.get(v, (None, None))] if n]
            fams = collections.Counter()
            for n, t in named:
                parts = n.split("/")
                if t == "material" or n.startswith("materials/"):
                    fams["material:" + "/".join(parts[:3])] += 1
                elif t == "level":
                    fams["level:" + ("_".join(parts[-1].split("_")[:3]))] += 1
                elif t[0] if t else "":
                    fams[t] += 1
            top = fams.most_common(3)
            fam_count[top[0][0] if top else "none"] += 1
            print(f"  {r['name_hash']}  {r['body_size']:>7}B  refs {len(sig):>3} "
                  f"named {len(named):>3}  {' | '.join(f'{k}x{v}' for k, v in top)}")
            ranked = []
            if args.twin or args.diff or args.guess:
                ranked = twins(data, hashes, sig, known_sigs)
            if args.twin:
                for sim, inter, name, _sig2 in ranked:
                    print(f"        twin {sim:5.2f} ({inter:>3} shared)  {name}")
            if (args.diff or args.guess) and ranked:
                alt = ranked[0][3]
                only_t = sorted((known.get(v, (f"<{v:016x}>",))[0] or "")
                                for v in sig - alt)
                only_k = sorted((known.get(v, (f"<{v:016x}>",))[0] or "")
                                for v in alt - sig)
                if args.diff:
                    print(f"        only-target: {'; '.join(x for x in only_t if x)[:220]}")
                    print(f"        only-twin  : {'; '.join(x for x in only_k if x)[:220]}")
                if args.guess:
                    hints = token_hints([x for x in only_t if x])
                    env = (r.get("package_path") or "").split("/")[1:2]
                    env = env[0].replace("d01_", "") if env else None
                    seeds = [ranked[0][2]] + size_seeds(r["body_size"], env)
                    hits = []
                    for seed in dict.fromkeys(seeds):
                        hits += guess_from_seed(r["name_hash"], seed, hints, index,
                                                extra_nums)
                    for nm in sorted(set(hits)):
                        print(f"        *** GUESS {r['name_hash']} -> {nm}")
                        guessed.append((r["name_hash"], nm))
            for n, _t in named[:args.depth]:
                print(f"        {n}")
    print("\nfamily histogram:", fam_count.most_common(12))
    if guessed:
        print(f"\nverified guesses: {len(guessed)}")
        for h, nm in guessed:
            print(f"  {h}  {nm}")
        if args.write:
            mf = HERE.parent / "hashcracker" / "matches.tsv"
            with mf.open("a") as fh:
                for h, nm in guessed:
                    fh.write(f"{h}\t{nm}\n")
            print(f"appended {len(guessed)} to {mf}")


if __name__ == "__main__":
    main()
