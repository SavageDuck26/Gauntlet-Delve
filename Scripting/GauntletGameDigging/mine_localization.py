#!/usr/bin/env python3
"""
Mine the shipped LOCALIZATION bundle for English text -> name vocabulary.

`resource_packages/localization` ships the whole game's text for six languages
in one banked resource. The string scan of bundle bodies missed it because the
useful parts are prose (the plausible-name filter rejects spaces), so this tool
extracts it properly:

    * every word            -> loc_words.txt    (composition vocabulary)
    * every Title-ish line  -> loc_phrases.txt  (lowercased, spaces -> "_")
    * phrase x icon/menu/... prefixes + _icon/_locked/_01/_02
                            -> loc_candidates.txt (ready for `crack --candidates`)

The phrase form is what names the achievement icons: the localised achievement
"Rude Interruption" is the resource `achievement_icons/rude_interruption`.

Usage:
    python3 mine_localization.py [--bundle <hash>] [--vocab-dir DIR]
"""
import argparse
import csv
import json
import re
from pathlib import Path

import list_game_bundles as L

PREFIXES = ["", "menu/", "achievement_icons/", "equippables_icons/", "hud/",
            "hero_sprites/", "cape_icons/", "loading_screens/", "effects/",
            "effects_ui/", "props/", "decals/", "gameobjects/", "characters/",
            "equipment/", "textures/"]


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=None, help="localization bundle hash")
    ap.add_argument("--vocab-dir", default=str(here.parent / "hashcracker" / "data" / "vocab"))
    args = ap.parse_args()

    root = L.find_install_root()
    contents = root / "contents"

    bundle = args.bundle
    if not bundle:
        ov = here / "bundle_name_overlay.json"
        names = json.loads(ov.read_text()) if ov.exists() else {}
        for h, n in names.items():
            if n == "resource_packages/localization":
                bundle = h
                break
    if not bundle:
        raise SystemExit("could not find the localization bundle hash")

    _, _, data = L.decompress_bundle((contents / bundle).read_bytes())
    _, toc = L.parse_toc(data)
    entries, _, _ = L.parse_resources(data, toc)

    words, phrases = set(), set()
    strings = 0
    for e in entries:
        body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]
        for m in re.finditer(rb"[ -~]{4,140}", body):
            strings += 1
            t = m.group().decode("ascii", "ignore").strip()
            for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", t):
                if len(w) > 2:
                    words.add(w.lower())
            if " " in t and re.match(r"^[A-Za-z][A-Za-z0-9 ,'\-!?.]*$", t):
                c = t.lower()
                for ch in "!,?.'":
                    c = c.replace(ch, "")
                c = re.sub(r"\s+", "_", c.strip())
                if 3 <= len(c) <= 80:
                    phrases.add(c)

    out = Path(args.vocab_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "loc_words.txt").write_text("\n".join(sorted(words)) + "\n")
    (out / "loc_phrases.txt").write_text("\n".join(sorted(phrases)) + "\n")

    cands = set()
    for c in words | phrases:
        for p in PREFIXES:
            cands.add(p + c)
        for s in ("_icon", "_locked", "_01", "_02"):
            cands.add(c + s)
    (out / "loc_candidates.txt").write_text("\n".join(sorted(cands)) + "\n")

    print(f"bundle    : {bundle}")
    print(f"strings   : {strings}")
    print(f"words     : {len(words)}")
    print(f"phrases   : {len(phrases)}")
    print(f"candidates: {len(cands)}  -> {out}/loc_candidates.txt")


if __name__ == "__main__":
    main()
