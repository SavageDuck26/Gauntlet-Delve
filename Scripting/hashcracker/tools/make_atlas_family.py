#!/usr/bin/env python3
"""
Per-atlas family recombination (FINDINGS.txt §48.4).

Each referring atlas is a directory, and the icons in it are *members of a
family*, so the resolved leaves of that directory carry the whole grammar:

    menu/level_select/level_button_adventure[_completed|_silver|_locked|_over]
    menu/level_select/flow_background_{horizontal,vertical}[_silver]
    menu/shop/shop_relic_tier_{1,2,3}      shop_item_background_{owned,equipped…}
    menu/hero_coins/{warrior,elf,…}_{colored,over,standard}

i.e. `<stem>[_<state>]`.  So for every atlas directory: take the stems and the
state suffixes seen in it (plus the global state set), and enumerate the cross
product - which is where the missing members are.

    python3 tools/make_atlas_family.py [--refs FILE] [--out DIR]
"""
import argparse
import collections
import csv
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
REFS = HC / "work" / "refs_texture.json"

STATES = ["completed", "silver", "silver_completed", "locked", "over", "down",
          "disabled", "up", "normal", "owned", "equipped", "active", "empty",
          "selected", "hover", "glow", "unlocked", "full", "half", "off", "on",
          "front", "back", "left", "right", "top", "bottom", "silver_locked"]
MOPS = ["", "_norm", "_diff", "_spec"]
# words the atlas families are built from (environments, classes, modes, tiers)
WORDS = ["caves", "crypt", "lava", "hub", "endless", "campaign", "tutorial",
         "adventure", "arena", "boss", "procedural", "colosseum", "silver",
         "gold", "bronze", "warrior", "wizard", "valkyrie", "elf",
         "necromagus", "lizard", "hero", "hero_coin", "coin", "level_button",
         "level_select", "flow_background", "hub_map", "relic", "relic_icon",
         "shop_relic", "shop_item", "item", "icon", "button", "frame",
         "background", "progressbar", "perk", "score", "badge", "title",
         "cape", "cape_background", "grade", "plate", "plate_background",
         "character_frame", "character_background", "new_arena", "shine",
         "padlock", "player_counter", "player", "gamepad", "talisman",
         "relics", "spell", "spells", "action", "ability"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", default=str(REFS))
    ap.add_argument("--out", default=str(HC / "work" / "atlasfam"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    names, unresolved = [], set()
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            names.append(n)
        else:
            unresolved.add(r["name_hash"].lower())

    by_dir = collections.defaultdict(list)
    for n in names:
        if "/" in n:
            by_dir[n.rsplit("/", 1)[0] + "/"].append(n.rsplit("/", 1)[-1])

    refs = json.loads(pathlib.Path(args.refs).read_text())
    atlases = collections.Counter()
    for h, rs in refs.items():
        if h in unresolved:
            for r in rs:
                atlases[r + "/"] += 1

    vocab = set()
    all_states = set(STATES)
    for d in atlases:
        leaves = by_dir.get(d, [])
        if not leaves:
            continue
        stems = set()
        states = set()
        for L in leaves:
            stems.add(L)
            for s in STATES:
                if L.endswith("_" + s):
                    stems.add(L[:-(len(s) + 1)])
                    states.add(s)
        all_states |= states
        # cross-dir stems: a `menu/shop/x` family also borrows `menu/*/shop_*`
        for n in names:
            if "/" not in n:
                continue
            dd, leaf = n.rsplit("/", 1)
            if dd == d.rstrip("/"):
                continue
            if d.rstrip("/").split("/")[-1] in dd:
                stems.add(leaf)
        states |= set(STATES)
        # global stem words these families use: environments, classes, modes
        stems |= set(WORDS)
        for st in stems:
            for s in states:
                vocab.add(f"{st}_{s}" if s else st)
                for m in MOPS:
                    if m:
                        vocab.add(f"{st}_{s}{m}" if s else f"{st}{m}")
            for k in range(1, 6):
                vocab.add(f"{st}_{k}")
                vocab.add(f"{st}_tier_{k}")
    vocab = sorted(v for v in vocab if len(v) > 3)
    pats = []
    for d in sorted(atlases):
        pats += [f"{d}%m", f"{d}%m_%n"]
    (out / "vocab.txt").write_text("\n".join(vocab) + "\n")
    # the `%m_%n` patterns need their own list: stems (`vocab.txt`) x states,
    # otherwise the slot has no --list and the crack refuses to compile
    states = sorted(all_states)
    (out / "states.txt").write_text("\n".join(states) + "\n")
    (out / "patterns.txt").write_text("\n".join(sorted(set(pats))) + "\n")
    print(f"atlas dirs {len(atlases)}  vocab {len(vocab):,}  states {len(states)}  "
          f"patterns {len(set(pats))}  candidates "
          f"~{len(vocab) * len(set(pats)) + len(vocab) * len(states):,}")
    print("top atlases:", [d for d, _ in atlases.most_common(8)])


if __name__ == "__main__":
    main()
