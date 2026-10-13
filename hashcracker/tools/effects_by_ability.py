#!/usr/bin/env python3
"""Hunt hero VFX with the *ability* vocabulary (FINDINGS 67).

`effects/<prefix>_<faction>_<ability>_<phase>` is the shape of the game's effect names -

    effects/wep_elf_arrow_snipershot_pierce_trail
    effects/wep_necromagus_heavy_shadowbolt_hit
    effects/wep_necromagus_ultimate_remnant_explode
    effects/cha_spider_queen_egg_projectile_trail
    effects/cha_cultist_sorcerer_beam_windup

- and `tools/effects_family.py` already sweeps that shape with the *unit* vocabulary.  That
is the wrong half of the sentence: it scored 0 across all ten prefixes and 2.7 M candidates
each, while the same shape driven by the *ability* names we already hold (every leaf under
`characters/*/abilities/`, `*/animations/`, `*/weapons/`, plus every prefix and suffix of
those leaves) named eight effects in one run.

The tails are the tails of the effects we hold (474 of them), the factions are the hero and
enemy families, the prefixes are every `effects/<p>_` family in the corpus.  The engine's
pattern mode does the whole product at ~2.4e9 candidates/s, so no candidate file is written:

    python3 tools/effects_by_ability.py --run        # eight engine passes
    python3 tools/effects_by_ability.py --list       # just report the vocabularies

The follow-ups that are *closed* (all 0) are recorded in FINDINGS 67.3: weapon/item stems in
the faction slot, a second tail token, ability-before-faction, and every effect texture
derivation from its referrer.
"""
import argparse
import collections
import csv
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
HCBIN = HC / "target" / "release" / "hashcracker"
TARGETS = HC / "data" / "vocab" / "unresolved_targets.txt"
FACTIONS = [
    "elf", "warrior", "wizard", "valkyrie", "necromagus", "summoned_valkyrie",
    "summoned_soldier", "summoned_archer", "skeleton", "skeleton_warrior",
    "skeleton_soldier", "skeleton_commander", "cultist", "cultist_novice",
    "cultist_sorcerer", "cultist_armor", "cultist_zealot", "orc", "orc_melee",
    "orc_juggernaut", "mummy", "mummy_risen", "mummy_priest", "mummy_giant",
    "mummy_bloated", "demon", "demon_ranged", "demon_heavy", "demon_melee", "grunt",
    "grunt_shaman", "grunt_scavenger", "spider", "spider_warrior", "spider_queen",
    "boss", "beast", "lich", "morak", "orox", "ghost", "necromancer", "wisp",
    "illusion", "trap", "elemental", "treasure",
]


def vocab():
    rows = list(csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace")))
    named = sorted({r["name"] for r in rows if r["name"]})
    abilities, effects = set(), []
    for n in named:
        if "/abilities/" in n or "/animations/" in n or "/weapons/" in n:
            leaf = re.sub(r"_(diff|norm|spec|hm|illu)$", "", n.rsplit("/", 1)[1])
            bits = leaf.split("_")
            abilities.add(leaf)
            abilities |= {"_".join(bits[:i]) for i in range(2, len(bits) + 1)}
            abilities |= {"_".join(bits[i:]) for i in range(len(bits))}
        if n.startswith("effects/") and n.count("/") == 1:
            effects.append(n.rsplit("/", 1)[1])
    tails = collections.Counter(t for e in effects for t in e.split("_")[1:] if len(t) > 2)
    prefs = collections.Counter(e.split("_")[0] for e in effects)
    return (sorted(a for a in abilities if len(a) > 2),
            [t for t, _ in tails.most_common(474)],
            [p for p, c in prefs.most_common() if len(p) > 1 and c >= 3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="run the engine passes")
    ap.add_argument("--list", action="store_true", help="report the vocabularies")
    args = ap.parse_args()
    abilities, tails, prefixes = vocab()
    print(f"ability stems {len(abilities)}  tails {len(tails)}  prefixes {len(prefixes)}  "
          f"factions {len(FACTIONS)}")
    print(f"space: {len(prefixes) * len(FACTIONS) * len(abilities) * len(tails):.3e} candidates")
    if not args.run:
        return
    tmp = pathlib.Path("/tmp")
    (tmp / "efa_p.txt").write_text("\n".join(prefixes) + "\n")
    (tmp / "efa_h.txt").write_text("\n".join(FACTIONS) + "\n")
    (tmp / "efa_a.txt").write_text("\n".join(abilities) + "\n")
    (tmp / "efa_t.txt").write_text("\n".join(tails) + "\n")
    import subprocess
    for pattern in ("effects/%p_%h_%a_%t", "effects/%p_%h_%a", "effects/%p_%a_%t"):
        print(f"### {pattern}")
        subprocess.run([str(HCBIN), "crack", "--cpu", "--targets", str(TARGETS),
                        "--list", f"p={tmp / 'efa_p.txt'}", "--list", f"h={tmp / 'efa_h.txt'}",
                        "--list", f"a={tmp / 'efa_a.txt'}", "--list", f"t={tmp / 'efa_t.txt'}",
                        "--pattern", pattern, "--matches", str(HC.parent / "Data" / "matches.tsv")], check=False)


if __name__ == "__main__":
    main()
