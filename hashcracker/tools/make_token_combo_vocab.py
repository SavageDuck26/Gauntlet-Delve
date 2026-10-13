#!/usr/bin/env python3
"""
Token-combination attack inputs (FINDINGS.txt #52).

The universal sweep (`make_universal_vocab.py`) crosses each known directory with
the vocabulary as a **single slot** (`dir%m`), so it can only ever propose
`<dir><leaf we already hold>` or `<dir><single token>`.  Every other sweep that
touches combinations is scoped - the pack sweep combines tokens but only inside
one package and only with its own tokens, `make_guess_patterns.py` only for
levels with a twin.

This widens that to the game's *whole* vocabulary at once.  Split every resolved
name on `/` and `_`, and the 17 k names give a token universe of ~2 k, which is
small enough to cross three deep on the GPU in seconds:

    %a_%b  %a/%b                     2 tokens, either separator
    %a_%b_%c  %a/%b_%c  %a_%b/%c     3 tokens, all separator placements
    %a/%b/%c

and, anchored on a directory we know (a name is `<directory><leaf>`):

    <dir>%a_%b                       a new two-token leaf in a known dir
    <dir>%a_%b_%c                    a new three-token leaf
    <dir><last>_%a_%b                the leaf repeats the directory's own name,
                                     which is this game's dominant convention
                                     (`characters/mummy_priest/mummy_priest_...`)

Positional vocabularies come out of the same pass, because a leaf's first and
last tokens are drawn from much smaller sets than the middle (a last token is a
state or a map or a number: `_01`, `_diff`, `_idle`).

    python3 tools/make_token_combo_vocab.py [--out DIR] [--min-len N]
"""
import argparse
import collections
import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

SPLIT = re.compile(r"[^a-z0-9]+")
NUMERIC = re.compile(r"^[0-9]+$")


def resolved():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    names = []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            names.append(n.lower())
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "tokcombo"))
    ap.add_argument("--min-len", type=int, default=1,
                    help="drop tokens shorter than this")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    names = resolved()
    tok = collections.Counter()
    first = collections.Counter()
    tail = collections.Counter()
    dirs = collections.Counter()
    for n in names:
        d, _, leaf = n.rpartition("/")
        if d:
            dirs[d + "/"] += 1
        toks = [t for t in SPLIT.split(n) if t]
        for t in toks:
            tok[t] += 1
        lt = [t for t in SPLIT.split(leaf) if t]
        if lt:
            first[lt[0]] += 1
            tail[lt[-1]] += 1

    tok = {t for t in tok if len(t) >= args.min_len}
    first = {t for t in first if len(t) >= args.min_len}
    tail = {t for t in tail if len(t) >= args.min_len}
    word = {t for t in tok if not NUMERIC.match(t)}
    num = {t for t in tok if NUMERIC.match(t)}
    dirs = set(dirs)

    def emit(name, values):
        (out / name).write_text("\n".join(sorted(values)) + "\n")
        return len(values)

    n_tok = emit("tok.txt", tok)
    n_word = emit("tok_word.txt", word)
    emit("num.txt", num)
    n_first = emit("first.txt", first)
    n_tail = emit("tail.txt", tail)
    n_dirs = emit("dirs.txt", dirs)

    # free-form patterns: no literal directory, so they can reach names in a
    # directory we have never seen
    free = ["%a_%b", "%a/%b",
            "%a_%b_%c", "%a/%b_%c", "%a_%b/%c", "%a/%b/%c"]
    (out / "patterns_free.txt").write_text("\n".join(free) + "\n")

    # directory-anchored: <dir><leaf> with the leaf built from tokens
    d2 = [f"{d}%a_%b" for d in sorted(dirs)]
    d3 = [f"{d}%a_%b_%c" for d in sorted(dirs)]
    (out / "patterns_dir2.txt").write_text("\n".join(d2) + "\n")
    (out / "patterns_dir3.txt").write_text("\n".join(d3) + "\n")
    # the leaf repeats the directory's own basename, then a tail vocabulary
    base2, base3 = [], []
    for d in sorted(dirs):
        last = d.rstrip("/").rsplit("/", 1)[-1]
        base2.append(f"{d}{last}_%a_%b")
        base3.append(f"{d}{last}_%a_%b_%c")
    (out / "patterns_dirbase2.txt").write_text("\n".join(base2) + "\n")
    (out / "patterns_dirbase3.txt").write_text("\n".join(base3) + "\n")

    print(f"names {len(names):,}  tokens {n_tok:,} (word {n_word:,}, "
          f"numeric {len(num):,})  dirs {n_dirs:,}")
    print(f"  leaf first tokens {n_first:,}   leaf last tokens {n_tail:,}")
    print(f"free 2-token  {2 * n_tok ** 2:,}")
    print(f"free 3-token  {4 * n_tok ** 3:,}")
    print(f"dir x 2-token {n_dirs * n_tok ** 2:,}")
    print(f"dir x 3-token {n_dirs * n_tok ** 3:,}   (gate: ~2 h)")
    print(f"dir + basename + 2 tokens {n_dirs * n_word * n_tail:,}")


if __name__ == "__main__":
    main()
