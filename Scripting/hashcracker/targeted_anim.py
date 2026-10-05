#!/usr/bin/env python3
"""
Context-driven animation candidates.

A blind sweep is `parents x tokens x tokens x tokens` (~1e12) which is far too
slow even on the GPU. But we already know, for every unresolved animation hash,
exactly which unit plays it (extract_anim_refs.py -> anim_map.json), and we know
every clip that unit already has. So:

    candidate = <unit_dir>/animations/<observed_prefix>_<t2>[_<t3>]

i.e. the first token is constrained to prefixes that unit really uses
(`lich` -> spell_*, `boss_mummy` -> ability_*), leaving only 1-2 free tokens
from the global clip vocabulary. That is ~1e4-1e6 candidates per unit instead of
1e12 overall.

Writes a plain candidate list for `hashcracker crack --candidates`.

Usage:
    python3 targeted_anim.py [--out /tmp/anim_cands.txt] [--max-third N]
"""
import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GD = HERE.parent / "GauntletGameDigging"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay", default=str(GD / "resource_name_overlay.json"))
    ap.add_argument("--csv", default=str(GD / "bundle_manifest" / "04_bundle_resources.csv"))
    ap.add_argument("--map", default=str(HERE / "data" / "vocab" / "anim_map.json"))
    ap.add_argument("--out", default="/tmp/anim_cands.txt")
    ap.add_argument("--max-third", type=int, default=4000,
                    help="how many third tokens to try after a known prefix")
    ap.add_argument("--max-prefix", type=int, default=12)
    ap.add_argument("--max-own", type=int, default=40)
    ap.add_argument("--max-heads", type=int, default=60)
    ap.add_argument("--max-tails", type=int, default=60)
    args = ap.parse_args()

    ov = json.loads(Path(args.overlay).read_text())
    anim_map = json.loads(Path(args.map).read_text())

    rows = list(csv.DictReader(open(args.csv, newline="", encoding="utf-8")))
    anim_int = {r["name_hash"] for r in rows if r["type"] == "animation"}
    unresolved = {r["name_hash"] for r in rows
                  if r["type"] == "animation" and r["name_hash"] not in ov}

    # global clip vocabulary, sorted by frequency across every solved clip
    global_toks = collections.Counter()
    for n in ov.values():
        if "/animations/" in n or "/animation/" in n:
            global_toks.update(n.rsplit("/", 1)[1].split("_"))
    vocab = [t for t, _ in global_toks.most_common()]
    free = vocab[: args.max_third]
    # every clip leaf we already know anywhere (for cross-unit transfer)
    all_leaves = sorted({n.rsplit("/", 1)[1] for n in ov.values()
                         if "/animations/" in n or "/animation/" in n})

    # modifiers that appear all over the clip corpus
    MODS = ("left right back front up down in out forward backward start end begin stop "
            "loop run walk idle hit death spawn attack ability spell move cast dive appear "
            "disappear windup winddown exit enter light heavy special normal default "
            "01 02 03 04 1 2 3 left_back right_back left_front right_front look").split()

    out = set()
    per_dir = collections.Counter()
    for unit_dir, hashes in anim_map.items():
        left = sorted(set(hashes) & unresolved)
        if not left:
            continue
        known = [n for h, n in ((h, ov.get(h)) for h in hashes) if n]
        own = collections.Counter()
        for n in known:
            own.update(n.rsplit("/", 1)[1].split("_"))
        toks = sorted(set(t for t, _ in own.most_common()) | set(MODS)
                      | {t for t, _ in global_toks.most_common(60)})[: args.max_tails]
        bases = (f"{unit_dir}/animations", f"{unit_dir}/animation")

        def emit(tl):
            leaf = "_".join(tl)
            if not leaf or len(leaf) > 90:
                return
            for b in bases:
                out.add(f"{b}/{leaf}")

        # edit-distance-1 from the unit's OWN clips: replace / insert / delete / append
        for n in known:
            tl = n.rsplit("/", 1)[1].split("_")
            for i in range(len(tl)):                       # replace token i
                for t in toks:
                    emit(tl[:i] + [t] + tl[i + 1:])
            for i in range(len(tl) + 1):                   # insert a token
                for t in toks:
                    emit(tl[:i] + [t] + tl[i:])
            for i in range(len(tl)):                       # delete token i
                emit(tl[:i] + tl[i + 1:])
        # the unit's own prefix + up to two more tokens
        prefixes = [p for p, _ in own.most_common()][: args.max_prefix]
        for b in bases:
            for p in prefixes:
                for a in toks[: args.max_heads]:
                    emit([p, a])
                    for c in toks[:40]:
                        emit([p, a, c])

        # cross-unit transfer: another unit's clip, optionally re-prefixed with
        # one of this unit's own prefixes (warrior axe_move_* <-> wizard staff_*)
        for leaf in all_leaves:
            emit(leaf.split("_"))
            tl = leaf.split("_")
            if len(tl) > 1:
                for p in prefixes[:6]:
                    emit([p] + tl[1:])
        per_dir[unit_dir] = len(left)

    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"units with unresolved clips : {len(per_dir)}")
    print(f"unresolved clips covered    : {sum(per_dir.values())}")
    print(f"candidates written          : {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
