#!/usr/bin/env python3
"""
Stingray .config resource encoder/decoder
Type hash: 0x82645835E6B73232

The .config format is identical to .render_config: a COBJ binary tree.
This module is a thin wrapper around render_config_tools.COBJEncoder / decode_cobj.

Round-trip:
  decode → JSON (human-editable)
  encode → binary COBJ blob

Usage:
  python3 config_tools.py decode <file.config>          → <file>.json
  python3 config_tools.py encode <file.json> [out.bin]  → binary blob
  python3 config_tools.py selftest
"""

import json, sys, os

# Locate render_config_tools (parent directory)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from render_config_tools import decode_cobj, COBJEncoder

TYPE_HASH = 0x82645835E6B73232


def decode_config(blob: bytes) -> dict:
    """Decode a Stingray .config binary blob to a Python dict."""
    return decode_cobj(blob)


def encode_config(data: dict) -> bytes:
    """Encode a Python dict back to a Stingray .config binary blob."""
    enc = COBJEncoder()
    return enc.encode(data)


def decode_config_json(blob: bytes) -> str:
    """Decode blob to pretty-printed JSON string."""
    return json.dumps(decode_config(blob), indent=2, ensure_ascii=False)


def encode_config_from_json(json_text: str) -> bytes:
    """Encode a JSON string to a .config blob."""
    return encode_config(json.loads(json_text))


def selftest():
    """Verify round-trip on the extracted sample."""
    sample = os.path.join(os.path.dirname(__file__), '..', 'Exports', 'samples',
                          'config_5a072e1b08042c05.config')
    if not os.path.exists(sample):
        print("SKIP: sample not found")
        return
    blob = open(sample, 'rb').read()
    data = decode_config(blob)
    blob2 = encode_config(data)
    if blob == blob2:
        print("config_tools selftest: PASS (byte-exact)")
    else:
        # Semantic check: both decode to identical JSON?
        data2 = decode_config(blob2)
        if json.dumps(data, sort_keys=True) == json.dumps(data2, sort_keys=True):
            print(f"config_tools selftest: PASS (semantic, {len(blob)}→{len(blob2)} bytes, encoder compacts duplicate strings)")
        else:
            print(f"config_tools selftest: MISMATCH  orig={len(blob)} re-enc={len(blob2)}")
            for i, (a, b) in enumerate(zip(blob, blob2)):
                if a != b:
                    print(f"  first diff @ byte {i}: orig={a:#04x} re={b:#04x}")
                    break


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]

    if cmd == 'selftest':
        selftest()

    elif cmd == 'decode':
        path = sys.argv[2]
        blob = open(path, 'rb').read()
        out = path.rsplit('.', 1)[0] + '.json'
        with open(out, 'w') as f:
            f.write(decode_config_json(blob))
        print(f"Decoded {path} → {out}")

    elif cmd == 'encode':
        path = sys.argv[2]
        out = sys.argv[3] if len(sys.argv) > 3 else path.rsplit('.', 1)[0] + '.config'
        blob = encode_config_from_json(open(path).read())
        with open(out, 'wb') as f:
            f.write(blob)
        print(f"Encoded {path} → {out}  ({len(blob)} bytes)")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
