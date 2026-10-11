#!/usr/bin/env python3
"""
Mod-tail patterns from the harvest vocabulary (FINDINGS.txt §45/§46).

The harvest (`work/harvest/quilt_ids.txt`) shows what the quilt mod tail really
is: a short run of the game's own mod words, sometimes *concatenated* rather
than underscore-joined, and often glued straight onto the number:

    crypt_quilt_straight__e_x_e_x__01chain            (no separator!)
    crypt_quilt_straight__e_x_e_x__03_goldchain       (compound token)
    lava_quilt_mediumroom__xox_ox_xix_ix__02_fountains_demons
    lava_quilt_straight__o_xx_i_xx__01_crankbridge

so the mod vocabulary is mined from the harvest, and the patterns must allow
both attach forms and both separators.  Combined with the legal code lists per
shape this covers the space the earlier sweeps could not express.

    python3 tools/make_mod_patterns.py [--out DIR] [--vocab N] [--patterns FILE]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
HARVEST = HC / "work" / "harvest" / "quilt_ids.txt"
QID = re.compile(r"^[a-z][a-z0-9]*_quilt_([a-z]+)__([a-z_]+)__([a-z0-9]+?)(_?)([a-z].*)?$")
STOP = {"diff", "norm", "spec", "var01", "e", "x", "xx", "quilt", "straight",
        "turn", "blackbox", "mediumroom", "largeroom", "smallroom", "rooms",
        "modules", "end", "start"}


def harvest_mods():
    mods, toks = set(), set()
    if not HARVEST.exists():
        return mods, toks
    for line in HARVEST.read_text(errors="replace").splitlines():
        m = QID.match(line.strip())
        if not m:
            continue
        mod = m.group(5)
        if not mod:
            continue
        for bad in ("omodules", "gmodules", "modules"):
            if mod.endswith(bad):
                mod = mod[:-len(bad)]
        mods.add(mod)
        for t in mod.split("_"):
            if t and not t.isdigit() and t not in STOP:
                toks.add(t)
    return mods, toks


def resolved_mods():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    mods, toks = set(), set()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if not n or "_quilt_" not in n:
            continue
        m = QID.match(n.rsplit("/", 1)[-1])
        if m and m.group(5):
            mods.add(m.group(5))
            toks |= {t for t in m.group(5).split("_")
                     if t and not t.isdigit() and t not in STOP}
    return mods, toks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "mods"))
    ap.add_argument("--vocab", type=int, default=3000)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    hm, ht = harvest_mods()
    rm, rt = resolved_mods()
    toks = sorted(ht | rt)
    vocab = set(hm) | set(rm) | set(toks)
    vocab |= {f"{a}_{b}" for a in toks for b in toks}
    vocab |= {f"{a}{b}" for a in toks for b in toks}     # glued compounds
    vocab |= {f"{a}_{b}_{c}" for a in toks[:14] for b in toks[:10]
              for c in toks[:6]}
    vocab = sorted(v for v in vocab if v)[:args.vocab]

    (out / "mod_vocab.txt").write_text("\n".join(vocab) + "\n")
    print(f"harvest mods {len(hm)}  resolved mods {len(rm)}  tokens {len(toks)}"
          f"  -> vocab {len(vocab)}")
    print("tokens:", " ".join(toks))


if __name__ == "__main__":
    main()
