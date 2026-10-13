#!/usr/bin/env python3
"""
Per-target guess patterns driven by the reference twin (FINDINGS.txt §44).

`hunt_level_refs.py --twin` finds the resolved level whose *reference set* is
most similar to an unresolved one, which names its family.  This turns each
target + twin into cracker patterns that keep the twin's exact prefix (env,
subdir, shape, cells, number) and vary only the tail:

    <twin dir>/<twin leaf>_%m              append a token
    <twin dir>/<leaf minus last token>_%m  replace the last token
    <twin dir>/<leaf minus 2 tokens>_%m    replace the last two
    <twin dir>/<leaf minus 2 tokens>_%m_%m2

with `%m` a few-hundred-thousand-word list.  Also emits size-twin patterns (a
level body's size is nearly a function of its name, so the same-size neighbours
are structural twins too).

    python3 tools/make_guess_patterns.py [--out FILE] [--twins FILE] [--size-twins]
"""
import argparse
import bisect
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "family" /
                                         "guess_patterns.txt"))
    ap.add_argument("--twins", default=str(HC / "work" / "level_twins.txt"))
    ap.add_argument("--size-twins", type=int, default=3)
    ap.add_argument("--window", type=int, default=64)
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    known, known_by_size = [], []
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if r.get("type") == "level" and n:
            known.append((int(r["body_size"]), n))
    known.sort()
    known_by_size = [s for s, _ in known]

    # best reference twin per target hash
    ref = {}
    target_sizes = {}
    try:
        lines = pathlib.Path(args.twins).read_text().splitlines()
    except OSError:
        lines = []
    cur = None
    for line in lines:
        m = re.match(r"^  ([0-9a-f]{16})  *(\d+)B", line)
        if m:
            cur = m.group(1)
            target_sizes[cur] = int(m.group(2))
            continue
        t = re.match(r"^        twin  ([\d.]+) \(\s*\d+ shared\)  (.*)$", line)
        if t and cur and cur not in ref:
            ref[cur] = t.group(2).strip()

    patterns = set()
    def add_from(seed):
        d, _, leaf = seed.rpartition("/")
        pre = d + "/" if d else ""
        toks = leaf.split("_")
        patterns.add(f"{pre}{leaf}_%m")
        for cut in (1, 2):
            if len(toks) > cut:
                stem = "_".join(toks[:-cut])
                patterns.add(f"{pre}{stem}_%m")
                patterns.add(f"{pre}{stem}_%m_%n")
                patterns.add(f"{pre}{stem}_%m_%n_%m")
                patterns.add(f"{pre}{stem}_%n_%m")
            if len(toks) > cut + 1:
                stem2 = "_".join(toks[:-cut - 1])
                patterns.add(f"{pre}{stem2}_%m_%m2")

    n = 0
    for h, name in ref.items():
        add_from(name)
        n += 1
        if not args.size_twins:
            continue
        sz = target_sizes.get(h)
        if sz is None:
            continue
        i = bisect.bisect_left(known_by_size, sz)
        picked = []
        for j in range(max(0, i - 10), min(len(known_by_size), i + 10)):
            if abs(known_by_size[j] - sz) <= args.window:
                picked.append((abs(known_by_size[j] - sz), known[j][1]))
        picked.sort()
        for _d, s in picked[:args.size_twins]:
            add_from(s)
    # every target still gets a bare-leaf guess
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sorted(patterns)) + "\n")
    print(f"targets with a ref twin {n}  patterns {len(patterns)}  -> {out}")


if __name__ == "__main__":
    main()
