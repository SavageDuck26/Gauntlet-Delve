#!/usr/bin/env python3
"""
Batch export all Gauntlet .unit resources to GLB format for Blender.

Reads unit data directly from game bundles without needing to pre-extract,
then converts each one to a .glb file that can be imported into Blender.

Usage:
  python3 batch_export_glb.py                    # Export all to Exports/glb/
  python3 batch_export_glb.py --out /tmp/glb     # Custom output dir
  python3 batch_export_glb.py --limit 50         # Only first N units
"""
import struct, zlib, os, sys, tempfile, argparse
from pathlib import Path

GAME    = os.path.expanduser('~/.local/share/Steam/steamapps/common/Gauntlet/contents/')
UNIT_TH = 0xE0A48D0BE9A7453F
BONE_TH = 0x18DEAD01056B72E9
HERE    = Path(__file__).parent

# ── bundle decompressor ───────────────────────────────────────────────────────

def decomp(path: str) -> bytes:
    with open(path, 'rb') as f:
        data = f.read()
    sig = struct.unpack_from('<I', data, 0)[0]
    if sig not in (0xF0000004, 0xF0000005, 0xF0000006):
        return data
    pos, out = 12, b''
    while pos + 4 <= len(data):
        cs = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if cs == 0:
            break
        try:
            out += zlib.decompress(data[pos:pos + cs])
        except:
            out += data[pos:pos + cs]
        pos += cs
    return out


def parse_resources(data: bytes) -> dict[tuple, bytes]:
    """Parse all resources from decompressed bundle data.
    Returns dict of (type_hash, name_hash) → data bytes.
    """
    results = {}
    try:
        N = struct.unpack_from('<I', data, 0)[0]
        if N > 50000 or N == 0:
            return results
        te = 0x104 + (N + 1) * 16

        # resource 0 (special layout)
        th, nh = struct.unpack_from('<QQ', data, 0x104)
        flags, _, dsz, ssz = struct.unpack_from('<IQII', data, te)
        if dsz > 0:
            results[(th, nh)] = data[te + 20:te + 20 + dsz]

        off = te + 20 + dsz
        for _ in range(1, N):
            if off + 36 > len(data):
                break
            th, nh, flags, _, dsz, ssz = struct.unpack_from('<QQIQII', data, off)
            if dsz > 0 and off + 36 + dsz <= len(data):
                results[(th, nh)] = data[off + 36:off + 36 + dsz]
            off += 36 + dsz
    except Exception:
        pass
    return results


# ── main batch export ─────────────────────────────────────────────────────────

def batch_export(out_dir: str, limit: int = 0, verbose: bool = False):
    import importlib.util as _ilu

    def load(name, path):
        spec = _ilu.spec_from_file_location(name, path)
        mod  = _ilu.module_from_spec(spec)
        sys.path.insert(0, str(HERE))
        spec.loader.exec_module(mod)
        return mod

    unit_to_gltf = load('unit_to_gltf', HERE / 'unit_to_gltf.py')

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    bundles = sorted(
        f for f in os.listdir(GAME)
        if '.' not in f and os.path.isfile(GAME + f)
    )

    # Collect all units and bones across all bundles
    all_units: dict[int, bytes] = {}   # name_hash → unit data
    all_bones: dict[int, bytes] = {}   # name_hash → bones data

    print(f"Scanning {len(bundles)} bundles...")
    for bname in bundles:
        bpath = GAME + bname
        try:
            data = decomp(bpath)
            resources = parse_resources(data)
            for (th, nh), blob in resources.items():
                if th == UNIT_TH and nh not in all_units:
                    all_units[nh] = blob
                elif th == BONE_TH and nh not in all_bones:
                    all_bones[nh] = blob
        except Exception as e:
            if verbose:
                print(f"  SKIP {bname}: {e}")

    print(f"Found {len(all_units)} unique unit resources, {len(all_bones)} unique bone resources")

    unit_hashes = sorted(all_units.keys())
    if limit:
        unit_hashes = unit_hashes[:limit]
        print(f"Limiting to first {limit}")

    success = fail = 0
    with tempfile.TemporaryDirectory(prefix='gauntlet_glb_') as tmpdir:
        for i, nh in enumerate(unit_hashes, 1):
            name = f'{nh:016x}'
            unit_path = os.path.join(tmpdir, f'{name}.unit')
            glb_path   = str(out / f'{name}.glb')

            if os.path.exists(glb_path):
                if verbose:
                    print(f"[{i}/{len(unit_hashes)}] SKIP (exists): {name}.glb")
                success += 1
                continue

            # Write unit to temp file
            with open(unit_path, 'wb') as f:
                f.write(all_units[nh])

            # Optionally write bones
            bones_path = None
            if nh in all_bones:
                bones_path = os.path.join(tmpdir, f'{name}.bones')
                with open(bones_path, 'wb') as f:
                    f.write(all_bones[nh])

            try:
                unit_to_gltf.convert_unit_to_gltf(
                    unit_path, bones_path, glb_path, verbose=False
                )
                sz = os.path.getsize(glb_path)
                print(f"[{i}/{len(unit_hashes)}] {name}.glb  ({sz:,} bytes)"
                      + (" +skel" if bones_path else ""))
                success += 1
            except Exception as e:
                print(f"[{i}/{len(unit_hashes)}] FAIL {name}: {e}")
                fail += 1

    print(f"\nDone: {success} exported, {fail} failed → {out}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='Exports/glb',
                        help='Output directory (default: Exports/glb)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Only export first N units')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    batch_export(args.out, args.limit, args.verbose)
