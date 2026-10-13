#!/usr/bin/env python3
"""Mine a per-type vocabulary and seed list out of the names we hold.

    python3 tools/mine_type_tokens.py work/types

Writes `work/types/<type>/{seeds,suffixes,tokens}.txt` for every resource type in
the catalogue (animation, material, particles, timpani_bank, shader, ...).

Why per type: the 978 names still missing are mostly NOT textures - 326 are
animations, 151 shader_library, 107 material, 91 particles, 37 timpani_bank - and
each of those has its own grammar.  `tex_suffixes.txt` (`_diff`/`_norm`/`_spec`)
is noise in an animation name, whose real tail tokens are `start`, `windup`,
`exit`, `offset_02`, `right_45`.  Mining the suffix pool from the names of the same
type keeps every candidate inside the right language:

    seeds     every held name of that type (the `--names` input: mutate uses a
              seed's directory and its leaf tokens)
    suffixes  tokens that end a held name of that type (>= 2 times), plus the
              _NN forms - the `--suffixes` input (what a stem can end with)
    tokens    every leaf token of the type - the `--tokens` input
"""
from __future__ import annotations

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
MATCHES = HC.parent / "Data" / "matches.tsv"

# map suffixes are worth offering in every text-ish type; harmless elsewhere
MAPS = ["_diff", "_norm", "_normal", "_nrm", "_spec", "_gloss", "_glow", "_illum",
        "_illu", "_alpha", "_mask", "_emissive", "_height", "_ao", "_opacity",
        "_d", "_n", "_s", "_c", "_map"]


def known_by_type() -> dict[str, set[str]]:
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    ms: dict[str, str] = {}
    if MATCHES.exists():
        for line in MATCHES.read_text().splitlines():
            if "\t" in line:
                h, n = line.split("\t")[:2]
                ms[h.strip().lower()] = n.strip()
    out: dict[str, set[str]] = collections.defaultdict(set)
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r.get("name_hash") or "").strip().lower()
            if not h:
                continue
            n = (r.get("name") or "").strip() or ov.get(h) or ms.get(h)
            if n:
                out[(r.get("type") or "").strip()].add(n)
    return out


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "work/types")
    root.mkdir(parents=True, exist_ok=True)
    for t, names in sorted(known_by_type().items()):
        if not t or not names:
            continue
        d = root / t
        d.mkdir(parents=True, exist_ok=True)
        (d / "seeds.txt").write_text("\n".join(sorted(names)) + "\n")

        tail = collections.Counter()
        toks: set[str] = set()
        for n in names:
            leaf = n.rsplit("/", 1)[-1]
            # chains (shader_library) split on ':' - the flags are the tokens there
            parts = leaf.split(":") if ":" in leaf else [leaf]
            for p in parts:
                t_ = [x for x in p.split("_") if x]
                if t_:
                    tail[t_[-1]] += 1
                toks.update(t_)
        suffix = [s for s, c in tail.items() if c >= 2 and not s.isdigit() and len(s) > 1]
        suffix = sorted(set(suffix) | {m.lstrip("_") for m in MAPS})
        (d / "suffixes.txt").write_text("".join(f"_{s}\n" for s in suffix))
        (d / "tokens.txt").write_text("\n".join(sorted(toks)) + "\n")
        print(f"{t:<16} seeds {len(names):>5}  tokens {len(toks):>5}  suffixes {len(suffix):>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
