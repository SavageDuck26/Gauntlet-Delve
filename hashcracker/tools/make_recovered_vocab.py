#!/usr/bin/env python3
"""
Rebuild the vocabulary that feeds `hashcracker mutate`.

Two files, both regenerated from the *current* catalogue so every sweep cycle
sees the names recovered by the previous one:

    data/vocab/recovered_names.txt   every resolved resource name (unique) -
                                     `mutate --names`
    data/vocab/tokens_ext.txt        the token list, = data/names.txt plus the
                                     leaf/path tokens mined from those names -
                                     `mutate --tokens`

Why this matters: `mutate` derives candidates per name *inside that name's own
directory* (suffix swaps, token append/prepend, token merge/replace, numeric
edits).  Run with the full recovered vocabulary it reopened the texture/material/
particle families that had been declared source-limited - 93 names in the first
sitting (FINDINGS.txt section 33) - because the earlier sweeps had only ever fed
it the 3,278-name `data/known.txt`.

    python3 tools/make_recovered_vocab.py
"""
import csv
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
CATALOGUE = HC.parent / "Data" / "bundle_manifest" / "04_bundle_resources.csv"
OUT = HC / "data" / "vocab"
BASE_TOKENS = HC / "data" / "names.txt"


def main() -> None:
    rows = csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8", errors="replace"))
    names = sorted({r["name"] for r in rows if r.get("name")})
    (OUT / "recovered_names.txt").write_text("\n".join(names) + "\n")

    tokens = set(BASE_TOKENS.read_text(errors="replace").split())
    for n in names:
        directory, _, leaf = n.rpartition("/")
        tokens.add(leaf)
        tokens.update(t for t in leaf.split("_") if len(t) > 1)
        tokens.update(c for c in directory.split("/") if c)
    tokens.discard("")
    (OUT / "tokens_ext.txt").write_text("\n".join(sorted(tokens)) + "\n")
    print(f"recovered names {len(names)}  tokens {len(tokens)}  -> {OUT}")


if __name__ == "__main__":
    main()
