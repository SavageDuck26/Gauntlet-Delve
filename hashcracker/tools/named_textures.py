#!/usr/bin/env python3
"""Dump every *texture* name we currently know - the `--names` input for `hashcracker mutate`.

    python3 tools/named_textures.py > work/named_textures.txt

Sources, unioned: the catalogue's own names, the name overlay, and `matches.tsv`.
A hash only counts as a texture if one of its catalogue rows has `type=texture`,
so a name we recovered for a mesh or a material does not pollute the list.

The point of regenerating this on every round is that the mode is self-feeding:
`mutate` swaps one token of a name we hold, so every name it finds immediately
becomes a new seed with a new directory and a new token neighbourhood.
"""
from __future__ import annotations

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


def load_names(all_types: bool = False) -> dict[str, str]:
    """hash -> name, from the catalogue, the overlay and matches.tsv (in that order).

    `all_types=False` keeps only names whose hash has a `texture` row.  `True` keeps
    every name we know: `mutate` only uses a seed's *directory* and its leaf tokens,
    and a candidate is verified by hashing, so a material/particle/animation name is a
    free source of directory and word context (`characters/avatar_warrior/animations/`
    and `..._turnleft` came out of exactly such neighbourhoods).
    """
    types: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r.get("name_hash") or "").strip().lower()
            if not h:
                continue
            types.setdefault(h, set()).add((r.get("type") or "").strip())
            n = (r.get("name") or "").strip()
            if n:
                names[h] = n
    if OVERLAY.exists():
        for h, n in json.loads(OVERLAY.read_text()).items():
            names.setdefault(h.strip().lower(), n)
    if MATCHES.exists():
        for line in MATCHES.read_text().splitlines():
            if "\t" in line:
                h, n = line.split("\t")[:2]
                names.setdefault(h.strip().lower(), n.strip())
    if all_types:
        return names
    return {h: n for h, n in names.items() if "texture" in types.get(h, ())}


def texture_names(all_types: bool = False) -> list[str]:
    return sorted(set(load_names(all_types).values()), key=str.lower)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true",
                    help="every known name, not just texture-typed ones")
    a = ap.parse_args()
    out = texture_names(a.all)
    sys.stdout.write("\n".join(out) + "\n")
    print(f"{len(out)} names{' (all types)' if a.all else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
