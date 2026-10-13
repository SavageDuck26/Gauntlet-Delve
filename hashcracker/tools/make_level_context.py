#!/usr/bin/env python3
"""
Context-conditioned `.level` vocabularies - the concrete-prefix trick.

A quilt name is

    modules/d01_<env>/<sub>/<env>_quilt_<shape>__<cells>__<nn>[_<mods>]

and each (env, sub) pair is its own little world: `crypt/quilts/base` only ever
uses ~4 cell codes, ~5 variant numbers and ~20 mods.  Crossing the *global*
vocabularies (3 envs x 5 subs x 29 shapes x 43 codes x 43 nn x 85k mods) is
68 billion candidates, but conditioned per (env, sub) it is ~350 M for the whole
staged ladder - and the first three stages are ~1,800 candidates in total.

So: bake the context into the **pattern literal** (only the tail stays a slot
product) and let the driver escalate one field at a time:

    stage 1  ctx codes x ctx nn x ctx shapes x ctx mods      (the closed form)
    stage 2  +1 char code neighbourhood ...
    stage 9  ... ctx codes x ctx nn x all shapes x all mods

    python3 tools/make_level_context.py [--out data/vocab/lvlctx]

Writes `manifest.tsv` (`slug <TAB> env <TAB> sub`, `-` = no sub dir) plus one
dir per context holding `codes.txt`, `nn.txt`, `mods.txt`, `shapes.txt` = the
values actually observed in that context.  the context sweep reads it.
"""
import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_level_full import (QUILT, SUBS_SEEN, load_known, HC)  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "lvlctx"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    names, _targets = load_known()
    ctx = collections.defaultdict(lambda: {"code": set(), "nn": set(), "mod": set(),
                                           "shape": set()})
    envs = set()
    for n in names:
        m = QUILT.match(n)
        if not m:
            continue
        env, sub, _base, shape, cells, tail = m.groups()
        envs.add(env)
        k = (env, sub.rstrip("/") or "-")
        c = ctx[k]
        c["shape"].add(shape)
        c["code"].add(cells)
        p = tail.split("_")
        c["nn"].add(p[0])
        if len(p) > 1:
            c["mod"].add("_".join(p[1:]))
            c["mod"].add(p[1])
    # every env gets every *seen* subdir, including ones this env never uses
    # (`caves/quilts/saferooms` exists only in the generator's head today), and
    # the bare form gets one row per env.
    keys = {(e, s) for e in envs for s in SUBS_SEEN} | {(e, "-") for e in envs}
    keys |= set(ctx)
    # an unseen (env, sub) borrows the values seen for that sub in other envs
    by_sub = collections.defaultdict(lambda: collections.defaultdict(set))
    for (e, s), c in ctx.items():
        for field in ("code", "nn", "mod", "shape"):
            by_sub[s][field] |= c[field]

    rows = []
    closed = 0
    for k in sorted(keys):
        env, sub = k
        c = ctx.get(k)
        vals = {f: (set(c[f]) if c else set(by_sub[sub][f]))
                for f in ("code", "nn", "mod", "shape")}
        slug = f"{env}_{sub.replace('/', '_')}"
        d = out / slug
        d.mkdir(exist_ok=True)
        for field, values in (("codes", vals["code"]), ("nn", vals["nn"]),
                              ("mods", vals["mod"]), ("shapes", vals["shape"])):
            (d / f"{field}.txt").write_text("\n".join(sorted(values)) +
                                            ("\n" if values else ""))
        closed += len(vals["code"]) * len(vals["nn"]) * max(1, len(vals["mod"]))
        rows.append(f"{slug}\t{env}\t{sub}")

    (out / "manifest.tsv").write_text("\n".join(rows) + "\n")
    print(f"contexts      : {len(rows)}  ({len(envs)} envs)")
    print(f"closed form   : {closed} candidates across all contexts")
    print(f"manifest      : {out / 'manifest.tsv'}")


if __name__ == "__main__":
    main()
