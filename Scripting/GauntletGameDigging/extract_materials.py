#!/usr/bin/env python3
"""
Extract ALL material resources from ALL bundles in Gauntlet.

Materials in Bitsquid/Stingray contain references to textures and shaders.
This tool:
1. Extracts raw material data from bundles
2. Parses material structure to find texture references
3. Builds a material->texture mapping database
4. Helps identify unknown textures by their material context

Usage:
    python extract_materials.py [contents_folder] [output_folder]

Output:
    extracted_materials/
        raw/                      - Raw material data files
            <hash>.material       - Binary material data
        materials_database.json   - Material->texture mappings
        texture_to_materials.json - Reverse lookup (texture->materials using it)
        analysis.txt              - Human-readable analysis
"""

import sys
import os
import struct
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Any

# Add current directory for bundle_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle_tools import decompress_bundle

MATERIAL_TYPE = 0xEAC0B497876ADEDF
TEXTURE_TYPE = 0xCD4238C6A0C69E32
SHADER_TYPE = 0xCCE8D5B5F5AE333F

GAUNTLET_CONTENTS = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents"


class MaterialExtractor:
    """Extracts and analyzes material resources from Gauntlet bundles."""
    
    def __init__(self, contents_folder: str, output_folder: str):
        self.contents_folder = contents_folder
        self.output_folder = output_folder
        self.raw_folder = os.path.join(output_folder, "raw")
        
        # Database
        self.materials: Dict[str, Dict[str, Any]] = {}  # hash -> material info
        self.texture_to_materials: Dict[str, List[str]] = defaultdict(list)  # texture -> materials using it
        self.all_texture_hashes: Set[int] = set()  # All known texture hashes in game
        
        # Stats
        self.total_bundles = 0
        self.total_materials = 0
        self.unique_materials = 0
        
    def find_bundles(self) -> List[str]:
        """Find all bundle files in contents folder."""
        bundles = []
        for filename in os.listdir(self.contents_folder):
            filepath = os.path.join(self.contents_folder, filename)
            if os.path.isfile(filepath) and not filename.endswith(('.stream', '.backup', '.ini', '.data')):
                # Check if it looks like a hash name (16 hex chars)
                if len(filename) == 16 and all(c in '0123456789abcdef' for c in filename.lower()):
                    bundles.append(filepath)
        return sorted(bundles)
    
    def parse_bundle_entries(self, data: bytes) -> Tuple[Set[Tuple[int, int]], Set[int], Set[int]]:
        """Parse bundle header to get resource entries and type sets."""
        count = struct.unpack('<I', data[:4])[0]
        if count > 100000:
            return set(), set(), set()
        
        entries = set()
        material_hashes = set()
        texture_hashes = set()
        
        for i in range(count):
            pos = 0x104 + i * 16
            if pos + 16 > len(data):
                break
            type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
            entries.add((type_hash, name_hash))
            if type_hash == MATERIAL_TYPE:
                material_hashes.add(name_hash)
            if type_hash == TEXTURE_TYPE:
                texture_hashes.add(name_hash)
        
        return entries, material_hashes, texture_hashes
    
    def find_texture_refs_in_material(self, mat_data: bytes, all_tex_hashes: Set[int]) -> List[Tuple[int, int]]:
        """Find texture hash references within material data."""
        refs = []
        for off in range(0, len(mat_data) - 8, 4):  # Check every 4 bytes
            try:
                potential_hash = struct.unpack('<Q', mat_data[off:off+8])[0]
                if potential_hash in all_tex_hashes and potential_hash != 0:
                    refs.append((off, potential_hash))
            except:
                pass
        return refs
    
    def parse_material_structure(self, mat_data: bytes) -> Dict[str, Any]:
        """Parse material data structure to extract meaningful fields."""
        info = {
            'size': len(mat_data),
            'texture_refs': [],
            'shader_hash': None,
            'properties': [],
        }
        
        if len(mat_data) < 32:
            return info
        
        # Common material header structure (based on analysis):
        # Offset 0x00: uint32 - Unknown (often 0x0A = 10)
        # Offset 0x04: uint32 - Property count or type
        # Offset 0x08: uint64 - Shader hash (?)
        # Offset 0x10: uint64 - Unknown  
        # Offset 0x18: uint64 - Unknown
        # Offset 0x20: uint64 - First texture hash (often)
        
        try:
            info['header_0'] = struct.unpack('<I', mat_data[0:4])[0]
            info['header_1'] = struct.unpack('<I', mat_data[4:8])[0]
            
            # Potential shader hash at offset 8
            potential_shader = struct.unpack('<Q', mat_data[8:16])[0]
            if potential_shader != 0:
                info['shader_hash'] = f"0x{potential_shader:016x}"
        except:
            pass
        
        return info
    
    def extract_materials_from_bundle(self, bundle_path: str) -> int:
        """Extract all materials from a single bundle."""
        bundle_name = os.path.basename(bundle_path)
        
        try:
            with open(bundle_path, 'rb') as f:
                packed_data = f.read()
            data = decompress_bundle(packed_data)
        except Exception as e:
            print(f"  Error reading bundle: {e}")
            return 0
        
        entries, mat_hashes, tex_hashes = self.parse_bundle_entries(data)
        if not mat_hashes:
            return 0
        
        # Add textures to global set
        self.all_texture_hashes.update(tex_hashes)
        
        # Parse resources
        count = struct.unpack('<I', data[:4])[0]
        pos = 0x104 + count * 16
        
        materials_extracted = 0
        
        while pos + 36 <= len(data):
            type_hash, name_hash, flags = struct.unpack('<QQI', data[pos:pos+20])
            
            if (type_hash, name_hash) not in entries:
                pos += 1
                continue
            
            stream_size = struct.unpack('<Q', data[pos+20:pos+28])[0]
            main_size = struct.unpack('<I', data[pos+28:pos+32])[0]
            
            if type_hash == MATERIAL_TYPE:
                hash_str = f"{name_hash:016x}"
                mat_data = data[pos+36:pos+36+main_size]
                
                # Save raw material if we haven't seen it before
                if hash_str not in self.materials:
                    # Save raw file
                    raw_path = os.path.join(self.raw_folder, f"{hash_str}.material")
                    os.makedirs(self.raw_folder, exist_ok=True)
                    with open(raw_path, 'wb') as f:
                        f.write(mat_data)
                    
                    # Parse structure
                    mat_info = self.parse_material_structure(mat_data)
                    
                    # Find texture references
                    tex_refs = self.find_texture_refs_in_material(mat_data, self.all_texture_hashes)
                    mat_info['texture_refs'] = [(off, f"0x{h:016x}") for off, h in tex_refs]
                    
                    # Store
                    self.materials[hash_str] = {
                        'bundles': [bundle_name],
                        'info': mat_info,
                    }
                    
                    # Reverse mapping
                    for _, tex_hash_str in mat_info['texture_refs']:
                        self.texture_to_materials[tex_hash_str].append(hash_str)
                    
                    self.unique_materials += 1
                else:
                    # Already seen - add bundle reference
                    if bundle_name not in self.materials[hash_str]['bundles']:
                        self.materials[hash_str]['bundles'].append(bundle_name)
                    
                    # Check for new texture refs (cross-bundle textures)
                    tex_refs = self.find_texture_refs_in_material(mat_data, self.all_texture_hashes)
                    existing = set(r[1] for r in self.materials[hash_str]['info']['texture_refs'])
                    for off, h in tex_refs:
                        h_str = f"0x{h:016x}"
                        if h_str not in existing:
                            self.materials[hash_str]['info']['texture_refs'].append((off, h_str))
                            self.texture_to_materials[h_str].append(hash_str)
                
                materials_extracted += 1
            
            pos += 36 + main_size
        
        return materials_extracted
    
    def second_pass_texture_refs(self):
        """Second pass to find cross-bundle texture references."""
        print("\n" + "=" * 70)
        print("SECOND PASS: CROSS-REFERENCING TEXTURE HASHES")
        print("=" * 70)
        
        new_refs_found = 0
        
        for hash_str, mat in self.materials.items():
            raw_path = os.path.join(self.raw_folder, f"{hash_str}.material")
            if not os.path.exists(raw_path):
                continue
            
            with open(raw_path, 'rb') as f:
                mat_data = f.read()
            
            # Re-check with complete texture set
            tex_refs = self.find_texture_refs_in_material(mat_data, self.all_texture_hashes)
            existing = set(r[1] for r in mat['info']['texture_refs'])
            
            for off, h in tex_refs:
                h_str = f"0x{h:016x}"
                if h_str not in existing:
                    mat['info']['texture_refs'].append((off, h_str))
                    self.texture_to_materials[h_str].append(hash_str)
                    new_refs_found += 1
        
        print(f"Found {new_refs_found} additional texture references")
    
    def save_database(self):
        """Save the material database and analysis."""
        os.makedirs(self.output_folder, exist_ok=True)
        
        # Materials database
        db_path = os.path.join(self.output_folder, "materials_database.json")
        with open(db_path, 'w') as f:
            json.dump(self.materials, f, indent=2)
        print(f"Saved: {db_path}")
        
        # Texture to materials mapping
        tex_map_path = os.path.join(self.output_folder, "texture_to_materials.json")
        with open(tex_map_path, 'w') as f:
            json.dump(dict(self.texture_to_materials), f, indent=2)
        print(f"Saved: {tex_map_path}")
        
        # Human-readable analysis
        analysis_path = os.path.join(self.output_folder, "analysis.txt")
        with open(analysis_path, 'w') as f:
            f.write("GAUNTLET MATERIAL ANALYSIS\n")
            f.write("=" * 70 + "\n\n")
            
            f.write(f"Total bundles processed: {self.total_bundles}\n")
            f.write(f"Total material instances: {self.total_materials}\n")
            f.write(f"Unique materials: {self.unique_materials}\n")
            f.write(f"Total texture hashes in game: {len(self.all_texture_hashes)}\n")
            f.write(f"Textures referenced by materials: {len(self.texture_to_materials)}\n")
            f.write("\n")
            
            # Materials with most texture references
            f.write("TOP MATERIALS BY TEXTURE REFERENCES:\n")
            f.write("-" * 70 + "\n")
            sorted_mats = sorted(
                self.materials.items(),
                key=lambda x: len(x[1]['info']['texture_refs']),
                reverse=True
            )[:50]
            for hash_str, mat in sorted_mats:
                refs = mat['info']['texture_refs']
                f.write(f"  {hash_str}: {len(refs)} textures, size {mat['info']['size']} bytes\n")
                for off, tex_hash in refs[:5]:
                    f.write(f"    +{off:04d}: {tex_hash}\n")
                if len(refs) > 5:
                    f.write(f"    ... and {len(refs) - 5} more\n")
            
            f.write("\n")
            f.write("TEXTURES USED BY MULTIPLE MATERIALS:\n")
            f.write("-" * 70 + "\n")
            shared_textures = sorted(
                [(k, v) for k, v in self.texture_to_materials.items() if len(v) > 1],
                key=lambda x: len(x[1]),
                reverse=True
            )[:100]
            for tex_hash, mats in shared_textures:
                f.write(f"  {tex_hash}: used by {len(mats)} materials\n")
        
        print(f"Saved: {analysis_path}")
    
    def run(self):
        """Run the full extraction process."""
        print("=" * 70)
        print("GAUNTLET MATERIAL EXTRACTOR")
        print("=" * 70)
        print()
        
        bundles = self.find_bundles()
        print(f"Found {len(bundles)} bundles to process")
        print()
        
        print("=" * 70)
        print("PHASE 1: EXTRACTING MATERIALS FROM ALL BUNDLES")
        print("=" * 70)
        
        for i, bundle_path in enumerate(bundles, 1):
            bundle_name = os.path.basename(bundle_path)
            count = self.extract_materials_from_bundle(bundle_path)
            if count > 0:
                print(f"[{i}/{len(bundles)}] {bundle_name}: {count} materials")
            self.total_materials += count
            self.total_bundles += 1
        
        print(f"\nTotal material instances: {self.total_materials}")
        print(f"Unique materials: {self.unique_materials}")
        
        # Second pass for cross-bundle texture refs
        self.second_pass_texture_refs()
        
        # Save results
        print("\n" + "=" * 70)
        print("SAVING DATABASE")
        print("=" * 70)
        self.save_database()
        
        print("\n" + "=" * 70)
        print("COMPLETE!")
        print("=" * 70)
        print(f"\nResults saved to: {self.output_folder}")
        print(f"  - {self.unique_materials} unique material files in raw/")
        print(f"  - materials_database.json (material details)")
        print(f"  - texture_to_materials.json (reverse lookup)")
        print(f"  - analysis.txt (human-readable summary)")


def main():
    contents_folder = sys.argv[1] if len(sys.argv) > 1 else GAUNTLET_CONTENTS
    output_folder = sys.argv[2] if len(sys.argv) > 2 else "extracted_materials"
    
    if not os.path.exists(contents_folder):
        print(f"Error: Contents folder not found: {contents_folder}")
        sys.exit(1)
    
    extractor = MaterialExtractor(contents_folder, output_folder)
    extractor.run()


if __name__ == "__main__":
    main()
