#!/usr/bin/env python3
"""
Positive controls for every tier in work/tokpos/tiers.tsv (FINDINGS.txt 53).

Slot/list alignment is the error-prone part of a positional sweep: the manifest
says "pattern file, then these list files in slot order", and if that order is
wrong the engine happily searches nonsense.  So for each tier, take its first
pattern, turn it into a regex with one named group per slot, find a *resolved*
name that matches, and use that name's token per slot as a one-word list - then
run the real crack against that name's hash.  A tier that cannot find its own
control is misaligned.

    python3 tools/check_token_tiers.py [--cap N]
"""
import argparse
import csv
import json
import pathlib
import re
import subprocess
import sys

HC = pathlib.Path(__file__).resolve().parent.parent
DIG = HC.parent / "Data"
P = HC / "work" / "tokpos"
TMP = HC / "work" / "tmp" / "tiercheck"
OV = DIG / "resource_name_overlay.json"
CAT = DIG / "bundle_manifest" / "04_bundle_resources.csv"


def resolved():
    ov = json.loads(OV.read_text())
    out = {}
    for r in csv.DictReader(CAT.open(newline="", encoding="utf-8",
                                     errors="replace")):
        n = r.get("name") or ov.get(r.get("name_hash"))
        if n:
            out[n.lower()] = r["name_hash"].lower()
    return out


def pattern_regex(pat):
    """Pattern -> regex with a capture group per slot, in slot order."""
    out, slots = "^", []
    i = 0
    while i < len(pat):
        c = pat[i]
        if c == "%":
            letter = pat[i + 1]
            if letter not in slots:
                slots.append(letter)
            out += "([a-z0-9]+)"
            i += 2
        else:
            out += re.escape(c)
            i += 1
    return re.compile(out + "$"), slots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=7_000_000_000_000)
    args = ap.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)
    names = resolved()
    by_dir = {}
    for n in names:
        d, _, _ = n.rpartition("/")
        by_dir.setdefault(d + "/" if d else "", []).append(n)

    tiers = []
    for line in (P / "tiers.tsv").read_text().splitlines():
        if not line.strip():
            continue
        f = line.split("\t")
        tiers.append((f[0], int(f[1]), f[2], f[3:]))

    ok = bad = skipped = 0
    for name, size, pf, lists in tiers:
        if size > args.cap:
            print(f"  {name:10s} SKIP (above cap)")
            skipped += 1
            continue
        plines = [l for l in (P / pf).read_text().splitlines() if l.strip()]
        listsets = [set((P / f).read_text().split()) for f in lists]
        hit = None
        for pat in plines:
            rx, slots = pattern_regex(pat)
            pre = pat.split("%", 1)[0]
            d = pre[:pre.rfind("/") + 1] if "/" in pre else ""
            pool = by_dir.get(d, ()) if d else names
            for n in pool:
                m = rx.match(n)
                if not m or len(m.groups()) != len(listsets):
                    continue
                if all(t in listsets[i] for i, t in enumerate(m.groups())):
                    hit = (n, m.groups())
                    break
            if hit:
                break
        if not hit:
            print(f"  {name:10s} no resolved name matches any of its "
                  f"{len(plines)} patterns")
            bad += 1
            continue
        n, toks = hit
        # one word per slot, from the control itself, in slot order
        lint = []
        for i, letter in enumerate(slots):
            f = TMP / f"{name}_{letter}.txt"
            f.write_text(toks[i] + "\n")
            lint += [f"--list", f"{letter}={f}"]
        ctrl = TMP / "control.txt"
        ctrl.write_text(names[n] + "\n")
        args_pat = []
        for line in (P / pf).read_text().splitlines():
            if line.strip():
                args_pat += ["--pattern", line]
        res = subprocess.run(
            [str(HC / "tools" / "hc.sh"), "crack", "--gpu", "--targets", str(ctrl),
             *lint, *args_pat, "--matches", str(TMP / "matches.tsv")],
            capture_output=True, text=True, cwd=HC)
        got = (TMP / "matches.tsv").read_text().lower() if (TMP / "matches.tsv").exists() else ""
        good = names[n] in got
        print(f"  {name:10s} {'OK  ' if good else 'FAIL'} {n}")
        ok, bad = ok + good, bad + (not good)
        for f in TMP.glob("*.txt"):
            if f.name != "control.txt":
                f.unlink()
        (TMP / "matches.tsv").unlink(missing_ok=True)
    print(f"controls ok {ok}  failed {bad}  skipped {skipped}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
