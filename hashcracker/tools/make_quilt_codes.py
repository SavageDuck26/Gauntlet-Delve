#!/usr/bin/env python3
"""
The *legal* quilt cell codes, enumerated from the game's own grammar (#44).

Every resolved quilt cell group follows one rule (verified: 29/29 distinct
groups, 0 exceptions):

    x^a  s^b  x^c        s in {e,i,o}, b >= 1        (or just x^L)

- `x` is solid, `e` an open edge, `i` an entrance, `o` an exit - hence
`xox`, `iix`, `eee`, `oox`, `xxi`, `xxxxx` and never e.g. `exi`.

And each shape has fixed side-length profiles (from the resolved corpus):

    blackbox   (1,1,1,1)
    straight   (1,1,1,1) (1,2,1,2) (2,1,2,1)
    turn       (1,1,1,1) (1,2,1,2)
    smallroom  (1,1,1,1) (2,2,2,2)
    mediumroom (3,2,3,2) (3,3,3,3)
    largeroom  (3,3,3,3)
    encounter  (3,2,3,2) (3,3,3,3)
    saferoom   (3,2,3,2)
    entrance   (2,2,2,2) (3,2,3,2) (3,5,3,5)
    exit       (2,2,2,2) (2,3,2,3) (3,2,3,2) (3,5,3,5)

so crossing the two gives the *complete* plausible code set per shape (~2.2 M
`<shape>__<cells>` pairs in total).  The earlier quilt sweep used only the 42
resolved codes plus one-character neighbours, which is why two-character
differences were invisible.

    python3 tools/make_quilt_codes.py [--out data/vocab/qcodes]
"""
import argparse
import csv
import itertools
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

PROFILES = {
    "blackbox": [(1, 1, 1, 1)],
    "straight": [(1, 1, 1, 1), (1, 2, 1, 2), (2, 1, 2, 1)],
    "turn": [(1, 1, 1, 1), (1, 2, 1, 2)],
    "smallroom": [(1, 1, 1, 1), (2, 2, 2, 2)],
    "mediumroom": [(3, 2, 3, 2), (3, 3, 3, 3)],
    "largeroom": [(3, 3, 3, 3)],
    "encounter": [(3, 2, 3, 2), (3, 3, 3, 3)],
    "saferoom": [(3, 2, 3, 2)],
    "entrance": [(2, 2, 2, 2), (3, 2, 3, 2), (3, 5, 3, 5)],
    "exit": [(2, 2, 2, 2), (2, 3, 2, 3), (3, 2, 3, 2), (3, 5, 3, 5)],
}


def groups_of_length(L):
    """Every legal cell group of side length L."""
    out = {"x" * L}
    for a in range(L + 1):
        b = L - a
        c = 0
        if b < 1:
            continue
        for s in "eio":
            out.add("x" * a + s * b)
    for b in range(1, L + 1):
        for a in range(L - b + 1):
            c = L - b - a
            for s in "eio":
                out.add("x" * a + s * b + "x" * c)
    return sorted(out)


CACHE = {}


def g(L):
    if L not in CACHE:
        CACHE[L] = groups_of_length(L)
    return CACHE[L]


def all_codes():
    pairs = set()
    for shape, profs in PROFILES.items():
        for prof in profs:
            for combo in itertools.product(*(g(L) for L in prof)):
                pairs.add(f"{shape}__{'_'.join(combo)}")
    return pairs


def known_names():
    names = {r["name"] for r in
             csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace"))
             if r.get("name")}
    if OVERLAY.exists():
        names |= set(json.loads(OVERLAY.read_text()).values())
    return sorted(n for n in names if n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "qcodes"))
    ap.add_argument("--mods", type=int, default=400,
                    help="cap on the generated mod vocabulary per environment")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    pairs = all_codes()
    # sanity: every code we already hold must be in here
    obs = set()
    QU = re.compile(r"_quilt_([a-z]+)__([a-z_]+)__")
    for n in known_names():
        m = QU.search(n)
        if m:
            obs.add(f"{m.group(1)}__{m.group(2)}")
    missing = sorted(obs - pairs)

    nn = [f"{i:02d}" for i in range(1, 13)] + ["start", "end", str(1), str(2), str(3)]
    subs = ["base", "encounters", "entrances", "exits", "saferooms"]
    envs = ["caves", "crypt", "lava"]

    mods = {}
    for env in envs:
        seen = set()
        toks = set()
        for n in known_names():
            if f"d01_{env}/quilts/" not in n:
                continue
            tail = n.rsplit("__", 1)[-1]
            parts = tail.split("_")[1:]
            if parts:
                seen.add("_".join(parts))
                toks |= {p for p in parts if not p.isdigit()}
        generated = set(seen) | set(toks)
        generated |= {f"{a}_{b}" for a in sorted(toks) for b in sorted(toks)}
        generated |= {f"{m}_{k}" for m in seen for k in nn[:12]}
        mods[env] = sorted(seen | set(sorted(generated)[:args.mods]))

    # the *complete* token n-gram space (1-3 tokens): the mod tail is a short
    # sequence of the game's own mod words, and three-token tails exist
    # (`bridge_fancy_02`, `sarcophagus_chain`), so enumerate them exhaustively
    all_toks = set()
    for env in envs:
        for n in known_names():
            if f"d01_{env}/quilts/" not in n:
                continue
            all_toks |= {p for p in n.rsplit("__", 1)[-1].split("_")[1:]
                         if not p.isdigit()}
    tk = sorted(all_toks)
    full = set(tk) | {p for p in all_toks if p}
    full |= {f"{a}_{b}" for a in tk for b in tk}
    full |= {f"{a}_{b}_{c}" for a in tk for b in tk for c in tk}
    for env in envs:
        full_e = set(full)
        for n in known_names():
            if f"d01_{env}/quilts/" in n:
                tail = n.rsplit("__", 1)[-1].split("_")[1:]
                if tail:
                    full_e.add("_".join(tail))
                    full_e |= {f"{'_'.join(tail)}_{k}" for k in nn[:12]}
        mods[env + "_full"] = sorted(full_e)

    def w(name, vals):
        (out / name).write_text("\n".join(vals) + ("\n" if vals else ""))

    w("pair.txt", sorted(pairs))
    # per shape too, so the big (prop-derived) mod vocabulary can be crossed
    # with a whole shape's code space instead of all 2.17 M pairs at once
    for shape in PROFILES:
        w(f"codes_{shape}.txt", sorted(p for p in pairs if p.startswith(shape + "__")))
    w("nn.txt", sorted(set(nn)))
    w("sub.txt", subs)
    w("env.txt", envs)
    for env, vals in mods.items():
        w(f"mod_{env}.txt", vals)
    print(f"legal <shape>__<cells> pairs : {len(pairs):,}")
    print(f"observed codes inside that set: {len(obs) - len(missing)}/{len(obs)}"
          f"  {'OK' if not missing else 'MISSING ' + str(missing[:5])}")
    for env in envs:
        print(f"  mods {env:6s} {len(mods[env]):>5}")


if __name__ == "__main__":
    main()
