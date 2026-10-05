#!/usr/bin/env python3
"""
Canonical package analyzer for Gauntlet Bitsquid bundles.

Scans bundle files (or a contents directory), parses package resources, and
reports dependency-ref behavior in JSON.
"""

import argparse
import json
import re
import struct
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BUNDLE_SIG_OLD = 0xF0000004
BUNDLE_SIG_NEW = 0xF0000005
ZLIB_CHUNK = 0x10000
TYPE_PACKAGE = 0xAD9C6D9ED1E5E77A

TYPE_NAMES = {
    0xCD4238C6A0C69E32: "texture",
    0xEAC0B497876ADEDF: "material",
    0xA14E8DFA2CD117E2: "lua",
    0xE0A48D0BE9A7453F: "unit",
    0xAD9C6D9ED1E5E77A: "package",
    0x48FF313713A997A1: "mesh",
    0x18DEAD01056B72E9: "bones",
    0xCCE8D5B5F5AE333F: "shader",
    0x931E336D7646CC26: "animation",
    0x2A690FD348FE9AC5: "level",
    0x5F7203C8F280DAB8: "physics",
    0xA486D4045106165C: "state_machine",
    0x99736BE1FFF739A4: "timpani_bank",
    0x82645835E6B73232: "config",
    0x92D3EE038EEB610D: "flow",
    0x712D6E3DD1024C9C: "ugg",
    0x76015845A6003765: "xml",
    0x9EFE0A916AAE7880: "font",
    0xFE73C7DCFF8A7CA5: "shading_environment",
    0xB277B11FE4A61D37: "mouse_cursor",
    0x0D972BAB10B40FD3: "strings",
    0xA8193123526FAD64: "particles",
}

HEX_BUNDLE_RE = re.compile(r"^[0-9a-f]{16}$")
DEFAULT_CONTENTS = Path("~/.local/share/Steam/steamapps/common/Gauntlet/contents").expanduser()
DEFAULT_HASH_DB = Path(__file__).with_name("hash_database.json")


@dataclass
class BundleResource:
    type_hash: int
    name_hash: int
    flags: int
    stream_size: int
    main_size: int
    unknown: int
    data: bytes


def format_u64(value: int) -> str:
    return f"0x{value:016X}"


def format_u32(value: int) -> str:
    return f"0x{value:08X}"


def type_name(type_hash: int) -> str:
    return TYPE_NAMES.get(type_hash, format_u64(type_hash))


def decompress_bundle(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) < 12:
        raise ValueError("bundle too small")

    sig, _, _ = struct.unpack_from("<III", raw, 0)
    if sig not in (BUNDLE_SIG_OLD, BUNDLE_SIG_NEW):
        raise ValueError(f"invalid signature 0x{sig:08X}")

    offset = 12
    out = bytearray()
    while offset + 4 <= len(raw):
        chunk_size = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        if chunk_size == 0:
            break
        if chunk_size == ZLIB_CHUNK:
            continue
        if offset + chunk_size > len(raw):
            raise ValueError(f"truncated chunk at 0x{offset:X}")

        chunk = raw[offset:offset + chunk_size]
        offset += chunk_size
        out.extend(zlib.decompress(chunk))

    return bytes(out)


def try_parse_bundle_resources(
    data: bytes, resource_count: int, entry_table_offset: int
) -> Tuple[List[BundleResource], bool]:
    entry_table_size = resource_count * 16
    data_offset = entry_table_offset + entry_table_size
    if data_offset > len(data):
        return [], True

    resources: List[BundleResource] = []
    offset = data_offset
    for _ in range(resource_count):
        if offset + 36 > len(data):
            return resources, True

        type_hash, name_hash, flags = struct.unpack_from("<QQI", data, offset)
        stream_size = struct.unpack_from("<Q", data, offset + 20)[0]
        main_size, unknown = struct.unpack_from("<II", data, offset + 28)
        data_start = offset + 36
        data_end = data_start + main_size
        if data_end > len(data):
            return resources, True

        resources.append(
            BundleResource(
                type_hash=type_hash,
                name_hash=name_hash,
                flags=flags,
                stream_size=stream_size,
                main_size=main_size,
                unknown=unknown,
                data=data[data_start:data_end],
            )
        )
        offset = data_end

    return resources, False


def parse_bundle(data: bytes) -> Tuple[int, int, List[BundleResource], bool]:
    if len(data) < 4:
        raise ValueError("unpacked bundle too small")

    resource_count = struct.unpack_from("<I", data, 0)[0]
    if resource_count <= 0:
        raise ValueError("invalid resource count")

    candidates: List[int] = []
    candidates.append(0x104)
    dynamic_offset = 4 + resource_count * 8
    if dynamic_offset != 0x104:
        candidates.append(dynamic_offset)

    best_candidate: Optional[Tuple[int, List[BundleResource], bool]] = None
    for entry_table_offset in candidates:
        resources, truncated = try_parse_bundle_resources(data, resource_count, entry_table_offset)
        if not resources:
            continue
        score = (0 if truncated else 1, len(resources))
        if best_candidate is None or score > (0 if best_candidate[2] else 1, len(best_candidate[1])):
            best_candidate = (entry_table_offset, resources, truncated)

    if best_candidate is not None:
        return resource_count, best_candidate[0], best_candidate[1], best_candidate[2]

    raise ValueError("failed to parse bundle with known entry table offsets")


def parse_package_entries(pkg_data: bytes) -> Tuple[List[Dict], int, str]:
    if len(pkg_data) < 4:
        return [], 0, "too_small"

    entry_count = struct.unpack_from("<I", pkg_data, 0)[0]
    offset = 4
    entries: List[Dict] = []
    for idx in range(entry_count):
        if offset + 20 > len(pkg_data):
            return entries, offset, f"truncated_entry_{idx}"

        e_type, e_name, dep_count = struct.unpack_from("<QQI", pkg_data, offset)
        offset += 20
        dep_bytes = dep_count * 4
        if offset + dep_bytes > len(pkg_data):
            return entries, offset, f"truncated_deps_{idx}"

        deps = [struct.unpack_from("<I", pkg_data, offset + d * 4)[0] for d in range(dep_count)]
        offset += dep_bytes
        entries.append(
            {
                "type_hash": e_type,
                "type_name": type_name(e_type),
                "name_hash": e_name,
                "name_hash_high32": (e_name >> 32) & 0xFFFFFFFF,
                "name_hash_low32": e_name & 0xFFFFFFFF,
                "dependency_count": dep_count,
                "dependencies": deps,
            }
        )

    return entries, offset, "ok"


def load_hash_db_high32(hash_db_path: Path) -> Dict[int, List[str]]:
    if not hash_db_path.exists():
        return {}

    out: Dict[int, List[str]] = defaultdict(list)
    suffix = hash_db_path.suffix.lower()

    if suffix == ".json":
        raw = json.loads(hash_db_path.read_text(encoding="utf-8"))
        for key, name in raw.items():
            if not isinstance(key, str) or len(key) != 16:
                continue
            try:
                value = int(key, 16)
            except ValueError:
                continue
            hi = (value >> 32) & 0xFFFFFFFF
            if len(out[hi]) < 5:
                out[hi].append(name)
        return out

    hash_line = re.compile(r"^\s*([0-9a-fA-F]{16})\s+(.+?)\s*$")
    for line in hash_db_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = hash_line.match(line)
        if not m:
            continue
        value = int(m.group(1), 16)
        hi = (value >> 32) & 0xFFFFFFFF
        if len(out[hi]) < 5:
            out[hi].append(m.group(2))
    return out


def analyze_package_resource(
    package_name_hash: int,
    pkg_data: bytes,
    sample_entries: int,
    hash_high32_to_names: Dict[int, List[str]],
) -> Tuple[Dict, Counter, Counter]:
    entries, consumed, parse_status = parse_package_entries(pkg_data)
    tail = pkg_data[consumed:]

    entry_high32_index: Dict[int, List[int]] = defaultdict(list)
    entry_low32_index: Dict[int, List[int]] = defaultdict(list)
    for idx, entry in enumerate(entries):
        entry_high32_index[entry["name_hash_high32"]].append(idx)
        entry_low32_index[entry["name_hash_low32"]].append(idx)

    dep_count_distribution: Counter = Counter()
    dep_values: Counter = Counter()
    unresolved_dep_values: Counter = Counter()
    dep_by_type: Dict[str, Counter] = defaultdict(Counter)
    counters = Counter()

    sample: List[Dict] = []
    for idx, entry in enumerate(entries):
        dep_count_distribution[entry["dependency_count"]] += 1
        dep_by_type[entry["type_name"]][entry["dependency_count"]] += 1

        if idx < sample_entries:
            sample_dep = []
        for dep in entry["dependencies"]:
            dep_values[dep] += 1
            counters["dependency_refs_total"] += 1
            is_entry_high32 = dep in entry_high32_index
            is_entry_low32 = dep in entry_low32_index
            is_self_high32 = dep == entry["name_hash_high32"]
            is_self_low32 = dep == entry["name_hash_low32"]

            if is_entry_high32:
                counters["dep_refs_entry_high32"] += 1
            if is_entry_low32:
                counters["dep_refs_entry_low32"] += 1
            if is_self_high32:
                counters["dep_refs_self_high32"] += 1
            if is_self_low32:
                counters["dep_refs_self_low32"] += 1

            if not is_entry_high32 and not is_entry_low32:
                counters["dep_refs_unresolved"] += 1
                unresolved_dep_values[dep] += 1

            if dep in hash_high32_to_names:
                counters["dep_refs_hash_db_high32_match"] += 1

            if idx < sample_entries:
                sample_dep.append(
                    {
                        "dep": format_u32(dep),
                        "matches_entry_high32": is_entry_high32,
                        "matches_entry_low32": is_entry_low32,
                        "matches_self_high32": is_self_high32,
                        "matches_self_low32": is_self_low32,
                        "hash_db_names": hash_high32_to_names.get(dep, []),
                    }
                )

        if idx < sample_entries:
            sample.append(
                {
                    "index": idx,
                    "type": entry["type_name"],
                    "type_hash": format_u64(entry["type_hash"]),
                    "name_hash": format_u64(entry["name_hash"]),
                    "name_hash_high32": format_u32(entry["name_hash_high32"]),
                    "dependency_count": entry["dependency_count"],
                    "dependencies": sample_dep,
                }
            )

    trailer_summary = {
        "tail_size": len(tail),
        "tail_hex": tail[:16].hex(),
        "single_trailer_byte": format_u32(tail[0]) if len(tail) == 1 else None,
    }

    summary = {
        "package_name_hash": format_u64(package_name_hash),
        "package_size": len(pkg_data),
        "parse_status": parse_status,
        "entry_count_header": struct.unpack_from("<I", pkg_data, 0)[0] if len(pkg_data) >= 4 else 0,
        "entry_count_parsed": len(entries),
        "parsed_bytes": consumed,
        "trailer": trailer_summary,
        "dependency_count_distribution": {str(k): v for k, v in sorted(dep_count_distribution.items())},
        "dependency_count_distribution_by_type": {
            t: {str(k): v for k, v in sorted(c.items())}
            for t, c in sorted(dep_by_type.items())
        },
        "counters": dict(counters),
        "top_dependency_values": [{"dep": format_u32(k), "count": v} for k, v in dep_values.most_common(12)],
        "top_unresolved_dependency_values": [
            {
                "dep": format_u32(k),
                "count": v,
                "hash_db_name_candidates": hash_high32_to_names.get(k, []),
            }
            for k, v in unresolved_dep_values.most_common(12)
        ],
        "sample_entries": sample,
    }
    return summary, dep_values, unresolved_dep_values


def iter_bundle_files(paths: List[Path], recursive: bool) -> List[Path]:
    files: List[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
            continue
        if not path.is_dir():
            continue

        iterator = path.rglob("*") if recursive else path.glob("*")
        for candidate in iterator:
            if not candidate.is_file():
                continue
            name = candidate.name.lower()
            if HEX_BUNDLE_RE.match(name):
                files.append(candidate)

    return sorted(set(files))


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Bitsquid package resources in Gauntlet bundles.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=f"Bundle files or directories. Default: {DEFAULT_CONTENTS}",
    )
    parser.add_argument("--recursive", action="store_true", help="Recursively scan directories.")
    parser.add_argument("--limit", type=int, default=0, help="Max number of bundle files to scan.")
    parser.add_argument("--sample-entries", type=int, default=4, help="Sample package entries per package summary.")
    parser.add_argument("--json-out", type=Path, help="Write full report JSON to this file.")
    parser.add_argument("--hash-db", type=Path, default=DEFAULT_HASH_DB, help="Hash DB for high32 hinting.")
    args = parser.parse_args()

    scan_paths = args.paths if args.paths else [DEFAULT_CONTENTS]
    bundle_files = iter_bundle_files(scan_paths, recursive=args.recursive)
    if args.limit > 0:
        bundle_files = bundle_files[: args.limit]

    hash_high32_to_names = load_hash_db_high32(args.hash_db)

    report = {
        "scan_paths": [str(p) for p in scan_paths],
        "bundle_file_count": len(bundle_files),
        "bundle_files": [str(p) for p in bundle_files],
        "global": {
            "bundles_parsed": 0,
            "bundles_failed": 0,
            "bundles_with_package_resource": 0,
            "package_resources": 0,
            "package_entries_total": 0,
            "dependency_refs_total": 0,
            "dep_refs_entry_high32": 0,
            "dep_refs_entry_low32": 0,
            "dep_refs_self_high32": 0,
            "dep_refs_self_low32": 0,
            "dep_refs_unresolved": 0,
            "dep_refs_hash_db_high32_match": 0,
            "package_parse_status_counts": {},
            "package_trailer_byte_counts": {},
            "dependency_count_distribution": {},
            "top_dependency_values": [],
            "top_unresolved_dependency_values": [],
        },
        "bundle_errors": [],
        "bundles": [],
    }

    global_dep_counts = Counter()
    global_unresolved_dep_counts = Counter()
    global_dep_count_dist = Counter()
    package_parse_status = Counter()
    package_trailers = Counter()

    for bundle_path in bundle_files:
        try:
            unpacked = decompress_bundle(bundle_path)
            resource_count, entry_table_offset, resources, truncated = parse_bundle(unpacked)
        except Exception as exc:  # explicit parse failure reporting
            report["global"]["bundles_failed"] += 1
            report["bundle_errors"].append({"bundle": str(bundle_path), "error": str(exc)})
            continue

        report["global"]["bundles_parsed"] += 1
        bundle_summary = {
            "bundle": str(bundle_path),
            "resource_count_header": resource_count,
            "resource_count_parsed": len(resources),
            "resource_parse_truncated": truncated,
            "entry_table_offset": f"0x{entry_table_offset:X}",
            "package_resources": [],
        }

        package_resources = [r for r in resources if r.type_hash == TYPE_PACKAGE]
        if package_resources:
            report["global"]["bundles_with_package_resource"] += 1

        for pkg_res in package_resources:
            pkg_summary, dep_values, unresolved_dep_values = analyze_package_resource(
                package_name_hash=pkg_res.name_hash,
                pkg_data=pkg_res.data,
                sample_entries=max(0, args.sample_entries),
                hash_high32_to_names=hash_high32_to_names,
            )
            bundle_summary["package_resources"].append(pkg_summary)

            report["global"]["package_resources"] += 1
            report["global"]["package_entries_total"] += pkg_summary["entry_count_parsed"]

            counters = pkg_summary["counters"]
            report["global"]["dependency_refs_total"] += counters.get("dependency_refs_total", 0)
            report["global"]["dep_refs_entry_high32"] += counters.get("dep_refs_entry_high32", 0)
            report["global"]["dep_refs_entry_low32"] += counters.get("dep_refs_entry_low32", 0)
            report["global"]["dep_refs_self_high32"] += counters.get("dep_refs_self_high32", 0)
            report["global"]["dep_refs_self_low32"] += counters.get("dep_refs_self_low32", 0)
            report["global"]["dep_refs_unresolved"] += counters.get("dep_refs_unresolved", 0)
            report["global"]["dep_refs_hash_db_high32_match"] += counters.get("dep_refs_hash_db_high32_match", 0)

            for dep_count, count in pkg_summary["dependency_count_distribution"].items():
                global_dep_count_dist[int(dep_count)] += count

            global_dep_counts.update(dep_values)
            global_unresolved_dep_counts.update(unresolved_dep_values)

            package_parse_status[pkg_summary["parse_status"]] += 1
            trailer_byte = pkg_summary["trailer"]["single_trailer_byte"]
            if trailer_byte is None:
                package_trailers["none_or_multi_byte_tail"] += 1
            else:
                package_trailers[trailer_byte] += 1

        if bundle_summary["package_resources"]:
            report["bundles"].append(bundle_summary)

    report["global"]["package_parse_status_counts"] = dict(package_parse_status)
    report["global"]["package_trailer_byte_counts"] = dict(package_trailers)
    report["global"]["dependency_count_distribution"] = {
        str(k): v for k, v in sorted(global_dep_count_dist.items())
    }
    report["global"]["top_dependency_values"] = [
        {"dep": format_u32(dep), "count": count} for dep, count in global_dep_counts.most_common(20)
    ]
    report["global"]["top_unresolved_dependency_values"] = [
        {"dep": format_u32(dep), "count": count, "hash_db_name_candidates": hash_high32_to_names.get(dep, [])}
        for dep, count in global_unresolved_dep_counts.most_common(20)
    ]

    output = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.write_text(output + "\n", encoding="utf-8")

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
