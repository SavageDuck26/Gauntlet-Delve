"""Deep byte-level comparison of our test bundle vs an original game bundle."""
import struct, zlib
from pathlib import Path

CONTENTS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents")

def decompress(path):
    with open(path, "rb") as f:
        raw = f.read()
    sig, unp_size, unk = struct.unpack("<III", raw[:12])
    offset = 12
    chunks = []
    while offset < len(raw):
        cs = struct.unpack("<I", raw[offset:offset+4])[0]; offset += 4
        chunks.append(zlib.decompress(raw[offset:offset+cs]))
        offset += cs
    return b"".join(chunks)

# Pick a small original game bundle to compare structure
# 0164ad48615ba9ed has 189 entries - too many. Let's find a game bundle
# and also compare d397e26a7f03456b (the other custom bundle)

print("="*70)
print("ORIGINAL GAME BUNDLE: 0164ad48615ba9ed (first 3 resources)")
print("="*70)
u = decompress(CONTENTS / "0164ad48615ba9ed")
count = struct.unpack("<I", u[:4])[0]
print(f"Count: {count}")
print(f"Total size: {len(u)}")

# First 3 hashes
for i in range(min(3, count)):
    h = struct.unpack("<Q", u[4+i*8:4+(i+1)*8])[0]
    print(f"  hash[{i}]: 0x{h:016X}")

# Entry table position
nhash_end = 4 + count * 8
print(f"Hash table ends at: 0x{nhash_end:X}")
# If overflows 0x104, entry table is right after hash table
if nhash_end > 0x104:
    et_off = nhash_end
else:
    et_off = 0x104
print(f"Entry table at: 0x{et_off:X}")

# Show first 3 entries
for i in range(min(3, count)):
    th, nh = struct.unpack("<QQ", u[et_off+i*16:et_off+(i+1)*16])
    print(f"  entry[{i}]: type=0x{th:016X} name=0x{nh:016X}")

# Data section
doff = et_off + count * 16
print(f"Data section at: 0x{doff:X}")
# First resource header as raw bytes
print(f"First resource header (36 bytes raw hex):")
print(f"  {u[doff:doff+36].hex()}")
# Parse it
rtype, rname, flags = struct.unpack("<QQI", u[doff:doff+20])
ss = struct.unpack("<Q", u[doff+20:doff+28])[0]
ms, unk = struct.unpack("<II", u[doff+28:doff+36])
print(f"  type=0x{rtype:016X} name=0x{rname:016X} flags={flags}")
print(f"  stream_size={ss} main_size={ms} unk={unk}")

print()
print("="*70)
print("OUR TEST BUNDLE: b5ddd5abe546fd2c (all resources)")
print("="*70)
u2 = decompress(CONTENTS / "b5ddd5abe546fd2c")
count2 = struct.unpack("<I", u2[:4])[0]
print(f"Count: {count2}")
print(f"Total size: {len(u2)}")

# All hashes
for i in range(count2):
    h = struct.unpack("<Q", u2[4+i*8:4+(i+1)*8])[0]
    print(f"  hash[{i}]: 0x{h:016X}")

# Padding area - check what's between hash table end and 0x104
print(f"\nHash table ends: 0x{4+count2*8:X}")
print(f"Bytes 0x14 to 0x24 (first 16 of padding): {u2[0x14:0x24].hex()}")
print(f"Bytes 0xF4 to 0x104 (last 16 of padding): {u2[0xF4:0x104].hex()}")

# Entry table
et2 = 0x104
print(f"\nEntry table at 0x104:")
for i in range(count2):
    th, nh = struct.unpack("<QQ", u2[et2+i*16:et2+(i+1)*16])
    print(f"  entry[{i}]: type=0x{th:016X} name=0x{nh:016X}")

# Data section
doff2 = et2 + count2 * 16
print(f"\nData section at: 0x{doff2:X}")
for i in range(count2):
    print(f"\nResource [{i}] header (36 bytes raw):")
    print(f"  {u2[doff2:doff2+36].hex()}")
    rtype, rname, flags = struct.unpack("<QQI", u2[doff2:doff2+20])
    ss = struct.unpack("<Q", u2[doff2+20:doff2+28])[0]
    ms, unk = struct.unpack("<II", u2[doff2+28:doff2+36])
    print(f"  type=0x{rtype:016X} name=0x{rname:016X} flags={flags}")
    print(f"  stream_size={ss} main_size={ms} unk={unk}")
    fb = u2[doff2+36:doff2+36+min(32,ms)]
    print(f"  data[0:32]={fb.hex()}")
    doff2 += 36 + ms

print(f"\nTotal: 0x{doff2:X}, remaining: {len(u2)-doff2}")
print(f"Trailing: {u2[doff2:].hex()}")

print()
print("="*70)
print("OTHER CUSTOM BUNDLE: d397e26a7f03456b")
print("="*70)
u3 = decompress(CONTENTS / "d397e26a7f03456b")
count3 = struct.unpack("<I", u3[:4])[0]
print(f"Count: {count3}")
print(f"Total size: {len(u3)}")
for i in range(min(count3,5)):
    h = struct.unpack("<Q", u3[4+i*8:4+(i+1)*8])[0]
    print(f"  hash[{i}]: 0x{h:016X}")

nhash_end3 = 4 + count3 * 8
et3 = 0x104 if nhash_end3 < 0x104 else nhash_end3
print(f"Entry table at: 0x{et3:X}")
for i in range(min(count3,5)):
    th, nh = struct.unpack("<QQ", u3[et3+i*16:et3+(i+1)*16])
    print(f"  entry[{i}]: type=0x{th:016X} name=0x{nh:016X}")

doff3 = et3 + count3 * 16
print(f"Data at: 0x{doff3:X}")
for i in range(min(count3,3)):
    rtype, rname, flags = struct.unpack("<QQI", u3[doff3:doff3+20])
    ss = struct.unpack("<Q", u3[doff3+20:doff3+28])[0]
    ms, unk = struct.unpack("<II", u3[doff3+28:doff3+36])
    tnames = {0xCD4238C6A0C69E32:"texture", 0xEAC0B497876ADEDF:"material", 0xAD9C6D9ED1E5E77A:"package"}
    print(f"  [{i}] {tnames.get(rtype,'?')} name=0x{rname:016X} flags={flags} stream={ss} main={ms}")
    fb = u3[doff3+36:doff3+36+min(16,ms)]
    print(f"      data hex: {fb.hex()}")
    if fb[:4] == b"DDS ":
        dw = struct.unpack_from("<I", fb, 16)[0] if len(fb) >= 20 else 0
        dh = struct.unpack_from("<I", fb, 12)[0] if len(fb) >= 16 else 0
        print(f"      DDS {dw}x{dh}")
    doff3 += 36 + ms
print(f"Remaining: {len(u3)-doff3}")
