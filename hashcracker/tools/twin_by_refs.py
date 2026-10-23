#!/usr/bin/env python3
"""
Name an unresolved resource from its nearest resolved twin (#49).

Two fingerprints locate a twin - the resolved resource of the same type that an
unnamed one is most likely a *derived* variant of:

  * size + bundle: a body size is nearly a function of the name (#43), so the
    resolved resources adjacent to it in the same bundle are its family.  Cheap:
    needs only the catalogue.
  * reference graph: a resource's set of referrers is nearly unique, so the twin
    is the resolved resource whose referrers overlap most (`hunt_ref_graph.py`).

Then the missing name is a small edit of the twin:

    <twin dir>/<twin leaf>                      (other members of the dir)
    <twin dir>/<leaf minus a token>[_<suffix>]
    <twin dir>/<leaf><number>[_<suffix>]
    <twin dir>/<leaf with a token swapped>

    python3 tools/twin_by_refs.py [--graph] [--write] [-v]
"""
import argparse
import collections
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
GRAPH = HC / "work" / "ref_graph.json"
sys.path.insert(0, str(DIG))
sys.path.insert(0, str(HC.parent / "scripts"))   # bundle_tools / list_game_bundles live here
from bundle_tools import murmur_hash64                              # noqa: E402

SUF = ["diff", "norm", "spec", "normal", "mask", "glow", "icon", "color",
       "alpha", "over", "locked", "active", "marker", "trail", "hit",
       "windup", "enter", "loop", "start", "end", "01", "02", "03"]


def load():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    named = collections.defaultdict(list)          # type -> [(bundle, size, name)]
    unresolved = collections.defaultdict(dict)     # type -> {hash: (bundle, size)}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        h, t = r["name_hash"].lower(), r.get("type", "?")
        n = r.get("name") or ov.get(h)
        if n:
            named[t].append((r.get("bundle", ""), int(r["body_size"] or 0), n))
        else:
            unresolved[t][h] = (r.get("bundle", ""), int(r["body_size"] or 0))
    return named, unresolved


def size_twins(named, unresolved, max_delta, top):
    out = {}
    for t, hs in unresolved.items():
        pool = named.get(t) or []
        if not pool:
            continue
        for h, (bundle, size) in hs.items():
            near = sorted((abs(sz - size), n) for b, sz, n in pool if b == bundle)
            picked = [n for d, n in near[:top] if d <= max_delta]
            if not picked:
                near = sorted((abs(sz - size), n) for _b, sz, n in pool)
                picked = [n for d, n in near[:top] if d <= max_delta]
            if picked:
                out[h] = picked
    return out


def graph_twins(unresolved, min_sim):
    graph = json.loads(GRAPH.read_text())
    referrers = collections.defaultdict(set)
    for src, dsts in graph.items():
        for d in dsts:
            referrers[d].add(src)
    named_here = {n: s for n, s in referrers.items() if s}
    out = {}
    for t, hs in unresolved.items():
        path = HC / "work" / f"refs_{t}.json"
        if not path.exists():
            continue
        refs = json.loads(path.read_text())
        groups = collections.defaultdict(list)
        for h in hs:
            if h in refs:
                groups[frozenset(refs[h])].append(h)
        for sig, group in groups.items():
            scored = sorted(((len(sig & s) / len(sig | s), n)
                             for n, s in named_here.items() if sig & s),
                            reverse=True)
            twins = [n for sim, n in scored[:3] if sim >= min_sim]
            if twins:
                for h in group:
                    out[h] = twins
    return out


VARIANT_TOKENS = ["caves", "crypt", "lava", "hub", "sand", "temple", "demons",
                  "spiders", "skeleton", "statues", "juggernauts", "cultists",
                  "priest", "priests", "queen", "lobbers", "spawner", "rocks",
                  "mixed", "endless", "blue", "red", "green", "gold", "silver",
                  "bronze", "black", "white", "dark", "light", "fire", "ice",
                  "poison", "shadow", "holy", "blood", "normal", "broken",
                  "destroyed", "lit", "unlit", "var01", "var02", "var03",
                  "06", "07", "08", "09", "10", "11", "12", "13", "14", "15"]


def token_edits_candidates(twin, dir_tokens, all_tokens, cap=400):
    """Token-level edits of the twin's leaf: swap/insert/delete one token."""
    d, _, leaf = twin.rpartition("/")
    dd = d + "/" if d else ""
    toks = leaf.split("_")
    pool = VARIANT_TOKENS + list(dir_tokens)[:200] + list(all_tokens)[:200]
    out = set()
    for i in range(len(toks)):
        for t in pool[:cap]:
            if t != toks[i]:
                out.add(f"{dd}{'_'.join(toks[:i] + [t] + toks[i + 1:])}")   # swap
        out.add(f"{dd}{'_'.join(toks[:i] + toks[i + 1:])}")                 # delete
        for t in pool[:cap]:
            out.add(f"{dd}{'_'.join(toks[:i] + [t] + toks[i:])}")           # insert
        if i + 1 < len(toks) and toks[i] != toks[i + 1]:                    # swap pair
            t2 = list(toks)
            t2[i], t2[i + 1] = t2[i + 1], t2[i]
            out.add(f"{dd}{'_'.join(t2)}")
    return out


def candidates_for(twin, leaves_by_dir, max_tokens):
    d, _, leaf = twin.rpartition("/")
    dd = d + "/" if d else ""
    toks = leaf.split("_")
    stems = {leaf}
    for k in (1, 2):
        if len(toks) > k:
            stems.add("_".join(toks[:-k]))
            stems.add("_".join(toks[-k:]))
    out = set()
    for st in stems:
        out.add(f"{dd}{st}")
        for s in SUF:
            out.add(f"{dd}{st}_{s}")
        for k in range(1, 13):
            out.add(f"{dd}{st}_{k:02d}")
            out.add(f"{dd}{st}{k}")
    for L in list(leaves_by_dir.get(dd, []))[:max_tokens]:
        out.add(f"{dd}{L}")
        if toks:
            out.add(f"{dd}{L}_{toks[-1]}")
            out.add(f"{dd}{toks[0]}_{L}")
            for s in SUF[:8]:
                out.add(f"{dd}{L}_{s}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", action="store_true",
                    help="use the reference graph instead of size+bundle")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--min-sim", type=float, default=0.34)
    ap.add_argument("--max-delta", type=int, default=48)
    ap.add_argument("--max-tokens", type=int, default=40)
    args = ap.parse_args()

    named, unresolved = load()
    print("unresolved:", {t: len(v) for t, v in unresolved.items() if v})
    twins = (graph_twins(unresolved, args.min_sim) if args.graph
             else size_twins(named, unresolved, args.max_delta, 3))
    print(f"targets with a twin: {len(twins):,}")

    leaves_by_dir = collections.defaultdict(set)
    tokens_by_dir = collections.defaultdict(set)
    tokens_by_type = collections.defaultdict(set)
    for t, ns in named.items():
        for _b, _s, n in ns:
            if "/" in n:
                dd = n.rsplit("/", 1)[0] + "/"
                leaves_by_dir[dd].add(n.rsplit("/", 1)[-1])
                tokens_by_dir[dd] |= {x for x in n.rsplit("/", 1)[-1].split("_")
                                      if len(x) > 1}
            tokens_by_type[t] |= {x for x in n.split("_") if len(x) > 1}

    type_of = {}
    for t, d in unresolved.items():
        for h in d:
            type_of[h] = t

    hits, tested, seen = [], 0, set()
    for h, tws in twins.items():
        cands = set()
        t = type_of.get(h, "?")
        for tw in tws:
            dd = (tw.rsplit("/", 1)[0] + "/") if "/" in tw else ""
            cands |= candidates_for(tw, leaves_by_dir, args.max_tokens)
            cands |= token_edits_candidates(tw, tokens_by_dir.get(dd, set()),
                                            tokens_by_type.get(t, set()))
        for c in cands:
            if c in seen:
                continue
            seen.add(c)
            tested += 1
            if f"{murmur_hash64(c):016x}" == h:
                hits.append((h, c, tws[0]))
    hits = sorted(set(hits))
    print(f"candidates tested {tested:,}  MATCHES {len(hits)}")
    by = collections.Counter()
    for h, c, tw in hits:
        for t, d in unresolved.items():
            if h in d:
                by[t] += 1
        print(f"  {h}  {c}   (twin {tw})")
    if by:
        print("by type:", dict(by))
    if args.write and hits:
        mf = HC.parent / "Data" / "matches.tsv"
        with mf.open("a") as fh:
            for h, c, _t in hits:
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
