#!/usr/bin/env python3
"""
Complete Material Decoder for Gauntlet (Bitsquid Engine, 2014)

Gauntlet Material Binary Format (older than Helldivers 2/Stingray):
- Header:
  - [0x00] Version: uint32 (always 0x0A)
  - [0x04] Section count: uint32
  - [0x08] Shader/Base hash: uint64
  - [0x10] Zero padding: uint64
- Body:
  - Multiple sections containing (index, ThinHash, texture_hash) entries
  - Settings as float values

ThinHash = upper 32 bits of MurmurHash64 (identifies texture slot type)
Hash = full 64 bits of MurmurHash64 (identifies actual texture resource)

This decoder scans for known ThinHash patterns to extract texture mappings.
"""

import os
import struct
import json
from pathlib import Path
from collections import defaultdict
from bundle_tools import murmur_hash64

def thin_hash(name):
    """Calculate ThinHash (upper 32-bit of MurmurHash64)"""
    full = murmur_hash64(name)
    return (full >> 32) & 0xFFFFFFFF

def build_slot_lookup():
    """Build lookup table for texture slot ThinHashes"""
    texture_slots = [
        # Standard PBR
        'diffuse_map', 'normal_map', 'specular_map', 'emissive_map', 'mask_map',
        'albedo', 'normal', 'specular', 'emissive', 'diffuse', 
        'roughness', 'metallic', 'ambient_occlusion', 'ao', 'occlusion',
        'color', 'tint', 'opacity', 'alpha', 'height', 'displacement',
        'diffuse_texture', 'normal_texture', 'specular_texture',
        
        # Advanced
        'color_roughness', 'color_specular_b', 'albedo_iridescence',
        'covering_albedo', 'covering_normal',
        'normal_specular_ao', 'NAC', 'NAR', 'normal_xy_ao_rough_map',
        'illuminate_data', 'metallic_intensity_map',
        'mra', 'base_data', 'base_color_emissive_map', 'albedo_emissive',
        'index_emissive', 'emissive_color', 'lens_emissive_texture',
        
        # Gauntlet specific
        'detail_map', 'detail_normal', 'blend_map', 'cube_map',
        'environment_map', 'reflection_map', 'light_map', 'shadow_map',
        'skin_map', 'blood_map', 'damage_map', 'glow_map',
        
        # LUTs
        'material_lut', 'texture_lut', 'cape_lut', 'pattern_lut',
        'lut_emissive', 'blood_lut', 'brdf_lut', 'color_lut',
        
        # Input
        'input_image', 'reticle_texture', 'ui_texture',
    ]
    
    return {thin_hash(n): n for n in texture_slots}


def is_valid_texture_hash(h):
    """Check if a value looks like a valid texture hash"""
    # Must be non-zero
    if h == 0 or h == 0xFFFFFFFFFFFFFFFF:
        return False
    # MurmurHash64 values are well-distributed - both halves should have significant bits
    upper = (h >> 32) & 0xFFFFFFFF
    lower = h & 0xFFFFFFFF
    # Small upper values indicate this isn't a hash (likely floats or indices)
    if upper < 0x01000000:  # Upper byte too small for a hash
        return False
    # Very small lower values also suspicious
    if lower < 0x01000000:
        return False
    return True


def parse_material(data, slot_lookup, texture_db=None):
    """
    Parse a Gauntlet material binary file by scanning for known patterns.
    
    The format uses (index, ThinHash) pairs followed by texture hashes.
    """
    if len(data) < 24:
        return {'error': 'File too small'}
    
    # Parse header
    version = struct.unpack_from('<I', data, 0)[0]
    section_count = struct.unpack_from('<I', data, 4)[0]
    shader_hash = struct.unpack_from('<Q', data, 8)[0]
    
    # Scan for texture slot mappings
    textures = []
    seen_offsets = set()
    
    for off in range(16, len(data) - 16, 4):
        # Look for (index, ThinHash) pattern where:
        # - index is small (0-15)
        # - ThinHash is in our known list
        idx = struct.unpack_from('<I', data, off)[0]
        th = struct.unpack_from('<I', data, off + 4)[0]
        
        if th in slot_lookup and idx <= 15:
            # Next 8 bytes should be texture hash
            tex_hash = struct.unpack_from('<Q', data, off + 8)[0]
            
            if is_valid_texture_hash(tex_hash):
                # Avoid duplicates at same offset
                if off not in seen_offsets:
                    seen_offsets.add(off)
                    slot_name = slot_lookup[th]
                    tex_name = texture_db.get(tex_hash) if texture_db else None
                    textures.append({
                        'slot': slot_name,
                        'slot_thin_hash': f'0x{th:08x}',
                        'slot_index': idx,
                        'texture_hash': f'0x{tex_hash:016x}',
                        'texture_hash_int': tex_hash,
                        'texture_name': tex_name,
                        'offset': off
                    })
    
    return {
        'header': {
            'version': version,
            'section_count': section_count,
            'shader_hash': f'0x{shader_hash:016x}'
        },
        'textures': textures
    }


def load_texture_database():
    """Load texture hash database if available"""
    db_path = Path('texture_database/texture_hash_database.json')
    if db_path.exists():
        with open(db_path) as f:
            db = json.load(f)
        return {int(k, 16): v for k, v in db.items() if k.startswith('0x')}
    return {}


def main():
    materials_dir = Path('extracted_materials/raw')
    output_dir = Path('decoded_materials')
    output_dir.mkdir(exist_ok=True)
    
    # Build lookup
    slot_lookup = build_slot_lookup()
    print(f"Loaded {len(slot_lookup)} known texture slot types")
    
    # Load texture database
    texture_db = load_texture_database()
    if texture_db:
        print(f"Loaded {len(texture_db)} textures from database")
    
    # Statistics
    slot_usage = defaultdict(int)
    all_decoded = []
    texture_to_materials = defaultdict(list)
    unique_textures = set()
    named_textures = set()
    
    # Process all materials
    material_files = list(materials_dir.glob('*.material'))
    print(f"\nDecoding {len(material_files)} materials...")
    
    for mat_file in material_files:
        with open(mat_file, 'rb') as f:
            data = f.read()
        
        mat_hash = mat_file.stem
        result = parse_material(data, slot_lookup, texture_db)
        result['material_hash'] = mat_hash
        result['file_size'] = len(data)
        
        # Track statistics
        for tex in result.get('textures', []):
            slot_usage[tex['slot']] += 1
            tex_hash = tex['texture_hash']
            unique_textures.add(tex_hash)
            if tex['texture_name']:
                named_textures.add(tex_hash)
            
            texture_to_materials[tex_hash].append({
                'material': mat_hash,
                'slot': tex['slot']
            })
        
        all_decoded.append(result)
    
    # Deduplicate textures per material
    for mat in all_decoded:
        seen = set()
        unique_tex = []
        for tex in mat.get('textures', []):
            key = (tex['slot'], tex['texture_hash'])
            if key not in seen:
                seen.add(key)
                unique_tex.append(tex)
        mat['textures'] = unique_tex
    
    # Save all decoded materials
    with open(output_dir / 'all_materials.json', 'w') as f:
        json.dump(all_decoded, f, indent=2)
    
    # Save slot usage statistics
    slot_usage_sorted = sorted(slot_usage.items(), key=lambda x: -x[1])
    with open(output_dir / 'texture_slot_usage.json', 'w') as f:
        json.dump(dict(slot_usage_sorted), f, indent=2)
    
    # Save texture to material mapping
    with open(output_dir / 'texture_to_materials.json', 'w') as f:
        json.dump(dict(texture_to_materials), f, indent=2)
    
    # Create a compact texture->slot database
    texture_slot_db = {}
    for mat in all_decoded:
        for tex in mat.get('textures', []):
            tex_hash = tex['texture_hash']
            if tex_hash not in texture_slot_db:
                texture_slot_db[tex_hash] = {
                    'slots': [],
                    'name': tex['texture_name']
                }
            if tex['slot'] not in texture_slot_db[tex_hash]['slots']:
                texture_slot_db[tex_hash]['slots'].append(tex['slot'])
    
    with open(output_dir / 'texture_slots_database.json', 'w') as f:
        json.dump(texture_slot_db, f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"MATERIAL DECODING COMPLETE")
    print(f"{'='*60}")
    print(f"Total materials decoded: {len(all_decoded)}")
    print(f"Materials with textures: {sum(1 for m in all_decoded if m.get('textures'))}")
    print(f"Unique texture references: {len(unique_textures)}")
    print(f"Textures with names: {len(named_textures)}")
    print()
    
    print("TEXTURE SLOT USAGE:")
    for slot, count in slot_usage_sorted:
        print(f"  {slot:30s} {count:5d} uses")
    
    # Sample outputs
    print("\n" + "="*60)
    print("SAMPLE DECODED MATERIALS:")
    print("="*60)
    for mat in all_decoded[:5]:
        if mat.get('textures'):
            print(f"\nMaterial {mat['material_hash']} ({mat['file_size']} bytes):")
            for tex in mat['textures'][:5]:
                name = tex['texture_name'] or 'unknown'
                print(f"  {tex['slot']:20s} -> {tex['texture_hash']} ({name})")
    
    print(f"\nOutput saved to {output_dir}/")
    print(f"  - all_materials.json ({len(all_decoded)} materials)")
    print(f"  - texture_slot_usage.json")
    print(f"  - texture_to_materials.json ({len(texture_to_materials)} unique textures)")
    print(f"  - texture_slots_database.json")


if __name__ == '__main__':
    main()
