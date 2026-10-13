#!/usr/bin/env python3
import struct
import sys
from pathlib import Path


def read_u32(data, off):
    return struct.unpack_from('<I', data, off)[0]

def read_u64(data, off):
    return struct.unpack_from('<Q', data, off)[0]

def read_f32(data, off):
    return struct.unpack_from('<f', data, off)[0]


def parse_unit(path):
    data = Path(path).read_bytes()
    off = 0
    sig = read_u32(data, off); off += 4
    mesh_count = read_u32(data, off); off += 4
    meshes = []
    for mesh_index in range(mesh_count):
        mesh = {"mesh_index": mesh_index, "start": off}
        vbuf_size = read_u32(data, off); off += 4
        mesh["vbuf_size"] = vbuf_size
        mesh["vbuf_start"] = off
        off += vbuf_size
        mesh["padding_qword"] = read_u64(data, off); off += 8
        mesh["vertex_count"] = read_u32(data, off); off += 4
        mesh["vertex_stride"] = read_u32(data, off); off += 4
        elem_count = read_u32(data, off); off += 4
        mesh["element_count"] = elem_count
        elems = []
        for _ in range(elem_count):
            elem_type = read_u32(data, off); off += 4
            elem_size = read_u32(data, off); off += 4
            elem_layer = read_u32(data, off); off += 4
            elem_format = read_u32(data, off); off += 4
            end_marker = data[off]; off += 1
            elems.append((elem_type, elem_size, elem_layer, elem_format, end_marker))
        mesh["elements"] = elems
        mesh["post_elem_pad_offset"] = off
        mesh["post_elem_pad"] = data[off:off+12]
        off += 12
        mesh["index_meta_offset"] = off
        total_index_count = read_u32(data, off); off += 4
        index_buffer_size = read_u32(data, off); off += 4
        mesh["total_index_count"] = total_index_count
        mesh["index_buffer_size"] = index_buffer_size
        mesh["index_buffer_start"] = off
        off += index_buffer_size
        mesh["shape_offset"] = off
        shape_count = read_u32(data, off); off += 4
        mesh["shape_count"] = shape_count
        shapes = []
        for _ in range(shape_count):
            mat_idx = read_u32(data, off); off += 4
            idx_off = read_u32(data, off); off += 4
            idx_cnt = read_u32(data, off); off += 4
            shape_idx = read_u32(data, off); off += 4
            shapes.append((mat_idx, idx_off, idx_cnt, shape_idx))
        mesh["shapes"] = shapes
        mesh["bbox_offset"] = off
        mesh["bbox"] = tuple(read_f32(data, off + i * 4) for i in range(7))
        off += 28
        mesh["material_offset"] = off
        material_count = read_u32(data, off); off += 4
        mesh["material_count"] = material_count
        mats = []
        for _ in range(material_count):
            strlen = read_u32(data, off); off += 4
            raw = data[off:off+strlen]
            off += strlen
            mats.append(raw)
        mesh["materials"] = mats
        mesh["end"] = off
        meshes.append(mesh)
    return {"path": str(path), "size": len(data), "sig": sig, "mesh_count": mesh_count, "meshes": meshes, "final_offset": off, "trailing": data[off:]}


def dump(info):
    print(f"FILE {info['path']}")
    print(f"size={info['size']} sig=0x{info['sig']:08X} mesh_count={info['mesh_count']} final_offset=0x{info['final_offset']:X} trailing={len(info['trailing'])}")
    for mesh in info['meshes']:
        print(f"MESH {mesh['mesh_index']} start=0x{mesh['start']:X} end=0x{mesh['end']:X}")
        print(f"  vbuf_size={mesh['vbuf_size']} vertex_count={mesh['vertex_count']} stride={mesh['vertex_stride']} elem_count={mesh['element_count']}")
        print(f"  post_elem_pad={mesh['post_elem_pad'].hex()}")
        print(f"  indices={mesh['total_index_count']} index_buffer_size={mesh['index_buffer_size']} shape_count={mesh['shape_count']} material_count={mesh['material_count']}")
        print(f"  bbox={mesh['bbox']}")
        print(f"  elements={mesh['elements']}")
        print(f"  shapes={mesh['shapes']}")
        mat_list = [m.decode('utf-8', errors='replace') for m in mesh['materials']]
        print(f"  materials={mat_list}")
    if info['trailing']:
        print(f"TRAILING_HEX={info['trailing'][:64].hex()}")


if __name__ == '__main__':
    for arg in sys.argv[1:]:
        dump(parse_unit(arg))
