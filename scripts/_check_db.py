import struct
from pathlib import Path

CONTENTS = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents")
with open(CONTENTS / "bundle_database.data", "rb") as f:
    data = f.read()

version, count = struct.unpack("<II", data[:8])
print(f"DB version: {version}, entries: {count}")

offset = 8
bundles = {}
for i in range(count):
    flags = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
    blen = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
    bname = data[offset:offset+blen].decode("utf-8"); offset += blen
    slen = struct.unpack("<I", data[offset:offset+4])[0]; offset += 4
    sname = data[offset:offset+slen].decode("utf-8"); offset += slen
    offset += 1
    if bname not in bundles:
        bundles[bname] = {"stream": sname, "flags": flags, "count": 0}
    bundles[bname]["count"] += 1

print(f"\nUnique bundles: {len(bundles)}")
print(f"Parsed {offset} / {len(data)} bytes (remaining: {len(data) - offset})")

# Show every bundle with stream info
print(f"\n{'Bundle':<20} {'Entries':>7} {'Stream Name':<30} {'Disk?':>5} {'Stream Size':>12}")
print("-" * 80)
for bname, info in sorted(bundles.items()):
    stream_path = CONTENTS / (bname + ".stream")
    on_disk = stream_path.exists()
    ssize = stream_path.stat().st_size if on_disk else "-"
    marker = " <<<" if bname == "b5ddd5abe546fd2c" else ""
    print(f"{bname:<20} {info['count']:>7} {info['stream']:<30} {str(on_disk):>5} {str(ssize):>12}{marker}")

# Check: do ANY game bundles have empty stream names?
empty_streams = [b for b, i in bundles.items() if i["stream"] == ""]
print(f"\nBundles with empty stream name: {len(empty_streams)}")
for b in empty_streams[:5]:
    print(f"  {b}")

# Check: do game bundles WITHOUT .stream on disk ever reference a stream?
no_stream_disk = [b for b in bundles if not (CONTENTS / (b + ".stream")).exists()]
print(f"\nBundles without .stream file on disk: {len(no_stream_disk)}")
for b in no_stream_disk[:5]:
    print(f"  {b} -> stream name: '{bundles[b]['stream']}'")
