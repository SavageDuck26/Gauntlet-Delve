#!/usr/bin/env python3
"""
Effect transplant: name an unknown resource from its closest known twin.

Resource bodies of a family are near-copies of each other - the same emitter at
a different colour, the same spawner for another creature.  So when a name is
missing, the *body* usually tells you which known resource to copy the name from,
and only one or two tokens differ:

    target (unresolved, 5820 B)  ~=  effects/gam_spawner_crypt_spawn_mummy
    -> effects/gam_spawner_lava_spawn_demon            (found, size-matched shape)
    target (unresolved, 6384 B)  ==  effects/cha_demon_heavy_super_nova (99.6%)
    target (unresolved, 5332 B)  ~=  ..._super_nova_chargeup           (94.6%)

Method, per unknown resource:
  1. find the nearest known body of the same type (byte similarity, size-window)
  2. take that resource's NAME as the shape
  3. substitute one - then two - tokens of the shape from the family vocabulary
     (every token used anywhere in that namespace, plus characters/units/stems)
  4. a candidate is a hit iff murmur64A(candidate) == the target hash

    python3 generators/effect_transplant.py --bundle <contents/<bundle-id>> \
        [--type particles] [--top 5] [--out work/transplant.tsv]

The bundle file is the depot `contents/<bundle-id>` one (`<bundle-id>` =
murmur64A of the package path).  Hits are printed and, with `--out`, written as
TSV lines ready to append to `matches.tsv`.
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
DIG = REPO / "Data"
sys.path.insert(0, str(DIG))
sys.path.insert(0, str(HC.parent / "scripts"))   # bundle_tools / list_game_bundles live here
import list_game_bundles as L          # noqa: E402
from bundle_tools import murmur_hash64  # noqa: E402

CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"


def load_names():
    named = {}
    if CATALOGUE.exists():
        for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                               errors="replace")):
            if r.get("name"):
                named[int(r["name_hash"], 16)] = (r["name"], r["type"])
    if OVERLAY.exists():
        for h, n in json.loads(OVERLAY.read_text()).items():
            named.setdefault(int(h, 16), (n, "?"))
    return named


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--type", default="particles")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default=None)
    ap.add_argument("--vocab", default=None,
                    help="extra vocabulary file (one token per line)")
    args = ap.parse_args()

    named = load_names()
    _sig, _u, data = L.decompress_bundle(pathlib.Path(args.bundle).read_bytes())
    _count, toc = L.parse_toc(data)
    entries, _end, _ok = L.parse_resources(data, toc)
    tmap = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("type_hash"):
            tmap[int(r["type_hash"], 16)] = r["type"]
    want = next((h for h, n in tmap.items() if n == args.type), None)

    bodies = {}
    for e in entries:
        if want is None or e.get("type_hash") == want:
            bodies.setdefault(e["name_hash"],
                              data[e["body_start"]:e["body_start"] + e["body_size"]])
    known = {h: named[h][0] for h in bodies if h in named}
    unknown = [h for h in bodies if h not in named]
    print(f"{args.type}: {len(bodies)} in bundle, {len(known)} named, "
          f"{len(unknown)} unknown")

    vocab = collections.Counter()
    for n in known.values():
        for t in n.replace("/", "_").split("_"):
            if len(t) > 1:
                vocab[t] += 1
    if args.vocab:
        for line in pathlib.Path(args.vocab).read_text().split():
            vocab[line.strip()] += 1
    V = sorted(vocab)
    print(f"vocabulary: {len(V)} tokens")

    found = {}
    for h in unknown:
        a = bodies[h]
        near = sorted(
            ((sum(1 for i in range(min(len(a), len(b))) if a[i] == b[i])
              / max(len(a), len(b)), len(b), n)
             for b, n in ((bodies[p], known[p]) for p in known
                          if abs(len(bodies[p]) - len(a)) < 512)),
            reverse=True)[:args.top]
        for sim, _l, shape in near:
            toks = shape.split("_")
            for i in range(1, len(toks)):
                for v in V:
                    c = "_".join(toks[:i] + [v] + toks[i + 1:])
                    if murmur_hash64(c) == h:
                        found[h] = (c, sim, shape)
                        break
                if h in found:
                    break
                for j in range(i + 1, len(toks)):
                    for v in V:
                        for w in V:
                            c = "_".join(toks[:i] + [v] + toks[i + 1:j]
                                         + [w] + toks[j + 1:])
                            if murmur_hash64(c) == h:
                                found[h] = (c, sim, shape)
                                break
                        if h in found:
                            break
                    if h in found:
                        break
            if h in found:
                break
        if h in found:
            c, sim, shape = found[h]
            print(f"  NAMED {h:016x}  {c}\n        (from {shape}, {100*sim:.1f}% body match)")
        else:
            sim, _l, shape = near[0] if near else (0, 0, "-")
            print(f"  ????  {h:016x}  nearest {shape} ({100*sim:.1f}%) - not named")

    if args.out and found:
        pathlib.Path(args.out).write_text(
            "".join(f"{h:016x}\t{c}\n" for h, (c, _, _) in found.items()))
        print(f"wrote {len(found)} name(s) to {args.out}")


if __name__ == "__main__":
    main()
