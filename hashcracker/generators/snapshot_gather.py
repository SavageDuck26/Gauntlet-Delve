#!/usr/bin/env python3
"""
Gather the full artefact set for a pulled depot snapshot.

The 2015-01-21 snapshot grew its files ad hoc (`_harvest_candidates.py`,
`_preslayer_matches.tsv`, `_slayer_all_hashes.txt`, `_slayer_unresolved_hashes.txt`,
`_seed_candidates.txt`).  This tool produces the same set for ANY snapshot folder
so every build can be worked the same way:

    <snapshot>/_names.txt              candidate names this build yields
                                       (bundle bodies + its binaries + its *.ini,
                                        colon-tolerant, with map-suffix expansion)
    <snapshot>/_all_hashes.txt         every resource name_hash stored in the build
    <snapshot>/_unresolved_hashes.txt  of those, the ones still unnamed today
    <snapshot>/_matches.tsv            only with --crack: hash<TAB>name this build
                                       resolves for its own unresolved set
    <snapshot>/_gather.log             one summary line per run

Usage:
    python3 generators/snapshot_gather.py --root ../../Gauntlet-PreSlayer-2015-08-11
    python3 generators/snapshot_gather.py --root ../../Gauntlet-PreSlayer-2014-10-10 --crack

A snapshot is any folder containing depot_258972/contents (depot_258971/binaries
is used when present).  Read-only apart from the files it writes into the folder.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
from list_game_bundles import decompress_bundle, parse_toc          # noqa: E402
from scan_depot_names import TOKEN, SUFFIX                          # noqa: E402

HASHCK = HERE.parent / "target" / "release" / "hashcracker"
TARGETS = HERE.parent / "data" / "vocab" / "unresolved_targets.txt"
SKIP_INI_MAX = 2 * 1024 * 1024          # ini files are tiny; guard anyway


def names_from(contents: Path, binaries: Path | None) -> set[str]:
    """Candidate names: bundle bodies, binaries and the *.ini configs.

    scan_depot_names.harvest() deliberately skips `.ini`/`.data`; the Slayer-era
    snapshots carry extra settings_scea/scee/sceasia/test .ini files, so those
    are swept here too."""
    raw: set[str] = set()
    for p in sorted(contents.iterdir()):
        if not p.is_file() or p.suffix == ".stream":
            continue
        if p.suffix == ".ini":
            b = p.read_bytes()[:SKIP_INI_MAX]
            raw.update(m.decode("latin1") for m in TOKEN.findall(b))
            raw.update(m.group(1).decode("latin1")
                       for m in re.finditer(rb'"([A-Za-z][^"\n]{2,120})"', b))
            continue
        if p.suffix == ".data":
            continue
        try:
            _sig, _unz, data = decompress_bundle(p.read_bytes())
        except Exception:                                    # noqa: BLE001
            continue
        raw.update(m.decode("latin1") for m in TOKEN.findall(data))
    if binaries and binaries.is_dir():
        for p in sorted(binaries.iterdir()):
            if p.suffix.lower() in (".exe", ".dll"):
                raw.update(m.decode("latin1") for m in TOKEN.findall(p.read_bytes()))

    out: set[str] = set()
    for s in raw:
        for v in {s, s.lower(), s.strip("_./-")}:
            if len(v) < 3 or " " in v or "\t" in v:
                continue
            out.add(v)
            if len(v) < 110:
                out.update(v + suf for suf in SUFFIX)
    return out


def hashes_of(contents: Path) -> set[str]:
    """Every resource name_hash in the build, straight from the bundle TOCs."""
    found: set[str] = set()
    for p in sorted(contents.iterdir()):
        if not p.is_file() or p.suffix in (".stream", ".ini", ".data"):
            continue
        try:
            _sig, _unz, data = decompress_bundle(p.read_bytes())
            _n, toc = parse_toc(data)
        except Exception:                                    # noqa: BLE001
            continue
        for _type_hash, name_hash in toc:
            found.add("%016x" % name_hash)
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="snapshot folder")
    ap.add_argument("--crack", action="store_true",
                    help="also crack _names.txt against this build's unresolved set")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    contents = root / "depot_258972" / "contents"
    binaries = root / "depot_258971" / "binaries"
    if not contents.is_dir():
        sys.exit(f"no bundle folder at {contents}")

    cands = names_from(contents, binaries if binaries.is_dir() else None)
    (root / "_names.txt").write_text("\n".join(sorted(cands)) + "\n")

    all_h = hashes_of(contents)
    (root / "_all_hashes.txt").write_text("\n".join(sorted(all_h)) + "\n")

    targets = set(TARGETS.read_text().split()) if TARGETS.exists() else set()
    unresolved = sorted(all_h & targets)
    (root / "_unresolved_hashes.txt").write_text(
        "\n".join(unresolved) + ("\n" if unresolved else ""))

    line = (f"names {len(cands)}  build hashes {len(all_h)}  "
            f"of our {len(targets)} unresolved targets present here: {len(unresolved)}")
    print(line)

    if args.crack and unresolved:
        tmp = root / "_unresolved_hashes.txt.tmp"
        tmp.write_text("\n".join(unresolved) + "\n")
        out = root / "_matches.tsv"
        subprocess.run([str(HASHCK), "crack", "--gpu",
                        "--targets", str(tmp),
                        "--candidates", str(root / "_names.txt"),
                        "--matches", str(out)], check=False)
        tmp.unlink(missing_ok=True)
        got = sum(1 for _ in out.open()) if out.exists() else 0
        line += f"  |  cracked -> _matches.tsv: {got} names"
        print(f"cracked against this build's own unresolved set -> {got} names")

    with (root / "_gather.log").open("a") as fh:
        fh.write(line + "\n")


if __name__ == "__main__":
    main()
