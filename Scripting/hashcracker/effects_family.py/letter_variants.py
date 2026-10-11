#!/usr/bin/env python3
"""Letter/number variants of every texture name we hold - the `01b` slot.

    python3 tools/letter_variants.py | python3 tools/check_names.py --write

Rust `mutate` replaces a whole digit token with another number, so it reaches
`_01` -> `_07` and never `_01` -> `_01b`, and it cannot touch `l01` at all
(`map_rock_l01`: the token *contains* a digit, so the replacement throws the `l`
away).  Both forms are everywhere in this game:

    caverock_stalagmites_01b_diff     lavastruct_borders_01b_diff
    menu/level_select/map_rock_l01    ... map_rock_r01..r06   (letter BEFORE number)

So: for every named texture, in every numeric token
    <n><letter>   <letter><n>   <n>_<letter>   <n>+-1..2   <n><letter><letter>
and for a mixed token (`01b`, `l01`, `2c`) swap the letters, drop them, or move
the number.  Names with no number at all get `_<n><letter>` and `_<letter><n>`
appended, which is how `mummy_bloated_01b`-shaped names would look.  Everything
is crossed with the map suffixes we have seen (`_diff`, `_norm`, `_illu`, ...).
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from named_textures import texture_names                              # noqa: E402

MAPS = ["_diff", "_norm", "_normal", "_nrm", "_spec", "_gloss", "_glow", "_illum",
        "_illu", "_alpha", "_mask", "_emissive", "_d", "_n", "_s"]
LETTERS = "abcdefgh"
PURE_NUM = re.compile(r"^\d+$")
NUM_LET = re.compile(r"^(\d+)([a-z]{1,2})$")
LET_NUM = re.compile(r"^([a-z]{1,2})(\d+)$")


def split_map(leaf: str) -> tuple[str, str]:
    for m in sorted(MAPS, key=len, reverse=True):
        if leaf.endswith(m):
            return leaf[: -len(m)], m
    return leaf, ""


def token_variants(tok: str) -> set[str]:
    """Every form of one leaf token that changes only its letters/number."""
    out: set[str] = set()
    if PURE_NUM.match(tok):
        width = len(tok)
        n = int(tok)
        for c in LETTERS:
            out.add(f"{n:0{width}d}{c}")          # 01b
            out.add(f"{c}{n:0{width}d}")          # b01  (map_rock_l01 shape)
            out.add(f"{n:0{width}d}_{c}")         # 01_b
        for d in (-2, -1, 1, 2):
            if n + d >= 0:
                out.add(f"{n + d:0{width}d}")     # 02, 00
        for c in "ab":
            for c2 in "abcdef":
                out.add(f"{n:0{width}d}{c}{c2}")  # 01ab
    elif NUM_LET.match(tok):
        n, lets = NUM_LET.match(tok).groups()
        width = len(n)
        for c in LETTERS:                          # 01b -> 01a..01h
            out.add(n + c)
        out.add(n)                                 # 01b -> 01
        for c in LETTERS:
            out.add(n + c + c)                      # 01bb
        for d in (-1, 1):
            if int(n) + d >= 0:
                for c in lets:
                    out.add(f"{int(n) + d:0{width}d}{c}")   # 01b -> 02b
    elif LET_NUM.match(tok):
        lets, n = LET_NUM.match(tok).groups()
        width = len(n)
        for c in LETTERS:                          # l01 -> a01..h01
            out.add(c + n)
        for d in (-1, 1):
            if int(n) + d >= 0:
                for c in lets:
                    out.add(f"{c}{int(n) + d:0{width}d}")   # l01 -> l02
        out.add(n)                                 # l01 -> 01
    return out - {tok}


def main() -> int:
    names = texture_names()
    seen: set[str] = set()
    out = sys.stdout
    for name in names:
        i = name.rfind("/")
        d, leaf = (name[: i + 1], name[i + 1:]) if i >= 0 else ("", name)
        base, map0 = split_map(leaf)
        maps = []
        for m in (map0, "", "_diff", "_norm"):
            if m not in maps:
                maps.append(m)
        toks = base.split("_")
        bases: set[str] = set()
        has_num = False
        for j, t in enumerate(toks):
            alts = token_variants(t)
            if not alts:
                continue
            has_num = True
            for a in alts:
                bases.add("_".join(toks[:j] + [a] + toks[j + 1:]))
        if not has_num:
            for n in range(1, 10):
                for c in LETTERS:
                    bases.add(f"{base}_{n:02d}{c}")
                    bases.add(f"{base}_{c}{n:02d}")
            for c in "abc":
                bases.add(f"{base}_{c}")
        for b in bases:
            for m in maps:
                cand = d + b + m
                if cand not in seen:
                    seen.add(cand)
                    out.write(cand + "\n")
    print(f"{len(seen)} candidates from {len(names)} names", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
