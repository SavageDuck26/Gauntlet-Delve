"""Check the REAL entry table position for game bundles.
The FINDINGS say entry table is ALWAYS at 0x104 and hash table is max 0x100 bytes."""
import struct, zlib
from pathlib import Path

CONTENTS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents")

TYPE_NAMES = {
    0xCD4238C6A0C69E32: "texture", 0xEAC0B497876ADEDF: "material",
    0xAD9C6D9ED1E5E77A: "package", 0xA14E8DFA2CD117E2: "lua",
    0xE0A48D0BE9A7453F: "unit",    0x48FF313713A997A1: "mesh",
    0x82645835E6B73232: "config",  0xCCE8D5B5F5AE333F: "shader",
    0x931E336D7646CC26: "animation", 0x18DEAD01056B72E9: "bones",
    0xA8193123526FAD64: "particles", 0x5F7203C8F280DAB8: "physics",
    0x2A690FD348FE9AC5: "level",   0x9EFE0A916AAE7880: "font",
    0x0D972BAB10B40FD3: "strings",
}

def decompress(path):
    with open(path, "rb") as f:
        raw = f.read()
    offset = 12
    chunks = []
    while offset < len(raw):
        cs = struct.unpack("<I", raw[offset:offset+4])[0]; offset += 4
        chunks.append(zlib.decompress(raw[offset:offset+cs]))
        offset += cs
    return b"".join(chunks)

# ===== Test: Read entry table ALWAYS from 0x104 for original game bundle =====
print("="*70)
print("GAME BUNDLE 0164ad48615ba9ed - Entry table AT 0x104")
print("="*70)
u = decompress(CONTENTS / "0164ad48615ba9ed")
count = struct.unpack("<I", u[:4])[0]
print(f"Resource count: {count}")

# Hash table: only min(count, 32) entries, max 0x100 bytes
hash_count = min(count, 32)
print(f"Hash table entries: {hash_count} (stored, out of {count} total)")
for i in range(hash_count):
    h = struct.unpack("<Q", u[4+i*8:4+(i+1)*8])[0]
    if i < 3 or i >= hash_count-1:
        print(f"  hash[{i}]: 0x{h:016X}")
    elif i == 3:
        print(f"  ...")

# Entry table at 0x104 - try reading entries
print(f"\nEntry table at 0x104 (first 10 entries):")
et = 0x104
type_counts = {}
for i in range(min(10, count)):
    th, nh = struct.unpack("<QQ", u[et+i*16:et+(i+1)*16])
    tname = TYPE_NAMES.get(th, f"0x{th:016X}")
    type_counts[tname] = type_counts.get(tname, 0) + 1
    if i < 10:
        print(f"  [{i:4d}] type=0x{th:016X} ({tname})  name=0x{nh:016X}")

# Count all types
type_counts_all = {}
for i in range(count):
    th = struct.unpack("<Q", u[et+i*16:et+i*16+8])[0]
    tname = TYPE_NAMES.get(th, f"UNKNOWN(0x{th:016X})")
    type_counts_all[tname] = type_counts_all.get(tname, 0) + 1

print(f"\nResource type breakdown (reading entry table from 0x104):")
for t, c in sorted(type_counts_all.items(), key=lambda x: -x[1]):
    print(f"  {t:20s}: {c}")

# Now try the OTHER orientation: (name, type) instead of (type, name)
print(f"\nALTERNATIVE: entry format = (name_hash, type_hash)?")
type_counts_alt = {}
for i in range(count):
    nh, th = struct.unpack("<QQ", u[et+i*16:et+(i+1)*16])
    tname = TYPE_NAMES.get(th, f"UNKNOWN(0x{th:016X})")
    type_counts_alt[tname] = type_counts_alt.get(tname, 0) + 1

print(f"Type breakdown (with reversed field order):")
for t, c in sorted(type_counts_alt.items(), key=lambda x: -x[1]):
    print(f"  {t:20s}: {c}")

# Data section: try reading from after the entry table
data_off = 0x104 + count * 16
print(f"\nData section should be at: 0x{data_off:X}")
print(f"First 64 bytes of data section:")
print(f"  {u[data_off:data_off+64].hex()}")

# Try to parse as resource header
rtype, rname, flags = struct.unpack("<QQI", u[data_off:data_off+20])
ss = struct.unpack("<Q", u[data_off+20:data_off+28])[0]
ms, unk = struct.unpack("<II", u[data_off+28:data_off+36])
tname = TYPE_NAMES.get(rtype, f"0x{rtype:016X}")
print(f"\nParsed as (type,name,flags,stream,main,unk):")
print(f"  type=0x{rtype:016X} ({tname})")
print(f"  name=0x{rname:016X}")
print(f"  flags={flags} stream_size={ss} main_size={ms} unk={unk}")
if ms < len(u) and ms > 0 and ms < 100_000_000:
    fb = u[data_off+36:data_off+36+min(16,ms)]
    print(f"  data starts with: {fb.hex()}")
    if fb[:4] == b"DDS ":
        print(f"  -> DDS MAGIC FOUND!")

# Also try: does the data section have a different header format?
print(f"\nTrying reversed header (name,type,flags...):")
rname2, rtype2, flags2 = struct.unpack("<QQI", u[data_off:data_off+20])
ss2 = struct.unpack("<Q", u[data_off+20:data_off+28])[0]
ms2, unk2 = struct.unpack("<II", u[data_off+28:data_off+36])
tname2 = TYPE_NAMES.get(rtype2, f"0x{rtype2:016X}")
print(f"  type=0x{rtype2:016X} ({tname2})")
print(f"  name=0x{rname2:016X}")
print(f"  flags={flags2} stream_size={ss2} main_size={ms2} unk={unk2}")
if ms2 < len(u) and ms2 > 0 and ms2 < 100_000_000:
    fb2 = u[data_off+36:data_off+36+min(16,ms2)]
    print(f"  data starts with: {fb2.hex()}")
    if fb2[:4] == b"DDS ":
        print(f"  -> DDS MAGIC FOUND!")

# ===== Also check: does d5ec4eb9fc5f3c88 (known good) work with entry at 0x104? =====
print(f"\n{'='*70}")
print("KNOWN GOOD d5ec4eb9fc5f3c88 - testing entry table at 0x104")
print("="*70)
u4 = decompress(CONTENTS / "d5ec4eb9fc5f3c88")
count4 = struct.unpack("<I", u4[:4])[0]
print(f"Resource count: {count4}")

# Check: what's at 0x104?
print(f"\nAt offset 0x104 (16 bytes):")
print(f"  {u4[0x104:0x114].hex()}")
th4, nh4 = struct.unpack("<QQ", u4[0x104:0x114])
print(f"  As (type, name): type=0x{th4:016X} ({TYPE_NAMES.get(th4, '?')}) name=0x{nh4:016X}")
nh4r, th4r = struct.unpack("<QQ", u4[0x104:0x114])
print(f"  As (name, type): name=0x{nh4r:016X} type=0x{th4r:016X} ({TYPE_NAMES.get(th4r, '?')})")

# With 41 resources, hash table = 41*8 = 328 bytes, ends at 0x14C
# If entry table is at 0x104, then hashes 32-40 overlap with entry table
# Check if hash table is truly limited to 32 entries
print(f"\nHash table analysis:")
print(f"  Full table (41 entries) would end at: 0x{4+41*8:X}")
print(f"  Limited (32 entries) would end at: 0x{4+32*8:X}")
# Read bytes at 0x104 and check if they look like hash or entry
val_at_104 = struct.unpack("<Q", u4[0x104:0x10C])[0]
val_at_10C = struct.unpack("<Q", u4[0x10C:0x114])[0]
print(f"  Value at 0x104: 0x{val_at_104:016X}")
print(f"  Value at 0x10C: 0x{val_at_10C:016X}")

# Hash values sorted check for first 40 entries
all_hashes = []
for i in range(41):
    h = struct.unpack("<Q", u4[4+i*8:4+(i+1)*8])[0]
    all_hashes.append(h)
for i in range(40):
    if all_hashes[i] > all_hashes[i+1]:
        print(f"  Sort break at index {i}: 0x{all_hashes[i]:016X} > 0x{all_hashes[i+1]:016X}")
        break
else:
    print(f"  All 41 hashes are sorted ascending")

# Check what entry table format produces valid types from 0x104
print(f"\nEntry table from 0x14C (current code reads from here):")
for i in range(3):
    th, nh = struct.unpack("<QQ", u4[0x14C+i*16:0x14C+(i+1)*16])
    print(f"  [{i}] type=0x{th:016X} ({TYPE_NAMES.get(th,'?')}) name=0x{nh:016X}")

print(f"\nEntry table from 0x104 instead:")
for i in range(3):
    th, nh = struct.unpack("<QQ", u4[0x104+i*16:0x104+(i+1)*16])
    print(f"  [{i}] type=0x{th:016X} ({TYPE_NAMES.get(th,'?')}) name=0x{nh:016X}")
