#!/usr/bin/env python3
"""
Apply cross-build rename evidence to unresolved names (FINDINGS.txt §50).

Inputs:
  * `work/renames_<snap>.json` - clean content moves between builds, as
    [old_hash, new_hash] (same body bytes, different name hash => renamed).
  * `work/old_names_<snap>.json` - names of the *old* build, mined from that
    build's own harvest.
  * the current overlay for the new side.

Where both sides are named the pair is a **rename example**; where only the old
side is named and the new hash is unresolved it is a **rename target**.  The
examples give two things to apply to the targets: a token translation table, and
per-example edit scripts (directory change + token insert/delete/replace), each of
which is replayed on the target's old name.

    python3 tools/apply_renames.py [--snap 2015-01] [--write] [-v]
"""
import argparse
import collections
import csv
import difflib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                              # noqa: E402


def name_map():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out, unresolved = {}, set()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        h = r["name_hash"].lower()
        n = r.get("name") or ov.get(h)
        if n:
            out[h] = n
        else:
            unresolved.add(h)
    return out, unresolved


def edit_of(old, new):
    """Directory change plus the token-level ops turning old's leaf into new's."""
    od, _, ol = old.rpartition("/")
    nd, _, nl = new.rpartition("/")
    ops = []
    a, b = ol.split("_"), nl.split("_")
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            ops.append((tag, i1, i2, tuple(a[i1:i2]), tuple(b[j1:j2])))
    return od, nd, ops


def apply_edit(name, edit):
    """Replay an edit script on another name (same dir/token shape)."""
    od, nd, ops = edit
    d, _, leaf = name.rpartition("/")
    toks = leaf.split("_")
    for tag, i1, i2, _old, new in ops:
        if i2 > len(toks):
            return None
        toks = toks[:i1] + list(new) + toks[i2:]
    new_dir = nd if d == od else d
    return (new_dir + "/" if new_dir else "") + "_".join(toks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", default="2015-01")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    names, unresolved = name_map()
    ren = json.loads((HC / "work" / f"renames_{args.snap}.json").read_text())
    old_names = json.loads((HC / "work" / f"old_names_{args.snap}.json").read_text())
    print(f"content moves {len(ren)}  old names known {len(old_names)}  "
          f"new names known {len(names)}")

    examples, targets = [], []
    for oh, nh in ren:
        oname, nname = old_names.get(oh), names.get(nh)
        if oname and nname:
            examples.append((oname, nname))
        elif oname and nh in unresolved:
            targets.append((oname, nh))
    print(f"rename examples {len(examples)}  rename targets {len(targets)}")
    for a, b in examples[:10]:
        print(f"   EXAMPLE {a}  ->  {b}")

    # token translation table from the examples
    trans = collections.Counter()
    for a, b in examples:
        _od, _nd, ops = edit_of(a, b)
        for tag, _i1, _i2, old, new in ops:
            if tag == "replace" and len(old) == len(new) == 1:
                trans[(old[0], new[0])] += 1
    print("top token translations:", trans.most_common(8))

    # The translations are history's own vocabulary map (`wep_` became `cha_`,
    # `bandit` became `soldier`), so they apply to *every* name we hold, not only
    # to the handful of unresolved rename targets.
    old_all = list(old_names.values())
    our_all = list(names.values())
    allnames = sorted(set(old_all) | set(our_all))
    tested0, hits0 = 0, []
    seen0 = set()
    for nm in allnames:
        d, _, leaf = nm.rpartition("/")
        dd = d + "/" if d else ""
        toks = leaf.split("_")
        cands = set()
        for (a, b), _c in trans.most_common(80):
            for i, t in enumerate(toks):
                if t == a:
                    cands.add(f"{dd}{'_'.join(toks[:i] + [b] + toks[i + 1:])}")
                if t == b:
                    cands.add(f"{dd}{'_'.join(toks[:i] + [a] + toks[i + 1:])}")
        for i in range(len(toks) - 1):          # adjacent token reorder
            if toks[i] != toks[i + 1]:
                t2 = list(toks)
                t2[i], t2[i + 1] = t2[i + 1], t2[i]
                cands.add(f"{dd}{'_'.join(t2)}")
        for c in cands:
            if c in seen0:
                continue
            seen0.add(c)
            tested0 += 1
            h = f"{murmur_hash64(c):016x}"
            if h in unresolved:
                hits0.append((h, c))
    hits0 = sorted(set(hits0))
    print(f"history-translation candidates {tested0:,}  MATCHES {len(hits0)}")
    for h, c in hits0:
        print(f"  {h}  {c}   (translation of a held name)")

    GEN_TOKENS = ["caves", "crypt", "lava", "hub", "blue", "red", "green",
                  "gold", "silver", "black", "white", "dark", "light",
                  "broken", "destroyed", "lit", "small", "large", "01", "02",
                  "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]

    tested, hits, seen = 0, [], set()
    for oname, nh in targets:
        d, _, leaf = oname.rpartition("/")
        dd = d + "/" if d else ""
        toks = leaf.split("_")
        cands = {oname}
        for (a, b), _c in trans.most_common(60):            # table-driven
            for i, t in enumerate(toks):
                if t == a:
                    cands.add(f"{dd}{'_'.join(toks[:i] + [b] + toks[i + 1:])}")
        # generic rename shapes: drop/append a token, change a number
        for i in range(len(toks)):
            cands.add(f"{dd}{'_'.join(toks[:i] + toks[i + 1:])}")
            for t in GEN_TOKENS:
                cands.add(f"{dd}{'_'.join(toks[:i] + [t] + toks[i + 1:])}")
                cands.add(f"{dd}{'_'.join(toks[:i] + [t] + toks[i:])}")
        for t in GEN_TOKENS:
            cands.add(f"{dd}{leaf}_{t}")
            cands.add(f"{dd}{t}_{leaf}")
        for a, b in examples:                               # analogy-driven
            e = edit_of(a, b)
            c = apply_edit(oname, e)
            if c:
                cands.add(c)
            # also replay only the *directory* part of the example
            c2 = apply_edit(oname, (e[0], e[1], ()))
            if c2:
                cands.add(c2)
        for c in cands:
            if c in seen:
                continue
            seen.add(c)
            tested += 1
            if f"{murmur_hash64(c):016x}" == nh:
                hits.append((nh, c, oname))
    hits = sorted(set(hits))
    print(f"candidates tested {tested:,}  MATCHES {len(hits)}")
    for h, c, o in hits:
        print(f"  {h}  {c}   (old name {o})")
    allhits = [(h, c) for h, c, _o in hits] + hits0
    if args.write and allhits:
        mf = HC / "matches.tsv"
        with mf.open("a") as fh:
            for h, c in sorted(set(allhits)):
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(set(allhits))} to {mf}")


if __name__ == "__main__":
    main()
