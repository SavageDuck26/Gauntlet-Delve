"""
Stingray .package resource decode/encode.

Format (confirmed from binary analysis):
  uint32  entry_count       number of resource entries

  Each entry (28 bytes):
    uint64  type_hash        MurmurHash64A of the resource type string
    uint64  name_hash        MurmurHash64A of the resource path/name string
    uint32  c1               = 2 (always; flags or version)
    uint32  c2               = fixed value per package (possibly derived from pkg hash)
    uint32  name_hash_hi32   upper 32 bits of name_hash (fast-lookup copy)

  uint8   trailer = 0x01

Known type hashes (from bundle analysis and FINDINGS.txt):
  0xa14e8dfa2cd117e2  texture
  0x9199a703b4f76e56  material
  0x13d5f9b71afb4fd2  unit
  ...

Usage:
  pkg = decode_package(blob)
  # pkg = {'entries': [{'type_hash': '0x...', 'name_hash': '0x...', 'c1': 2, ...}, ...]}
  blob2 = encode_package(pkg)
"""

from __future__ import annotations
import json, os, struct, sys
from typing import Any, Dict, List

ENTRY_SIZE = 28
ENTRY_FMT  = '<QQ II I'  # type_hash, name_hash, c1, c2, name_hash_hi32

KNOWN_TYPE_HASHES: Dict[str, str] = {
    "0xcd4238c6a0c69e32": "texture",
    "0xa14e8dfa2cd117e2": "lua",
    "0xeac0b497876adedf": "material",
    "0xe0a48d0be9a7453f": "unit",
    "0xf7505491a64f4b44": "mesh",
    "0x27862fe24795319c": "render_config",
    "0x18dead01056b72e9": "bones",
    "0xad9c6d9ed1e5e77a": "package",
    "0xb7893adf7567506a": "level",
    "0x82645835e6b73232": "physics_properties",
    "0x2b02b3a4e0e594f5": "config",
    "0x3fcdd69156a46417": "bones",
    "0x6aa91aa3c4d9e90f": "animation",
    "0x7ffd67aeb2a75069": "shader",
    "0xa8193123526fad64": "strings",
    "0xd7468465328c897f": "particles",
    "0x9e5b493b3a5f1b3c": "font",
}


def decode_package(blob: bytes) -> Dict[str, Any]:
    """Parse raw .package blob → dict."""
    if len(blob) < 5:
        raise ValueError("blob too short")

    n = struct.unpack_from('<I', blob, 0)[0]
    expected = 4 + n * ENTRY_SIZE + 1
    if len(blob) != expected:
        raise ValueError(f"size mismatch: expected {expected} (count={n}), got {len(blob)}")

    entries: List[Dict[str, Any]] = []
    for i in range(n):
        off = 4 + i * ENTRY_SIZE
        th, nh, c1, c2, nh_hi = struct.unpack_from('<QQ II I', blob, off)
        th_s = f"0x{th:016x}"
        nh_s = f"0x{nh:016x}"
        entry: Dict[str, Any] = {
            "type_hash": th_s,
            "name_hash": nh_s,
            "c1": c1,
            "c2": f"0x{c2:08x}",
            "_name_hash_hi32": f"0x{nh_hi:08x}",
        }
        if th_s in KNOWN_TYPE_HASHES:
            entry["_type_name"] = KNOWN_TYPE_HASHES[th_s]
        entries.append(entry)

    trailer_byte = blob[-1]
    return {
        "entries": entries,
        "_trailer_byte": trailer_byte,
    }


def encode_package(data: Dict[str, Any]) -> bytes:
    """Encode package dict → binary blob."""
    entries = data["entries"]
    n = len(entries)
    body = bytearray(struct.pack('<I', n))
    for e in entries:
        th = int(e["type_hash"], 16)
        nh = int(e["name_hash"], 16)
        c1 = e.get("c1", 2)
        c2 = int(e.get("c2", "0x0"), 16)
        nh_hi = int(e.get("_name_hash_hi32", f"0x{nh >> 32:08x}"), 16)
        body += struct.pack('<QQ II I', th, nh, c1, c2, nh_hi)
    trailer_byte = data.get("_trailer_byte", 0x01)
    return bytes(body) + bytes([trailer_byte])


def decode_package_file(src: str, dst: str | None = None) -> str:
    blob = open(src, 'rb').read()
    data = decode_package(blob)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.json'
    with open(dst, 'w') as f:
        json.dump(data, f, indent=2)
    n = len(data["entries"])
    print(f"Decoded {src} → {dst}  ({n} entries)")
    return dst


def encode_package_file(src: str, dst: str | None = None) -> str:
    with open(src) as f:
        data = json.load(f)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.package'
    open(dst, 'wb').write(encode_package(data))
    print(f"Encoded {src} → {dst}")
    return dst


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'selftest':
        sample = 'Exports/samples/package_0bd097fa120382fe.package'
        orig = open(sample, 'rb').read()
        data = decode_package(orig)
        re_enc = encode_package(data)
        if orig == re_enc:
            print("package_tools selftest: PASS (byte-exact)")
        else:
            print(f"package_tools selftest: MISMATCH  orig={len(orig)} re-enc={len(re_enc)}")
            first = next(i for i in range(min(len(orig), len(re_enc))) if orig[i] != re_enc[i])
            print(f"  first diff @ byte {first}: orig=0x{orig[first]:02x} re=0x{re_enc[first]:02x}")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'decode':
        decode_package_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'encode':
        encode_package_file(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("Usage: package_tools.py selftest | decode <file.package> | encode <file.json>")
