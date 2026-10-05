#!/usr/bin/env python3
"""Inspect Gauntlet/Bitsquid material binaries and flag suspicious layouts.

This tool is intentionally heuristic: it decodes the stable header/slot region and
then reports tail fingerprints seen in native files.
"""

from __future__ import annotations

import argparse
import struct
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Tuple


def parse_slots(data: bytes, section_count: int) -> List[Tuple[int, int, int]]:
    slots: List[Tuple[int, int, int]] = []
    off = 24
    for _ in range(section_count):
        if off + 16 > len(data):
            break
        slot_idx = struct.unpack_from("<I", data, off)[0]
        thin = struct.unpack_from("<I", data, off + 4)[0]
        tex = struct.unpack_from("<Q", data, off + 8)[0]
        slots.append((slot_idx, thin, tex))
        off += 16
    return slots


def classify_material(data: bytes) -> List[str]:
    notes: List[str] = []
    if len(data) < 24:
        return ["too_small"]

    version, section_count = struct.unpack_from("<II", data, 0)
    if version != 0x0A:
        notes.append("nonstandard_version")

    expected_slots_end = 24 + (16 * section_count)
    if expected_slots_end > len(data):
        notes.append("truncated_slot_table")
        return notes

    tail = data[expected_slots_end:]
    if len(tail) == 12 and tail == b"\x00" * 12:
        notes.append("minimal_layout_compatible")
    elif len(tail) == 0:
        notes.append("no_tail")
    else:
        notes.append(f"extended_tail_{len(tail)}")

    # A known crash-prone hybrid seen in experiments: 56-byte blob with marker
    # bytes that indicate an extended block, but without enough payload.
    if len(data) == 56 and data[40:44] == b"\x01\x00\x00\x00" and data[44:48] == b"\xDE\x0A\xF8\x46":
        notes.append("suspect_truncated_extended_block")

    return notes


def inspect_file(path: Path) -> None:
    data = path.read_bytes()
    print(f"\\n== {path} ==")
    print(f"size={len(data)}")

    if len(data) < 24:
        print("  too small for header")
        return

    version, section_count = struct.unpack_from("<II", data, 0)
    shader = struct.unpack_from("<Q", data, 8)[0]
    pad = struct.unpack_from("<Q", data, 16)[0]

    print(f"  version=0x{version:08X} ({version})")
    print(f"  section_count={section_count}")
    print(f"  shader=0x{shader:016X}")
    print(f"  pad16=0x{pad:016X}")

    slots = parse_slots(data, section_count)
    for i, (slot_idx, thin, tex) in enumerate(slots):
        print(f"  slot[{i}] idx={slot_idx} thin=0x{thin:08X} tex=0x{tex:016X}")

    for note in classify_material(data):
        print(f"  note={note}")


def inspect_corpus(paths: Iterable[Path]) -> None:
    size_counter: Counter[int] = Counter()
    issue_counter: Counter[str] = Counter()

    for path in paths:
        data = path.read_bytes()
        size_counter[len(data)] += 1
        for issue in classify_material(data):
            issue_counter[issue] += 1

    print("\\n== corpus summary ==")
    print(f"files={sum(size_counter.values())}")
    print("sizes_smallest=")
    for size, count in sorted(size_counter.items())[:20]:
        print(f"  {size}: {count}")
    print("issues=")
    for issue, count in issue_counter.most_common(20):
        print(f"  {issue}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Gauntlet material binary layouts")
    parser.add_argument("paths", nargs="+", help="Material files or directories")
    parser.add_argument("--corpus", action="store_true", help="Treat directory inputs as corpora and print summary")
    args = parser.parse_args()

    file_paths: List[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            file_paths.extend(sorted(p.glob("*.material")))
        elif p.is_file():
            file_paths.append(p)

    if args.corpus:
        inspect_corpus(file_paths)
    else:
        for p in file_paths:
            inspect_file(p)


if __name__ == "__main__":
    main()
