#!/usr/bin/env python3
"""
Stingray .lua resource encoder/decoder
Type hash: 0xA14E8DFA2CD117E2

Binary format:
  uint32 bytecode_size    -- size of the LuaJIT bytecode blob
  uint32 version = 2      -- always 2
  bytes  luajit_bytecode  -- starts with \x1bLJ\x01 marker

Round-trip:
  decode -> extracts .luajit bytecode file
  encode -> compiles .lua source with luajit, wraps in Stingray header

Usage:
  python3 lua_tools.py decode <file.lua>   -> writes <file>.luajit + <file>.src.lua
  python3 lua_tools.py encode <source.lua> -> writes <source>.lua.bin
  python3 lua_tools.py selftest
"""

import struct, sys, os, subprocess, tempfile

TYPE_HASH = 0xA14E8DFA2CD117E2
LUAJIT_MAGIC = b'\x1bLJ'


def decode_lua(blob: bytes) -> dict:
    """
    Decode a Stingray .lua resource blob.
    Returns: {'bytecode': bytes, 'source_path': str|None, 'version': int}
    """
    if len(blob) < 8:
        raise ValueError(f"Too short: {len(blob)} bytes")

    bc_size, ver = struct.unpack_from('<II', blob, 0)
    bytecode = blob[8:8 + bc_size]

    if not bytecode.startswith(LUAJIT_MAGIC):
        raise ValueError(f"Missing LuaJIT magic, got {bytecode[:4].hex()!r}")

    # Extract embedded source path from LuaJIT header
    # Format: \x1bLJ\x01 flags(1) [source_len(varint) source_str]
    source_path = None
    try:
        flags = bytecode[4]
        if not (flags & 0x02):  # bit 1 = strip debug info; if NOT stripped, source follows
            # varint-encoded source name length at byte 5
            pos = 5
            slen = 0
            shift = 0
            while pos < len(bytecode):
                b = bytecode[pos]; pos += 1
                slen |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            if slen > 0:
                source_path = bytecode[pos:pos + slen - 1].decode('utf-8', 'replace')
    except Exception:
        pass

    return {
        'version': ver,
        'bytecode_size': bc_size,
        'source_path': source_path,
        'bytecode': bytecode,
    }


def encode_lua_from_bytecode(bytecode: bytes, version: int = 2) -> bytes:
    """Wrap raw LuaJIT bytecode in Stingray .lua resource header."""
    if not bytecode.startswith(LUAJIT_MAGIC):
        raise ValueError("Not valid LuaJIT bytecode (missing \\x1bLJ header)")
    header = struct.pack('<II', len(bytecode), version)
    return header + bytecode


def encode_lua_from_source(source: str, luajit_path: str = 'luajit') -> bytes:
    """
    Compile Lua source text to Stingray .lua resource blob.
    Requires luajit to be in PATH (or provide full path).
    """
    with tempfile.NamedTemporaryFile(suffix='.lua', mode='w', delete=False) as f:
        f.write(source)
        src_path = f.name
    bc_path = src_path + '.jit'
    try:
        result = subprocess.run(
            [luajit_path, '-b', src_path, bc_path],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"luajit compile failed: {result.stderr.decode()}")
        with open(bc_path, 'rb') as f:
            bytecode = f.read()
        return encode_lua_from_bytecode(bytecode)
    finally:
        os.unlink(src_path)
        if os.path.exists(bc_path):
            os.unlink(bc_path)


def disassemble_lua(blob: bytes, luajit_path: str = 'luajit') -> str:
    """
    Disassemble a Stingray .lua blob using luajit -ds.
    Returns disassembly as a string.
    """
    info = decode_lua(blob)
    with tempfile.NamedTemporaryFile(suffix='.jit', delete=False) as f:
        f.write(info['bytecode'])
        bc_path = f.name
    try:
        result = subprocess.run(
            [luajit_path, '-ds', bc_path],
            capture_output=True, timeout=30
        )
        out = result.stdout.decode('utf-8', 'replace')
        err = result.stderr.decode('utf-8', 'replace')
        return out + err
    finally:
        os.unlink(bc_path)


def selftest():
    """Test round-trip with a trivial Lua program."""
    import shutil
    if not shutil.which('luajit'):
        print("SKIP: luajit not found in PATH")
        return

    src = 'local x = 1 + 2\nreturn x\n'
    blob = encode_lua_from_source(src)
    info = decode_lua(blob)
    assert info['bytecode'].startswith(LUAJIT_MAGIC), "Missing LuaJIT magic"
    assert info['version'] == 2
    # Re-encode from bytecode
    blob2 = encode_lua_from_bytecode(info['bytecode'])
    assert blob == blob2, "Round-trip mismatch"
    print("lua_tools selftest: PASS")


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
        info = decode_lua(blob)
        out_jit = path.rsplit('.', 1)[0] + '.luajit'
        with open(out_jit, 'wb') as f:
            f.write(info['bytecode'])
        print(f"Decoded: {path}")
        print(f"  version={info['version']}, bytecode_size={info['bytecode_size']}")
        print(f"  source_path={info['source_path']!r}")
        print(f"  -> {out_jit}")
        print("  To disassemble: luajit -ds <file>.luajit")

    elif cmd == 'encode':
        path = sys.argv[2]
        src = open(path, 'r').read()
        blob = encode_lua_from_source(src)
        out = path + '.bin'
        with open(out, 'wb') as f:
            f.write(blob)
        print(f"Encoded {path} -> {out}  ({len(blob)} bytes)")

    elif cmd == 'disasm':
        path = sys.argv[2]
        blob = open(path, 'rb').read()
        print(disassemble_lua(blob))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
