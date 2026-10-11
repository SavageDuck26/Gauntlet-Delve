#!/usr/bin/env python3
"""
Decompress only the bundles that are known to hold *missing* resources.

`mine_bundle_strings.py` walks all 1.5 GB of `contents/`, which is the wrong shape:
compiled textures have no strings, so most of it is wasted.  The manifest already
says where every resource lives -

    bundle_manifest/09_reachability.tsv
    hash          type            package                        bundle          size ...
    8c168139a2f6dc7d texture     modules/d01_crypt/resources    0164ad48615ba9ed 43836 ...

- so the residual can be grouped by `(type, package, bundle)` and only those bundles
need decompressing.  A compiled `render_config` really does spell its
`shader_libraries` list out as literal strings (seen directly in
`contents/1a9c33dcd0301dfd`: `core/rendering/base`, `core/rendering/caustic`, ...),
and a compiled shader library lists its shader names, so the strings are there to be
found - the tool just has to look in the right bundle.

Streams, remembers nothing but hits, and reports per bundle so a miss is informative.

    python3 tools/mine_target_bundles.py [--types t1,t2] [--top N] [--dry-run] [--write]
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent.parent
DIG = HC.parent / "GauntletGameDigging"
sys.path.insert(0, str(DIG))
from bundle_tools import murmur_hash64  # noqa: E402

CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
REACH = DIG / "bundle_manifest" / "09_reachability.tsv"
OVERLAY = DIG / "resource_name_overlay.json"
CONTENTS = REPO / "Gauntlet-install" / "contents"

RUN = re.compile(rb"[ -~]{6,4000}")
WORDS = re.compile(r"[a-z0-9_/]{6,120}")
CHAINS = re.compile(r"[a-z0-9_/]+:[a-z0-9_:]{4,120}")


def unresolved() -> dict[str, str]:
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r["name_hash"] or "").lower()
            if h and h not in ov:
                out[h] = r["type"]
    return out


def groups(un, types):
    """(type, package, bundle) -> count, straight out of the reachability table."""
    g = collections.Counter()
    for line in REACH.read_text(errors="replace").splitlines():
        f = line.split("\t")
        if len(f) < 4 or "\t" not in line:
            continue
        t = un.get(f[0].lower())
        if not t or (types and t not in types):
            continue
        g[(t, f[2], f[3])] += 1
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="")
    ap.add_argument("--top", type=int, default=0, help="only the N biggest groups")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    types = {t.strip() for t in a.types.split(",") if t.strip()}
    un = unresolved()
    g = groups(un, types)
    print(f"unresolved {len(un)}   groups {len(g)}", file=sys.stderr)
    for (t, p, b), k in g.most_common(a.top or len(g)):
        print(f"   {k:5d}  {t:16s} {p:36s} {b}", file=sys.stderr)
    if a.dry_run:
        return 0

    hits: list[tuple[str, str]] = []
    bundles = sorted({b for (_, _, b), _ in
                      ((k, v) for k, v in g.most_common(a.top or len(g)))})
    for b in bundles:
        p = CONTENTS / b
        if not p.exists():
            print(f"   {b}: missing file", file=sys.stderr)
            continue
        data = p.read_bytes()
        seen: set[int] = set()
        n_str = 0
        i = 0
        while True:
            j = data.find(bytes([0x78, 0x9C]), i)
            if j < 0:
                break
            i = j + 1
            d = zlib.decompressobj()
            try:
                out = d.decompress(data[j:j + 8_000_000], 6_000_000)
            except zlib.error:
                continue
            if len(out) < 256:
                continue
            for m in RUN.finditer(out):
                run = m.group().decode("ascii", "replace")
                for w in WORDS.findall(run) + CHAINS.findall(run):
                    if hash(w) in seen:
                        continue
                    if len(seen) < 2_000_000:
                        seen.add(hash(w))
                    n_str += 1
                    h = f"{murmur_hash64(w):016x}"
                    if h in un:
                        hits.append((h, w))
        print(f"   {b} {len(data)/1e6:5.1f}MB strings {n_str:7d} hits-so-far {len(hits)}",
              file=sys.stderr)
    print(f"HITS {len(hits)}", file=sys.stderr)
    for h, n in hits:
        print(f"   {h}  {un[h]:16s} {n}")
    if a.write and hits:
        with open(HC / "matches.tsv", "a", encoding="utf-8") as fh:
            for h, n in hits:
                fh.write(f"{h}\t{n}\n")
        print(f"appended {len(hits)} to {HC / 'matches.tsv'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
