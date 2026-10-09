#!/usr/bin/env python3
"""
Dump the unresolved hashes for hashcat (FINDINGS.txt section 58).

MurmurHash64A is not a stock hashcat mode, but the community has already built
the kernel for it.  `reference/filediver/` (a Helldivers 2 / Bitsquid tool) points
at the fork **github.com/ryanjsims/hashcat, branch murmur64a** and ships its own
`hash-tool` - "a simple tool for calculating and cracking murmur64a hashes" - whose
crack mode is `-c -d _ -w <wordlist> <hash_in_little_endian>`.  Same engine, same
hash, same lowercase names.

hashcat wants the hash in **little-endian hex**; our catalogue stores it
big-endian.  This writes both, plus command lines for the attacks that matter.

    python3 tools/dump_hashcat_targets.py [--out DIR]
"""
import argparse
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ov = json.loads((DIG / "resource_name_overlay.json").read_text())
    unresolved = set()
    for r in csv.DictReader((DIG / "bundle_manifest" /
                             "04_bundle_resources.csv").open(
                                 newline="", encoding="utf-8", errors="replace")):
        if not r.get("name") and r["name_hash"] not in ov:
            unresolved.add(r["name_hash"].lower())

    le = sorted("".join(reversed([h[i:i + 2] for i in range(0, 16, 2)]))
                for h in unresolved)
    (out / "targets_hashcat_le.txt").write_text("\n".join(le) + "\n")
    (out / "targets_hashcat_be.txt").write_text("\n".join(sorted(unresolved)) + "\n")

    print(f"unresolved {len(unresolved):,}")
    print(f"  little-endian (hashcat):  {out / 'targets_hashcat_le.txt'}")
    print(f"  big-endian   (our engine):{out / 'targets_hashcat_be.txt'}")
    print()
    print("On the NVIDIA machine, with the murmur64a hashcat fork built:")
    print(f"  # mask: 3-5 token leaves under every directory we know")
    print(f"  hashcat -m <murmur64a mode> -a 3 {out / 'targets_hashcat_le.txt'} \\")
    print( "          'characters/avatar_wolf/animations/attack?a?a?a?a' --increment")
    print(f"  # combinator (the community's own shape, -d _):")
    print(f"  hashcat -m <mode> -a 1 -j _ {out / 'targets_hashcat_le.txt'} w1.txt w2.txt")
    print(f"  # rules over every resolved name's leaf (mutations at 10-30x our speed):")
    print(f"  hashcat -m <mode> -r rules/best64.rule {out / 'targets_hashcat_le.txt'} leaves.txt")
    print()
    print("Their tool as a reference implementation (CPU):")
    print("  cd reference/filediver && go run ./cmd/tools/hash-tool \\")
    print("      -c -d _ -w cmd/tools/hash-tool/wordlist_10k_plus.txt <hash_in_little_endian>")


if __name__ == "__main__":
    sys.exit(main())
