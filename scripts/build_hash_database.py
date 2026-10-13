#!/usr/bin/env python3
"""
Build a hash-to-name database for Gauntlet resources.

This scans the Lua source code and other files to extract resource paths,
then computes their MurmurHash64 hashes to create a lookup database.

Usage:
    python build_hash_database.py [source_folder] [output_file]

Defaults:
    source_folder: C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\Aussiemon-gauntlet-slayer-edition-source-code-74e4ee3ab612
    output_file: hash_database.json
"""

import os
import sys
import json
import re
import struct
from pathlib import Path

# MurmurHash64A implementation (same as in bundle_tools.py)
def murmur_hash64(key: str, seed: int = 0) -> int:
    """
    MurmurHash64A implementation for matching Bitsquid resource names.
    """
    m = 0xc6a4a7935bd1e995
    r = 47
    
    key_bytes = key.lower().encode('utf-8')
    length = len(key_bytes)
    h = seed ^ ((length * m) & 0xFFFFFFFFFFFFFFFF)
    
    # Process 8-byte chunks
    nblocks = length // 8
    for i in range(nblocks):
        k = struct.unpack('<Q', key_bytes[i*8:(i+1)*8])[0]
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        k ^= (k >> r)
        k = (k * m) & 0xFFFFFFFFFFFFFFFF
        h ^= k
        h = (h * m) & 0xFFFFFFFFFFFFFFFF
    
    # Process remaining bytes
    tail = key_bytes[nblocks * 8:]
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
    
    h ^= (h >> r)
    h = (h * m) & 0xFFFFFFFFFFFFFFFF
    h ^= (h >> r)
    
    return h


def extract_paths_from_lua(content: str) -> set:
    """Extract resource paths from Lua source code."""
    paths = set()
    
    # Pattern 1: String literals that look like paths (contain /)
    # e.g., "characters/avatar_warrior/warrior"
    string_pattern = r'"([a-zA-Z0-9_/]+(?:/[a-zA-Z0-9_]+)+)"'
    for match in re.finditer(string_pattern, content):
        path = match.group(1)
        # Filter out obvious non-resource paths
        if not any(x in path.lower() for x in ['http', 'www.', 'file://']):
            paths.add(path)
    
    # Pattern 2: Single-quoted strings
    string_pattern2 = r"'([a-zA-Z0-9_/]+(?:/[a-zA-Z0-9_]+)+)'"
    for match in re.finditer(string_pattern2, content):
        path = match.group(1)
        if not any(x in path.lower() for x in ['http', 'www.', 'file://']):
            paths.add(path)
    
    return paths


def extract_gui_materials(content: str) -> set:
    """Extract GUI material references from Lua code."""
    paths = set()
    
    # Pattern for material loads like: load_material("menu/buttons/buttons")
    mat_pattern = r'load_material\s*\(\s*["\']([^"\']+)["\']\s*\)'
    for match in re.finditer(mat_pattern, content):
        paths.add(match.group(1))
    
    # Pattern for material references in tables
    mat_pattern2 = r'material\s*=\s*["\']([^"\']+)["\']'
    for match in re.finditer(mat_pattern2, content, re.IGNORECASE):
        paths.add(match.group(1))
    
    return paths


def generate_texture_variants(base_path: str) -> set:
    """Generate common texture name variants for a resource path."""
    variants = set()
    variants.add(base_path)
    
    # Add common texture suffixes (comprehensive list based on actual findings)
    suffixes = [
        '_diffuse', '_diff', '_d',
        '_normal', '_norm', '_n', '_nrm',
        '_specular', '_spec', '_s',
        '_gloss', '_glossy', '_roughness',
        '_ao', '_ambient', '_occlusion',
        '_height', '_h', '_bump',
        '_emissive', '_emit', '_glow',
        '_mask', '_alpha', '_opacity',
        '_color', '_col', '_albedo',
        '_metallic', '_metal',
        '_detail', '_det',
        '_blend', '_overlay',
    ]
    
    for suffix in suffixes:
        variants.add(f"{base_path}{suffix}")
    
    return variants


def generate_character_textures() -> set:
    """Generate expected texture paths for characters."""
    paths = set()
    
    # Character types (comprehensive list from unit_paths.lua)
    characters = [
        # Avatars
        ('avatar_warrior', 'warrior'),
        ('avatar_valkyrie', 'valkyrie'),
        ('avatar_wizard', 'wizard'),
        ('avatar_elf', 'elf'),
        ('avatar_necromagus', 'necromagus'),
        # Summoned units
        ('avatar_necromagus_summoned_archer', 'necromagus_summoned_archer'),
        ('avatar_necromagus_summoned_archer', 'necromagus_summoned_superarcher'),
        ('avatar_necromagus_summoned_ghost', 'necromagus_summoned_ghost'),
        ('avatar_necromagus_summoned_soldier', 'necromagus_summoned_soldier'),
        ('avatar_valkyrie_summoned_valkyrie', 'valkyrie_summoned_valkyrie'),
        # Illusions
        ('illusion_elf', 'illusion_elf'),
        ('illusion_necromagus', 'illusion_necromagus'),
        ('illusion_valkyrie', 'illusion_valkyrie'),
        ('illusion_warrior', 'illusion_warrior'),
        ('illusion_wizard', 'illusion_wizard'),
        # Bosses
        ('boss_morak', 'boss_morak'),
        ('boss_morak', 'boss_morak_illusion'),
        ('boss_morak_sword', 'boss_morak_sword'),
        ('boss_mummy', 'boss_mummy'),
        ('boss_mummy', 'boss_mummy_heart'),
        ('boss_orox', 'boss_orox'),
        # Skeletons
        ('skeleton_soldier', 'skeleton_soldier'),
        ('skeleton_warrior', 'skeleton_warrior'),
        ('skeleton_defender', 'skeleton_defender'),
        ('skeleton_commander', 'skeleton_commander'),
        # Mummies
        ('mummy_risen', 'mummy_risen'),
        ('mummy_bloated', 'mummy_bloated'),
        ('mummy_giant', 'mummy_giant'),
        ('mummy_giant_greed', 'mummy_giant_greed'),
        ('mummy_priest', 'mummy_priest'),
        # Orcs
        ('orc_melee', 'orc_melee'),
        ('orc_juggernaut', 'orc_juggernaut'),
        # Cultists
        ('cultist_novice', 'cultist_novice'),
        ('cultist_zealot', 'cultist_zealot'),
        ('cultist_armor', 'cultist_armor'),
        ('cultist_sorcerer', 'cultist_sorcerer'),
        # Demons
        ('demon_melee', 'demon_melee'),
        ('demon_ranged', 'demon_ranged'),
        ('demon_heavy', 'demon_heavy'),
        ('demon_overlord_mini', 'demon_overlord_mini'),
        # Spiders
        ('spider_warrior', 'spider_warrior'),
        ('spider_queen', 'spider_queen'),
        ('spider_hatchling', 'spider_hatchling'),
        # Others
        ('ghost', 'ghost'),
        ('lich', 'lich'),
        ('necromancer', 'necromancer'),
        ('living_statue', 'living_statue'),
        ('grunt_scavenger', 'grunt_scavenger'),
        ('grunt_shaman', 'grunt_shaman'),
        ('lake_dweller', 'lake_dweller'),
        ('relic_gargoyle', 'relic_gargoyle'),
        ('death', 'death'),
        ('merchant', 'merchant'),
        ('enemy_template', 'enemy_template'),
    ]
    
    suffixes = ['', '_diffuse', '_diff', '_normal', '_norm', '_specular', '_spec', 
                '_mask', '_glow', '_emissive', '_alpha']
    
    for folder, unit_name in characters:
        for suffix in suffixes:
            # Pattern: characters/folder/unit_name + suffix
            paths.add(f"characters/{folder}/{unit_name}{suffix}")
            # Pattern: characters/folder/folder + suffix (some use folder name)
            paths.add(f"characters/{folder}/{folder}{suffix}")
            # Gib textures
            paths.add(f"characters/{folder}/gib/gib_chunk{suffix}")
            paths.add(f"characters/{folder}/gib/{unit_name}_gib{suffix}")
        
        # Ability textures
        for ability in ['abilities', 'ability']:
            paths.add(f"characters/{folder}/{ability}")
    
    return paths


def generate_gui_textures() -> set:
    """Generate expected GUI texture paths."""
    paths = set()
    
    # GUI materials/textures from the source analysis
    gui_paths = [
        'achievement_icons/achievement_icons',
        'cape_icons/cape_icons_s01', 'cape_icons/cape_icons_s02', 'cape_icons/cape_icons_s03',
        'cape_icons/cape_icons_s04', 'cape_icons/cape_icons_s05', 'cape_icons/cape_icons_s06',
        'equippables_icons/equipment',
        'equippables_icons/shop_action_icons',
        'equippables_icons/relics',
        'hud/action_icons', 'hud/boss', 'hud/controller_icons', 'hud/elements',
        'hud/hud', 'hud/relic_icons', 'hud/spells',
        'hero_sprites/hero_sprites',
        'menu/buttons/buttons', 'menu/effects/effects', 'menu/floor_end_screen',
        'menu/hero_coins/hero_coins', 'menu/how_to_play/how_to_play',
        'menu/icons', 'menu/menu', 'menu/level_select',
        'menu/colosseum/colosseum', 'menu/colosseum/arenas', 'menu/colosseum/grades/grades',
        'menu/perk_screen/perk_screen', 'menu/image_strips/image_strips',
        'menu/score_screen/score_screen', 'menu/steam_avatar', 'menu/shop',
        'menu/standard_elements',
        'loading_screens/loading_screens',
        'cutscenes/outro/cutscene_outro',
        'fonts/all_fonts', 'fonts/default', 'foundation/fonts/debug_small',
        'foundation/gui/gui',
        'decals/decals_global',
    ]
    
    for path in gui_paths:
        paths.add(path)
        paths.add(f"gui/{path}")
        paths.add(f"materials/{path}")
        paths.add(f"textures/{path}")
    
    # UI effect materials
    ui_effects = [
        'hero_coin_hover', 'hero_coin_locked', 'hero_coin_locked_elf',
        'hero_coin_locked_valkyrie', 'hero_coin_locked_warrior', 'hero_coin_locked_wizard',
        'hero_ready', 'score_bar_fillup', 'shop_gold_glint',
        'shop_item_equip', 'shop_item_purchase', 'test',
    ]
    for effect in ui_effects:
        paths.add(f"effects_ui/{effect}")
        paths.add(f"gui/effects_ui/{effect}")
    
    return paths


def generate_prop_textures() -> set:
    """Generate expected prop texture paths."""
    paths = set()
    
    # Prop categories
    prop_categories = ['d01_caves', 'd01_crypt', 'd01_common', 'd01_lava']
    
    for cat in prop_categories:
        paths.add(f"props/{cat}")
        paths.add(f"units/props/{cat}")
        paths.add(f"textures/props/{cat}")
    
    # Common props
    props = [
        'barrel_01', 'barrel_01_rotten', 'box_small_01', 'urn_01', 'urn_02_var01',
        'urn_02_var02', 'urn_03', 'torch_floor_01', 'torch_floor_02',
        'cart_02', 'cave_goldrock_01', 'spideregg_01',
        'dummy_target_01', 'burned_corpse_01', 'burned_corpse_02',
        'burned_corpse_03', 'burned_corpse_04', 'burned_corpse_05', 'burned_corpse_06',
        'lava_metalbox', 'lava_redwizard_chair', 'lava_torture_device_01',
        'lava_weapon_rack_01', 'vase',
    ]
    
    for prop in props:
        paths.add(f"props/{prop}")
        paths.add(f"units/props/{prop}")
    
    return paths


def generate_block_textures() -> set:
    """Generate expected block/level texture paths."""
    paths = set()
    
    level_types = ['caves', 'crypt', 'lava', 'arcade', 'common']
    
    for level in level_types:
        # Common naming patterns
        paths.add(f"blocks/d01_{level}")
        paths.add(f"units/blocks/d01_{level}")
        paths.add(f"textures/blocks/d01_{level}")
        paths.add(f"textures/environment/{level}")
        paths.add(f"textures/dungeon/{level}")
        
        # Floor/wall textures
        for surface in ['floor', 'wall', 'ceiling', 'trim', 'detail']:
            paths.add(f"textures/{level}_{surface}")
            paths.add(f"textures/environment/{level}_{surface}")
    
    return paths


def generate_effect_textures() -> set:
    """Generate expected effect/particle texture paths."""
    paths = set()
    
    # Effect types from source analysis
    effects = [
        'hit_block', 'hit_block_broken', 'footstep_default', 'footstep_default_charge',
        'footstep_sand', 'footstep_water', 'hit_arrow_sand', 'hit_arrow_stone',
        'hit_arrow_water', 'hit_arrow_generic', 'hit_stone_small',
        'hit_slam_stone', 'hit_slam_water',
        'hit_slash_red', 'hit_slash_black', 'hit_slash_burning', 'hit_slash_yellow',
        'hit_slash_ethereal', 'hit_slash_bone', 'hit_slash_metal', 'hit_slash_hero',
        'hit_fire', 'hit_punch',
        'gib_blasted_red', 'gib_blasted_black', 'gib_blasted_burning',
        'gib_crushed_red', 'gib_crushed_black', 'gib_crushed_burning',
        'hit_gib_frozen', 'cha_elf_tumble_land',
        'menu_hero_spawn',
    ]
    
    for effect in effects:
        paths.add(f"effects/{effect}")
        paths.add(f"particles/{effect}")
        paths.add(f"textures/effects/{effect}")
    
    # Decal textures
    decals = [
        'decal_enemyshadow', 'footstep_sand', 'test_decal0',
        'cracks_ground_01', 'cracks_ground_heavy_01',
        'blood_splat_red_01', 'blood_splat_red_02', 'blood_splat_red_03',
        'blood_splat_spider_01', 'blood_splat_spider_02', 'blood_splat_spider_03',
        'blood_splat_burning_01', 'blood_splat_burning_02', 'blood_splat_burning_03',
        'blood_splat_black_01', 'blood_splat_black_02', 'blood_splat_black_03',
        'bloodpour_01', 'freeze_ring', 'gib_frozen',
    ]
    
    for decal in decals:
        paths.add(f"decals/{decal}")
        paths.add(f"textures/decals/{decal}")
    
    return paths


def generate_equipment_textures() -> set:
    """Generate expected equipment texture paths."""
    paths = set()
    
    heroes = ['warrior', 'valkyrie', 'wizard', 'elf', 'necromagus']
    
    for hero in heroes:
        paths.add(f"equipment/{hero}")
        paths.add(f"units/equipment/{hero}")
        paths.add(f"textures/equipment/{hero}")
        
        # Weapon types
        for weapon in ['weapon', 'shield', 'helmet', 'armor', 'cape']:
            paths.add(f"equipment/{hero}/{weapon}")
            paths.add(f"units/equipment/{hero}/{weapon}")
    
    return paths


def scan_lua_files(source_folder: str) -> set:
    """Scan all Lua files for resource paths."""
    paths = set()
    
    source_path = Path(source_folder)
    if not source_path.exists():
        print(f"Warning: Source folder not found: {source_folder}")
        return paths
    
    print(f"Scanning Lua files in: {source_folder}")
    
    lua_count = 0
    for lua_file in source_path.rglob('*.lua'):
        try:
            content = lua_file.read_text(encoding='utf-8', errors='ignore')
            extracted = extract_paths_from_lua(content)
            paths.update(extracted)
            
            # Also extract GUI materials
            gui_mats = extract_gui_materials(content)
            paths.update(gui_mats)
            
            lua_count += 1
        except Exception as e:
            print(f"  Warning: Could not read {lua_file}: {e}")
    
    print(f"  Scanned {lua_count} Lua files, found {len(paths)} paths")
    return paths


def build_database(source_folder: str) -> dict:
    """Build the complete hash-to-name database."""
    all_paths = set()
    
    # Scan Lua source files
    lua_paths = scan_lua_files(source_folder)
    all_paths.update(lua_paths)
    
    # Add generated paths
    print("Generating common resource paths...")
    all_paths.update(generate_character_textures())
    all_paths.update(generate_gui_textures())
    all_paths.update(generate_prop_textures())
    all_paths.update(generate_block_textures())
    all_paths.update(generate_effect_textures())
    all_paths.update(generate_equipment_textures())
    
    # Add texture variants for all paths
    print("Generating texture variants...")
    all_with_variants = set()
    for path in all_paths:
        all_with_variants.update(generate_texture_variants(path))
    
    print(f"Total paths (with variants): {len(all_with_variants)}")
    
    # Compute hashes
    print("Computing hashes...")
    database = {}
    for path in all_with_variants:
        hash_val = murmur_hash64(path)
        hash_str = f"{hash_val:016x}"
        
        # Store hash -> name mapping
        if hash_str not in database:
            database[hash_str] = path
        else:
            # Keep shorter path if collision (more likely to be the actual name)
            if len(path) < len(database[hash_str]):
                database[hash_str] = path
    
    return database


def main():
    # Parse arguments
    if len(sys.argv) > 1:
        source_folder = sys.argv[1]
    else:
        source_folder = r"C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\Aussiemon-gauntlet-slayer-edition-source-code-74e4ee3ab612"
    
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    else:
        output_file = "hash_database.json"
    
    print("=" * 60)
    print("GAUNTLET HASH DATABASE BUILDER")
    print("=" * 60)
    print()
    
    # Build the database
    database = build_database(source_folder)
    
    print()
    print(f"Database contains {len(database)} hash -> name mappings")
    
    # Save to JSON
    with open(output_file, 'w') as f:
        json.dump(database, f, indent=2, sort_keys=True)
    
    print(f"Saved to: {output_file}")
    
    # Also save a human-readable version
    txt_file = output_file.replace('.json', '.txt')
    with open(txt_file, 'w') as f:
        f.write("GAUNTLET HASH DATABASE\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total entries: {len(database)}\n\n")
        f.write("Hash                 -> Name\n")
        f.write("-" * 80 + "\n")
        for hash_str in sorted(database.keys()):
            f.write(f"{hash_str}  {database[hash_str]}\n")
    
    print(f"Saved readable version to: {txt_file}")
    
    # Print some sample entries
    print()
    print("Sample entries:")
    for i, (hash_str, name) in enumerate(sorted(database.items())[:10]):
        print(f"  {hash_str} -> {name}")
    print("  ...")


if __name__ == "__main__":
    main()
