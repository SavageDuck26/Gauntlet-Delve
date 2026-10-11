#!/usr/bin/env python3
"""
Bundle-scoped candidates (FINDINGS.txt §47).

A resource's bundle is a strong hint about its directory: a texture sitting in
the `characters/mummy_risen` bundle is almost certainly
`characters/mummy_risen/<leaf>`, not some other tree.  So for each bundle, take
the directories of the *resolved* names in that same bundle and cross them with
a vocabulary - per bundle, not globally.

Writes `work/bundle/<id>.targets` and `work/bundle/<id>.patterns` for the
bundles that have unresolved names.

    python3 tools/make_bundle_targets.py [--vocab FILE] [--out DIR]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "work" / "bundle"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    dirs = collections.defaultdict(collections.Counter)
    targets = collections.defaultdict(list)
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        b = r.get("bundle")
        if not b:
            continue
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n and "/" in n:
            dirs[b][n.rsplit("/", 1)[0] + "/"] += 1
        elif not n:
            targets[b].append((r["name_hash"].lower(), r.get("type", "?")))

    n_b = n_t = n_p = 0
    for b, tg in sorted(targets.items()):
        if not tg or not dirs[b]:
            continue
        (out / f"{b}.targets").write_text(
            "\n".join(h for h, _ in tg) + "\n")
        pats = sorted(dirs[b])
        (out / f"{b}.patterns").write_text("\n".join(f"{d}%m" for d in pats) + "\n")
        n_b += 1
        n_t += len(tg)
        n_p += len(pats)
    print(f"bundles {n_b}  targets {n_t}  patterns {n_p}  -> {out}")


if __name__ == "__main__":
    main()
