#!/usr/bin/env python3
"""
Vocabularies for the particle sweep.

Resolved particles show the shape

    effects/<prefix>_<subject>_<verb>[_<modifier>]
      cha_beast_charge_step, cha_boss_mummy_heart_burst,
      cha_beast_fallingrock_marker, wep_..., gam_..., env_..., hud_...

with `effects` + `effects_ui` the only directories.  Prefixes are
cha/wep/gam/env/hud/... (character / weapon / gameobject / environment / hud),
the subject is the unit or weapon name, and the verb set is shared across the
whole family (`windup hit marker trail spawn glow charge burst explode ...`).

    python3 make_particles_vocab.py       # -> data/vocab/par_*.txt
"""
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
CATALOGUE = REPO / "Scripting/GauntletGameDigging/bundle_manifest/04_bundle_resources.csv"
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
OUT = HERE.parent / "data/vocab"

DIRS = ["effects", "effects_ui", "effects/meshes", "effects/ui", "particles",
        "particles/ui", "vfx", "fx"]
PRE = ["cha", "wep", "gam", "env", "hud", "ui", "mat", "prop", "trp", "abi",
       "skl", "itm", "shd", "drk", "sor"]
VERB = """windup winddown hit marker trail spawn glow charge burst explode
explosion impact projectile appear disappear death die destroy ground land
launch slash destroy_ground beam burning shockwave transform loop end start
step target tell footstep jump leap swipe shout chomp punch bash heart carry
cast summon teleport heal buff shield aura orb ring wave dust smoke spark
flame ice fire poison freeze shock lightning blood gib debris splash ripple
streak flash pulse sweep arc cone cylinder sphere box line ray bolt missile
arrow bullet bomb mine trap fire_spawn idle walk run hover rotate spin open
close break crack dissolve fade in out light dim flash_light glow_pulse
looping single multi add remove charge_up charge_down glint shimmer trail_02
over time spawn_02 death_02 hit_02 impact_02""".split()
MOD = """outer inner small big large huge tiny up down left right front back top
bottom mid middle forward backward horizontal vertical diagonal 01 02 03 04 05
06 07 08 red blue green gold dark light orange purple white grey gray yellow
a b c d loop start end one two three long short wide narrow thin thick""".split()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ov = json.loads(OVERLAY.read_text())
    rows = list(csv.DictReader(CATALOGUE.open()))
    type_of = {}
    for r in rows:
        type_of.setdefault(r["name_hash"], r["type"])

    subs, verbs, toks = collections.Counter(), collections.Counter(), collections.Counter()
    for h, n in ov.items():
        t = type_of.get(h)
        if t not in ("particles", "effects", "textures", "material", "unit"):
            continue
        leaf = n.rsplit("/", 1)[-1]
        parts = leaf.split("_")
        if t == "particles" and len(parts) >= 3:
            subs["_".join(parts[1:-1])] += 1          # <pre>_<subject>_<verbs>
            subs[parts[1]] += 1
            verbs[parts[-1]] += 1
            verbs[parts[-2]] += 1
        for x in parts:
            if x and not x.isdigit():
                toks[x] += 1
        if t in ("unit", "material", "textures"):
            subs[leaf] += 1

    def dump(fn, vals, cap=None):
        vals = list(dict.fromkeys(vals))
        if cap:
            vals = vals[:cap]
        (OUT / fn).write_text("\n".join(vals) + "\n")
        print(f"  {fn:18s} {len(vals):>6} entries")

    dump("par_dir.txt", DIRS)
    dump("par_pre.txt", PRE)
    dump("par_sub.txt", [s for s, _ in subs.most_common(700)] + MOD, cap=800)
    dump("par_verb.txt", VERB + [v for v, _ in verbs.most_common(160)], cap=260)
    dump("par_mod.txt", MOD + [t for t, _ in toks.most_common(120)], cap=200)


if __name__ == "__main__":
    main()
