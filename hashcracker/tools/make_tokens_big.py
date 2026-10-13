#!/usr/bin/env python3
"""
Build the WIDE token vocabulary used by the big mutate runs.

`make_recovered_vocab.py` mints tokens from the recovered names alone, which is
what the per-cycle pipeline phase uses (cheap).  This is the heavy version: it
sweeps every text corpus we own for word-ish tokens, so `hashcracker mutate` can
append/prepend/replace far more combinations per name.

Sources (missing ones are skipped):
    data/names.txt              base token list (legacy vocab)
    data/lua_strings.txt        string literals from the shipped Lua
    data/events.txt             flow event names
    data/vocab/bundle_words.txt words found inside bundle bodies
    data/vocab/recovered_names.txt  + their leaf/path tokens (always)
    reference/Stingray-Docs-md/ the engine documentation crawl
    <any> --corpus FILE ...     extra text corpora

Tokens are lowercased word runs (a-z0-9, len >= 2) plus snake_case combinations
of 2-3 words that literally occur, ranked by frequency and capped by
--max-tokens (mutate cost grows linearly with this number).

    python3 tools/make_tokens_big.py --max-tokens 80000
"""
import argparse
import collections
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
VOCAB = HC / "data" / "vocab"

DEFAULT_CORPORA = [
    HC / "data" / "names.txt",
    HC / "data" / "lua_strings.txt",
    HC / "data" / "events.txt",
    VOCAB / "bundle_words.txt",
]
# Engine vocabulary mined from the Stingray/Bitsquid video tutorials and from
# gamefromscratch's Stingray review (captions, frame OCR, screenshot OCR).  These
# live in gitignored scratch folders; skipped when absent.  FINDINGS.txt §35.
OPTIONAL_CORPORA = [
    REPO / "Stingray-Video-Mine" / "video_ocr_candidates.txt",
    REPO / "Stingray-Video-Mine" / "caption_candidates.txt",
    REPO / "Stingray-Web-Mine" / "web_candidates.txt",
]
DOC_DIR = REPO / "reference" / "Stingray-Docs-md"

WORD = re.compile(r"[a-z0-9]{2,}")
SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+){1,2}")


def add_text(text: str, counts: collections.Counter) -> None:
    low = text.lower()
    counts.update(m.group(0) for m in WORD.finditer(low))
    counts.update(m.group(0) for m in SNAKE.finditer(low))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", default=[],
                    help="extra text corpus (repeatable)")
    ap.add_argument("--max-tokens", type=int, default=80000)
    ap.add_argument("--out", default=str(VOCAB / "tokens_big.txt"))
    args = ap.parse_args()

    counts: collections.Counter = collections.Counter()
    used = []

    recovered = VOCAB / "recovered_names.txt"
    if recovered.exists():
        names = recovered.read_text(errors="replace").split()
        used.append(f"recovered_names.txt ({len(names)} names)")
        for n in names:
            directory, _, leaf = n.rpartition("/")
            counts.update(t for t in leaf.split("_") if len(t) > 1)
            counts.update(c for c in directory.split("/") if len(c) > 1)

    for p in [*DEFAULT_CORPORA, *OPTIONAL_CORPORA,
              *(pathlib.Path(c) for c in args.corpus)]:
        p = pathlib.Path(p)
        if p.is_file():
            add_text(p.read_text(errors="replace"), counts)
            used.append(f"{p.name} ({p.stat().st_size // 1024} KB)")

    if DOC_DIR.is_dir():
        n = 0
        for f in DOC_DIR.rglob("*.md"):
            add_text(f.read_text(errors="replace"), counts)
            n += 1
        used.append(f"Stingray-Docs-md ({n} files)")

    # keep the list word-like: no paths, no dots, sane length
    keep = {t: c for t, c in counts.items()
            if 2 <= len(t) <= 40 and "." not in t and "/" not in t and not t.isdigit()}
    ranked = sorted(keep.items(), key=lambda kv: (-kv[1], kv[0]))[: args.max_tokens]
    tokens = sorted(t for t, _ in ranked)

    pathlib.Path(args.out).write_text("\n".join(tokens) + "\n")
    print(f"corpora: {'; '.join(used)}")
    print(f"distinct candidates {len(counts)}  ->  kept {len(tokens)}  ->  {args.out}")


if __name__ == "__main__":
    main()
