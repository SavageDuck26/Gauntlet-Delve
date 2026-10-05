import struct
import os
from dataclasses import dataclass
from typing import List, Tuple, BinaryIO

@dataclass
class Vector3:
    x: float
    y: float
    z: float

@dataclass
class Vector2:
    x: float
    y: float

@dataclass
class ElementInfo:
    element_id: int
    element_size: int
    unknown_0: int
    unknown_1: int
    end_marker: int

@dataclass
class ShapeInfo:
    material_index: int
    index_offset: int
    index_count: int
    shape_index: int

@dataclass
class MaterialInfo:
    name: str

@dataclass
class VertexData:
    position: Vector3
    normal: Vector3 = None
    uv: Vector2 = None
    tangent: Vector3 = None
    binormal: Vector3 = None
    color: tuple = None

@dataclass
class Mesh:
    vertices: List[VertexData]
    indices: List[int]
    shapes: List[ShapeInfo]
    materials: List[MaterialInfo]

class UnitFileParser:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.meshes: List[Mesh] = []
        
    def parse(self) -> List[Mesh]:
        """Parse the .unit file and return list of meshes"""
        with open(self.filepath, 'rb') as f:
            # Read header
            signature = struct.unpack('<I', f.read(4))[0]
            mesh_count = struct.unpack('<I', f.read(4))[0]
            
            print(f"Signature: 0x{signature:08X}")
            print(f"Mesh Count: {mesh_count}")
            
            # Parse each mesh
            for i in range(mesh_count):
                print(f"\n=== Parsing Mesh {i} ===")
                mesh = self._parse_mesh(f, i)
                self.meshes.append(mesh)
        
        return self.meshes
    
    def _parse_mesh(self, f: BinaryIO, mesh_index: int) -> Mesh:
        """Parse a single mesh from the file"""
        # Read element buffer size
        element_buffer_size = struct.unpack('<I', f.read(4))[0]
        element_buffer_start = f.tell()
        
        # Skip element buffer for now, we'll come back to it
        f.seek(element_buffer_size, 1)
        
        # Read mesh metadata
        f.read(8)  # Skip 2 nulls
        vertex_count = struct.unpack('<I', f.read(4))[0]
        stride = struct.unpack('<I', f.read(4))[0]
        element_count = struct.unpack('<I', f.read(4))[0]
        
        print(f"Vertex Count: {vertex_count}")
        print(f"Stride: {stride}")
        print(f"Element Count: {element_count}")
        
        # Read element info
        elements = []
        for j in range(element_count):
            elem = ElementInfo(
                element_id=struct.unpack('<I', f.read(4))[0],
                element_size=struct.unpack('<I', f.read(4))[0],
                unknown_0=struct.unpack('<I', f.read(4))[0],
                unknown_1=struct.unpack('<I', f.read(4))[0],
                end_marker=struct.unpack('<B', f.read(1))[0]
            )
            elements.append(elem)
            print(f"  Element {j}: ID={elem.element_id}, Size={elem.element_size}")
        
        # Skip dummy data
        f.read(12)
        
        # Read index buffer info
        total_index_count = struct.unpack('<I', f.read(4))[0]
        index_buffer_size = struct.unpack('<I', f.read(4))[0]
        index_buffer_start = f.tell()
        
        print(f"Index Count: {total_index_count}")
        print(f"Index Buffer Size: {index_buffer_size}")
        
        # Skip index buffer for now
        f.seek(index_buffer_size, 1)
        
        # Read shape info
        shape_count = struct.unpack('<I', f.read(4))[0]
        print(f"Shape Count (declared): {shape_count}")
        
        shapes = []
        for j in range(shape_count):
            shape = ShapeInfo(
                material_index=struct.unpack('<I', f.read(4))[0],
                index_offset=struct.unpack('<I', f.read(4))[0],
                index_count=struct.unpack('<I', f.read(4))[0],
                shape_index=struct.unpack('<I', f.read(4))[0]
            )
            shapes.append(shape)
            print(f"  Shape {j}: MatIdx={shape.material_index}, IdxOff={shape.index_offset}, IdxCnt={shape.index_count}")
        
        # Check if we need to read more shapes
        indices_accounted = sum(s.index_count for s in shapes)
        if indices_accounted < total_index_count:
            print(f"\n  WARNING: Only {indices_accounted}/{total_index_count} indices accounted for!")
            print(f"  Attempting to find additional shapes...")
            
            # Try reading more shapes (maybe shape_count was wrong)
            max_additional_shapes = 20  # Safety limit
            for extra in range(max_additional_shapes):
                try:
                    # Save position in case this fails
                    save_pos = f.tell()
                    
                    # Try to read another shape
                    test_shape = ShapeInfo(
                        material_index=struct.unpack('<I', f.read(4))[0],
                        index_offset=struct.unpack('<I', f.read(4))[0],
                        index_count=struct.unpack('<I', f.read(4))[0],
                        shape_index=struct.unpack('<I', f.read(4))[0]
                    )
                    
                    # Validate: offset and count should be reasonable
                    if (test_shape.index_offset < total_index_count and 
                        test_shape.index_count > 0 and 
                        test_shape.index_offset + test_shape.index_count <= total_index_count and
                        test_shape.material_index < 100):  # Sanity check
                        
                        shapes.append(test_shape)
                        indices_accounted += test_shape.index_count
                        print(f"  Found extra shape {len(shapes)-1}: MatIdx={test_shape.material_index}, IdxOff={test_shape.index_offset}, IdxCnt={test_shape.index_count}")
                        
                        if indices_accounted >= total_index_count:
                            print(f"  All indices now accounted for!")
                            break
                    else:
                        # This doesn't look like a valid shape, restore position
                        f.seek(save_pos)
                        break
                        
                except:
                    # Failed to read, restore position and stop
                    f.seek(save_pos)
                    break
            
            print(f"  Final: {len(shapes)} shapes, {sum(s.index_count for s in shapes)}/{total_index_count} indices")
        
        unknown_floats_pos = f.tell()
        f.read(28)  # 7 floats
        
        # Read materials
        material_count = struct.unpack('<I', f.read(4))[0]
        print(f"Material Count: {material_count}")
        
        # DEBUG: Check if there might be more data
        if mesh_index == 0:  # Only for first mesh
            current = f.tell()
            print(f"\n  DEBUG: Checking for unused index data...")
            print(f"    Shapes use {sum(s.index_count for s in shapes)} of {total_index_count} indices")
            print(f"    That's {(sum(s.index_count for s in shapes) / total_index_count * 100):.1f}% usage")
        
        materials = []
        for j in range(material_count):
            str_len = struct.unpack('<I', f.read(4))[0]
            mat_name = f.read(str_len).decode('utf-8', errors='ignore')
            materials.append(MaterialInfo(name=mat_name))
            print(f"  Material {j}: {mat_name}")
        
        # Now go back and parse vertex data
        current_pos = f.tell()
        f.seek(element_buffer_start)
        vertices = self._parse_vertices_stride_based(f, vertex_count, stride, elements)
        
        # Go back and parse indices
        f.seek(index_buffer_start)
        indices = self._parse_indices(f, total_index_count, shapes)
        
        # Return to end position
        f.seek(current_pos)
        
        return Mesh(vertices=vertices, indices=indices, shapes=shapes, materials=materials)
    
    def _parse_vertices_stride_based(self, f: BinaryIO, vertex_count: int, stride: int, elements: List[ElementInfo]) -> List[VertexData]:
        """Parse vertex buffer using stride - read entire buffer then parse"""
        vertices = []
        
        # Calculate expected element sizes
        element_sizes = {
            0: 12,  # Position: float3
            1: 12,  # Normal: float3
            2: 12,  # Tangent: float3
            3: 12,  # Binormal: float3
            4: 8,   # UV: float2
            5: 16,  # Color/Weights: float4
        }
        
        for i in range(vertex_count):
            vert = VertexData(position=Vector3(0, 0, 0))
            vertex_start = f.tell()
            
            # Read each element in order
            for elem in elements:
                if elem.element_id == 0:  # Position
                    x, y, z = struct.unpack('<fff', f.read(12))
                    vert.position = Vector3(x, y, z)
                    
                elif elem.element_id == 1:  # Normal
                    x, y, z = struct.unpack('<fff', f.read(12))
                    vert.normal = Vector3(x, y, z)
                    
                elif elem.element_id == 2:  # Tangent
                    x, y, z = struct.unpack('<fff', f.read(12))
                    vert.tangent = Vector3(x, y, z)
                    
                elif elem.element_id == 3:  # Binormal
                    x, y, z = struct.unpack('<fff', f.read(12))
                    vert.binormal = Vector3(x, y, z)
                    
                elif elem.element_id == 4:  # UV
                    u, v = struct.unpack('<ff', f.read(8))
                    vert.uv = Vector2(u, -v)  # Flip V coordinate
                    
                elif elem.element_id == 5:  # Color/Weights
                    x, y, z, w = struct.unpack('<ffff', f.read(16))
                    vert.color = (x, y, z, w)
                    
                elif elem.element_id == 6:  # Variable size
                    size = (elem.element_size + 1) * 4
                    f.read(size)
                    
                elif elem.element_id == 7:  # Variable size
                    size = (elem.element_size + 1) * 4
                    f.read(size)
                    
                else:
                    print(f"Warning: Unknown element ID {elem.element_id}")
            
            # Make sure we've read exactly stride bytes
            bytes_read = f.tell() - vertex_start
            if bytes_read < stride:
                # Skip any padding
                f.read(stride - bytes_read)
            elif bytes_read > stride:
                print(f"Warning: Read {bytes_read} bytes but stride is {stride}")
            
            vertices.append(vert)
        
        return vertices
    
    def _parse_indices(self, f: BinaryIO, total_count: int, shapes: List[ShapeInfo]) -> List[int]:
        """Parse index buffer - read all indices at once"""
        indices = []
        for i in range(total_count):
            idx = struct.unpack('<H', f.read(2))[0]
            indices.append(idx)
        return indices
    
    def export_obj(self, output_path: str, debug: bool = False, use_all_indices: bool = False):
        """Export all meshes to OBJ format"""
        with open(output_path, 'w') as f:
            vertex_offset = 1  # OBJ indices start at 1
            
            for mesh_idx, mesh in enumerate(self.meshes):
                f.write(f"# Mesh {mesh_idx}\n")
                
                # Write vertices
                for vert in mesh.vertices:
                    f.write(f"v {vert.position.x} {vert.position.y} {vert.position.z}\n")
                
                # Write UVs
                if mesh.vertices and mesh.vertices[0].uv:
                    for vert in mesh.vertices:
                        f.write(f"vt {vert.uv.x} {vert.uv.y}\n")
                
                # Write normals
                if mesh.vertices and mesh.vertices[0].normal:
                    for vert in mesh.vertices:
                        f.write(f"vn {vert.normal.x} {vert.normal.y} {vert.normal.z}\n")
                
                # DEBUG: Check index buffer usage
                total_indices_used = sum(shape.index_count for shape in mesh.shapes)
                if debug:
                    print(f"\n  DEBUG Mesh {mesh_idx}:")
                    print(f"    Total indices in buffer: {len(mesh.indices)}")
                    print(f"    Total indices in shapes: {total_indices_used}")
                    print(f"    Vertices: {len(mesh.vertices)}")
                    if len(mesh.indices) > 0:
                        print(f"    Usage: {total_indices_used / len(mesh.indices) * 100:.1f}%")
                        print(f"    Max index value: {max(mesh.indices)}")
                
                # Write faces by shape (submesh)
                if use_all_indices:
                    # EXPERIMENTAL: Use ALL indices ignoring shape definitions
                    print(f"  WARNING: Using ALL {len(mesh.indices)} indices (experimental mode)")
                    f.write(f"\ng mesh_{mesh_idx:04d}_all_geometry\n")
                    
                    for i in range(0, len(mesh.indices), 3):
                        if i + 2 < len(mesh.indices):
                            i1 = mesh.indices[i] + vertex_offset
                            i2 = mesh.indices[i + 1] + vertex_offset
                            i3 = mesh.indices[i + 2] + vertex_offset
                            
                            # Bounds check
                            if all(idx <= vertex_offset + len(mesh.vertices) for idx in [i1, i2, i3]):
                                if mesh.vertices[0].uv and mesh.vertices[0].normal:
                                    f.write(f"f {i1}/{i1}/{i1} {i2}/{i2}/{i2} {i3}/{i3}/{i3}\n")
                                elif mesh.vertices[0].uv:
                                    f.write(f"f {i1}/{i1} {i2}/{i2} {i3}/{i3}\n")
                                else:
                                    f.write(f"f {i1} {i2} {i3}\n")
                else:
                    # Normal mode: use shape definitions
                    for shape_idx, shape in enumerate(mesh.shapes):
                        # Get material name
                        mat_name = "default"
                        if shape.material_index < len(mesh.materials):
                            mat_name = mesh.materials[shape.material_index].name
                        
                        f.write(f"\ng mesh_{mesh_idx:04d}_shape_{shape_idx:04d}_{mat_name}\n")
                        
                        # Direct offset (Mode 1 was best)
                        start_idx = shape.index_offset
                        end_idx = start_idx + shape.index_count
                        
                        if debug:
                            print(f"    Shape {shape_idx}: offset={shape.index_offset}, count={shape.index_count}")
                            print(f"      Index range: {start_idx} to {end_idx} (of {len(mesh.indices)})")
                        
                        faces_written = 0
                        for i in range(start_idx, end_idx, 3):
                            if i + 2 < len(mesh.indices):
                                i1 = mesh.indices[i] + vertex_offset
                                i2 = mesh.indices[i + 1] + vertex_offset
                                i3 = mesh.indices[i + 2] + vertex_offset
                                
                                # Bounds check
                                if all(idx <= vertex_offset + len(mesh.vertices) for idx in [i1, i2, i3]):
                                    if mesh.vertices[0].uv and mesh.vertices[0].normal:
                                        f.write(f"f {i1}/{i1}/{i1} {i2}/{i2}/{i2} {i3}/{i3}/{i3}\n")
                                    elif mesh.vertices[0].uv:
                                        f.write(f"f {i1}/{i1} {i2}/{i2} {i3}/{i3}\n")
                                    else:
                                        f.write(f"f {i1} {i2} {i3}\n")
                                    faces_written += 1
                                elif debug:
                                    print(f"      WARNING: Skipping face with out-of-bounds indices: {i1}, {i2}, {i3}")
                        
                        if debug:
                            print(f"      Faces written: {faces_written} (expected: {shape.index_count // 3})")
                
                vertex_offset += len(mesh.vertices)
                f.write("\n")
        
        print(f"\nExported to: {output_path}")

# Example usage
if __name__ == "__main__":
    import sys
    import glob
    
    # Check if a specific file was provided
    if len(sys.argv) >= 2:
        unit_file = sys.argv[1]
        
        # Check for flags
        debug_mode = '--debug' in sys.argv
        use_all = '--all' in sys.argv  # Use ALL indices experimental mode
        
        output_file = None
        for arg in sys.argv[2:]:
            if not arg.startswith('--'):
                output_file = arg
                break
        
        if not output_file:
            output_file = unit_file.replace('.unit', '.obj')
        
        if not os.path.exists(unit_file):
            print(f"Error: File '{unit_file}' not found!")
            sys.exit(1)
        
        print(f"Parsing: {unit_file}")
        print("=" * 60)
        
        parser = UnitFileParser(unit_file)
        meshes = parser.parse()
        
        print(f"\n{'=' * 60}")
        print(f"Successfully parsed {len(meshes)} mesh(es)")
        
        # Always export both versions
        print("\nExporting normal version (using shapes)...")
        normal_output = output_file
        parser.export_obj(normal_output, debug=debug_mode, use_all_indices=False)
        
        print("\nExporting ALL indices version (ignoring shapes)...")
        all_output = output_file.replace('.obj', '_all_indices.obj')
        parser.export_obj(all_output, debug=debug_mode, use_all_indices=True)
        
        if use_all:
            print("\nExporting 3 test modes with different offset calculations...")
            parser.export_obj_test_modes(output_file)
        
        print(f"\nAll export modes complete!")
        print(f"Files created:")
        print(f"  - {normal_output} (normal)")
        print(f"  - {all_output} (ALL indices)")
        if use_all:
            print(f"  - {output_file.replace('.obj', '_mode1_direct.obj')} (test mode 1)")
            print(f"  - {output_file.replace('.obj', '_mode2_byte.obj')} (test mode 2)")
            print(f"  - {output_file.replace('.obj', '_mode3_tri.obj')} (test mode 3)")
    
    else:
        # Batch mode - process all .unit files in script directory
        script_dir = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
        unit_files = glob.glob(os.path.join(script_dir, "*.unit"))
        
        if not unit_files:
            print("No .unit files found in script directory!")
            print("\nUsage:")
            print("  python helldivers_unit_parser.py <file.unit>         # Process specific file")
            print("  python helldivers_unit_parser.py <file.unit> --debug # Debug mode")
            print("  python helldivers_unit_parser.py <file.unit> --all   # Also export 3 test offset modes")
            print("  python helldivers_unit_parser.py                     # Process all .unit files")
            sys.exit(1)
        
        print(f"Found {len(unit_files)} .unit file(s)")
        print("=" * 60)
        
        # Create output directory
        output_dir = os.path.join(script_dir, "exported_obj")
        os.makedirs(output_dir, exist_ok=True)
        
        success_count = 0
        failed_files = []
        
        for idx, unit_file in enumerate(unit_files, 1):
            filename = os.path.basename(unit_file)
            print(f"\n[{idx}/{len(unit_files)}] Processing: {filename}")
            output_file = os.path.join(output_dir, filename.replace('.unit', '.obj'))
            
            try:
                parser = UnitFileParser(unit_file)
                meshes = parser.parse()
                parser.export_obj(output_file)
                
                # Print material summary
                total_materials = sum(len(mesh.materials) for mesh in meshes)
                print(f"  ✓ Exported {len(meshes)} mesh(es), {total_materials} material(s)")
                success_count += 1
                
            except Exception as e:
                import traceback
                print(f"  ✗ Failed: {e}")
                if '--verbose' in sys.argv:
                    traceback.print_exc()
                failed_files.append((filename, str(e)))
        
        # Summary
        print("\n" + "=" * 60)
        print(f"BATCH COMPLETE: {success_count}/{len(unit_files)} files processed successfully")
        print(f"Output directory: {output_dir}/")
        
        if failed_files:
            print(f"\nFailed files ({len(failed_files)}):")
            for filename, error in failed_files:
                print(f"  - {filename}: {error}")
        
        print("\nDone!")