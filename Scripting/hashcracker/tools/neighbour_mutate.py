#!/usr/bin/env python3
"""One-slot mutation with the name corpus *itself* as the token pool.

    python3 tools/neighbour_mutate.py | python3 tools/check_names.py --write

`hashcracker mutate` swaps in a token from a 350k-word list mined from elsewhere.
This does the opposite: inside every directory, replace one leaf token with any
token that already lives in that directory (plus append/prepend one).  Neighbour
tokens are the game's own vocabulary for that folder - `turnleft`/`turnright`/
`pos02` in `characters/*/animations/`, `windup`/`start`/`loop` in an attack set,
`_2c`/`_4c`/`_low` in a block set - so the hit rate is far better than a
dictionary, and it runs on the CPU, so it never queues behind the GPU modes.

    --global   also cross with the tokens of every other directory (slow, 250M)
    --min-dir  skip directories with fewer than N names (default 2)
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from named_textures import load_names                                # noqa: E402

MAPS = ["_diff", "_norm", "_normal", "_nrm", "_spec", "_gloss", "_glow", "_illum",
        "_illu", "_alpha", "_mask", "_emissive", "_d", "_n", "_s", "_l", "_m",
        "_hm", "_ml", "_2c", "_4c", "_8c"]


def split_map(leaf: str) -> tuple[str, str]:
    for m in sorted(MAPS, key=len, reverse=True):
        if leaf.endswith(m):
            return leaf[: -len(m)], m
    return leaf, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--global", dest="glob", action="store_true",
                    help="cross with the tokens of every directory as well")
    ap.add_argument("--min-dir", type=int, default=2)
    ap.add_argument("--only", action="append", default=[],
                    help="restrict to directories starting with this prefix (repeatable)")
    ap.add_argument("--pool-file", action="append", default=[],
                    help="extra token pool, one token per line (repeatable)")
    ap.add_argument("--group-by", type=int, default=0,
                    help="pool tokens by the first N path components instead of by "
                         "directory: 2 groups `characters/boss_morak/*` together, so a "
                         "unit's abilities/gibs vocabulary reaches its animations/")
    a = ap.parse_args()

    dirs: dict[str, list[str]] = collections.defaultdict(list)
    dir_maps: dict[str, set[str]] = collections.defaultdict(set)
    all_tokens: set[str] = set()
    for name in set(load_names(all_types=True).values()):
        i = name.rfind("/")
        d, leaf = (name[: i + 1], name[i + 1:]) if i >= 0 else ("", name)
        base, m = split_map(leaf)
        dirs[d].append(base)
        dir_maps[d].add(m)
        all_tokens.update(base.split("_"))

    groups: dict[str, set[str]] = collections.defaultdict(set)
    if a.group_by:
        for name in set(load_names(all_types=True).values()):
            i = name.rfind("/")
            d, leaf = (name[: i + 1], name[i + 1:]) if i >= 0 else ("", name)
            base, _m = split_map(leaf)
            key = "/".join(d.split("/")[: a.group_by]) + "/"
            groups[key].update(base.split("_"))

    out = sys.stdout
    total = 0
    for d, bases in sorted(dirs.items()):
        if len(bases) < a.min_dir:
            continue
        if a.only and not any(d.startswith(p) for p in a.only):
            continue
        bases = sorted(set(bases))
        pool = set(all_tokens) if a.glob else set()
        if a.group_by:
            keys = ["/".join(d.split("/")[: a.group_by]) + "/"]
            for k in keys:
                pool |= groups.get(k, set())
        for p in a.pool_file:
            pool.update(t.strip().lstrip("_") for t in
                        pathlib.Path(p).read_text().splitlines() if t.strip())
        for b in bases:
            pool.update(b.split("_"))
        pool = sorted(pool)
        maps = [""] + sorted({m for m in dir_maps[d]}) + ["_diff", "_norm"]
        seen: set[str] = set()
        for b in bases:
            toks = b.split("_")
            cands: set[str] = set()
            for i in range(len(toks)):
                if len(toks) == 1 and len(pool) > 4000:
                    continue
                for t in pool:
                    if t != toks[i]:
                        cands.add("_".join(toks[:i] + [t] + toks[i + 1:]))
            # insertion, not just replacement: `move_jog_left` -> `move_jog_look_left`
            # is how the animation names in FINDINGS 61.9 were actually spelled.
            for i in range(len(toks) + 1):
                for t in pool:
                    cands.add("_".join(toks[:i] + [t] + toks[i:]))
            for t in pool:
                cands.add(f"{b}_{t}")
                cands.add(f"{t}_{b}")
            for c in cands:
                for m in maps:
                    cand = d + c + m
                    if cand not in seen:
                        seen.add(cand)
                        out.write(cand + "\n")
        total += len(seen)
    print(f"{total} candidates from {len(dirs)} directories", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
