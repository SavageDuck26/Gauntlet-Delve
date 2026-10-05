#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def murmur64(key: str, seed: int = 0) -> int:
    m = 0xC6A4A7935BD1E995
    r = 47
    kb = key.lower().encode('utf-8')
    ln = len(kb)
    h = (seed ^ ((ln * m) & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF

    for i in range(ln // 8):
        k = struct.unpack_from('<Q', kb, i * 8)[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    tail = kb[ln & ~7:]
    if len(tail) >= 7:
        h ^= tail[6] << 48
    if len(tail) >= 6:
        h ^= tail[5] << 40
    if len(tail) >= 5:
        h ^= tail[4] << 32
    if len(tail) >= 4:
        h ^= tail[3] << 24
    if len(tail) >= 3:
        h ^= tail[2] << 16
    if len(tail) >= 2:
        h ^= tail[1] << 8
    if len(tail) >= 1:
        h ^= tail[0]
        h = (h * m) & 0xFFFFFFFFFFFFFFFF

    h ^= h >> r
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> r
    return h


def parse_resource_token(token: str) -> int:
    token = token.strip()
    if token.lower().startswith('0x'):
        return int(token, 16)
    return murmur64(token)


def replace_all_u64(buf: bytearray, old_val: int, new_val: int) -> int:
    old_b = old_val.to_bytes(8, 'little')
    new_b = new_val.to_bytes(8, 'little')
    count = 0
    pos = 0
    while True:
        idx = buf.find(old_b, pos)
        if idx < 0:
            break
        buf[idx:idx + 8] = new_b
        count += 1
        pos = idx + 8
    return count


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Clone a native .material blob and patch selected texture hash references.'
    )
    parser.add_argument('template', type=Path, help='Source .material file to clone')
    parser.add_argument('output', type=Path, help='Patched output .material file')
    parser.add_argument(
        '--replace',
        nargs=2,
        action='append',
        metavar=('OLD', 'NEW'),
        default=[],
        help='Replace a texture reference. Each token can be a resource path or 0x-prefixed hash.',
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.replace:
        parser.error('at least one --replace OLD NEW mapping is required')

    data = bytearray(args.template.read_bytes())

    total_replacements = 0
    for old_token, new_token in args.replace:
        old_hash = parse_resource_token(old_token)
        new_hash = parse_resource_token(new_token)
        count = replace_all_u64(data, old_hash, new_hash)
        total_replacements += count
        print(
            f'{old_token} (0x{old_hash:016X}) -> {new_token} (0x{new_hash:016X}) : {count} occurrence(s)'
        )

    args.output.write_bytes(data)
    print(f'Wrote {args.output} ({len(data)} bytes, {total_replacements} replacements)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
