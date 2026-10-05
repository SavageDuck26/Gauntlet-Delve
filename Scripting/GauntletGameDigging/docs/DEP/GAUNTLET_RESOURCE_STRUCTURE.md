# Gauntlet Resource Structure Guide
## File Hierarchy & Package Creation Reference

> [!WARNING]
> **⚠ PARTIALLY DEPRECATED (January 9, 2026 content).**
>
> - The **Package Resource Format** section below documents the OLD 20-byte entry
>   layout (`dependency_count` / `dependency_refs`). This is **WRONG**: the
>   confirmed layout is a 4-byte count, then N × **28-byte** entries
>   (`type_hash`, `name_hash`, `c1=2`, `c2`, `name_hi32`), then a 1-byte `0x01`
>   trailer (FINDINGS §9B).
> - The custom-texture-package workflow (create_texture_package.py) is superseded
>   by FINDINGS §15J/§16 — custom bundles need payload trailers to load.
> - **Known broken reference:** `custom/texture_loader.lua` does not exist.
>
> The folder-hierarchy, naming-convention and hash tables below are still useful
> reference material.

---

## 📁 Gauntlet Texture/Material Folder Structure

Based on analysis of the game's extracted assets, here's the **exact folder hierarchy**:

```
textures/
├── characters/
│   ├── avatar_elf/
│   │   ├── abilities/
│   │   │   └── special_explosive_bomb_diff
│   │   ├── elf_diff
│   │   ├── elf_norm
│   │   └── elf_spec
│   ├── avatar_necromagus/
│   │   ├── abilities/
│   │   │   ├── skeleton_heavy
│   │   │   ├── skeleton_heavy_coffin_diff
│   │   │   ├── skeleton_heavy_hammer_diff
│   │   │   └── ultimate_remnant_diff
│   │   ├── necromagus_diff
│   │   └── necromagus_spec
│   ├── avatar_valkyrie/
│   │   ├── valkyrie_diff
│   │   └── valkyrie_spec
│   ├── avatar_warrior/
│   │   ├── warrior_diff
│   │   ├── warrior_norm
│   │   └── warrior_spec
│   ├── avatar_wizard/
│   │   ├── abilities/
│   │   │   └── spell_lightning_shield
│   │   ├── wizard_diff
│   │   ├── wizard_norm
│   │   └── wizard_spec
│   ├── boss_morak/
│   │   ├── boss_morak_normal_diff
│   │   └── boss_morak_normal_normal
│   ├── boss_morak_sword/
│   │   ├── boss_morak_sword_diff
│   │   ├── boss_morak_sword_mask
│   │   └── boss_morak_sword_norm
│   ├── boss_mummy/
│   │   ├── boss_mummy_diff
│   │   ├── boss_mummy_heart_diff
│   │   ├── boss_mummy_heart_norm
│   │   ├── boss_mummy_heart_spec
│   │   ├── boss_mummy_norm
│   │   └── boss_mummy_spec
│   ├── boss_orox/
│   │   ├── boss_orox_diff
│   │   ├── boss_orox_norm
│   │   └── boss_orox_spec
│   ├── cultist_armor/
│   │   └── cultist_armor_diff
│   ├── cultist_novice/
│   │   ├── cultist_novice_diff
│   │   └── cultist_novice_normal
│   ├── cultist_sorcerer/
│   │   ├── cultist_sorcerer_diff
│   │   └── cultist_sorcerer_normal
│   ├── cultist_zealot/
│   │   ├── cultist_zealot_diff
│   │   └── cultist_zealot_normal
│   ├── death/
│   │   └── death_diff
│   ├── demon_heavy/
│   │   ├── demon_heavy_diff
│   │   └── demon_heavy_normal
│   ├── demon_melee/
│   │   ├── demon_melee_diffuse
│   │   └── demon_melee_normal
│   ├── demon_ranged/
│   │   ├── demon_ranged_diffuse
│   │   └── demon_ranged_normal
│   ├── ghost/
│   │   ├── ghost_diff
│   │   ├── ghost_glow
│   │   └── ghost_norm
│   ├── grunt_scavenger/
│   │   ├── grunt_scavenger_diffuse
│   │   └── grunt_scavenger_normal
│   ├── grunt_shaman/
│   │   ├── abilities/
│   │   │   └── summoned_wall_diff
│   │   └── grunt_shaman_diff
│   ├── lake_dweller/
│   │   ├── lake_dweller_diffuse
│   │   └── lake_dweller_normal
│   ├── lich/
│   │   └── lich_diff
│   ├── mummy_bloated/
│   │   └── mummy_bloated_diff
│   ├── mummy_giant/
│   │   └── mummy_giant
│   ├── mummy_priest/
│   │   └── mummy_priest_diff
│   ├── mummy_risen/
│   │   └── mummy_risen_diff
│   ├── necromancer/
│   │   └── necromancer_diff
│   ├── orc_juggernaut/
│   │   ├── orc_juggernaut_diff
│   │   └── orc_juggernaut_normal
│   ├── orc_melee/
│   │   ├── orc_melee_diff
│   │   └── orc_melee_normal
│   ├── relic_gargoyle/
│   │   └── relic_gargoyle_diff
│   ├── skeleton_commander/
│   │   └── skeleton_commander_diff
│   ├── skeleton_soldier/
│   │   └── skeleton_soldier_diff
│   ├── skeleton_warrior/
│   │   ├── skeleton_warrior_diff
│   │   └── skeleton_warrior_spec
│   ├── spider_hatchling/
│   │   ├── spider_hatchling_diff
│   │   └── spider_hatchling_normal
│   └── spider_queen/
│       ├── abilities/
│       │   └── spider_egg
│       ├── spider_queen_diff
│       └── spider_queen_normal
│
├── decals/
│   ├── blood_splat_black_01
│   ├── blood_splat_black_02
│   ├── blood_splat_black_03
│   ├── blood_splat_burning_01
│   ├── blood_splat_burning_02
│   ├── blood_splat_burning_03
│   ├── blood_splat_red_01
│   ├── blood_splat_red_02
│   ├── blood_splat_red_03
│   ├── blood_splat_spider_01
│   ├── blood_splat_spider_02
│   ├── blood_splat_spider_03
│   ├── bloodpour_01
│   ├── cracks_ground_01
│   ├── cracks_ground_heavy_01
│   ├── decal_direction_marker_elf
│   └── decal_direction_marker_wizard
│
├── effects/
│   └── meshes/
│       └── death_smoke_cone
│
├── equipment/
│   ├── elf/
│   │   ├── weapon01_diff    (256x512 DXT1)
│   │   ├── weapon01_spec    (256x512 DXT1)
│   │   ├── weapon02_diff    (256x256 DXT1)
│   │   ├── weapon03_diff    (256x512 DXT1)
│   │   ├── weapon04_diff    (256x512 DXT1)
│   │   └── weapon05_diff    (256x512 DXT1)
│   ├── necromagus/
│   │   ├── weapon01_diff    (256x256 DXT1)
│   │   ├── weapon02_diff    (256x512 DXT1)
│   │   ├── weapon03_diff    (256x512 DXT1)
│   │   └── weapon04_diff    (256x256 DXT1)
│   └── warrior/
│       ├── weapon01_diff    (512x512 DXT1)
│       ├── weapon01_spec    (512x512 DXT1)
│       ├── weapon02_diff    (256x512 DXT1)
│       ├── weapon02_spec    (256x512 DXT1)
│       ├── weapon03_diff    (256x512 DXT1)
│       ├── weapon03_spec    (256x512 DXT1)
│       ├── weapon04_diff    (512x256 DXT1)
│       ├── weapon04_spec    (512x256 DXT1)
│       ├── weapon05_diff    (256x512 DXT1)
│       ├── weapon05_norm    (256x512 ATI2)
│       ├── weapon05_spec    (256x512 DXT1)
│       ├── weapon09_diff    (512x256 DXT5)
│       ├── weapon09_spec    (512x256 DXT5)
│       ├── weapon10_diff    (256x512 DXT1)
│       ├── weapon10_spec    (256x512 DXT1)
│       ├── weapon11_diff    (256x512 DXT1)
│       └── weapon11_spec    (256x512 DXT1)
│
├── fonts/
│   └── default
│
├── foundation/
│   └── fonts/
│       └── debug_small
│
├── gameobjects/
│   ├── bombs/
│   │   └── explosive_diff
│   ├── carry/
│   │   ├── carry_barrel_caves
│   │   ├── carry_barrel_crypt
│   │   ├── carry_barrel_lava
│   │   ├── carry_boulder_diff
│   │   ├── carry_caves_key_01_diff
│   │   ├── carry_caves_key_01_glow
│   │   ├── carry_caves_key_01_norm
│   │   ├── carry_caves_key_01_receptor_diff
│   │   ├── carry_caves_key_01_receptor_glow
│   │   ├── carry_caves_key_01_receptor_norm
│   │   ├── carry_crypt_relic_mask
│   │   └── carry_crypt_relic_norm
│   ├── crests/
│   │   ├── crank_diff
│   │   ├── crank_norm
│   │   ├── pushable_block_diff
│   │   └── pushable_block_norm
│   ├── dispensers/
│   │   ├── dispenser_barrel_crypt_diff
│   │   └── dispenser_barrel_lava_diff
│   ├── doors/
│   │   └── [various door textures]
│   ├── food/
│   │   ├── apple_diff
│   │   ├── ham_diff
│   │   ├── ham_gold_diff
│   │   ├── ham_gold_spec
│   │   ├── turkey_diff
│   │   ├── turkey_gold_diff
│   │   ├── turkey_gold_spec
│   │   └── turkey_spec
│   ├── gold/
│   │   ├── chest_diff
│   │   ├── chest_locked_diff
│   │   ├── chest_spec
│   │   ├── pile_small
│   │   ├── skullcoin_diff
│   │   └── skullcoin_spec
│   ├── keys/
│   │   └── small
│   ├── potions/
│   │   └── potion_gold_diff
│   ├── relics/
│   │   └── golden_feather_turkey_diff
│   ├── spawners/
│   │   ├── spawner_beam_diff
│   │   ├── spawner_beam_norm
│   │   ├── spawner_mortar_diff
│   │   ├── spawner_twister_diff
│   │   └── spawner_twister_norm
│   ├── teleporter/
│   │   ├── teleporter_diff
│   │   ├── teleporter_emissive
│   │   └── teleporter_norm
│   └── treasures/
│       └── crown/
│           └── crown_diff
│
└── props/
    ├── d01_caves/
    │   ├── bridge_01_diff
    │   ├── bridge_01_norm
    │   ├── cave_goldrock_01_diff
    │   ├── cave_goldrock_01_emissive
    │   ├── cave_goldrock_01_norm
    │   ├── caves_cobweb_01_diff
    │   ├── mushroom_tree_01_diff
    │   ├── mushroom_tree_01_norm
    │   ├── spider_den_01_diff
    │   ├── spider_den_01_norm
    │   ├── spider_den_wall_01_diff
    │   ├── spider_den_wall_01_norm
    │   ├── spider_den_wall_02_diff
    │   ├── spider_den_wall_02_norm
    │   ├── spideregg_01_diff
    │   ├── spideregg_01_spec
    │   ├── spiderweb_01_diff
    │   └── mini_beast_statue_diff/norm
    └── d01_common/
        ├── barrel_01
        ├── barrel_01_rotten
        ├── box_small_01_diff
        ├── box_small_01_norm
        ├── bucket_01_diff
        ├── colosseum_banner_01
        └── colosseum_banner_01_norm
```

---

## 🎨 Texture Naming Conventions

### Suffix Types
| Suffix | Purpose | DDS Format |
|--------|---------|------------|
| `_diff` or `_diffuse` | Diffuse/Albedo color map | DXT1 or DXT5 |
| `_norm` or `_normal` | Normal map | ATI2 (BC5) |
| `_spec` | Specular/Roughness map | DXT1 or DXT5 |
| `_glow` or `_emissive` | Emissive/Self-illumination | DXT1 |
| `_mask` | Mask texture for effects | DXT1 |

### Common Dimensions by Category
| Category | Common Sizes |
|----------|--------------|
| Characters (main) | 512x512, 768x768, 1024x1024 |
| Characters (abilities) | 128x128, 256x256 |
| Equipment/Weapons | 256x256, 256x512, 512x256, 512x512 |
| Props | 256x256, 512x512, 1024x1024 |
| Effects | 128x128, 256x128, 256x256 |
| Decals | 256x256, 512x512 |

---

## 📦 Package Structure

### How Resource Packages Work

Gauntlet uses the **Bitsquid/Stingray** engine. Resources are:
1. **Hashed** using MurmurHash64 (filename becomes 16-char hex)
2. **Bundled** into archive files (the hex-named files in `contents/`)
3. **Loaded** via package resources that list dependencies

### Package Resource Format (Binary)  *** CORRECTED — see banner above ***
```
Header:
  uint32: entry_count

Per Entry (28 bytes):
  uint64: resource_type_hash  (texture=0xCD4238C6A0C69E32)
  uint64: resource_name_hash  (MurmurHash64 of path)
  uint32: c1                  (ALWAYS 2)
  uint32: c2                  (per-package constant; 0 safe for custom bundles)
  uint32: name_hi32           (upper 32 bits of resource_name_hash)

Trailer:
  uint8: 0x01   (one byte after the last entry — NOT 0x00)
```

### Resource Type Hashes
```python
TYPE_TEXTURE  = 0xCD4238C6A0C69E32  # murmur_hash64("texture")
TYPE_MATERIAL = 0xEAC0B497876ADEDF  # murmur_hash64("material")
TYPE_PACKAGE  = 0xAD9C6D9ED1E5E77A  # murmur_hash64("package")
TYPE_UNIT     = 0xE0A48D0BE9A7453F  # murmur_hash64("unit")
TYPE_LUA      = 0xA14E8DFA2CD117E2  # murmur_hash64("lua")
TYPE_SHADER   = 0xCCE8D5B5F5AE333F  # murmur_hash64("shader")
```

---

## 🔧 Creating Custom Packages

### Step 1: Prepare Your Textures

Create your DDS textures following the naming convention:
```
my_mod/
├── equipment/
│   └── warrior/
│       ├── custom_sword_diff.dds    (256x512 DXT1)
│       ├── custom_sword_norm.dds    (256x512 ATI2)
│       └── custom_sword_spec.dds    (256x512 DXT1)
└── characters/
    └── avatar_warrior/
        └── custom_armor_diff.dds    (512x512 DXT1)
```

### Step 2: Use create_texture_package.py

```bash
python create_texture_package.py my_mod/ my_custom_pack --prefix mods
```

This creates:
- `<hash>` - Bundle file with your textures + package resource
- `my_custom_pack_manifest.json` - Hash reference for your textures

### Step 3: Install the Bundle

Copy the bundle to Gauntlet's contents folder:
```
C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\<hash>
```

### Step 4: Load in Lua

```lua
-- In your mod's Lua script
Game:load_package("resource_packages/mods/my_custom_pack", true)

-- Reference textures by hash from manifest
local sword_diff_hash = 0x1234567890ABCDEF  -- Get from manifest
```

---

## 🎮 Vermintide Modding Reference (Similar Engine)

Both Gauntlet and Vermintide use the **Bitsquid/Stingray** engine, so modding approaches are similar:

### Key Differences
| Aspect | Vermintide | Gauntlet |
|--------|------------|----------|
| Mod Support | Official SDK + Steam Workshop | No official support |
| Package API | `Managers.package:load()` | `Game:load_package()` |
| Bundle Location | Workshop folder | `contents/` folder |
| Validation | Mod sanctioning | None |

### Vermintide Mod Approach (Reference)
```lua
-- Vermintide uses similar package loading
Managers.package:load("resource_packages/mods/my_textures", "async", function()
    print("Custom textures loaded!")
end)
```

### PigBots-style Mods
Cosmetic mods in Vermintide typically:
1. Hook into rendering/equipment systems
2. Replace material texture references at runtime
3. Load custom texture packages on mod initialization
4. Use hash lookups to swap textures

---

## 📋 Material Structure

Materials in Gauntlet are binary resources that reference textures by hash.

### Material Format (Extracted Analysis)
```json
{
  "03054db6a1586c9b": {
    "bundles": ["0164ad48615ba9ed", "1bbcb9610a009446", ...],
    "info": {
      "size": 256,
      "texture_refs": [
        [32, "0x9f87cdf231ef5056"],   // offset, texture_hash
        [44, "0xa563102d9ea883cc"],   // Likely diffuse map
        [152, "0xa8d16be0dd26e2a0"]   // Likely normal map
      ],
      "shader_hash": "0x26fbe7181f811036"
    }
  }
}
```

### Texture Reference Positions in Materials
- Offset ~32: Primary texture (usually diffuse)
- Offset ~44: Secondary texture
- Offset 140+: Additional maps (normal, spec, etc.)

---

## 🔑 Quick Reference: Texture Hashes

### Example Character Textures
| Name | Hash | Size |
|------|------|------|
| `characters/avatar_warrior/warrior_diff` | `0x67111D9E39E1CABC` | 512x512 |
| `characters/avatar_warrior/warrior_norm` | `0xF8C23D1F8B219C6D` | 512x512 |
| `characters/avatar_warrior/warrior_spec` | `0x6A77D7C1FF442EE7` | 256x256 |
| `characters/avatar_elf/elf_diff` | `0x5A946011CD458AA6` | 768x768 |
| `characters/avatar_wizard/wizard_diff` | `0x7151952485EEA483` | 768x768 |

### Example Equipment Textures
| Name | Hash | Size |
|------|------|------|
| `equipment/warrior/weapon01_diff` | `0x52A65FAB447503E1` | 512x512 |
| `equipment/warrior/weapon01_spec` | `0x810939F95B3A2A03` | 512x512 |
| `equipment/elf/weapon01_diff` | `0x39E05CB975E6F8BF` | 256x512 |

---

## 📂 Files in This Project

| File | Purpose |
|------|---------|
| `create_texture_package.py` | Creates custom texture bundles |
| `custom/texture_loader.lua` | Lua helper for loading custom packages |
| `Exports/extracted_named/_index.txt` | Full list of named textures |
| `Exports/texture_database/` | Texture analysis database |
| `Exports/extracted_materials/materials_database.json` | Material-texture mappings |

---

## 🚀 Next Steps

1. **To replace a texture**: Match the original's dimensions/format, create DDS, package it
2. **To add new content**: Create textures, materials, and potentially units
3. **To hook rendering**: Modify Lua scripts to intercept texture/material loading

---

*Last Updated: January 9, 2026*
