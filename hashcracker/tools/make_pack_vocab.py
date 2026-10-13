#!/usr/bin/env python3
"""
Build a hyper-targeted vocabulary for ONE resource package ("pack").

A pack's own names are a tiny, self-consistent world: `blocks/d01_crypt/<sub>/...`,
`effects/<pre>_<sub>_<verb>`, `characters/<hero>/animations/...`.  Because the
token list is small, sweeps can afford combinatorial depth per pack that is
impossible against the whole catalogue.

    python3 tools/make_pack_vocab.py --pack resource_packages/menu

Writes into work/pack/<slug>/:
    names.txt      every NAMED resource of that pack (mutate seeds)
    targets.txt    the pack's unresolved hashes
    tokens.txt     leaf tokens + path components mined from the pack's names
    suffixes.txt   map/decal suffixes seen inside the pack
    dirs.txt       directories the pack's names live in (with trailing '/')
    info.txt       counts and the type mix
"""
import argparse
import collections
import csv
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
CATALOGUE = HC.parent / "Data" / "bundle_manifest" / "04_bundle_resources.csv"
OUT_ROOT = HC / "work" / "pack"

SUF_RE = re.compile(r"(_[a-z0-9]+)$")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="package_path, e.g. resource_packages/menu")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    pack = args.pack
    rows = [r for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                                     errors="replace"))
            if r["package_path"] == pack]
    if not rows:
        raise SystemExit(f"no catalogue rows for pack {pack!r}")

    out = pathlib.Path(args.out) if args.out else OUT_ROOT / pack.replace("/", "_")
    out.mkdir(parents=True, exist_ok=True)

    names = sorted({r["name"] for r in rows if r["name"]})
    targets = sorted({r["name_hash"] for r in rows if not r["name"]})

    tokens: collections.Counter = collections.Counter()
    dirs: collections.Counter = collections.Counter()
    suffixes: collections.Counter = collections.Counter()
    for n in names:
        directory, _, leaf = n.rpartition("/")
        if directory:
            dirs[directory + "/"] += 1
        for t in leaf.split("_"):
            if len(t) > 1:
                tokens[t] += 1
        for part in directory.split("/"):
            if len(part) > 1:
                tokens[part] += 1
        m = SUF_RE.search(leaf)
        if m:
            suffixes[m.group(1)] += 1
        if leaf.endswith(("_diff", "_norm", "_spec")):
            suffixes["_" + leaf.rsplit("_", 1)[1]] += 1
    tokens.update({s.lstrip("_"): 1 for s in suffixes})

    (out / "names.txt").write_text("\n".join(names) + ("\n" if names else ""))
    (out / "targets.txt").write_text("\n".join(targets) + ("\n" if targets else ""))
    (out / "tokens.txt").write_text("\n".join(t for t, _ in tokens.most_common()) + "\n")
    (out / "suffixes.txt").write_text("\n".join(s for s, _ in suffixes.most_common()) + "\n")
    (out / "dirs.txt").write_text("\n".join(d for d, _ in dirs.most_common()) + "\n")

    types = collections.Counter(r["type"] for r in rows if not r["name"])
    (out / "info.txt").write_text(
        f"pack          : {pack}\n"
        f"rows          : {len(rows)}\n"
        f"named         : {len(names)}\n"
        f"unresolved    : {len(targets)} unique hashes\n"
        f"tokens        : {len(tokens)}\n"
        f"dirs          : {len(dirs)}\n"
        f"suffixes      : {len(suffixes)}\n"
        f"unresolved by type: {types.most_common()}\n")
    print(f"{pack}: named {len(names)}  targets {len(targets)}  tokens {len(tokens)}  "
          f"dirs {len(dirs)}  suffixes {len(suffixes)} -> {out}")


if __name__ == "__main__":
    main()
