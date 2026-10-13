# Gauntlet Custom Texture Modding Guide

> [!WARNING]
> **⚠ PARTIALLY DEPRECATED (January 9, 2026 content).**
>
> - **Approach 1 (Custom Texture Packages)** is **not reliable as written** —
>   custom bundles containing textures/materials hang the engine unless each
>   resource carries its required payload trailer. See `FINDINGS.txt` §15J
>   (disproof) and §16 (working recipe), and `CUSTOM_ASSET_LOADING_FINDINGS.md`.
> - **Approach 2 (Texture Slot Injection via `replace_textures_v4.py`)** is the
>   proven, still-valid path — prefer it.
>
> **Known broken reference:** `texture_loader.lua` (referenced below) does not
> exist in this repo — the `require("custom/texture_loader")` example will fail.

## Overview

This guide explains how to add custom textures to Gauntlet Slayer Edition. There are two main approaches:

1. **Custom Texture Packages** - Create standalone packages loadable from Lua scripts (NEW!)
2. **Texture Slot Injection** - Replace existing textures in bundles (proven reliable)

## Quick Start: Custom Texture Package

```powershell
# 1. Put your DDS textures in a folder
#    my_textures/sword.dds, my_textures/shield.dds

# 2. Create the package
python create_texture_package.py my_textures my_pack

# 3. Copy to game
copy output\<hash> "C:\...\Gauntlet\contents\"

# 4. Load in Lua
# Game:load_package("resource_packages/custom/my_pack", true)
```

---

## Approach 1: Custom Texture Packages (Recommended)

This approach creates standalone packages that can be loaded from Lua scripts
using `Game:load_package()`. This is how the game's own resource system works.

### How It Works

1. **Packages** are resources that list other resources to load
2. **Bundles** contain the compiled resources (textures, packages, etc.)
3. When you call `Game:load_package("resource_packages/custom/mypack")`:
   - The engine looks up the package by its MurmurHash64
   - Loads all resources listed in that package
   - Textures become available to materials and scripts

### Prerequisites

- Python 3.8+
- DDS textures (convert PNG using texconv or GIMP)
- Gauntlet with mod support (custom Lua scripts)

### Step 1: Prepare Your Textures

Convert your images to DDS format:

```powershell
# Using Microsoft's texconv (download from GitHub)
texconv -f DXT5 -m 8 my_texture.png

# Or use GIMP with the DDS plugin
# Save as .dds with BC3/DXT5 compression
```

Organize textures in a folder:
```
my_mod_textures/
    sword_diff.dds      # Diffuse/color texture
    sword_norm.dds      # Normal map
    shield_diff.dds
    armor/
        chest_diff.dds
        helmet_diff.dds
```

### Step 2: Create the Package

```powershell
python create_texture_package.py my_mod_textures my_weapons

# Or with custom prefix:
python create_texture_package.py my_mod_textures my_weapons --prefix "mods"
```

This creates:
- `<hash>` - The bundle file (16-character hex name)
- `my_weapons_manifest.json` - Maps texture names to hashes

### Step 3: Install the Bundle

```powershell
# Copy to game contents folder
copy "output_packages\<hash>" "C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\"
```

### Step 4: Load in Lua

```lua
-- In your mod script, load the package:
Game:load_package("resource_packages/custom/my_weapons", true)

-- Textures are now available!
-- Use the hash from the manifest to reference them
```

### Step 5: Use Your Textures

Check the manifest file for texture hashes:

```json
{
  "textures": {
    "custom/my_weapons/sword_diff": {
      "hash_hex": "0x1234567890ABCDEF",
      "hash_dec": 1311768467294899695
    }
  }
}
```

Reference textures by hash in materials or code:

```lua
-- Example: Applying texture to a material
local sword_tex = 0x1234567890ABCDEF  -- From manifest
-- Use with material system
```

### Using the Texture Loader Helper

Copy `texture_loader.lua` to your custom scripts folder and use it:

```lua
local CustomTextures = require("custom/texture_loader")

-- Load your package
CustomTextures:load_package("my_weapons")

-- Get texture hash by name
local hash = CustomTextures:get_texture_hash("custom/my_weapons/sword_diff")

-- Or use precomputed hashes for performance
CustomTextures.TEXTURE_HASHES = {
    ["custom/my_weapons/sword_diff"] = 0x1234567890ABCDEF,
    ["custom/my_weapons/shield_diff"] = 0xFEDCBA0987654321,
}
```

---

## Approach 2: Texture Slot Injection (Recommended)

This approach is more reliable because it uses the proven texture replacement system.

### Concept

Instead of creating new textures, you:
1. Find an existing texture that's unused or unimportant
2. Replace it with your custom texture
3. The texture is now in the game at that hash!

### Step 1: Find a Replacement Candidate

```powershell
python texture_injector.py find-candidates 07c9b8511b5aff2e
```

This shows textures sorted by how many materials use them. Unused textures are best:

```
=== UNUSED TEXTURES (Best candidates) ===

0xABCD1234ABCD1234        11068      128x128      DXT5   0 materials
0xDEADBEEFDEADBEEF        22012      256x256      DXT5   0 materials
```

### Step 2: Prepare Your Replacement Texture

1. Note the target texture's format and size
2. Create your texture in DDS format
3. Name it with the target hash:

```
my_textures/
    abcd1234abcd1234.dds   # Named after the target hash (without 0x)
```

### Step 3: Inject Your Texture

Use the proven replace_textures_v4.py tool:

```powershell
python replace_textures_v4.py "C:\...\Gauntlet\contents\07c9b8511b5aff2e" my_textures/
```

The tool will:
- Auto-detect the bundle type
- Auto-convert your texture to match the original format
- Replace the texture in-place
- Create a backup automatically

### Step 4: Verify

List textures to confirm:

```powershell
python list_textures.py 07c9b8511b5aff2e
```

### Step 5: Use in Materials

Now your texture lives at that hash. To use it:

**Option A:** Modify a material to point to this hash (requires material editing)

**Option B:** Replace a texture that's already used where you want your texture

---

## Recommended Workflow

For most mods, this workflow is recommended:

### For Texture Replacements (Character skins, etc.)

1. Find the texture you want to replace using `extract_textures_named.py`
2. Identify its hash
3. Create your replacement texture
4. Use `replace_textures_v4.py` to inject it

### For Adding New Textures

1. Use `texture_injector.py find-candidates` to find unused slots
2. Pick a slot matching your desired size/format
3. Replace that slot with your texture
4. Modify a material to reference that hash

---

## Tools Reference

| Tool | Purpose |
|------|---------|
| `create_custom_bundle.py` | Create new texture bundles |
| `bundle_database_manager.py` | Manage bundle_database.data |
| `texture_injector.py` | Find texture replacement candidates |
| `replace_textures_v4.py` | Replace textures in bundles |
| `list_textures.py` | List textures in a bundle |
| `extract_textures_named.py` | Extract textures with names |
| `decode_materials.py` | Understand material->texture mapping |

---

## Hash Reference

All resources in Gauntlet are identified by MurmurHash64:

```python
# Python example
from bundle_tools import murmur_hash64

# Your custom texture name
name = "mymod/cool_sword"
hash_value = murmur_hash64(name)
print(f"0x{hash_value:016X}")  # Use this in materials
```

---

## Troubleshooting

### Bundle not loading
- Make sure it's copied to the contents folder
- Try registering it with `bundle_database_manager.py add`
- Verify the bundle format with `list_textures.py`

### Texture not visible in game
- Check the texture format matches (DXT1 vs DXT5)
- Verify dimensions are correct
- Make sure the hash is referenced by a material

### Game crashes
- Restore from .backup files
- Check bundle compression is correct
- Verify DDS headers are valid

---

## File Locations

```
Gauntlet Installation:
  C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\

Contents folder (bundles go here):
  contents\

Bundle database:
  contents\bundle_database.data

Safe bundles to modify (no .stream file):
  07c9b8511b5aff2e  - Menu/UI textures
  07cdebae91f29fae  - Lobby/character textures
  feec2c9522011d13  - Additional textures
```

---

## Example: Complete Mod Workflow

Let's say you want to add a custom sword texture:

```powershell
# 1. Find candidates in the lobby bundle
python texture_injector.py find-candidates 07cdebae91f29fae

# 2. Found unused 128x128 DXT5 at 0xABCD1234DEADBEEF
#    Create your sword texture as 128x128 DXT5:
#    texconv -f DXT5 -m 8 my_sword.png

# 3. Name it with the target hash
#    Rename: my_sword.dds -> abcd1234deadbeef.dds
#    Put in folder: my_textures/

# 4. Inject the texture
python replace_textures_v4.py "C:\...\Gauntlet\contents\07cdebae91f29fae" my_textures/

# 5. Your texture is now in the game at that hash!
#    Modify a material or replace a weapon's texture hash to use it.
```

---

## Advanced: Material Modification

To use custom textures, you often need to modify materials. Materials are stored in bundles with hash `0xEAC0B497876ADEDF`.

See `decode_materials.py` output for material structure:
- Texture slots: diffuse_map, normal_map, specular_map, etc.
- Each slot has a texture hash reference

To change a material's texture reference:
1. Extract the material data
2. Find the texture hash field
3. Replace with your custom texture hash
4. Rebuild the bundle

This is advanced modding and requires understanding the binary material format documented in FINDINGS.txt.
