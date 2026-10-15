"""
Gauntlet Unit to OBJ/glTF Converter v2
Converts .unit files from Gauntlet bundles to OBJ format.

Based on analysis of Bitsquid/Stingray engine unit format,
informed by the Helldivers 2 Extractor codebase (FileDiver).

=== STINGRAY .UNIT FILE STRUCTURE ===

A .unit file in older Stingray engines (like Gauntlet uses) contains:

1. HEADER (8 bytes)
   - uint32: Signature/version (may vary)
   - uint32: Mesh count

2. PER-MESH DATA (repeated for each mesh):
   
   a) VERTEX BUFFER
      - uint32: vertex_buffer_size (total bytes of raw vertex data)
      - bytes[vertex_buffer_size]: interleaved vertex data
   
   b) PADDING
      - 8 bytes of zeros/padding
   
   c) MESH METADATA
      - uint32: vertex_count
      - uint32: vertex_stride (bytes per vertex)
      - uint32: element_count (number of vertex attributes)
   
   d) ELEMENT DESCRIPTORS (per attribute)
      - uint32: element_type (0=position, 1=normal, 2=tangent, 3=binormal, 4=UV, etc.)
      - uint32: element_size (component count minus 1, or format indicator)
      - uint32: unknown0 (layer index or stream index)
      - uint32: unknown1 (offset or format details)
      - uint8: end_marker
   
   e) PADDING: 12 bytes
   
   f) INDEX BUFFER INFO
      - uint32: total_index_count
      - uint32: index_buffer_size
      - bytes[index_buffer_size]: index data (typically uint16)
   
   g) SHAPES/SUBMESHES
      - uint32: shape_count
      - For each shape (16 bytes):
        - uint32: material_index
        - uint32: index_offset (TRIANGLE offset - multiplied by 3 on parse)
        - uint32: index_count (TRIANGLE count - multiplied by 3 on parse)
        - uint32: shape_index
   
   h) BOUNDING BOX (28 bytes = 7 floats)
      - float[3]: min bounds (or center)
      - float[3]: max bounds (or extent)
      - float: radius or padding
   
   i) MATERIALS
      - uint32: material_count
      - For each material:
        - uint32: string_length
        - char[string_length]: material name

=== VERTEX FORMAT TYPES ===

Gauntlet (older Stingray) typically uses:
- Position: float32[3] = 12 bytes
- Normal: float32[3] = 12 bytes
- Tangent: float32[3] = 12 bytes
- Binormal: float32[3] = 12 bytes
- UV: float32[2] = 8 bytes
- Color: float32[4] = 16 bytes

Newer Stingray (Helldivers 2) also supports:
- Packed normals: R10G10B10A2 = 4 bytes (octahedral encoding)
- Half-floats: float16 for UVs and some attributes
- Packed bone weights: R10G10B10A2 = 4 bytes

=== KEY DIFFERENCES FROM HELLDIVERS 2 ===

1. Gauntlet embeds mesh data inline; HD2 often uses separate geometry_group files
2. Gauntlet uses simpler vertex formats (float32 instead of packed/half-float)
3. Gauntlet doesn't seem to use the split Main/GPU data streams
4. Element descriptor format differs slightly
"""

import struct
import os
import sys
import math
import argparse
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, BinaryIO, Dict, Any
from enum import IntEnum


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class ElementType(IntEnum):
    """Vertex element types in Stingray engine."""
    POSITION = 0
    NORMAL = 1
    TANGENT = 2
    BINORMAL = 3
    UV_COORDS = 4
    COLOR = 5
    BONE_INDICES = 6
    BONE_WEIGHTS = 7


class ElementFormat(IntEnum):
    """Vertex element data formats (newer Stingray)."""
    F32 = 0           # 1x float32 = 4 bytes
    VEC2F = 1         # 2x float32 = 8 bytes
    VEC3F = 2         # 3x float32 = 12 bytes
    VEC4F = 3         # 4x float32 = 16 bytes
    S32 = 4           # 1x int32 = 4 bytes
    U32 = 17          # 1x uint32 = 4 bytes
    VEC4U32 = 20      # 4x uint32 = 16 bytes
    VEC4S8 = 24       # 4x int8 = 4 bytes (bone indices)
    R10G10B10A2_TYPELESS = 25  # Packed bone weights
    R10G10B10A2_UNORM = 26     # Packed normal/tangent (octahedral)
    F16 = 28          # 1x float16 = 2 bytes
    VEC2F16 = 29      # 2x float16 = 4 bytes
    VEC3F16 = 30      # 3x float16 = 6 bytes
    VEC4F16 = 31      # 4x float16 = 8 bytes


# Format sizes in bytes
FORMAT_SIZES = {
    ElementFormat.F32: 4,
    ElementFormat.VEC2F: 8,
    ElementFormat.VEC3F: 12,
    ElementFormat.VEC4F: 16,
    ElementFormat.S32: 4,
    ElementFormat.U32: 4,
    ElementFormat.VEC4U32: 16,
    ElementFormat.VEC4S8: 4,
    ElementFormat.R10G10B10A2_TYPELESS: 4,
    ElementFormat.R10G10B10A2_UNORM: 4,
    ElementFormat.F16: 2,
    ElementFormat.VEC2F16: 4,
    ElementFormat.VEC3F16: 6,
    ElementFormat.VEC4F16: 8,
}


@dataclass
class Vector3:
    """3D vector."""
    x: float
    y: float
    z: float
    
    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z
    
    def normalized(self) -> 'Vector3':
        length = math.sqrt(self.x**2 + self.y**2 + self.z**2)
        if length > 0:
            return Vector3(self.x/length, self.y/length, self.z/length)
        return Vector3(0, 1, 0)


@dataclass
class Vector2:
    """2D vector for UVs."""
    u: float
    v: float
    
    def __iter__(self):
        yield self.u
        yield self.v


@dataclass
class ElementDescriptor:
    """Describes a vertex attribute in the buffer."""
    type: int           # ElementType enum value
    size: int           # Component count or format indicator
    layer: int          # UV layer index or bone influence layer
    offset: int         # Byte offset within vertex (computed)
    format: int         # Data format (for newer Stingray)
    
    @property
    def byte_size(self) -> int:
        """Estimate byte size based on element type and size field."""
        # For Gauntlet (older Stingray), size seems to be component_count - 1
        # Position/Normal/Tangent/Binormal = 3 floats = 12 bytes
        # UV = 2 floats = 8 bytes
        # Color = 4 floats = 16 bytes
        
        type_sizes = {
            ElementType.POSITION: 12,
            ElementType.NORMAL: 12,
            ElementType.TANGENT: 12,
            ElementType.BINORMAL: 12,
            ElementType.UV_COORDS: 8,
            ElementType.COLOR: 16,
        }
        
        if self.type in type_sizes:
            return type_sizes[self.type]
        
        # For bone indices/weights, size field indicates format
        return (self.size + 1) * 4


@dataclass
class Vertex:
    """Complete vertex data."""
    position: Vector3
    normal: Optional[Vector3] = None
    tangent: Optional[Vector3] = None
    binormal: Optional[Vector3] = None
    uv: Optional[Vector2] = None
    uv2: Optional[Vector2] = None
    color: Optional[Tuple[float, float, float, float]] = None
    bone_indices: Optional[Tuple[int, int, int, int]] = None
    bone_weights: Optional[Tuple[float, float, float, float]] = None


@dataclass
class Shape:
    """Submesh/shape definition."""
    material_index: int
    index_offset: int
    index_count: int
    shape_index: int
    
    def __repr__(self):
        return f"Shape(mat={self.material_index}, offset={self.index_offset}, count={self.index_count})"


@dataclass
class BoundingBox:
    """Axis-aligned bounding box."""
    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    max_z: float = 0.0
    extra: float = 0.0  # Radius or padding


@dataclass 
class Mesh:
    """Complete mesh data."""
    vertices: List[Vertex] = field(default_factory=list)
    indices: List[int] = field(default_factory=list)
    shapes: List[Shape] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    elements: List[ElementDescriptor] = field(default_factory=list)
    stride: int = 0
    bounding_box: Optional[BoundingBox] = None
    
    # Debug info
    raw_vertex_buffer: bytes = field(default=b'', repr=False)
    raw_index_buffer: bytes = field(default=b'', repr=False)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def float16_to_float32(bits: int) -> float:
    """Convert a 16-bit float to 32-bit float."""
    sign = (bits >> 15) & 0x1
    exponent = (bits >> 10) & 0x1f
    mantissa = bits & 0x3ff
    
    if exponent == 0:
        if mantissa == 0:
            return -0.0 if sign else 0.0
        # Denormalized number
        exponent = 1
        while not (mantissa & 0x400):
            mantissa <<= 1
            exponent -= 1
        mantissa &= 0x3ff
        exponent = exponent - 15 + 127
    elif exponent == 31:
        if mantissa == 0:
            return float('-inf') if sign else float('inf')
        return float('nan')
    else:
        exponent = exponent - 15 + 127
    
    f32_bits = (sign << 31) | (exponent << 23) | (mantissa << 13)
    return struct.unpack('<f', struct.pack('<I', f32_bits))[0]


def decode_octahedral_normal(x: float, y: float) -> Vector3:
    """Decode octahedral-encoded normal. Input in range [-1, +1]."""
    z = 1.0 - abs(x) - abs(y)
    if z < 0:
        old_x, old_y = x, y
        x = (1.0 - abs(old_y)) * (1.0 if old_x >= 0 else -1.0)
        y = (1.0 - abs(old_x)) * (1.0 if old_y >= 0 else -1.0)
    
    # Normalize
    length = math.sqrt(x*x + y*y + z*z)
    if length > 0:
        return Vector3(x/length, y/length, z/length)
    return Vector3(0, 1, 0)


def decode_packed_normal(packed: int) -> Tuple[Vector3, Vector3, Vector3]:
    """
    Decode packed normal/tangent from R10G10B10A2 format.
    Uses octahedral encoding with diamond tangent encoding.
    
    Returns: (normal, tangent, bitangent)
    """
    r10 = packed & 0x3ff
    g10 = (packed >> 10) & 0x3ff
    b10 = (packed >> 20) & 0x3ff
    a2 = (packed >> 30) & 0x3
    
    # Decode normal using octahedral encoding
    nx = r10 * (2.0 / 1023.0) - 1.0
    ny = g10 * (2.0 / 1023.0) - 1.0
    normal = decode_octahedral_normal(nx, ny)
    
    # Decode tangent rotation using diamond encoding
    rot = b10 / 1023.0
    
    if rot < 0.5:
        cos_r = 4 * rot - 1
        neg_sin_r = abs(cos_r) - 1
    else:
        cos_r = 3 - 4 * rot
        neg_sin_r = 1 - abs(cos_r)
    
    # Normalize
    length = math.sqrt(cos_r * cos_r + neg_sin_r * neg_sin_r)
    if length > 0:
        cos_r /= length
        neg_sin_r /= length
    
    # Choose tangent base vector orthogonal to normal
    if abs(normal.z) < abs(normal.y):
        tb_length = math.sqrt(normal.y**2 + normal.x**2)
        if tb_length > 0:
            tangent_base = Vector3(normal.y/tb_length, -normal.x/tb_length, 0.0)
        else:
            tangent_base = Vector3(1.0, 0.0, 0.0)
    else:
        tb_length = math.sqrt(normal.z**2 + normal.x**2)
        if tb_length > 0:
            tangent_base = Vector3(normal.z/tb_length, 0.0, -normal.x/tb_length)
        else:
            tangent_base = Vector3(1.0, 0.0, 0.0)
    
    # Cross product: tangent_base x normal
    cross = Vector3(
        tangent_base.y * normal.z - tangent_base.z * normal.y,
        tangent_base.z * normal.x - tangent_base.x * normal.z,
        tangent_base.x * normal.y - tangent_base.y * normal.x
    )
    
    # Rotate tangent_base around normal
    tangent = Vector3(
        tangent_base.x * cos_r + cross.x * neg_sin_r,
        tangent_base.y * cos_r + cross.y * neg_sin_r,
        tangent_base.z * cos_r + cross.z * neg_sin_r
    )
    
    # Bitangent = normal x tangent
    bitangent = Vector3(
        normal.y * tangent.z - normal.z * tangent.y,
        normal.z * tangent.x - normal.x * tangent.z,
        normal.x * tangent.y - normal.y * tangent.x
    )
    
    # Flip bitangent if a2 == 3
    if a2 == 3:
        bitangent = Vector3(-bitangent.x, -bitangent.y, -bitangent.z)
    
    return normal, tangent, bitangent


def decode_packed_bone_weights(packed: int) -> Tuple[float, float, float, float]:
    """Decode bone weights from R10G10B10A2_TYPELESS format."""
    w0 = (packed & 0x3ff) / 1023.0
    w1 = ((packed >> 10) & 0x3ff) / 1023.0
    w2 = ((packed >> 20) & 0x3ff) / 1023.0
    w3 = 0.0  # A2 bits often problematic
    return (w0, w1, w2, w3)


# ============================================================================
# UNIT FILE PARSER
# ============================================================================

class UnitParser:
    """Parse Gauntlet/Stingray .unit files and extract mesh data."""
    
    def __init__(self, filepath: str, verbose: bool = False):
        self.filepath = filepath
        self.verbose = verbose
        self.meshes: List[Mesh] = []
        self.header_signature: int = 0
        
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
    def parse(self) -> List[Mesh]:
        """Parse the unit file and return list of meshes."""
        with open(self.filepath, 'rb') as f:
            data = f.read()
        
        offset = 0
        
        # Parse header
        self.header_signature = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        mesh_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        
        self.log(f"File: {os.path.basename(self.filepath)}")
        self.log(f"Signature: 0x{self.header_signature:08X}")
        self.log(f"Mesh count: {mesh_count}")
        
        # Validate mesh count
        if mesh_count > 100:
            self.log(f"WARNING: Unusually high mesh count ({mesh_count}), may be parsing error")
        
        for i in range(mesh_count):
            self.log(f"\n{'='*60}")
            self.log(f"=== Mesh {i} ===")
            try:
                mesh, offset = self._parse_mesh(data, offset)
                self.meshes.append(mesh)
            except Exception as e:
                self.log(f"ERROR parsing mesh {i}: {e}")
                if self.verbose:
                    traceback.print_exc()
                break
        
        return self.meshes
    
    def _parse_mesh(self, data: bytes, offset: int) -> Tuple[Mesh, int]:
        """Parse a single mesh from the data."""
        mesh = Mesh()
        start_offset = offset
        
        # ---- VERTEX BUFFER ----
        vertex_buffer_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        vertex_buffer_start = offset
        mesh.raw_vertex_buffer = data[offset:offset + vertex_buffer_size]
        offset += vertex_buffer_size
        
        self.log(f"Vertex buffer: {vertex_buffer_size:,} bytes at offset 0x{vertex_buffer_start:X}")
        
        # ---- PADDING ----
        # Skip 8 bytes (typically zeros)
        padding1 = struct.unpack_from('<Q', data, offset)[0]
        offset += 8
        if padding1 != 0:
            self.log(f"  Note: Non-zero padding: 0x{padding1:016X}")
        
        # ---- MESH METADATA ----
        vertex_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        vertex_stride = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        element_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        
        mesh.stride = vertex_stride
        self.log(f"Vertices: {vertex_count:,}, Stride: {vertex_stride} bytes, Elements: {element_count}")
        
        # Validate
        expected_buffer_size = vertex_count * vertex_stride
        if expected_buffer_size != vertex_buffer_size:
            self.log(f"  WARNING: Expected {expected_buffer_size:,} bytes, got {vertex_buffer_size:,}")
        
        # ---- ELEMENT DESCRIPTORS ----
        elements = []
        computed_offset = 0
        
        for j in range(element_count):
            elem_type = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            elem_size = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            elem_layer = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            elem_format = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            end_marker = struct.unpack_from('<B', data, offset)[0]
            offset += 1
            
            elem = ElementDescriptor(
                type=elem_type,
                size=elem_size,
                layer=elem_layer,
                offset=computed_offset,
                format=elem_format
            )
            elements.append(elem)
            mesh.elements.append(elem)
            computed_offset += elem.byte_size
            
            type_name = ElementType(elem_type).name if elem_type < 8 else f"UNKNOWN_{elem_type}"
            self.log(f"  Element {j}: type={type_name}({elem_type}), size={elem_size}, "
                    f"layer={elem_layer}, format={elem_format}, byte_size={elem.byte_size}")
        
        self.log(f"  Computed stride: {computed_offset} (declared: {vertex_stride})")
        
        # ---- PADDING ----
        # Skip 12 bytes
        offset += 12
        
        # ---- INDEX BUFFER ----
        total_index_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        index_buffer_size = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        index_buffer_start = offset
        mesh.raw_index_buffer = data[offset:offset + index_buffer_size]
        offset += index_buffer_size
        
        # Determine index stride (16-bit or 32-bit)
        if total_index_count > 0:
            index_stride = index_buffer_size // total_index_count
        else:
            index_stride = 2
        
        self.log(f"Indices: {total_index_count:,}, Buffer: {index_buffer_size:,} bytes, "
                f"Stride: {index_stride} bytes")
        
        # ---- SHAPES/SUBMESHES ----
        shape_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        
        self.log(f"Shapes: {shape_count}")
        
        for j in range(shape_count):
            mat_idx = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            idx_off = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            idx_cnt = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            shape_idx = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            
            # The shape table stores its ranges in TRIANGLES, not indices.
            # Verified over the whole corpus (802 meshes): every mesh satisfies
            #   sum(shape.index_count) * 3 == total_index_count
            # and multi-shape meshes only tile the buffer when the counts (and
            # offsets) are read as triangle units.  Treating them as index ranges
            # left each shape covering exactly one third of the buffer, so the
            # coverage pass added a synthetic shape starting mid-triangle and the
            # exporters emitted misaligned, distorted triangles for the other two
            # thirds.  Convert to index units once, here, so every consumer
            # (glTF/OBJ writers, coverage check) slices the index buffer correctly.
            shape = Shape(mat_idx, idx_off * 3, idx_cnt * 3, shape_idx)
            mesh.shapes.append(shape)
            self.log(f"  Shape {j}: material={mat_idx}, tri_offset={idx_off}, "
                    f"tri_count={idx_cnt} -> index_offset={idx_off * 3}, "
                    f"index_count={idx_cnt * 3}, index={shape_idx}")
        
        # Check for coverage gaps
        self._check_index_coverage(mesh, total_index_count)
        
        # ---- BOUNDING BOX ----
        bbox = BoundingBox(
            min_x=struct.unpack_from('<f', data, offset)[0],
            min_y=struct.unpack_from('<f', data, offset + 4)[0],
            min_z=struct.unpack_from('<f', data, offset + 8)[0],
            max_x=struct.unpack_from('<f', data, offset + 12)[0],
            max_y=struct.unpack_from('<f', data, offset + 16)[0],
            max_z=struct.unpack_from('<f', data, offset + 20)[0],
            extra=struct.unpack_from('<f', data, offset + 24)[0]
        )
        mesh.bounding_box = bbox
        offset += 28
        
        self.log(f"BBox: ({bbox.min_x:.3f}, {bbox.min_y:.3f}, {bbox.min_z:.3f}) to "
                f"({bbox.max_x:.3f}, {bbox.max_y:.3f}, {bbox.max_z:.3f})")
        
        # ---- MATERIALS ----
        material_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        
        self.log(f"Materials: {material_count}")
        
        for j in range(material_count):
            str_len = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            mat_name = data[offset:offset + str_len].decode('utf-8', errors='replace').rstrip('\x00')
            offset += str_len
            mesh.materials.append(mat_name)
            self.log(f"  Material {j}: {mat_name}")
        
        # ---- PARSE ACTUAL DATA ----
        mesh.vertices = self._parse_vertices(
            mesh.raw_vertex_buffer, vertex_count, vertex_stride, elements
        )
        mesh.indices = self._parse_indices(
            mesh.raw_index_buffer, total_index_count, index_stride
        )
        
        self.log(f"Parsed {len(mesh.vertices)} vertices, {len(mesh.indices)} indices")
        
        return mesh, offset
    
    def _check_index_coverage(self, mesh: Mesh, total_index_count: int):
        """Check if shapes cover all indices and create synthetic shapes for gaps."""
        if not mesh.shapes:
            # No shapes defined - create one covering all indices
            if total_index_count > 0:
                mesh.shapes.append(Shape(0, 0, total_index_count, 0))
                self.log("  No shapes defined, created synthetic shape for all indices")
            return
        
        indices_in_shapes = sum(s.index_count for s in mesh.shapes)
        if indices_in_shapes >= total_index_count:
            return
        
        self.log(f"  WARNING: Shapes only cover {indices_in_shapes}/{total_index_count} indices")
        
        # Find gaps in coverage
        covered = [False] * total_index_count
        for shape in mesh.shapes:
            end = min(shape.index_offset + shape.index_count, total_index_count)
            for i in range(shape.index_offset, end):
                covered[i] = True
        
        # Create synthetic shapes for uncovered ranges
        synthetic_idx = len(mesh.shapes)
        gap_start = None
        
        for i in range(total_index_count + 1):
            if i < total_index_count and not covered[i]:
                if gap_start is None:
                    gap_start = i
            elif gap_start is not None:
                gap_count = i - gap_start
                # Round down to multiple of 3 for valid triangles
                gap_count = (gap_count // 3) * 3
                if gap_count > 0:
                    mesh.shapes.append(Shape(0, gap_start, gap_count, synthetic_idx))
                    self.log(f"  Created synthetic shape: offset={gap_start}, count={gap_count}")
                    synthetic_idx += 1
                gap_start = None
    
    def _parse_vertices(self, buffer: bytes, count: int, stride: int, 
                        elements: List[ElementDescriptor]) -> List[Vertex]:
        """Parse vertex data from buffer."""
        vertices = []
        
        for i in range(count):
            v_start = i * stride
            vert = Vertex(position=Vector3(0, 0, 0))
            
            elem_offset = 0
            for elem in elements:
                curr_offset = v_start + elem_offset
                
                try:
                    if elem.type == ElementType.POSITION:
                        x, y, z = struct.unpack_from('<fff', buffer, curr_offset)
                        vert.position = Vector3(x, y, z)
                        elem_offset += 12
                        
                    elif elem.type == ElementType.NORMAL:
                        x, y, z = struct.unpack_from('<fff', buffer, curr_offset)
                        vert.normal = Vector3(x, y, z)
                        elem_offset += 12
                        
                    elif elem.type == ElementType.TANGENT:
                        x, y, z = struct.unpack_from('<fff', buffer, curr_offset)
                        vert.tangent = Vector3(x, y, z)
                        elem_offset += 12
                        
                    elif elem.type == ElementType.BINORMAL:
                        x, y, z = struct.unpack_from('<fff', buffer, curr_offset)
                        vert.binormal = Vector3(x, y, z)
                        elem_offset += 12
                        
                    elif elem.type == ElementType.UV_COORDS:
                        u, v = struct.unpack_from('<ff', buffer, curr_offset)
                        # Check which UV layer
                        if elem.layer == 0 or vert.uv is None:
                            vert.uv = Vector2(u, 1.0 - v)  # Flip V for OBJ
                        else:
                            vert.uv2 = Vector2(u, 1.0 - v)
                        elem_offset += 8
                        
                    elif elem.type == ElementType.COLOR:
                        r, g, b, a = struct.unpack_from('<ffff', buffer, curr_offset)
                        vert.color = (r, g, b, a)
                        elem_offset += 16
                        
                    elif elem.type == ElementType.BONE_INDICES:
                        # Variable size based on size field
                        byte_size = (elem.size + 1) * 4
                        if byte_size == 4:
                            indices = struct.unpack_from('<4B', buffer, curr_offset)
                        elif byte_size == 8:
                            indices = struct.unpack_from('<4H', buffer, curr_offset)
                        else:
                            indices = struct.unpack_from('<4I', buffer, curr_offset)
                        vert.bone_indices = tuple(indices[:4])
                        elem_offset += byte_size
                        
                    elif elem.type == ElementType.BONE_WEIGHTS:
                        byte_size = (elem.size + 1) * 4
                        if byte_size == 4:
                            # Packed format
                            packed = struct.unpack_from('<I', buffer, curr_offset)[0]
                            vert.bone_weights = decode_packed_bone_weights(packed)
                        else:
                            # Float format
                            weights = struct.unpack_from(f'<{byte_size//4}f', buffer, curr_offset)
                            vert.bone_weights = tuple(weights[:4]) if len(weights) >= 4 else tuple(weights) + (0,) * (4 - len(weights))
                        elem_offset += byte_size
                        
                    else:
                        # Unknown element type, skip based on size
                        byte_size = elem.byte_size
                        elem_offset += byte_size
                        
                except struct.error as e:
                    # Buffer overrun - stop parsing this vertex
                    break
            
            vertices.append(vert)
        
        return vertices
    
    def _parse_indices(self, buffer: bytes, count: int, stride: int) -> List[int]:
        """Parse index buffer."""
        indices = []
        
        for i in range(count):
            pos = i * stride
            if pos + stride > len(buffer):
                break
                
            if stride == 2:
                idx = struct.unpack_from('<H', buffer, pos)[0]
            else:
                idx = struct.unpack_from('<I', buffer, pos)[0]
            indices.append(idx)
        
        return indices
    
    def export_obj(self, output_path: str, use_shapes: bool = True, 
                   flip_faces: bool = False, transform: str = 'none'):
        """
        Export all meshes to OBJ format.
        
        Args:
            output_path: Output file path
            use_shapes: If True, group faces by shape; if False, export all indices
            flip_faces: If True, reverse winding order (for coordinate system conversion)
            transform: Coordinate transform ('none', 'y_up', 'z_up')
        """
        with open(output_path, 'w') as f:
            f.write(f"# Gauntlet Unit to OBJ Export\n")
            f.write(f"# Source: {os.path.basename(self.filepath)}\n")
            f.write(f"# Signature: 0x{self.header_signature:08X}\n")
            f.write(f"# Meshes: {len(self.meshes)}\n\n")
            
            # Write MTL reference
            mtl_path = output_path.replace('.obj', '.mtl')
            f.write(f"mtllib {os.path.basename(mtl_path)}\n\n")
            
            vertex_offset = 1  # OBJ indices are 1-based
            uv_offset = 1
            normal_offset = 1
            
            for mesh_idx, mesh in enumerate(self.meshes):
                f.write(f"# Mesh {mesh_idx}: {len(mesh.vertices)} vertices, "
                       f"{len(mesh.indices)} indices, {len(mesh.shapes)} shapes\n")
                f.write(f"o mesh_{mesh_idx:03d}\n\n")
                
                # Determine what data we have
                has_uv = any(v.uv is not None for v in mesh.vertices)
                has_normal = any(v.normal is not None for v in mesh.vertices)
                
                # Write vertices
                for vert in mesh.vertices:
                    pos = self._transform_position(vert.position, transform)
                    f.write(f"v {pos.x:.6f} {pos.y:.6f} {pos.z:.6f}\n")
                
                f.write("\n")
                
                # Write UVs
                if has_uv:
                    for vert in mesh.vertices:
                        if vert.uv:
                            f.write(f"vt {vert.uv.u:.6f} {vert.uv.v:.6f}\n")
                        else:
                            f.write("vt 0.0 0.0\n")
                    f.write("\n")
                
                # Write normals
                if has_normal:
                    for vert in mesh.vertices:
                        if vert.normal:
                            norm = self._transform_normal(vert.normal, transform)
                            f.write(f"vn {norm.x:.6f} {norm.y:.6f} {norm.z:.6f}\n")
                        else:
                            f.write("vn 0.0 1.0 0.0\n")
                    f.write("\n")
                
                # Write faces
                if use_shapes and mesh.shapes:
                    for shape_idx, shape in enumerate(mesh.shapes):
                        # Get material name
                        mat_name = "default"
                        if 0 <= shape.material_index < len(mesh.materials):
                            mat_name = mesh.materials[shape.material_index]
                            # Sanitize material name for OBJ
                            mat_name = mat_name.replace('/', '_').replace('\\', '_').replace(' ', '_')
                        
                        f.write(f"g mesh_{mesh_idx:03d}_shape_{shape_idx:03d}\n")
                        f.write(f"usemtl {mat_name}\n")
                        
                        self._write_faces(
                            f, mesh, shape.index_offset, shape.index_count,
                            vertex_offset, uv_offset, normal_offset,
                            has_uv, has_normal, flip_faces
                        )
                        f.write("\n")
                else:
                    # Export all indices as one group
                    f.write(f"g mesh_{mesh_idx:03d}_all\n")
                    if mesh.materials:
                        mat_name = mesh.materials[0].replace('/', '_').replace('\\', '_')
                        f.write(f"usemtl {mat_name}\n")
                    
                    self._write_faces(
                        f, mesh, 0, len(mesh.indices),
                        vertex_offset, uv_offset, normal_offset,
                        has_uv, has_normal, flip_faces
                    )
                
                # Update offsets
                vertex_offset += len(mesh.vertices)
                if has_uv:
                    uv_offset += len(mesh.vertices)
                if has_normal:
                    normal_offset += len(mesh.vertices)
                
                f.write("\n")
        
        # Write MTL file
        self._write_mtl(mtl_path)
        
        print(f"Exported: {output_path}")
        print(f"Materials: {mtl_path}")
    
    def _write_faces(self, f, mesh: Mesh, start_idx: int, count: int,
                     vertex_offset: int, uv_offset: int, normal_offset: int,
                     has_uv: bool, has_normal: bool, flip_faces: bool):
        """Write face data to OBJ file."""
        max_vertex = len(mesh.vertices)
        
        for i in range(start_idx, start_idx + count, 3):
            if i + 2 >= len(mesh.indices):
                break
            
            # Get indices
            if flip_faces:
                i1 = mesh.indices[i]
                i2 = mesh.indices[i + 2]  # Swap 2 and 3 for flip
                i3 = mesh.indices[i + 1]
            else:
                i1 = mesh.indices[i]
                i2 = mesh.indices[i + 1]
                i3 = mesh.indices[i + 2]
            
            # Bounds check
            if not all(0 <= idx < max_vertex for idx in [i1, i2, i3]):
                continue
            
            # Convert to 1-based OBJ indices
            v1 = i1 + vertex_offset
            v2 = i2 + vertex_offset
            v3 = i3 + vertex_offset
            
            if has_uv and has_normal:
                f.write(f"f {v1}/{v1}/{v1} {v2}/{v2}/{v2} {v3}/{v3}/{v3}\n")
            elif has_uv:
                f.write(f"f {v1}/{v1} {v2}/{v2} {v3}/{v3}\n")
            elif has_normal:
                f.write(f"f {v1}//{v1} {v2}//{v2} {v3}//{v3}\n")
            else:
                f.write(f"f {v1} {v2} {v3}\n")
    
    def _write_mtl(self, mtl_path: str):
        """Write MTL material library file."""
        all_materials = set()
        for mesh in self.meshes:
            for mat in mesh.materials:
                mat_name = mat.replace('/', '_').replace('\\', '_').replace(' ', '_')
                all_materials.add(mat_name)
        
        with open(mtl_path, 'w') as f:
            f.write(f"# Gauntlet Material Library\n")
            f.write(f"# Source: {os.path.basename(self.filepath)}\n\n")
            
            if not all_materials:
                all_materials.add("default")
            
            for mat_name in sorted(all_materials):
                f.write(f"newmtl {mat_name}\n")
                f.write(f"Ka 0.2 0.2 0.2\n")  # Ambient
                f.write(f"Kd 0.8 0.8 0.8\n")  # Diffuse
                f.write(f"Ks 0.0 0.0 0.0\n")  # Specular
                f.write(f"Ns 10.0\n")         # Shininess
                f.write(f"d 1.0\n")           # Opacity
                f.write(f"illum 2\n\n")
    
    def _transform_position(self, pos: Vector3, transform: str) -> Vector3:
        """Apply coordinate system transformation to position."""
        if transform == 'y_up':
            # Stingray is Y-up, this is a no-op
            return pos
        elif transform == 'z_up':
            # Convert Y-up to Z-up: swap Y and Z
            return Vector3(pos.x, -pos.z, pos.y)
        else:
            return pos
    
    def _transform_normal(self, norm: Vector3, transform: str) -> Vector3:
        """Apply coordinate system transformation to normal."""
        if transform == 'y_up':
            return norm
        elif transform == 'z_up':
            return Vector3(norm.x, -norm.z, norm.y)
        else:
            return norm
    
    def print_summary(self):
        """Print a summary of parsed data."""
        print(f"\n{'='*60}")
        print(f"UNIT FILE SUMMARY: {os.path.basename(self.filepath)}")
        print(f"{'='*60}")
        print(f"Signature: 0x{self.header_signature:08X}")
        print(f"Meshes: {len(self.meshes)}")
        
        total_verts = sum(len(m.vertices) for m in self.meshes)
        total_indices = sum(len(m.indices) for m in self.meshes)
        total_tris = total_indices // 3
        
        print(f"Total vertices: {total_verts:,}")
        print(f"Total triangles: {total_tris:,}")
        
        for i, mesh in enumerate(self.meshes):
            print(f"\n  Mesh {i}:")
            print(f"    Vertices: {len(mesh.vertices):,}")
            print(f"    Triangles: {len(mesh.indices) // 3:,}")
            print(f"    Stride: {mesh.stride} bytes")
            print(f"    Shapes: {len(mesh.shapes)}")
            print(f"    Materials: {mesh.materials}")
            
            # Check for valid vertex data
            if mesh.vertices:
                v = mesh.vertices[0]
                has = []
                if v.normal: has.append("normals")
                if v.uv: has.append("UVs")
                if v.tangent: has.append("tangents")
                if v.color: has.append("colors")
                if v.bone_indices: has.append("bones")
                print(f"    Data: positions, {', '.join(has) if has else 'no extras'}")


# ============================================================================
# MAIN
# ============================================================================

def process_unit_file(unit_path: str, output_dir: str = None, verbose: bool = False,
                      use_shapes: bool = True, flip_faces: bool = False) -> bool:
    """Process a single .unit file."""
    unit_path = Path(unit_path)
    
    if not unit_path.exists():
        print(f"Error: File not found: {unit_path}")
        return False
    
    if output_dir:
        output_path = Path(output_dir) / (unit_path.stem + ".obj")
    else:
        output_path = unit_path.with_suffix(".obj")
    
    try:
        parser = UnitParser(str(unit_path), verbose=verbose)
        meshes = parser.parse()
        
        if verbose:
            parser.print_summary()
        else:
            print(f"Parsed {len(meshes)} mesh(es)")
            for i, mesh in enumerate(meshes):
                print(f"  Mesh {i}: {len(mesh.vertices)} verts, {len(mesh.indices)//3} tris, "
                      f"{len(mesh.shapes)} shapes, {len(mesh.materials)} mats")
        
        # Export with shapes
        parser.export_obj(str(output_path), use_shapes=use_shapes, flip_faces=flip_faces)
        
        # Also export without shapes for comparison
        if use_shapes:
            no_shapes_path = output_path.with_stem(output_path.stem + "_all")
            parser.export_obj(str(no_shapes_path), use_shapes=False, flip_faces=flip_faces)
        
        return True
        
    except Exception as e:
        print(f"Error processing {unit_path}: {e}")
        traceback.print_exc()
        return False


def batch_process(input_dir: str, output_dir: str = None, verbose: bool = False,
                  use_shapes: bool = True, flip_faces: bool = False):
    """Process all .unit files in a directory."""
    input_path = Path(input_dir)
    unit_files = list(input_path.glob("*.unit"))
    
    if not unit_files:
        print(f"No .unit files found in {input_dir}")
        return
    
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = input_path / "exported_obj"
        output_path.mkdir(exist_ok=True)
    
    print(f"Found {len(unit_files)} .unit files")
    print(f"Output directory: {output_path}")
    print("=" * 60)
    
    success = 0
    failed = []
    
    for i, unit_file in enumerate(unit_files, 1):
        print(f"\n[{i}/{len(unit_files)}] {unit_file.name}")
        if process_unit_file(str(unit_file), str(output_path), verbose, use_shapes, flip_faces):
            success += 1
        else:
            failed.append(unit_file.name)
    
    print("\n" + "=" * 60)
    print(f"Complete: {success}/{len(unit_files)} successful")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed[:10])}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Convert Gauntlet .unit files to OBJ format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s model.unit                    # Convert single file
  %(prog)s model.unit -o output/         # Output to specific directory
  %(prog)s units/ --batch                # Batch convert directory
  %(prog)s model.unit -v                 # Verbose output with structure info
  %(prog)s model.unit --flip-faces       # Flip face winding order
  %(prog)s model.unit --no-shapes        # Ignore shape definitions
        """
    )
    
    parser.add_argument("input", help="Input .unit file or directory")
    parser.add_argument("-o", "--output", help="Output directory")
    parser.add_argument("-v", "--verbose", action="store_true", 
                        help="Verbose output with detailed structure info")
    parser.add_argument("--batch", action="store_true", 
                        help="Process all .unit files in directory")
    parser.add_argument("--no-shapes", action="store_true",
                        help="Ignore shape definitions, export all indices")
    parser.add_argument("--flip-faces", action="store_true",
                        help="Flip face winding order (for coordinate system conversion)")
    
    args = parser.parse_args()
    
    use_shapes = not args.no_shapes
    
    if args.batch or os.path.isdir(args.input):
        batch_process(args.input, args.output, args.verbose, use_shapes, args.flip_faces)
    else:
        process_unit_file(args.input, args.output, args.verbose, use_shapes, args.flip_faces)


if __name__ == "__main__":
    main()
