#!/usr/bin/env python3
"""
Harvest resource names out of the snapshot depots (FINDINGS.txt §45).

The bundles look string-free to `grep`, which is why the depots were long
considered name-less: every body is a chain of zlib blocks.  Decompress them and
real resource names fall out - as slash-joined runs of them:

    .../caves_quilt_straight__xx_e_xx_e__05_spider/caves_quilt_...__04_spider/...

This is the single highest-yield step on the level family: hashing the extracted
ids under every plausible package path named 60-odd levels that 80 G candidates
of pattern sweeping could not reach, because the names violate the grammar the
sweeps assumed (`__01chain` with no separator, `lavastruct_16c_16c_uu_ug_uu_gu_
01_encounter`, `*_dungeon_tiles_master`).

Writes, next to `--out`:
    raw.txt        every ASCII string found in the bundles (deduped)
    quilt_ids.txt  `*_quilt_<shape>__<cells>__...` ids
    tile_ids.txt   `*_<Nc>_<Mc>_...` ids
    broad_ids.txt  the union of the id patterns above plus rooms/masters/arena

    python3 tools/harvest_depot.py [--snapshots DIR ...] [--out DIR]
"""
import argparse
import pathlib
import re
import struct
import zlib

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HC.parent

Z = (b"\x78\x9c", b"\x78\xda", b"\x78\x01", b"\x78\x5e")
STR = re.compile(rb"[a-zA-Z][a-zA-Z0-9_:./-]{2,120}")
IDS = {
    "quilt_ids": re.compile(r"[a-z0-9]*_quilt_[a-z]+__[a-z0-9_]+"),
    "tile_ids": re.compile(r"[a-z0-9]+_[0-9]+c_[0-9]+c_[a-z0-9_]+"),
    "room_ids": re.compile(r"room_[a-z0-9_]+"),
    "master_ids": re.compile(r"[a-z0-9]*tiles_master"),
    "arena_ids": re.compile(r"[a-z0-9]+_(arena|colosseum)[a-z0-9_]*"),
    "prefab_ids": re.compile(r"prefab_[a-z0-9_]+"),
}


def harvest(path: pathlib.Path) -> set:
    """Every ASCII string in one packed bundle."""
    d = path.read_bytes()
    out = set()
    pos = 12
    while pos + 4 <= len(d):
        size = struct.unpack_from("<I", d, pos)[0]
        pos += 4
        if size == 0 or pos + size > len(d):
            break
        blk = d[pos:pos + size]
        try:
            buf = zlib.decompress(blk) if blk[:2] in Z else blk
        except zlib.error:
            break
        for m in STR.findall(buf):
            out.add(m.decode("latin1"))
        pos += size
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", nargs="*",
                    default=[str(REPO / f) for f in
                             ("Gauntlet-PreSlayer-2014-10-10",
                              "Gauntlet-PreSlayer-2015-01-21",
                              "Gauntlet-PreSlayer-2015-08-11")])
    ap.add_argument("--out", default=str(HC / "work" / "harvest"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw = set()
    for snap in args.snapshots:
        sp = pathlib.Path(snap)
        for contents in sorted(sp.glob("depot_*/contents")):
            for f in sorted(contents.iterdir()):
                if not f.is_file() or f.suffix == ".stream":
                    continue
                try:
                    raw |= harvest(f)
                except OSError:
                    continue
        for bdir in sorted(sp.glob("depot_*/binaries")):
            for f in sorted(bdir.iterdir()):
                if f.suffix.lower() in (".exe", ".dll"):
                    for m in STR.findall(f.read_bytes()):
                        raw.add(m.decode("latin1"))
    print(f"raw strings {len(raw):,}")

    text = "\n".join(sorted(raw))
    (out / "raw.txt").write_text(text + "\n")
    for name, rx in IDS.items():
        ids = sorted({m.group(0) for m in rx.finditer(text)})
        (out / f"{name}.txt").write_text("\n".join(ids) + ("\n" if ids else ""))
        print(f"  {name:12s} {len(ids):>7}")
    broad = set()
    for n in ("quilt_ids", "tile_ids", "room_ids", "master_ids", "arena_ids",
              "prefab_ids"):
        p = out / f"{n}.txt"
        if p.exists():
            broad |= set(p.read_text().split())
    (out / "broad_ids.txt").write_text("\n".join(sorted(broad)) + "\n")
    print(f"  broad_ids    {len(broad):>7}")


if __name__ == "__main__":
    main()
