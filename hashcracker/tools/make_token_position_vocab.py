#!/usr/bin/env python3
"""
Positional token vocabularies, for the leaf shapes beyond three tokens (section 53).

The run that produced the biggest haul yet (`dir%a_%b_%c`, +47) reached leaves of
three tokens after a known directory.  Four- and five-token leaves are the bulk
of what remains, and `dir x token^4` is 5.4e15 - out of the question.

But a leaf token is not drawn uniformly: the *position* it occupies has its own,
much smaller vocabulary.  Measured over the resolved leaves:

    len 4   |pos| = 131  245  334  283         -> 1.1e12 with 368 dirs (~10 min)
    len 5   |pos| =  59   80  126  170  144    -> 5.4e12                  (~48 min)
    len 6   |pos| =  16   20   29   34   38   36 -> 0.16e12               (~2 min)

so the idea that paid for three tokens extends to four and five for the cost of a
coffee.  Two wider variants guard against the obvious failure mode - a token that
is plausible in a position but has never yet been *seen* there:

  * last position from the full `tail` vocabulary instead of the position's own;
  * every position from a frequency-ranked list (`top<N>.txt`).

Generation is per length with its own slot letters; the sweep runs one crack per
length so the letters never have to be shared.

    python3 tools/make_token_position_vocab.py [--out DIR]
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
MAXLEN = 7
TOP = (40, 50, 60, 80, 100, 150, 200, 300, 500)


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
    ap.add_argument("--out", default=str(HC / "work" / "tokpos"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    names = resolved()
    pos = collections.defaultdict(lambda: collections.defaultdict(set))
    freq = collections.Counter()
    dirs = set()
    for n in names:
        d, _, leaf = n.rpartition("/")
        if not d:
            continue
        dirs.add(d + "/")
        lt = [t for t in SPLIT.split(leaf) if t]
        if not lt or len(lt) > MAXLEN:
            continue
        for i, t in enumerate(lt):
            pos[len(lt)][i].add(t)
            freq[t] += 1
    tail = set((HC / "work" / "tokcombo" / "tail.txt").read_text().split())
    dirs = sorted(dirs)
    (out / "tailall.txt").write_text("\n".join(sorted(tail)) + "\n")
    print(f"names {len(names):,}  dirs {len(dirs):,}  tail {len(tail):,}")

    freq_sorted = [t for t, _ in freq.most_common()]
    for n in TOP:
        (out / f"top{n}.txt").write_text("\n".join(freq_sorted[:n]) + "\n")

    total = 0
    tiers = []          # (name, candidates, pattern file, [slot list files])
    for L in range(4, MAXLEN + 1):
        if L not in pos:
            continue
        sizes, ok = [], True
        for i in range(L):
            vals = sorted(pos[L].get(i, ()))
            if not vals:
                ok = False
            sizes.append(len(vals))
            (out / f"pos{L}_{i}.txt").write_text("\n".join(vals) + "\n")
        if not ok:
            continue
        sl = "abcdefghij"[:L]
        pat = "".join(f"%{c}" + ("_" if i < L - 1 else "")
                      for i, c in enumerate(sl))
        (out / f"patterns_pos{L}.txt").write_text(
            "\n".join(f"{d}{pat}" for d in dirs) + "\n")
        prod = 1
        for s in sizes:
            prod *= s
        a = prod * len(dirs)
        tiers.append((f"pos{L}", a, f"patterns_pos{L}.txt",
                      [f"pos{L}_{i}.txt" for i in range(L)]))

        sl2 = "abcdefghij"[:L - 1]
        pat2 = "".join(f"%{c}" + ("_" if i < L - 2 else "")
                       for i, c in enumerate(sl2))
        (out / f"patterns_posbase{L}.txt").write_text(
            "\n".join(f"{d}{d.rstrip('/').rsplit('/', 1)[-1]}_{pat2}"
                      for d in dirs) + "\n")
        prod2 = 1
        for s in sizes[1:]:
            prod2 *= s
        b = prod2 * len(dirs)
        tiers.append((f"posbase{L}", b, f"patterns_posbase{L}.txt",
                      [f"pos{L}_{i}.txt" for i in range(1, L)]))

        (out / f"patterns_postail{L}.txt").write_text(
            "\n".join(f"{d}{pat}" for d in dirs) + "\n")
        prod3 = prod // max(sizes[-1], 1) * len(tail)
        c = prod3 * len(dirs)
        tiers.append((f"postail{L}", c, f"patterns_postail{L}.txt",
                      [f"pos{L}_{i}.txt" for i in range(L - 1)] + ["tailall.txt"]))
        print(f"  len {L}: pos {sizes}  A {a:,}  B {b:,}  C {c:,}")
        total += a + b + c

    for L, spec in {4: (100, 200, 300, "tail"),
                    5: (40, 60, 80, 100, "tail")}.items():
        if L not in pos:
            continue
        sl = "abcdefghij"[:L]
        pat = "".join(f"%{c}" + ("_" if i < L - 1 else "")
                      for i, c in enumerate(sl))
        (out / f"patterns_wide{L}.txt").write_text(
            "\n".join(f"{d}{pat}" for d in dirs) + "\n")
        (out / f"wide{L}_lists.txt").write_text(
            "\n".join(f"top{n}.txt" if isinstance(n, int) else "tailall.txt"
                      for n in spec) + "\n")
        prod = 1
        for n in spec:
            prod *= len(tail) if n == "tail" else len(freq_sorted[:n])
        print(f"  wide {L}: {spec}  x {len(dirs)} dirs = {prod * len(dirs):,}")
        total += prod * len(dirs)
        tiers.append((f"wide{L}", prod * len(dirs), f"patterns_wide{L}.txt",
                      [f"top{n}.txt" if isinstance(n, int) else "tailall.txt"
                       for n in spec]))

    # 5-token positional with ONLY the last slot widened to a frequency list:
    # pos5's last position holds 144 tokens, the full tail holds 1,300, and the
    # full widen (postail5, 48e12) is a 10-hour tier.  This is the middle ground.
    if 5 in pos:
        sl = "abcdefghij"[:5]
        pat = "".join(f"%{c}" + ("_" if i < 4 else "") for i, c in enumerate(sl))
        (out / "patterns_postail5top.txt").write_text(
            "\n".join(f"{d}{pat}" for d in dirs) + "\n")
        prod = 1
        for i in range(4):
            prod *= len(pos[5].get(i, ()))
        n = prod * len(freq_sorted[:300]) * len(dirs)
        tiers.append(("postail5top", n, "patterns_postail5top.txt",
                      [f"pos5_{i}.txt" for i in range(4)] + ["top300.txt"]))
        print(f"  postail5top: pos5_0..3 x top300  x {len(dirs)} dirs = {n:,}")
        total += n

    if 4 in pos:
        seps = ["___", "__/", "_/_", "_//", "/__", "/_/", "//_", "///"]
        pats = ["%a" + s[0] + "%b" + s[1] + "%c" + s[2] + "%d" for s in seps]
        (out / "patterns_free4.txt").write_text("\n".join(pats) + "\n")
        prod = 1
        for i in range(4):
            prod *= len(pos[4].get(i, ()))
        print(f"  free4 positional: {len(pats)} placements x {prod:,} = "
              f"{prod * len(pats):,}")
        total += prod * len(pats)
        tiers.append(("free4", prod * len(pats), "patterns_free4.txt",
                      [f"pos4_{i}.txt" for i in range(4)]))

    # manifest for the sweep: cheapest tier first, so a quick win lands early
    rows = []
    for name, n, pf, lists in sorted(tiers, key=lambda t: t[1]):
        rows.append("\t".join([name, str(n), pf] + lists))
    (out / "tiers.tsv").write_text("\n".join(rows) + "\n")
    print(f"total candidates {total:,}  "
          f"(~{total / 1.87e9 / 3600:.1f} h at 1.87 G/s)")
    print("tiers.tsv (cheapest first):")
    for name, n, _pf, _l in sorted(tiers, key=lambda t: t[1]):
        print(f"  {name:10s} {n:>18,}  ~{n / 1.87e9 / 60:6.1f} min")


if __name__ == "__main__":
    main()
