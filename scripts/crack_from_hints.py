#!/usr/bin/env python3
"""Recover resource names from human hints (what a file looks like).

Human-readable guesses arrive as word runs ("vampirehearticon"), but this engine
names resources as underscored paths ("menu/buttons/vampire_heart_icon").  So: take
each hint, cut it into vocabulary words taken from names we already have, and try
every combination of hint-segmentation x directory-that-exists x word order against
the target hash.  A hit is exact - the hash is the proof, not a similarity score.

    python3 crack_from_hints.py --hints /tmp/hint_targets.tsv --type texture
"""
import argparse
import collections
import csv
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hunt_unit_textures import murmur                                   # noqa: E402

EXPORT = pathlib.Path.home() / "Documents/Coding/Gauntlet-Export"
TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def load_index():
    with (EXPORT / "index.tsv").open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def build_vocab(rows, want_type):
    """Words from every named resource, directories from the same type only.

    Words come from everywhere on purpose: `campaign` may only ever appear in a level
    or a Lua name, and a texture hint still needs it as a token.
    """
    tokens = collections.Counter()
    dirs = collections.Counter()
    for r in rows:
        if r["status"] != "named":
            continue
        name = r["name"]
        for part in TOKEN_SPLIT.split(name):
            if part and not part.isdigit():
                tokens[part] += 1
        if not want_type or r["type"] == want_type:
            dirs["/".join(name.split("/")[:-1])] += 1
    return tokens, dirs


def variant_names(name):
    """Spellings to try alongside a name that is already underscore-separated."""
    out = [name]
    if name.endswith("s"):
        out.append(name[:-1])
    else:
        out.append(name + "s")
    # channel suffixes: a texture often carries the role its picture suggests
    for suffix in ("_diff", "_spec", "_norm", "_nrm", "_alpha", "_mask", "_glow"):
        out.append(name + suffix)
    if "/" not in name:
        for prefix in ("diff_", "alpha_"):
            out.append(prefix + name)
    return out


def segment(hint, vocab, cap=400):
    """All ways to cut a word run into vocabulary words joined by underscores."""
    hint = hint.lower()
    n = len(hint)
    out = []
    seen = set()

    def walk(pos, parts):
        if len(out) >= cap:
            return
        if pos == n:
            s = "_".join(parts)
            if s not in seen:
                seen.add(s)
                out.append(s)
            return
        # longest-first so the natural reading ("vampire_heart_icon") comes early
        for end in range(min(n, pos + 18), pos, -1):
            piece = hint[pos:end]
            if piece in vocab or len(piece) <= 3 or piece.isdigit():
                walk(end, parts + [piece])

    walk(0, [])
    if hint not in out:
        out.append(hint)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hints", required=True, help="TSV: hash<hash>\\thint[\\tpackage...]")
    ap.add_argument("--type", default="texture")
    ap.add_argument("--cap", type=int, default=400, help="segmentations per hint")
    ap.add_argument("--max-dirs", type=int, default=400, help="most-used directories to try")
    ap.add_argument("--all-dirs", action="store_true",
                    help="try every directory, not just the most used")
    args = ap.parse_args()

    rows = load_index()
    vocab, dirs = build_vocab(rows, args.type)
    print(f"vocabulary: {len(vocab):,} words, {len(dirs):,} directories", flush=True)

    order = list(dirs) if args.all_dirs else [d for d, _ in dirs.most_common(args.max_dirs)]
    prefixes = [""] + order

    targets = {}
    for line in pathlib.Path(args.hints).read_text().splitlines():
        if not line.strip() or line.startswith("hash"):
            continue
        parts = line.split("\t")
        targets[parts[0].strip().lower()] = parts[1].strip()

    print(f"targets: {len(targets)}", flush=True)
    tried = 0
    hits = []
    for hash_hex, hint in targets.items():
        # A hint with underscores already tells us the words; only the directory and
        # the small spelling variants are unknown.  A word run needs segmenting first.
        segs = (segment(hint, vocab, args.cap) if "_" not in hint
                else variant_names(hint))
        print(f"\n{hint} -> {len(segs)} candidate names: {segs[:8]}", flush=True)
        found = False
        for prefix in prefixes:
            for s in segs:
                cand = f"{prefix}/{s}" if prefix else s
                tried += 1
                if f"{murmur(cand):016x}" == hash_hex:
                    hits.append((hash_hex, cand, hint))
                    print(f"   HIT  {hash_hex}  {cand}", flush=True)
                    found = True
                    break
            if found:
                break
        if not found:
            print(f"   no hit after {len(prefixes) * len(segs):,} candidates", flush=True)

    print(f"\ntried {tried:,} candidates, {len(hits)} hits", flush=True)
    if hits:
        out = pathlib.Path("/tmp/hint_hits.tsv")
        with out.open("w") as fh:
            fh.write("hash\tname\thint\n")
            for h, n, hint in hits:
                fh.write(f"{h}\t{n}\t{hint}\n")
        print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
