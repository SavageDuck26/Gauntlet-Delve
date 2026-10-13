#!/usr/bin/env python3
"""Every slug of the game's own display text - the vocabulary the icons are made of.

Confirmed rule (FINDINGS 60.19): an icon's word is the glued slug of a display
string.  `localization/game_strings.strings` holds "More of Thor" and the icon is
`hud/action_icons/warrior_ultimate_moreofthor`; "Dryad's Song" gives
`elf_ultimate_dryadssong`; "Heart of Vlad" gives
`equippables_icons/relic_heart_of_vlad`.  So the language file *is* the vocabulary:
this writes every 1-4 word n-gram that starts on a capitalised word, in glued and
underscored form, ready for the localization sweep.

The `.strings` resource is a null-separated value list (a language index + offset
table, no text keys), so it is read as text.

    python3 tools/make_loc_slugs.py [--export DIR] [--out FILE]

The export folder is the one `export_all_resources.py` writes (`Gauntlet-Export`);
regenerate it first if the game has been re-exported.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DEFAULT_EXPORT = pathlib.Path.home() / "Documents" / "Coding" / "Gauntlet-Export"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(DEFAULT_EXPORT),
                    help=f"export folder (default: {DEFAULT_EXPORT})")
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "loc_slugs.txt"))
    ap.add_argument("--max-words", type=int, default=4)
    ap.add_argument("--max-len", type=int, default=34)
    args = ap.parse_args()

    strings = pathlib.Path(args.export).expanduser() / "named" / "localization" \
        / "game_strings.strings"
    if not strings.is_file():
        sys.exit(f"no {strings} - run export_all_resources.py first")
    values = [v.decode("utf-8", "replace") for v in strings.read_bytes().split(b"\x00")]

    slugs = set()
    for v in values:
        if not v or not re.fullmatch(r"[\x20-\x7e]+", v) or len(v) > 60:
            continue
        if any(c in v for c in ".!?;,:#$%&*()[]{}=<>/\\|~^`\""):
            continue
        ws = re.findall(r"[A-Za-z0-9']+", v)
        if not ws or not ws[0][:1].isupper():
            continue
        for i in range(len(ws)):
            if not ws[i][:1].isupper():
                continue
            for n in range(1, args.max_words + 1):
                gram = ws[i:i + n]
                if len(gram) < n:
                    continue
                low = [w.lower().replace("'s", "s").replace("'", "") for w in gram]
                if not all(low):
                    continue
                for form in ("".join(low), "_".join(low)):
                    if 3 <= len(form) <= args.max_len:
                        slugs.add(form)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sorted(slugs)) + "\n")
    print(f"strings        : {len(values):,}")
    print(f"slug forms     : {len(slugs):,}  -> {out}")


if __name__ == "__main__":
    main()
