#!/usr/bin/env python3
"""
Mine resource names out of the decompiled Lua source tree.

The dungeon generator ships its quilt *catalogue* as data: each
`lua/dungeon/layouts/*.lua` file holds dictionaries of quilt names that are
written **relative to a `path = "modules/d01_<env>/quilts/<cat>/"` field**, e.g.

    fillers = {
        path = "modules/d01_caves/quilts/base/",
        straight_vert_short = {
            caves_quilt_straight__e_x_e_x__01_spider = {},
            ...
        },
    }

so the names have to be reassembled with the path that is in scope.  Bare keys
are also worth testing on their own (some resource names really are relative to
their package).

    python3 tools/mine_lua_modules.py [--source game-source] [--out FILE]

Writes one candidate per line, lowercased, de-duplicated; feed it to
`tools/hc.sh crack --candidates FILE`.
"""
import argparse
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent

PATH_FIELD = re.compile(r'path\s*=\s*"([^"]+)"')
# a resource-ish string literal: dotted path or a `_`-joined leaf.
# NB `__` yields an *empty* token, so the token body must allow runs of `_`.
LITERAL = re.compile(r'"([a-z0-9_]+(?:/[a-z0-9_]+)+)"')
LEAF = re.compile(r'"([a-z0-9_][a-z0-9_]{3,})"')
# bare table keys: `caves_quilt_straight__e_x_e_x__01_spider = {}`
KEY = re.compile(r'^\s*([a-z0-9_][a-z0-9_]{3,})\s*=')


def mine(path: pathlib.Path, out: set):
    cur = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        m = PATH_FIELD.search(line)
        if m:
            cur = m.group(1)
            out.add(cur.rstrip("/"))
            continue
        for m in LITERAL.finditer(line):
            out.add(m.group(1))
            if cur and not m.group(1).startswith("modules/"):
                out.add(cur.rstrip("/") + "/" + m.group(1))
        m = KEY.match(line)
        if m:
            key = m.group(1)
            out.add(key)
            if cur:
                out.add(cur.rstrip("/") + "/" + key)
            continue
        for m in LEAF.finditer(line):
            out.add(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(REPO / "game-source"))
    ap.add_argument("--out", default=str(HERE.parent / "work" / "level" / "lua_candidates.txt"))
    args = ap.parse_args()

    root = pathlib.Path(args.source)
    files = sorted(root.rglob("*.lua"))
    cand: set = set()
    for f in files:
        mine(f, cand)
    cand = {c for c in cand if re.fullmatch(r"[a-z0-9_/]+", c)}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sorted(cand)) + "\n")
    quilts = sum(1 for c in cand if "_quilt_" in c)
    print(f"lua files   : {len(files)}")
    print(f"candidates  : {len(cand)}  (quilts {quilts})")
    print(f"written to  : {out}")


if __name__ == "__main__":
    main()
