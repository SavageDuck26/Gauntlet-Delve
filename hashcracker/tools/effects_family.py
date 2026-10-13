#!/usr/bin/env python3
"""
Enumerate an `effects/<prefix>_` family from the names we already hold.

`effects/` is the `particles` type and it is written as a *sentence* -

    effects/cha_beast_leap_shockwave
    effects/cha_cultist_sorcerer_beam_windup
    effects/cha_skeleton_archer_aim_marker      (found by this tool)
    effects/cha_necromagus_light_attack_burst   (found by the GPU box)
    effects/boss_circle_turn_outer

- so every family member is `<prefix>_<stem>_<action>[_<phase>]` and both halves are
recoverable: the stems are the unit directories (and their tokens), the actions are
the tails of the family members we hold, the animation leaves the units play, and a
verb x noun cross, and the phases are mined from the family itself
(`marker`/`tell`/`trail`/`windup`/`burst`/`spawn`/`destroy`/`2c`/`4c`/...).

Self-feeding by construction: the stem/action/phase pools are read from the overlay
and `matches.tsv` on every run, so a name found by the engine becomes a stem for the
next pass.  Streams to stdout for `tools/check_names.py` (memory flat - it never
remembers a candidate).

    python3 tools/effects_family.py [--prefix cha] [--min-stem 4] [--verbose] \\
        | python3 tools/check_names.py --write
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
SRC = REPO / "game-source" / "Gauntlet-SourceCode-LUA"
sys.path.insert(0, str(HERE))
from named_textures import load_names                                 # noqa: E402

PHASES = ["marker", "tell", "trail", "windup", "winddown", "burst", "hit", "impact",
          "cast", "spawn", "death", "destroy", "vanish", "land", "step", "target",
          "shockwave", "smash", "charge", "start", "end", "loop", "idle", "enter",
          "exit", "complete", "timer", "ground", "interrupt", "damage", "recover",
          "explode", "shatter", "fade", "return", "finish", "2c", "4c", "8c"]
VERBS = ["aim", "attack", "bash", "beam", "bite", "blast", "block", "burst", "cast",
         "charge", "chomp", "claw", "death", "dive", "drain", "enter", "exit",
         "explode", "fall", "fire", "flame", "grab", "heal", "hit", "howl", "jump",
         "kick", "land", "leap", "light", "heavy", "melee", "open", "punch", "raise",
         "roar", "shoot", "shout", "slash", "smash", "spawn", "spike", "spit",
         "splash", "stab", "stomp", "summon", "swipe", "swing", "throw", "vanish"]
NOUNS = ["attack", "shot", "ball", "bolt", "arrow", "sword", "axe", "fire", "ice",
         "beam", "wave", "aura", "glow", "heart", "book", "shield", "summon", "spawn",
         "soul", "bone", "rock", "ground", "air", "spin", "slam", "punch", "swipe",
         "tail", "horn", "claw", "circle", "marker", "tell", "trail", "burst"]


def stems() -> list[str]:
    """Unit directories (with and without `avatar_`), their tokens, and Lua units."""
    out = set()
    for n in load_names(all_types=True).values():
        if n.startswith("characters/") and n.count("/") > 1:
            u = n.split("/")[1]
            out.add(u)
            out.update(t for t in u.split("_") if len(t) > 3)
            if u.startswith("avatar_"):
                out.add(u[7:])
    for f in ("characters_unit_path.lua", "settings_paths.lua", "unit_paths.lua",
              "unit_path_to_components.lua", "spawners_unit_path.lua"):
        p = SRC / "lua" / "generated" / f
        if not p.exists():
            continue
        for u in re.findall(r'"characters/([a-z0-9_]+)/"', p.read_text(encoding="utf-8", errors="replace")):
            out.add(u)
            out.update(t for t in u.split("_") if len(t) > 3)
            if u.startswith("avatar_"):
                out.add(u[7:])
    return sorted(s for s in out if len(s) > 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", action="append", default=[],
                    help="family prefix(es); default: every `effects/<x>_` seen")
    ap.add_argument("--min-stem", type=int, default=4)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    names = sorted(set(load_names(all_types=True).values()))
    eff = [n[len("effects/"):] for n in names if n.startswith("effects/")]
    if not a.prefix:
        pfxs = sorted({e.split("_")[0] for e in eff if "_" in e})
    else:
        pfxs = a.prefix
    leaves = sorted({n.rsplit("/", 1)[-1] for n in names
                     if "/animations/" in n or "/animation/" in n})
    st = sorted(s for s in stems() if len(s) >= a.min_stem)

    out = sys.stdout
    seen_line = 0

    def emit(name: str) -> None:
        nonlocal seen_line
        out.write(name + "\n")
        seen_line += 1

    for pfx in pfxs:
        members = [e for e in eff if e.startswith(pfx + "_")]
        tails = set()
        for leaf in members:
            parts = leaf.split("_")
            for i in range(1, len(parts)):
                tails.add("_".join(parts[i:]))
        for s in st:
            for t in sorted(tails):
                emit(f"effects/{pfx}_{s}_{t}")
            for l in leaves:
                emit(f"effects/{pfx}_{s}_{l}")
                for ph in PHASES:
                    emit(f"effects/{pfx}_{s}_{l}_{ph}")
            for v in VERBS:
                emit(f"effects/{pfx}_{s}_{v}")
                for no in NOUNS:
                    emit(f"effects/{pfx}_{s}_{v}_{no}")
    print(f"{seen_line:,} candidates, prefixes {len(pfxs)}, stems {len(st)}, "
          f"leaves {len(leaves)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
