#!/usr/bin/env python3
"""
Sweep the repository for hash -> name pairs that are still unresolved.

The project has been cracking this game for years, in several tools and several
snapshot directories, and not every one of those runs left its result in
`matches.tsv`.  `Gauntlet-PreSlayer-2015-01-21/_slayer_all_matches.tsv` alone holds
2,410 `hash<TAB>name` pairs of which **113 hash to names that are still missing
today** - `characters/avatar_elf/elf_diff`, `gameobjects/doors/door_crypt_3keys_norm`,
`props/d01_caves/bridge_01_diff`, ...  A pair is only worth taking if it is
*verifiable*: this tool re-hashes the name and accepts it only when
`murmur64(name) == hash`, which is exactly what defines the name in the first place
(the engine looks resources up by hash, so any preimage is a correct answer).

Scans every text file under the repo (skipping the giant generated vocabularies and
the engine build directory), streams line by line - memory flat - and writes the
verified pairs to `--out` for `matches.tsv`.

    python3 tools/harvest_hash_pairs.py [--out /tmp/pairs.tsv] [--write] [-v]
"""
import argparse
import csv
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent
DIG = HC.parent / "Data"
sys.path.insert(0, str(DIG))
sys.path.insert(0, str(HC.parent / "scripts"))   # bundle_tools / list_game_bundles live here
from bundle_tools import murmur_hash64  # noqa: E402

CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
SKIP = ("data/vocab", "target/", "Gauntlet-install/", ".git/", "node_modules")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".glb", ".gz", ".zst", ".bin", ".exe", ".dll",
            ".so", ".rlib", ".zip", ".7z", ".ttf", ".wav", ".ogg", ".wem")
HEX = re.compile(r"\b([0-9a-f]{16})\b")
NAME = re.compile(r"([a-z][a-z0-9_/]{5,120})")


def unresolved() -> dict[str, str]:
    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    out = {}
    with CATALOGUE.open(newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            h = (r["name_hash"] or "").lower()
            if h and h not in ov:
                out[h] = r["type"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/harvest_pairs.tsv")
    ap.add_argument("--root", default="",
                    help="directory to sweep (default: this repository)")
    ap.add_argument("--max-mb", type=int, default=20)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    un = unresolved()
    root = pathlib.Path(a.root).expanduser().resolve() if a.root else REPO
    print(f"unresolved {len(un)}   root {root}", file=sys.stderr)
    found: dict[str, str] = {}
    scanned = 0
    cap = a.max_mb * 1_000_000

    with open(a.out, "w", encoding="utf-8") as out:
        for p in root.rglob("*"):
            s = str(p)
            if not p.is_file() or any(k in s for k in SKIP):
                continue
            if p.suffix.lower() in SKIP_EXT:
                continue
            try:
                if p.stat().st_size > cap:
                    continue
                text = p.read_text(errors="replace")
            except Exception:
                continue
            if len(text) < 100:
                continue
            scanned += 1
            for line in text.splitlines():
                m = HEX.search(line)
                if not m:
                    continue
                h = m.group(1)
                if h not in un or h in found:
                    continue
                for nm in NAME.findall(line):
                    if f"{murmur_hash64(nm):016x}" == h:
                        found[h] = nm
                        out.write(f"{h}\t{nm}\n")
                        if a.verbose:
                            print(f"   {h} {un[h]:14s} {nm}   [{p}]", file=sys.stderr)
                        break
    print(f"scanned {scanned} text files; verified pairs {len(found)}",
          file=sys.stderr)
    for h, n in list(found.items())[:25]:
        print(f"   {h} {un[h]:14s} {n}", file=sys.stderr)
    if a.write and found:
        with open(HC.parent / "Data" / "matches.tsv", "a", encoding="utf-8") as fh:
            for h, n in found.items():
                fh.write(f"{h}\t{n}\n")
        print(f"appended {len(found)} to matches.tsv", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
