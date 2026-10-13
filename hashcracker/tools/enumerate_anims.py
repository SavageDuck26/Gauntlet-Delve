#!/usr/bin/env python3
"""Enumerate the locomotion/combat animation grammar, per unit.

    python3 tools/enumerate_anims.py | python3 tools/check_names.py --write

`characters/avatar_valkyrie/animations/move_jog_look_left_back` (FINDINGS 61.9) is
not a word we could have guessed token by token - it is a *sentence*:

    move_<gait>_<action>_<direction>[_back]

so once one member of the family is known the rest is a small product, and it is
the same sentence for every unit: a boss's walk set and a hero's walk set are
spelled with the same vocabulary.  The other animation sentences that we can read
off the held names are enumerated here too:

    attack_<weapon|verb>[_<direction>][_<NN>]      turn_<direction>_<angle>
    death_<direction>[_<NN>]                       hit_<direction>[_<NN>]
    <verb>_offset_<NN> / _offset<NN> / _offset      <verb>_windup/_winddown
    block_<direction>_<NN>                         <verb>_<NN>_start / _NN
    ability_<ability name we hold for any unit>    spawn/_appear/_summon_<direction>

Both directory spellings are used by the game (`animations/` and `animation/`).
"""
from __future__ import annotations

import itertools
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
REPO_SRC = REPO / "game-source" / "Gauntlet-SourceCode-LUA"
sys.path.insert(0, str(HERE))
from named_textures import load_names                                 # noqa: E402

GAITS = ["jog", "run", "walk", "sprint", "strafe", "dash", "backdash", "hop",
         "creep", "sneak", "charge", "shuffle", "step", "leap", "roll", "slide"]
ACTIONS = ["look", "break", "turn", "start", "stop", "lean", "aim", "shoot",
           "attack", "dodge", "jump", "land", "fall", "crouch", "skid", "vault",
           "idle", "go", "enter", "exit", "loop", "settle", "windup", "winddown"]
DIRS = ["left", "right", "forward", "back", "backward", "up", "down", "left30",
        "right30", "left45", "right45", "left90", "right90", "left180", "right180"]
WEAPONS = ["sword", "axe", "mace", "spear", "staff", "wand", "bow", "crossbow",
           "dagger", "shield", "fist", "claw", "bite", "chomp", "tail", "horn",
           "slam", "stomp", "slash", "stab", "bash", "punch", "kick", "shoot",
           "cast", "spit", "spike", "beam", "wave", "chop", "thrust", "swipe"]
VERBS = ["idle", "walk", "run", "attack", "death", "hit", "block", "spawn",
         "appear", "summon", "cast", "roar", "stun", "taunt", "victory", "defeat",
         "sleep", "wakeup", "dormant", "revive", "heal", "dance", "sit", "gib"]
ANGLES = ["45", "90", "135", "180", "270", "30", "60", "120", "360"]
NN = [f"{i:02d}" for i in range(1, 7)]


def main() -> int:
    names = sorted(set(load_names(all_types=True).values()))
    units = sorted({n.split("/")[1] for n in names
                    if n.startswith("characters/") and n.count("/") > 1})
    # The Lua's generated lists carry units we do not hold yet
    # (`characters/<unit>/<unit stem>` in characters_unit_path.lua, the unit paths
    # in settings_paths.lua), so the unit axis is not a function of our names.
    for f in ("characters_unit_path.lua", "settings_paths.lua", "unit_paths.lua",
              "spawners_unit_path.lua"):
        p = REPO_SRC / "lua" / "generated" / f
        if not p.exists():
            continue
        for s in re.findall(r'"characters/([a-z0-9_]+)/',
                            p.read_text(encoding="utf-8", errors="replace")):
            if s not in units:
                units.append(s)
    units = sorted(set(units))
    # the ability vocabulary is per unit, so every unit gets the union - a boss
    # reuses hero ability names and vice versa
    abilities = sorted({n.rsplit("/", 1)[-1] for n in names
                        if "/abilities/" in n or "/ability/" in n})
    leafless = sorted({n.rsplit("/", 1)[-1] for n in names
                       if "/animations/" in n or "/animation/" in n})
    offsets = [""] + [f"_offset_{x}" for x in NN] + [f"_offset{x}" for x in NN] \
                  + ["_offset", "_offset01", "_offset02"]

    out = sys.stdout

    def emit(d: str, stem: str) -> None:
        # NB no `seen` set: the candidate stream is millions of names and holding
        # them all is what OOMs the box.  `check_names.py` hashes each line, so a
        # duplicate only costs the hash.
        out.write(d + stem + "\n")

    # The shipped Lua names animation *events* (`charselect_turn`,
    # `spearthrust_impale`) and the equipment tables name ability animations
    # (`animation = "ability_talisman_03"`), so Lua leaves are a vocabulary the
    # per-unit grammar can be crossed with - something the held leaves alone
    # cannot do, because the leaves we hold are exactly the ones we already have.
    LUA = pathlib.Path(REPO_SRC)
    lua_leaves = set()
    if LUA.exists():
        for p in LUA.rglob("*.lua"):
            for s in re.findall(r'"([a-z0-9_]{4,60})"',
                                p.read_text(encoding="utf-8", errors="replace")):
                lua_leaves.add(s)
            for s in re.findall(r'^\s*([a-z0-9_]{4,60})\s*=\s*[{"]',
                                p.read_text(encoding="utf-8", errors="replace"),
                                re.M):
                lua_leaves.add(s)

    for u in units:
        for sub in ("animations/", "animation/"):
            d = f"characters/{u}/{sub}"
            for gait, act, dr in itertools.product(GAITS, ACTIONS, DIRS):
                for back in ("", "_back"):
                    emit(d, f"move_{gait}_{act}_{dr}{back}")
                    emit(d, f"{act}_{gait}_{dr}{back}")
            for g, a in itertools.product(GAITS, ACTIONS):
                emit(d, f"move_{g}")
                emit(d, f"move_{g}_{a}")
                emit(d, f"move_{a}_{g}")
            for w, dr in itertools.product(WEAPONS, [""] + DIRS):
                emit(d, f"attack_{w}" + (f"_{dr}" if dr else ""))
                for nn in NN[:3]:
                    emit(d, f"attack_{w}" + (f"_{dr}" if dr else "") + f"_{nn}")
            for v in VERBS:
                for o in offsets:
                    emit(d, f"{v}{o}")
                for dr in DIRS:
                    emit(d, f"{v}_{dr}")
                    for nn in NN[:3]:
                        emit(d, f"{v}_{dr}_{nn}")
                for nn in NN:
                    emit(d, f"{v}_{nn}")
                    emit(d, f"{v}_{nn}_start")
                    emit(d, f"{v}_{nn}_end")
                emit(d, f"block_{v}")
            for dr, ang in itertools.product(DIRS, ANGLES):
                emit(d, f"turn_{dr}_{ang}")
                emit(d, f"turn_{ang}_{dr}")
                emit(d, f"turn_{ang}")
            for a in abilities:
                emit(d, a)
            for l in leafless:
                emit(d, l)

    # Unit *variants* are separate units with their own animation sets: the game
    # names them `boss_morak_sword` (a second weapon state) and the avatars have
    # `avatar_necromagus_summoned_archer`.  So every unit's stem set belongs to each
    # of its variants as well.
    VARIANTS = ["sword", "shield", "scepter", "staff", "bow", "axe", "mace", "dagger",
                "alt", "mini", "boss", "elite", "summoned", "summoned_archer",
                "summoned_ghost", "summoned_soldier", "transformed", "normal", "armed",
                "mount", "rider", "pet", "enraged", "shielded", "armored"]
    unit_leaves: dict[str, set[str]] = {}
    for n in names:
        if n.startswith("characters/") and n.count("/") > 1:
            unit_leaves.setdefault(n.split("/")[1], set()).add(n.rsplit("/", 1)[-1])
    for u in units:
        for v in VARIANTS:
            for sub in ("animations/", "animation/"):
                for l in leafless:
                    emit(f"characters/{u}_{v}/{sub}", l)
                for l in sorted(unit_leaves.get(u, ())):
                    emit(f"characters/{u}_{v}/{sub}", l)

    # Body parts and the character-select family: `talisman_03_lowerbody` and
    # `charselect_01_directional_left` (61.10) are the same sentence with two more
    # slots - a body part, and a screen-side prefix.
    BODY = ["lowerbody", "upperbody", "fullbody", "torso", "arms", "legs", "head",
            "skirt", "cape", "cloth", "weapon", "attach", "socket", "root", "base"]
    CSACT = ["directional", "idle", "turn", "pose", "ready", "loop", "select",
             "deselect", "highlight", "hover", "confirm", "turnleft", "turnright"]
    for u in units:
        for sub in ("animations/", "animation/"):
            d = f"characters/{u}/{sub}"
            for l in leafless:
                stem = l.rsplit("_", 1)[0]
                for b in BODY:
                    emit(d, f"{l}_{b}")
                    emit(d, f"{stem}_{b}")
            for nn in NN[:4]:
                for a, dr in itertools.product(CSACT, [""] + DIRS[:8]):
                    emit(d, f"charselect_{nn}_{a}" + (f"_{dr}" if dr else ""))
                    emit(d, f"character_select_{nn}_{a}" + (f"_{dr}" if dr else ""))
                emit(d, f"charselect_{nn}")
        for v in VARIANTS:
            for sub in ("animations/", "animation/"):
                for nn in NN[:4]:
                    for a, dr in itertools.product(CSACT, [""] + DIRS[:8]):
                        emit(f"characters/{u}_{v}/{sub}",
                             f"charselect_{nn}_{a}" + (f"_{dr}" if dr else ""))

    # Lua leaves (above) crossed with the slots we can read off the held names:
    # `<ability>_<body>` is the shape of the one animation leaf that was recovered
    # from the source side (`talisman_03_lowerbody`), and the Lua's animation /
    # event vocabulary is the only vocabulary that is not a function of the names
    # we already hold.
    for u in units:
        for sub in ("animations/", "animation/"):
            d = f"characters/{u}/{sub}"
            for l in sorted(lua_leaves):
                emit(d, l)
                for b in BODY:
                    emit(d, f"{l}_{b}")
                for a in ACTIONS:
                    emit(d, f"{l}_{a}")

    print(f"candidates streamed over {len(units)} units, "
          f"{len(abilities)} abilities, {len(lua_leaves)} lua leaves",
          file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
