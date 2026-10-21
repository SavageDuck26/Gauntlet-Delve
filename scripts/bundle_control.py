#!/usr/bin/env python3
"""
bundle_control.py - put the game's mod-bundle state into EXACTLY a declared set.

The loader injects three things per bundle, and only one is a folder in mods/bundles:

    mods/bundles/<Name>/      the folder              <- deleting it removes only this
    contents/<bundleHash>     a copy it places there  <- SURVIVES deleting the folder
    bundle_database.data rows one row per resource    <- SURVIVES deleting the folder

So removing a bundle folder does NOT remove the bundle: the engine still resolves its
package from the leftover rows and copy.  That invalidated two test runs today.

    bundle_control.py --list
    bundle_control.py --only LuaResTest
    bundle_control.py --none

Paths: the install root is found from the usual candidate list, and the loader's dev tree is
derived from this repo's own location, so nothing here names a home directory.
GAUNTLET_ROOT and GAUNTLET_MODS override either.
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
from pathlib import Path

# Paths are DISCOVERED, never written down: the install root uses the same candidate list
# as list_game_bundles.py, and the loader's dev tree is DERIVED from this file's own
# location - the two checkouts are siblings by convention.  Env overrides for anything
# exotic: GAUNTLET_ROOT, GAUNTLET_MODS.
TOOL_DIR = Path(__file__).resolve().parent
REPO = TOOL_DIR.parent

INSTALL_CANDIDATES = [
    Path(os.path.expanduser('~/.local/share/Steam/steamapps/common/Gauntlet')),
    Path(r'C:\Program Files (x86)\Steam\steamapps\common\Gauntlet'),
    Path(r'C:\Program Files\Steam\steamapps\common\Gauntlet'),
]
DEV_CANDIDATES = [REPO.parent / 'GauntletModLoader' / 'mods' / 'bundles']


def _first_dir(candidates, env):
    """The first candidate that exists, with `env` able to name one living elsewhere."""
    override = os.environ.get(env)
    for c in ([Path(override).expanduser()] if override else []) + candidates:
        if c.is_dir():
            return c
    return None


GAME = _first_dir(INSTALL_CANDIDATES, 'GAUNTLET_ROOT')
if GAME is None:
    raise SystemExit('no Gauntlet install found - tried %s; set GAUNTLET_ROOT'
                     % ', '.join(str(c) for c in INSTALL_CANDIDATES))

BUNDLES = GAME / 'mods/bundles'
CONTENTS = GAME / 'contents'
DB = CONTENTS / 'bundle_database.data'
# Falls back to the deployed tree: a bundle with no dev folder cannot be DEPLOYED, but the
# ones already in the game can still be listed and stripped.
DEV = _first_dir(DEV_CANDIDATES, 'GAUNTLET_MODS') or BUNDLES

KNOWN = ['RoomEditTest', 'RtexTest', 'HamTexOverride', 'LuaResTest', 'CraneTexTest',
         'LevelProbe', 'FlatPlaneTest', 'FlatPlaneLevel', 'CustomArena', 'CustomRunLevel']


def hash_of(name: str) -> str:
    """The 16-hex bundle hash for a bundle name, looking in the DEV tree first.

    Dev first, deliberately: the deployed folder is what a strip step removes, and
    reading the hash from a folder that is mid-strip is how this script reported
    RtexTest as 0 rows after it had just deployed it.  The dev tree is the stable
    source of truth for "which hash does this bundle own".
    """
    for d in (DEV / name, BUNDLES / name):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if (f.suffix != '.stream' and len(f.name) == 16
                    and all(c in '0123456789abcdef' for c in f.name.lower())):
                return f.name.lower()
    return ''


def rows() -> list:
    raw = DB.read_bytes()
    _v, count = struct.unpack('<II', raw[0:8])
    off, out = 8, []
    for _ in range(count):
        start = off
        _fl, blen = struct.unpack_from('<II', raw, off); off += 8
        off += blen
        slen, = struct.unpack_from('<I', raw, off); off += 4
        off += slen + 1
        out.append(raw[start:off])
    return out


def row_hash(row: bytes) -> str:
    _fl, blen = struct.unpack_from('<II', row, 0)
    return row[8:8 + blen].decode('utf-8', 'replace')


def write(rs: list) -> None:
    raw = DB.read_bytes()
    (version,), = [struct.unpack_from('<I', raw, 0)]
    out = bytearray(struct.pack('<II', version, len(rs)))
    for r in rs:
        out += r
    DB.write_bytes(bytes(out))


def report() -> set:
    deployed = {p.name for p in BUNDLES.iterdir() if p.is_dir()}
    rs = rows()
    print('  deployed: %s' % (', '.join(sorted(deployed)) or 'none'))
    print('  db rows : %d' % len(rs))
    for name in KNOWN:
        h = hash_of(name)
        n = sum(1 for r in rs if row_hash(r) == h) if h else 0
        print('    %-14s %s  rows %-3d  contents %s'
              % (name, h or '(not built)', n,
                 'present' if h and (CONTENTS / h).exists() else 'absent'))
    return deployed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', action='append', default=[])
    ap.add_argument('--none', action='store_true')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()

    if a.list:
        report()
        return 0

    want = set() if a.none else set(a.only)
    bad = want - set(KNOWN)
    if bad:
        print('unknown bundle(s): %s' % ', '.join(sorted(bad)))
        return 2

    print('== before'); report()

    # Deploy first, so a strip can never race the folders, and tolerate a name the dev
    # tree does not have: sorted() put CraneTexTest first, its copytree raised, and the
    # whole deploy aborted before RtexTest/HamTexOverride - which then looked like the
    # script had stripped their rows when it had never reached them.
    for p in BUNDLES.iterdir():
        if p.is_dir() and p.name not in want:
            shutil.rmtree(p, ignore_errors=True)

    for name in sorted(want):
        src = DEV / name
        dst = BUNDLES / name
        if not src.is_dir():
            print('  WARNING: %s has no folder in the dev tree; cannot deploy' % name)
            continue
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)

    # Strip the rows of every KNOWN bundle we are NOT keeping.  This was inverted
    # (want_hashes), which kept the stripped bundle's rows and would have dropped the
    # kept bundle's - it printed "stripped: 0 row(s)" while RoomEditTest still had 9
    # rows live, pointing at content files this same run had just deleted.
    strip_hashes = {hash_of(n) for n in KNOWN if n not in want}
    strip_hashes.discard('')
    all_rows = rows()
    keep = [r for r in all_rows if row_hash(r) not in strip_hashes]
    stripped = len(all_rows) - len(keep)

    removed_files = []
    for name in KNOWN:
        if name in want:
            continue
        h = hash_of(name)
        if not h:
            continue
        for suffix in ('', '.stream'):
            f = CONTENTS / (h + suffix)
            if f.exists():
                f.unlink()
                removed_files.append(f.name)

    write(keep)

    print()
    print('== after')
    deployed = report()
    print('  stripped: %d row(s), %s' % (stripped, ', '.join(removed_files) or 'no files'))
    ok = deployed == want
    print('  %s' % ('STATE MATCHES REQUEST' if ok else 'STATE DOES NOT MATCH'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
