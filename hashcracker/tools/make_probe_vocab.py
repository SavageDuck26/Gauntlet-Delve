#!/usr/bin/env python3
"""Build the probe vocabularies for the shader `technique:[flags]` wall.

FINDINGS.txt 60.14 concluded that the chains still unresolved use flags "that
appear nowhere in our vocabulary", and 60.16 corrects that: the words were in
sources we hold, they had simply never been placed in the *flag position*.
Every earlier sweep combined a CURATED flag list (the flags mined from named
chains, the render_config pass flags, another game's name list), and a chain has
only two kinds of position, so the probe that needs no curation is:

    <known technique>:<any token>    --list t=probe_techniques.txt \
                                     --list f=probe_tokens.txt --pattern '%t:%f'
    <any token>:<known flag>          --list f=probe_tokens.txt \
                                     --list g=probe_flags.txt   --pattern '%f:%g'
    <any token>                       --candidates probe_tokens.txt

All three are expressible with the *pattern* engine, so a full probe needs no
candidate file on disk.  Tokens are pooled from everything that could spell an
engine word: the shipped Lua, the depot string harvest, the runtime captures the
mod loader writes next to the game binary, every catalogue name, the game
binaries and the Stingray documentation.  Hex runs, pure digits and 1-2
character fragments are dropped - the 3-character floor is deliberate, it is
what lets short flags like `hdr`/`hq`/`4x4` through.

    python3 tools/make_probe_vocab.py            # -> data/vocab/probe_*.txt
    GAUNTLET_DIR=/path/to/Gauntlet python3 tools/make_probe_vocab.py

The result of the first run is in FINDINGS.txt 60.16 (13 chains, incl.
`tone_mapping:hdr` and `character:enemy:self_illumination`).
"""
import argparse
import csv
import os
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
HARVEST = HC / "work" / "harvest2" / "raw.txt"
LUA = HC.parent.parent / "game-source"
DOCS = HC.parent.parent / "reference" / "Stingray-Docs-md"

TOKEN = re.compile(r"[a-z0-9][a-z0-9_]{1,40}")
HEXISH = re.compile(r"^[0-9a-f]{6,}$")


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HC / "data" / "vocab"))
    ap.add_argument("--game-dir", default=None,
                    help="Gauntlet install dir; default $GAUNTLET_DIR or the usual Steam path")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    game = pathlib.Path(
        args.game_dir
        or os.environ.get("GAUNTLET_DIR")
        or (pathlib.Path.home() / ".local/share/Steam/steamapps/common/Gauntlet")
    )

    tokens: set[str] = set()

    def feed(text: str) -> None:
        for m in TOKEN.finditer(text):
            t = m.group(0)
            if HEXISH.fullmatch(t) and "_" not in t:
                continue
            if t.isdigit():
                continue
            if len(t) < 3 and "_" not in t:
                continue
            tokens.add(t)

    def feed_file(path: pathlib.Path, limit: int = 0) -> bool:
        if not path.is_file():
            return False
        try:
            data = path.read_bytes()
            if limit:
                data = data[:limit]
            feed(data.decode("latin-1"))
        except OSError:
            return False
        return True

    used = []
    if LUA.is_dir():
        for p in LUA.rglob("*.lua"):
            feed(p.read_text(errors="replace"))
        used.append(f"shipped Lua ({LUA})")
    if feed_file(HARVEST):
        used.append(f"string harvest ({HARVEST})")
    for name in ("runtime_names.tsv", "runtime_names_classified.tsv"):
        if feed_file(game / "binaries" / name):
            used.append(f"runtime capture ({name})")
    if feed_file(game / "binaries" / "gauntlet.exe"):
        used.append("gauntlet.exe strings")
    if DOCS.is_dir():
        for p in DOCS.rglob("*"):
            if p.is_file() and p.stat().st_size < 4_000_000:
                feed(p.read_text(errors="replace"))
        used.append(f"Stingray docs ({DOCS})")

    chains = set()
    flags = set()
    with CATALOGUE.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            nm = (r.get("name") or "").strip()
            if nm:
                feed(nm)
            if (r.get("type") or "").strip() == "shader_library" and nm:
                chains.add(nm)
    # today's finds may not be in the catalogue CSV yet - the find log is the
    # authority, and taking them from there is what makes the probe *compound*
    for line in (HC.parent / "Data" / "matches.tsv").read_text(errors="replace").splitlines():
        if "\t" in line:
            nm = line.split("\t", 1)[1].strip()
            if ":" in nm and "/" not in nm and " " not in nm:
                chains.add(nm)
    for c in chains:
        flags.update(c.split(":")[1:])

    techs = sorted({c.split(":")[0] for c in chains})
    tokens -= flags | set(techs)
    probe_tokens = sorted(tokens)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe_techniques.txt").write_text("\n".join(techs) + "\n")
    (out / "probe_tokens.txt").write_text("\n".join(probe_tokens) + "\n")
    (out / "probe_flags.txt").write_text("\n".join(sorted(flags)) + "\n")

    print(f"sources used   : {len(used)}")
    for u in used:
        print(f"  - {u}")
    print(f"techniques     : {len(techs)}   -> data/vocab/probe_techniques.txt")
    print(f"known flags    : {len(flags)}   -> data/vocab/probe_flags.txt")
    print(f"probe tokens   : {len(probe_tokens)}   -> data/vocab/probe_tokens.txt")
    print("probe: --pattern '%t:%f'  (t=probe_techniques, f=probe_tokens)"
          "   |   '%f:%g'  (g=probe_flags)   |   --candidates probe_tokens.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
