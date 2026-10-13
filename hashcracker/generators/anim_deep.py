#!/usr/bin/env python3
"""
Deep per-unit animation clip generation.

The wide edit-distance-1 sweep keeps paying (+8, +9), and the clips it finds
have a very regular per-unit grammar:

    <prefix>_<verb>[_<modifier>][_<speed>][_<direction>[_<direction2>]]
      bow_move_run_backwards_left, axe_attack_heavy3_chop, legs_turn_left-60,
      spear_attack_heavy1, walk_strafe_left, die_default1

so instead of editing existing clips we rebuild them from each unit's OWN
vocabulary: its clip prefixes, its own tokens, the shared verb list, speed words
and direction words.  Everything is derived from the unit itself, which is why
it generalises across units.

    python3 generators/anim_deep.py [--seeds FILE] [--out FILE] [--cap N]
"""
import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DIG = REPO / "Data"
CATALOGUE = DIG / "bundle_manifest/04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

VERB = """move attack idle walk run jog sprint dash jump land hit die death react
carry throw pickup drop cast shoot aim draw sheathe reload block dodge parry
guard stagger stun knockback slide smash whirlwind chop stab swing thrust
turn strafe look taunt celebrate victory revive spawn summon charge windup
winddown blink leap climb crouch slide_02 roll emote point wave drink eat
sit stand crouch panic flee roar shout laugh cheer""".split()
SPEED = ["walk", "run", "jog", "sprint", "dash", "fast", "slow", "normal"]
DIR = ["left", "right", "forward", "backwards", "backward", "in", "out", "up",
       "down", "left_back", "right_back", "left_front", "right_front"]
MOD = ([f"{i:02d}" for i in range(1, 5)] + [f"fast{i}" for i in range(1, 5)]
       + [f"slow{i}" for i in range(1, 3)] + [f"light{i}" for i in range(1, 4)]
       + [f"heavy{i}" for i in range(1, 4)] + ["default", "default1", "offset",
       "offset1", "windup", "winddown", "loop", "start", "end", "30", "-30", "45",
       "-45", "60", "-60", "90", "-90", "180"])


TWO = ([f"{i:02d}" for i in range(1, 5)] + DIR
       + ["run", "walk", "jog", "sprint", "default", "windup", "winddown",
          "light", "heavy", "fast", "slow"])


def derive_two_token(focus_units, clips_by_unit, per_unit):
    """
    Insert TWO tokens (direction/number/speed) into each of a unit's own clips,
    at every position pair.  This is the shape the wide edit-1 sweep kept
    finding one token at a time (`bow_move_run_backwards_left`).
    """
    out = set()
    for d in focus_units:
        clips = clips_by_unit.get(d, [])
        made = 0
        for clip in clips:
            tl = clip.split("_")
            for i in range(len(tl) + 1):
                for x in TWO:
                    for j in range(i, len(tl) + 2):
                        for y in TWO:
                            out.add(f"{d}/" + "_".join(tl[:i] + [x] + tl[i:j] + [y] + tl[j:]))
                            made += 1
                            if made > per_unit:
                                return out
    return out

def known_names(seeds=None):
    names = set(json.loads(OVERLAY.read_text()).values())
    for r in csv.DictReader(CATALOGUE.open()):
        if r["name"]:
            names.add(r["name"])
    if seeds:
        names |= {l.split("\t", 1)[1].strip() for l in
                  Path(seeds).read_text().splitlines() if "\t" in l}
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds")
    ap.add_argument("--out", default="/tmp/anim_deep.txt")
    ap.add_argument("--per-unit", type=int, default=600_000)
    ap.add_argument("--two-token", action="store_true")
    args = ap.parse_args()

    names = known_names(args.seeds)
    by_unit = collections.defaultdict(list)
    for n in names:
        if "/animations/" not in n and "/animation/" not in n:
            continue
        d, _, leaf = n.rpartition("/")
        by_unit[d].append(leaf)

    # focus on units that actually own unresolved clips, when we know them
    focus = None
    amap = HERE.parent / "data/vocab/anim_map.json"
    if amap.exists():
        focus = set(json.loads(amap.read_text()))

    out = set()
    per_form = (1 + len(MOD) + len(SPEED) * (1 + len(DIR) * len(DIR))
                + len(DIR) * (1 + DIR.__len__()))
    for d, clips in by_unit.items():
        if focus is not None and d.rsplit("/", 1)[0] not in focus:
            continue
        pre = collections.Counter(c.split("_")[0] for c in clips)
        prefixes = [p for p, _ in pre.most_common(4)]
        own = collections.Counter()
        for c in clips:
            own.update(t for t in c.split("_") if t and not t.isdigit())
        budget = max(2, args.per_unit // max(1, len(prefixes) * per_form))
        pool = ([t for t, _ in own.most_common(40)] + VERB)[:budget]
        for p in prefixes:
            for v in pool:
                out.add(f"{d}/{p}_{v}")
                for m in MOD:
                    out.add(f"{d}/{p}_{v}_{m}")
                for s in SPEED:
                    out.add(f"{d}/{p}_{v}_{s}")
                    for x in DIR:
                        out.add(f"{d}/{p}_{v}_{s}_{x}")
                        for y in DIR:
                            if x != y:
                                out.add(f"{d}/{p}_{v}_{s}_{x}_{y}")
                for x in DIR:
                    out.add(f"{d}/{p}_{v}_{x}")
                    for y in DIR:
                        if x != y:
                            out.add(f"{d}/{p}_{v}_{x}_{y}")
    if args.two_token:
        from collections import defaultdict as _dd
        clips_by_unit = _dd(list)
        for n in names:
            if "/animations/" in n or "/animation/" in n:
                dd_, _, lf = n.rpartition("/")
                clips_by_unit[dd_].append(lf)
        out |= derive_two_token([u for u in clips_by_unit
                                 if focus is None or u.rsplit("/", 1)[0] in focus],
                                clips_by_unit, args.per_unit)
    new = sorted(n for n in out if n not in names)
    Path(args.out).write_text("\n".join(new) + "\n")
    print(f"units {len(by_unit)}  candidates {len(new)} -> {args.out}")


if __name__ == "__main__":
    main()
