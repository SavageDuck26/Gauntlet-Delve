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

# the resource is a banked blob: (u32 index, u64 size) pairs, then the blocks.
# Only ONE block is English - the rest are localisations (pl, pt, de, fr, es,
# es-LA, it, cs, ...) plus platform strings. Those are worthless for us: the
# game was never hashed with non-English text, and they only pollute the word
# list with foreign words.
ENGLISH_HINTS = (" the ", " you ", " and ", " of ", " to ", " is ", " for ",
                 " with ", " your ", " a ")


def blocks(body):
    """Split the banked body into its sub-blocks."""
    pairs, off = [], 0
    while off + 12 <= len(body):
        size = int.from_bytes(body[off + 4:off + 12], "little")
        if size == 0 or off + 12 + size > len(body) + 64:
            break
        pairs.append((int.from_bytes(body[off:off + 4], "little"), size))
        off += 12
    if not pairs:
        return [(0, body)]
    out, pos = [], off
    for tag, size in pairs:
        out.append((tag, body[pos:pos + size]))
        pos += size
    return out


def english_block(body):
    """Pick the block that reads as English.

    Scoring purely on English function words is decisive here (the English
    block scores ~3900 hits, every localisation <520) and avoids being fooled
    by accented-text heuristics - the English block even begins with a binary
    index, so a "fewest non-ASCII bytes" rule picks German.
    """
    best, best_score = None, -1
    for tag, blk in blocks(body):
        txt = blk.decode("latin-1", "ignore").lower()
        score = sum(txt.count(h) for h in ENGLISH_HINTS)
        if score > best_score:
            best, best_score = (tag, blk), score
    return best



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
    e = entries[0]
    body = data[e["body_start"]:e["body_start"] + (e["body_size"] or 0)]
    tag, eng = english_block(body)

    words, phrases = set(), set()
    strings = 0
    for m in re.finditer(rb"[ -~]{4,140}", eng):
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

    print(f"bundle    : {bundle}  (block tag={tag}, {len(eng)} bytes, English only)")
    print(f"strings   : {strings}")
    print(f"words     : {len(words)}")
    print(f"phrases   : {len(phrases)}")
    print(f"candidates: {len(cands)}  -> {out}/loc_candidates.txt")


if __name__ == "__main__":
    main()
