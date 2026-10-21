#!/usr/bin/env python3
"""
bundle_inspect.py - read a Gauntlet/Stingray bundle and say what is inside it.

*** THIS TOOL'S LAYOUT MODEL IS WRONG - DO NOT TRUST ITS VERDICT ***

It mirrors src/bundle_diagnostics.cpp, and both share three mistakes that make them
report malformed bundles as clean:

  - resource 0 does NOT have a 20-byte header without type/name.  EVERY payload,
    the first included, carries the same 36-byte header.
  - the TOC does NOT have (N+1) entries with a "sentinel".  It is exactly N x 16 bytes
    and the payloads begin immediately at 0x104 + N*16.
  - payloads are NOT padded to any boundary.  The engine advances to
    data_start + data_size, so a pad byte shifts every following header.

Consequence, measured: a bundle the engine could not read a single resource out of was
reported by this tool (and by the loader's diagnostics) as having "no structural
problems".  Its "PROBLEM:" lines fire on shipped, working bundles too, so neither the
absence nor the presence of a line here is evidence.

Use analyze_package_dependencies.py instead - it parses shipped bundles correctly:

    python3 analyze_package_dependencies.py <bundle> --sample-entries 2

and it must report the TOC offset as 0x104 with every resource's type and name decoded.
A fallback offset means the container is malformed.  See FINDINGS 9H.12 and the
"Mod bundles" section of SCRIPTS.md.

What follows is the model this tool actually implements, kept for the structural summary
(counts, type hashes, file sizes) which is still useful.

  packed file
      uint32 signature      0xF0000004 or 0xF0000005
      uint32 uncompressedSize
      uint32 padding
      then repeating: uint32 chunkSize, <chunk>  - each a RAW deflate stream
                      (occasionally zlib-wrapped: 2-byte header + 4-byte Adler)

  decompressed
      0x000  uint32 resourceCount  (N)
      0x004  256-byte preamble up to 0x104
      0x104  TOC: (N+1) x 16 bytes, each { uint64 typeHash, uint64 nameHash }

  payloads, in order:
      resource 0   20-byte header { u32 flags, u64 zeros, u32 dataSize, u32 streamSize }
      resource 1+  36-byte header { u64 type, u64 name, u32 flags, u64 zeros,
                                     u32 dataSize, u32 streamSize }
      each payload padded to a 4-byte boundary before the next header.

Resource 0 carries no type or name in its own header - it is the package, identified by
its TOC entry.  That asymmetry is easy to get wrong, and it is the first thing to check
when a bundle loads but its contents are never found.

Usage:
    bundle_inspect.py FILE [FILE ...]
    bundle_inspect.py --compare A B
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path
from typing import Dict

SIGNATURES = (0xF0000004, 0xF0000005)

# MurmurHash64A(name) for the names we can be sure of, checked against
# mod_bundle_builder.py's implementation.  Unknowns print as hex.
TYPE_NAMES: Dict[int, str] = {
    0xCD4238C6A0C69E32: 'texture',
    0xE0A48D0BE9A7453F: 'unit',
    0xEAC0B497876ADEDF: 'material',
    0xA14E8DFA2CD117E2: 'lua',
    0xAD9C6D9ED1E5E77A: 'package',
    0x18DEAD01056B72E9: 'bones',
    0x2A690FD348FE9AC5: 'level',
}


def type_name(h: int) -> str:
    return TYPE_NAMES.get(h, '0x%016X' % h)


def decompress(path: str):
    """(signature, uncompressed_size, blob), or raise with why not."""
    raw = Path(path).read_bytes()
    if len(raw) < 12:
        raise ValueError('too small to be a bundle')

    signature, uncomp, _padding = struct.unpack_from('<III', raw, 0)
    if signature not in SIGNATURES:
        raise ValueError('signature 0x%08X is not a bundle signature' % signature)

    out = bytearray()
    pos = 12
    while pos + 4 <= len(raw) and len(out) < uncomp:
        chunk_size, = struct.unpack_from('<I', raw, pos)
        pos += 4
        if pos + chunk_size > len(raw):
            raise ValueError('chunk at %d runs past the end of the file' % pos)
        chunk = raw[pos:pos + chunk_size]
        pos += chunk_size

        body = chunk
        if len(chunk) >= 2:
            cmf, flg = chunk[0], chunk[1]
            if (cmf & 0x0F) == 0x08 and ((cmf << 8) + flg) % 31 == 0:
                body = chunk[2:]
                if len(body) >= 4:
                    body = body[:-4]

        out += zlib.decompressobj(-15).decompress(body)

    # InflateRaw in bundle_diagnostics.cpp stops at the declared size; the last chunk
    # can decompress past it.  Without this cap a shipped bundle reports more bytes than
    # its header claims and the parse is abandoned - 195,624,960 vs 195,565,857 declared.
    if len(out) > uncomp:
        out = out[:uncomp]

    if len(out) != uncomp:
        raise ValueError('decompressed %d bytes, header says %d' % (len(out), uncomp))

    return signature, uncomp, bytes(out)


def parse(path: str) -> dict:
    signature, uncomp, blob = decompress(path)
    if len(blob) < 4:
        raise ValueError('decompressed data is too small')

    count, = struct.unpack_from('<I', blob, 0)
    info = dict(path=str(path), file_size=Path(path).stat().st_size,
                signature=signature, uncompressed=uncomp, count=count,
                toc=[], resources=[], problems=[])

    toc_offset = 0x104
    toc_size = (count + 1) * 16
    if toc_offset + toc_size > len(blob):
        info['problems'].append('TOC extends past the end of the data')
        return info

    for i in range(count + 1):
        th, nh = struct.unpack_from('<QQ', blob, toc_offset + i * 16)
        info['toc'].append((th, nh))

    offset = toc_offset + toc_size

    # resource 0: 20-byte header, its type/name come only from the TOC
    if count >= 1 and offset + 20 <= len(blob):
        flags, zeros, data_size, stream_size = struct.unpack_from('<IQII', blob, offset)
        th, nh = info['toc'][0]
        info['resources'].append(dict(index=0, type=th, name=nh, flags=flags,
                                      data_size=data_size, stream_size=stream_size,
                                      header=20))
        if zeros != 0:
            info['problems'].append('resource 0: expected 8 zero bytes, found %d' % zeros)
        offset += 20 + ((data_size + 1) // 2) * 2
    elif count >= 1:
        info['problems'].append('resource 0 header runs past the end of the data')

    for i in range(1, count):
        if offset + 36 > len(blob):
            info['problems'].append('resource %d header runs past the end of the data' % i)
            break
        th, nh, flags, zeros, data_size, stream_size = struct.unpack_from(
            '<QQIQII', blob, offset)
        info['resources'].append(dict(index=i, type=th, name=nh, flags=flags,
                                      data_size=data_size, stream_size=stream_size,
                                      header=36))
        toc_th, toc_nh = info['toc'][i]
        if (th, nh) != (toc_th, toc_nh):
            info['problems'].append(
                'resource %d: TOC says (0x%016X, 0x%016X) but the header says '
                '(0x%016X, 0x%016X)' % (i, toc_th, toc_nh, th, nh))
        if zeros != 0:
            info['problems'].append('resource %d: expected 8 zero bytes' % i)
        offset += 36 + ((data_size + 1) // 2) * 2

    info['consumed'] = offset
    if offset != len(blob):
        info['problems'].append(
            'payload walk ended at %d of %d bytes - the walk does not reach the end '
            'of the data' % (offset, len(blob)))

    return info


def show(info: dict) -> None:
    print('== %s' % info['path'])
    print('   file %s bytes  sig 0x%08X  uncompressed %s  resources %s'
          % (f"{info['file_size']:,}", info['signature'],
             f"{info['uncompressed']:,}", info['count']))
    for r in info['resources']:
        print('   [%2d] %-10s name 0x%016X  data %-9s stream %-6s flags %-3s hdr %d'
              % (r['index'], type_name(r['type']), r['name'],
                 f"{r['data_size']:,}", r['stream_size'], r['flags'], r['header']))
    if len(info['toc']) > info['count']:
        th, nh = info['toc'][info['count']]
        print('   TOC terminator: type 0x%016X name 0x%016X' % (th, nh))
    for p in info['problems']:
        print('   PROBLEM: %s' % p)
    if not info['problems']:
        print('   no structural problems')
    print()


def compare(a: dict, b: dict) -> None:
    print('== comparing')
    print('   A %s (%s resources)' % (a['path'], a['count']))
    print('   B %s (%s resources)' % (b['path'], b['count']))
    print()
    ra, rb = a['resources'], b['resources']
    print('   %-5s %-34s %-34s' % ('idx', 'A', 'B'))
    for i in range(max(len(ra), len(rb))):
        x = ra[i] if i < len(ra) else None
        y = rb[i] if i < len(rb) else None

        def fmt(r):
            if r is None:
                return '(none)'
            return '%-10s hdr=%-3d data=%s' % (type_name(r['type']), r['header'],
                                               f"{r['data_size']:,}")
        same = x and y and (x['header'], x['type']) == (y['header'], y['type'])
        print('   %-5d %-34s %-34s%s' % (i, fmt(x), fmt(y), '' if same else '  <-- differs'))
    print()
    for label, info in (('A', a), ('B', b)):
        print('   %s: consumed %s of %s bytes; problems: %s'
              % (label, info.get('consumed'), f"{info['uncompressed']:,}",
                 info['problems'] or 'none'))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*')
    ap.add_argument('--compare', nargs=2, metavar=('A', 'B'))
    args = ap.parse_args()

    if args.compare:
        compare(parse(args.compare[0]), parse(args.compare[1]))
        return 0

    if not args.files:
        ap.error('give one or more bundle files, or --compare A B')

    bad = 0
    for f in args.files:
        try:
            show(parse(f))
        except Exception as exc:                                # noqa: BLE001
            print('== %s\n   FAILED: %s\n' % (f, exc))
            bad += 1
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
