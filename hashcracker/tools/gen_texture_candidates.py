#!/usr/bin/env python3
"""
Texture candidates from the resources that draw them (FINDINGS.txt §48).

`hunt_texture_refs.py` gives, for each unnamed texture, the resolved resources
whose bodies reference it.  That is worth more than it looks:

  * the referrer's *directory* is the texture's directory, and
  * the referrer's *name* supplies the stem - which matters most exactly where we
    are stuck: `effects_ui/` has 67 referrers and **zero** resolved textures, so
    the sibling sweeps had nothing to seed from, yet the textures it draws are
    plainly named after the effect.

So each edge (texture <- referrer) becomes candidates `<dir><stem><suffix>` with
the suffix vocabulary mined from the resolved textures, and checked by hash.

    python3 tools/gen_texture_candidates.py [--refs FILE] [--write]
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
REFS = HC / "work" / "texture_refs.json"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64                              # noqa: E402

EXTRA_SUF = ["diff", "norm", "spec", "normal", "mask", "glow", "emissive",
             "alpha", "atlas", "icon", "icons", "locked", "hover", "active",
             "pressed", "disabled", "sel", "selected", "bg", "background",
             "base", "shadow", "overlay", "tint", "idle", "off", "on", "dead",
             "shine", "colour", "color", "grey", "gray", "fill", "frame",
             "glowmap", "distort", "noise", "detail", "small", "big", "wide"]


def unresolved_textures():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("type") == "texture" and not r.get("name") \
                and r.get("name_hash") not in ov:
            out[r["name_hash"].lower()] = int(r["body_size"])
    return out


def resolved_textures():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("type") != "texture":
            continue
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            out.append(n)
    return out


def suffixes(names):
    suf = collections.Counter()
    by_dir = collections.defaultdict(set)
    for n in names:
        leaf = n.rsplit("/", 1)[-1]
        d = n.rsplit("/", 1)[0] + "/" if "/" in n else ""
        toks = leaf.split("_")
        if len(toks) > 1:
            suf["_".join(toks[-1:])] += 1
            suf["_".join(toks[-2:])] += 1
            by_dir[d].add("_".join(toks[-2:]))
    for s in EXTRA_SUF:
        suf[s] += 1
    return suf, by_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", default=str(REFS))
    ap.add_argument("--type", default="texture")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    ref = args.refs if args.refs != str(REFS) else str(HC / "work" / f"refs_{args.type}.json")
    refs = json.loads(pathlib.Path(ref).read_text())
    un = unresolved_textures()
    names = resolved_textures()
    suf, by_dir = suffixes(names)
    print(f"edges {len(refs)}  unresolved textures {len(un)}  "
          f"suffixes {len(suf)}")

    tex_dirs = collections.Counter(n.rsplit("/", 1)[0] + "/" for n in names
                                   if "/" in n)
    stem_tokens = collections.defaultdict(set)
    for n in names:
        leaf = n.rsplit("/", 1)[-1]
        for t in leaf.split("_"):
            stem_tokens[t].add(n.rsplit("/", 1)[0] + "/" if "/" in n else "")

    hits = []
    tested = 0
    for h, referrers in refs.items():
        if h not in un:
            continue
        cands = set()
        for r in referrers:
            d, _, leaf = r.rpartition("/")
            dd = d + "/" if d else ""
            toks = leaf.split("_")
            stems = {leaf}
            for k in (1, 2):
                if len(toks) > k:
                    stems.add("_".join(toks[:-k]))
            for st in stems:
                for s, _c in suf.most_common(400):
                    cands.add(f"{dd}{st}_{s}")
                    cands.add(f"{dd}{st}{s}")
                cands.add(f"{dd}{st}")
                for k in range(1, 10):
                    cands.add(f"{dd}{st}_0{k}")
                    cands.add(f"{dd}{st}{k}")
            # a texture drawn by a `hud/<x>`/`effects/<x>` unit can live in the
            # sibling texture tree, and the stem may be a token of the referrer
            for t in toks:
                for dd2, _c in tex_dirs.most_common(300):
                    if t in dd2.split("/"):
                        for s, _c2 in suf.most_common(60):
                            cands.add(f"{dd2}{st}_{s}")
        for c in cands:
            tested += 1
            if f"{murmur_hash64(c):016x}" == h:
                hits.append((h, c))
    hits = sorted(set(hits))
    print(f"candidates tested {tested:,}  MATCHES {len(hits)}")
    for h, c in hits:
        print(f"  {h}  {c}")
    if args.write and hits:
        mf = HC.parent / "Data" / "matches.tsv"
        with mf.open("a") as fh:
            for h, c in hits:
                fh.write(f"{h}\t{c}\n")
        print(f"appended {len(hits)} to {mf}")


if __name__ == "__main__":
    main()
