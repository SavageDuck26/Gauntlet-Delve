#!/usr/bin/env python3
"""
Harvest the ASCII strings out of the shipped bundle payloads.

`Gauntlet-install/contents/<hex>` is a Stingray bundle container: a small header
per entry followed by a **zlib stream** (`78 9c`).  Nothing in the repo had ever
decompressed them (FINDINGS 60.13 only grepped the compressed bytes and correctly
concluded that compressed data has no path-like strings), but the payloads are
the compiled resources themselves - `.shader` DXBC blobs, geometry, textures - and
compiled payloads keep plenty of *names* in plain text:

    global_viewport        a shader constant
    charselect_turn        an animation event (the state machines are compiled,
                           but the .lua lookup generated from them is not the only
                           place these words live)

so this is a genuinely new vocabulary, and for `shader_library` the technique and
flag words live here as strings.  Two uses:

    * every harvested string is hashed as-is against the unresolved set (a
      compiled payload may well spell a name out), and
    * the strings are written out as a token corpus for the `mutate` engine,
      which is where the reach ultimately comes from (FINDINGS 61.4).

Deliberately streaming and capped: only a bounded per-file set of 64-bit hashes is
held, never the strings themselves.

    python3 tools/mine_bundle_strings.py [--files N] [--max-bytes N]
                                         [--out FILE] [--tokens FILE] [-v]
"""
import argparse
import csv
import json
import pathlib
import re
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
DIG = HC.parent / "Data"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64  # noqa: E402

CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
CONTENTS = REPO / "Gauntlet-install" / "contents"

ZHEAD = b"\x78\x9c"
ASCII_RUN = re.compile(rb"[ -~]{5,120}")
WORDISH = re.compile(r"^[A-Za-z0-9_./:+-]+$")


def unresolved():
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r["name_hash"] or "").lower()
            if h and h not in ov:
                out[h] = r["type"]
    return out


def streams(blob: bytes, cap: int):
    """Yield decompressed chunks of every zlib stream in `blob`, bounded."""
    i = 0
    while True:
        j = blob.find(ZHEAD, i)
        if j < 0:
            return
        i = j + 1
        d = zlib.decompressobj()
        try:
            out = d.decompress(blob[j:j + 64_000_000], cap)
        except zlib.error:
            continue
        if len(out) >= 256:
            yield out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=0,
                    help="process only the N smallest bundles (0 = all)")
    ap.add_argument("--largest", type=int, default=0,
                    help="process only the N largest bundles")
    ap.add_argument("--max-bytes", type=int, default=0,
                    help="read only the first N bytes of each bundle (0 = all)")
    ap.add_argument("--out")
    ap.add_argument("--tokens")
    ap.add_argument("--cap", type=int, default=1_000_000,
                    help="max decompressed bytes per zlib stream")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    un = unresolved()
    blobs = sorted((p for p in CONTENTS.iterdir() if p.is_file()
                    and not p.name.endswith(".stream")
                    and p.suffix == ""),
                   key=lambda p: p.stat().st_size)
    if a.files:
        blobs = blobs[:a.files]
    if a.largest:
        blobs = blobs[-a.largest:]
    print(f"unresolved {len(un)}   bundles {len(blobs)}", file=sys.stderr)

    out_fh = open(a.out, "a", encoding="utf-8") if a.out else None
    tok_fh = open(a.tokens, "w", encoding="utf-8") if a.tokens else None
    seen_hash: set[int] = set()
    seen_tok: set[int] = set()
    hits: list[tuple[str, str]] = []
    total_str = 0

    for p in blobs:
        raw = p.read_bytes() if not a.max_bytes else p.read_bytes()[:a.max_bytes]
        n_streams = n_chunks = 0
        for out in streams(raw, a.cap):
            n_streams += 1
            n_chunks += len(out)
            for m in ASCII_RUN.finditer(out):
                s = m.group().decode("ascii", "replace").strip()
                if len(s) < 5 or not WORDISH.match(s):
                    continue
                total_str += 1
                if tok_fh and "." not in s and "/" not in s:
                    # token corpus for the mutate engine
                    for tok in s.lower().split("_"):
                        if len(tok) > 2 and hash(tok) not in seen_tok:
                            if len(seen_tok) < 3_000_000:
                                seen_tok.add(hash(tok))
                            tok_fh.write(tok + "\n")
                low = s.lower()
                if hash(low) in seen_hash:
                    continue
                if len(seen_hash) < 4_000_000:   # bounded: 4M int64s ~ 250 MB
                    seen_hash.add(hash(low))
                h = f"{murmur_hash64(low):016x}"
                if h in un:
                    hits.append((h, low))
                    print(f"HIT {h} {un[h]:16s} {low}", file=sys.stderr)
        if a.verbose:
            print(f"  {p.name} {len(raw)/1e6:.1f}MB streams {n_streams} "
                  f"out {n_chunks/1e6:.1f}MB", file=sys.stderr)

    print(f"strings {total_str:,}  distinct {len(seen_hash):,}  HITS {len(hits)}",
          file=sys.stderr)
    if out_fh:
        for h, n in hits:
            out_fh.write(f"{h}\t{n}\n")
        out_fh.close()
        print(f"appended {len(hits)} to {a.out}", file=sys.stderr)
    if tok_fh:
        tok_fh.close()
        print(f"tokens written to {a.tokens}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
