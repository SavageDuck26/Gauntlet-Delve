"""Compare bundle_database.data with its backup to find exactly what changed."""
import struct
from pathlib import Path

CONTENTS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents")

def parse_db(path):
    with open(path, "rb") as f:
        data = f.read()
    version, count = struct.unpack("<II", data[:8])
    entries = []
    offset = 8
    for _ in range(count):
        flags = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
        blen = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
        bname = data[offset:offset+blen].decode("utf-8"); offset += blen
        slen = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
        sname = data[offset:offset+slen].decode("utf-8"); offset += slen
        offset += 1
        entries.append({"flags": flags, "bundle": bname, "stream": sname})
    return version, entries, len(data)

print("=" * 70)
print("COMPARING CURRENT DB vs BACKUP")
print("=" * 70)

backup = CONTENTS / "bundle_database.data.backup"
current = CONTENTS / "bundle_database.data"

if not backup.exists():
    print("No backup found!")
    exit()

bver, bentries, bsize = parse_db(backup)
cver, centries, csize = parse_db(current)

print(f"Backup:  version={bver}  entries={len(bentries)}  size={bsize}")
print(f"Current: version={cver}  entries={len(centries)}  size={csize}")
print(f"Diff:    {len(centries) - len(bentries)} entries added")

# Find unique bundle names
bset = {}
for e in bentries:
    bset[e["bundle"]] = bset.get(e["bundle"], 0) + 1

cset = {}
for e in centries:
    cset[e["bundle"]] = cset.get(e["bundle"], 0) + 1

# Bundles in current but not backup
new_bundles = set(cset.keys()) - set(bset.keys())
removed_bundles = set(bset.keys()) - set(cset.keys())
changed_count = {b for b in bset if b in cset and bset[b] != cset[b]}

print(f"\nNew bundles (in current, not in backup): {len(new_bundles)}")
for b in sorted(new_bundles):
    print(f"  {b}  entries={cset[b]}")

print(f"\nRemoved bundles (in backup, not in current): {len(removed_bundles)}")
for b in sorted(removed_bundles):
    print(f"  {b}  entries={bset[b]}")

print(f"\nBundles with entry count changes: {len(changed_count)}")
for b in sorted(changed_count):
    print(f"  {b}  backup={bset[b]} -> current={cset[b]}")

# Also check: d397e26a7f03456b (the other custom bundle)
print(f"\n--- d397e26a7f03456b status ---")
print(f"  In backup: {bset.get('d397e26a7f03456b', 'NOT FOUND')}")
print(f"  In current: {cset.get('d397e26a7f03456b', 'NOT FOUND')}")

# Check our bundle
print(f"\n--- b5ddd5abe546fd2c (our TestBundle) ---")
print(f"  In backup: {bset.get('b5ddd5abe546fd2c', 'NOT FOUND')}")
print(f"  In current: {cset.get('b5ddd5abe546fd2c', 'NOT FOUND')}")

# Also inspect d397e26a7f03456b bundle file
d3_path = CONTENTS / "d397e26a7f03456b"
if d3_path.exists():
    import zlib
    with open(d3_path, "rb") as f:
        raw = f.read()
    sig = struct.unpack("<I", raw[:4])[0]
    print(f"\n--- d397e26a7f03456b bundle file ---")
    print(f"  Size: {len(raw)} bytes")
    print(f"  Signature: 0x{sig:08X}")
    if sig == 0xF0000004:
        unp_size = struct.unpack("<I", raw[4:8])[0]
        print(f"  Unpacked size: {unp_size}")
else:
    print(f"\n  d397e26a7f03456b bundle file: NOT ON DISK")

# Check the auto-generated mod still exists
auto_mod = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\custom\functions\Local Mods\TestBundle(FF)v1.0\script_main.lua")
dev_mod = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\custom\functions\DEV\TestBundle(DEV)\script_main.lua")
print(f"\nAuto-generated mod (Local Mods): {'EXISTS' if auto_mod.exists() else 'not found'}")
print(f"User's mod (DEV):                {'EXISTS' if dev_mod.exists() else 'not found'}")
if auto_mod.exists() and dev_mod.exists():
    print("  WARNING: Both mod locations exist - could cause double loading!")
