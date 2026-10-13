# Global Texture Package System for Gauntlet
## Complete Technical Guide with Explanations

> [!WARNING]
> **[!] DEPRECATED / SUPERSEDED (January 9, 2026 content) - HISTORICAL ONLY.**
>
> The "custom texture packages just work" claim on this page was **disproven**
> (July 2, 2026 - FINDINGS #15J) and then **re-solved with specific payload
> requirements** (July 5, 2026 - FINDINGS #16 / `CUSTOM_ASSET_LOADING_FINDINGS.md`).
> A custom bundle containing textures/materials only loads if each resource
> carries its required payload trailer (4-byte texture trailer; unit trailing
> sections + footer material hash).
>
> **Authoritative references:** `FINDINGS.txt` #15J and #16,
> `CUSTOM_ASSET_LOADING_FINDINGS.md`.
>
> **Known broken items in this document (kept for archaeology):**
> - `create_global_package.py` - does NOT exist in this repo.
> - `texture_loader.lua` - does NOT exist in this repo.
> - `add_bundle_to_db.py --verify <hash>` - no such flag (see below).
> - The `Dep Count (4 bytes) = 0` package-entry format - obsolete; the confirmed
>   layout is 28-byte entries + 1-byte `0x01` trailer (FINDINGS #9B).
> - `verify_bundle.py` - parses the OLD 20-byte package format and is stale.
> - `import mmh3` - not installed here; use `bundle_tools.murmur_hash64()`.

**STATUS (original, now outdated): [ok] VERIFIED WORKING (January 9, 2026)**

Custom texture packages successfully load via Lua! Tested with 20 textures.

---

##  TL;DR - Can You Use Textures Globally?

**YES, but with important caveats:**

| What Works | What Doesn't Work | Why |
|------------|-------------------|-----|
| [ok] Loading textures into memory globally | [X] Existing materials auto-using your textures | Materials are pre-compiled with specific texture hashes |
| [ok] Referencing textures by hash anywhere | [X] "Dropping in" a replacement texture file | The engine uses hashes, not file paths |
| [ok] Creating new materials that use your textures | [X] Changing a material's textures without modifying it | Material binary contains hardcoded texture references |
| [ok] Runtime texture swapping via Lua hooks | [X] Simple file replacement like Skyrim mods | Bitsquid doesn't load loose files |

---

##  How the Bitsquid/Stingray Resource System Works

### The Hash-Based System

Unlike games that use file paths (e.g., `textures/sword.dds`), Bitsquid uses **MurmurHash64** for everything:

```
Resource Path: "characters/avatar_warrior/warrior_diff"
                           v
                   MurmurHash64()
                           v
              Hash: 0x67111D9E39E1CABC
                           v
          Stored in bundle as: 67111d9e39e1cabc
```

**Why This Matters:**
- The game NEVER looks for "warrior_diff.dds" on disk
- It looks for hash `0x67111D9E39E1CABC` in loaded bundles
- Two different paths = two different hashes = two different resources
- You can't just rename your texture to match - the hash must match

### The Bundle System

Resources are packed into **bundles** (the hex-named files in `contents/`):

```
Bundle: 0164ad48615ba9ed
+-- Resource 0x67111D9E39E1CABC (texture: warrior_diff)
+-- Resource 0xF8C23D1F8B219C6D (texture: warrior_norm)
+-- Resource 0x03054DB6A1586C9B (material: warrior_material)
+-- Resource 0xAD9C6D9ED1E5E77A (package: level_package)
```

**Key Insight:** A bundle can contain ANY resources. The bundle name is just a hash - it doesn't determine what's inside.

### The Package System

A **package** is a special resource type that lists other resources to load:

```
Package: "resource_packages/characters/warrior"
Contains:
  - texture: "characters/avatar_warrior/warrior_diff"
  - texture: "characters/avatar_warrior/warrior_norm"  
  - material: "characters/avatar_warrior/warrior_material"
  - unit: "characters/avatar_warrior/warrior"
```

When you call `Game:load_package("resource_packages/characters/warrior")`:
1. Engine finds the package resource by its hash
2. Reads the list of resources inside
3. Loads each resource from bundles into memory
4. Resources are now available globally by their hashes

---

##  What "Global" Really Means

### Textures ARE Global (Once Loaded)

```lua
-- Load your custom package
Game:load_package("resource_packages/custom/my_textures", true)

-- Now EVERY system in the game can access your textures by hash
-- The textures exist in the global resource pool
local my_texture_hash = 0x1234567890ABCDEF
```

### But Materials Are Pre-Compiled

Here's the problem. A material file looks like this internally:

```
Material Binary (simplified):
+-----------------------------------------+
| Shader Hash: 0x26FBE7181F811036         |
| Texture Slot 0: 0x67111D9E39E1CABC      |  <- Hardcoded!
| Texture Slot 1: 0xF8C23D1F8B219C6D      |  <- Hardcoded!
| Texture Slot 2: 0x6A77D7C1FF442EE7      |  <- Hardcoded!
| Parameters: [color, roughness, etc.]    |
+-----------------------------------------+
```

The material doesn't say "use warrior_diff" - it says "use texture hash `0x67111D9E...`"

**This is why you can't just "replace" a texture:**
- Your new texture has a DIFFERENT hash (based on its path)
- The material still asks for the OLD hash
- The engine finds the old texture, not yours

---

##  Methods to Use Textures Globally

### Method 1: Create Custom Materials (Recommended)

Create new materials that reference YOUR texture hashes:

```python
# In your package creation tool
def create_custom_material(texture_hashes):
    """
    Create a material that uses your custom textures.
    The material will reference your texture hashes.
    """
    material_data = build_material(
        shader="standard_pbr",
        diffuse_texture=texture_hashes["diffuse"],
        normal_texture=texture_hashes["normal"],
        specular_texture=texture_hashes["specular"]
    )
    return material_data
```

**Pros:** 
- Full control over the material
- Your textures are properly referenced

**Cons:**
- Existing game objects still use old materials
- Need to also modify units to use your materials

### Method 2: Hash Collision (Replace Original)

Make your texture have the SAME hash as the original:

```python
# If you name your texture with the EXACT same path as the original:
original_path = "characters/avatar_warrior/warrior_diff"
original_hash = murmur_hash64(original_path)  # 0x67111D9E39E1CABC

# Your texture in the package uses this path:
my_texture_path = "characters/avatar_warrior/warrior_diff"  # SAME!
my_texture_hash = murmur_hash64(my_texture_path)  # 0x67111D9E39E1CABC - SAME!
```

When both have the same hash, YOUR bundle loads AFTER the game's bundle, your texture overwrites it!

**Pros:**
- Existing materials automatically use your texture
- No Lua hooks needed
- True "drop-in replacement"

**Cons:**
- Only works for replacement, not new textures
- Must match original path exactly
- Bundle load order matters (yours must load last)

### Method 3: Runtime Lua Hooks (Most Flexible)

Hook into the rendering/material system to swap textures at runtime:

```lua
-- Hook material texture assignment
local original_set_texture = Material.set_texture
Material.set_texture = function(material, slot, texture_hash)
    -- Check if this is a texture we want to replace
    local replacement = TEXTURE_REPLACEMENTS[texture_hash]
    if replacement then
        texture_hash = replacement
    end
    return original_set_texture(material, slot, texture_hash)
end

-- Define replacements
TEXTURE_REPLACEMENTS = {
    [0x67111D9E39E1CABC] = 0x1234567890ABCDEF,  -- warrior_diff -> my_texture
}
```

**Pros:**
- Can replace any texture with any other texture
- Dynamic - can change at runtime
- Works with existing materials

**Cons:**
- Requires Lua mod framework
- Performance overhead
- May not catch all texture usage

### Method 4: Boot Package Injection

Add your package to the game's boot sequence so it loads first:

```lua
-- In boot.lua or early initialization
local CUSTOM_PACKAGES = {
    "resource_packages/custom/global_textures",
}

for _, pkg in ipairs(CUSTOM_PACKAGES) do
    if Game:can_load_package(pkg) then
        Game:load_package(pkg, true)
    end
end
```

**Pros:**
- Textures available from game start
- Works with Method 2 (hash collision)

**Cons:**
- Need to modify game boot scripts
- Package must exist in a loadable bundle

---

##  Creating a True Global Texture Package

Here's the complete process:

### Step 1: Decide on Your Approach

| Goal | Best Method |
|------|-------------|
| Replace existing texture (e.g., warrior skin) | Method 2 (Hash Collision) |
| Add new textures for new content | Method 1 (Custom Materials) |
| Dynamically swap textures | Method 3 (Lua Hooks) |
| Both replace and add | Method 2 + Method 1 |

### Step 2: Structure Your Textures

For **replacements** (Method 2), use the ORIGINAL game paths:
```
my_mod/
+-- characters/
|   +-- avatar_warrior/
|       +-- warrior_diff.dds      # Will hash to 0x67111D9E39E1CABC
|       +-- warrior_norm.dds      # Will hash to 0xF8C23D1F8B219C6D
|       +-- warrior_spec.dds      # Will hash to 0x6A77D7C1FF442EE7
+-- equipment/
    +-- warrior/
        +-- weapon01_diff.dds     # Will hash to 0x52A65FAB447503E1
```

For **new content** (Method 1), use your own paths:
```
my_mod/
+-- custom/
    +-- my_textures/
        +-- cool_sword_diff.dds   # Your unique hash
        +-- cool_sword_norm.dds   # Your unique hash
```

### Step 3: Create the Package

```python
# create_global_package.py

from create_texture_package import (
    murmur_hash64, 
    build_bundle, 
    build_package_data,
    compress_bundle,
    TYPE_TEXTURE,
    TYPE_PACKAGE
)

def create_global_package(
    texture_folder: str,
    package_name: str,
    use_original_paths: bool = True  # For Method 2
):
    """
    Create a global texture package.
    
    Args:
        texture_folder: Folder with your DDS textures
        package_name: Name for your package
        use_original_paths: If True, preserves folder structure for hash collision
                           If False, uses custom prefix for new content
    """
    
    if use_original_paths:
        # Method 2: Keep original game paths for replacement
        prefix = ""  # No prefix - use exact game paths
    else:
        # Method 1: Use custom prefix for new content
        prefix = f"custom/{package_name}/"
    
    # ... rest of package creation
```

### Step 4: Install and Load

1. Copy bundle to `Gauntlet/contents/`
2. Create a Lua loader:

```lua
-- custom/global_texture_loader.lua

local GlobalTextures = {}

-- Package info (from manifest)
GlobalTextures.PACKAGE_PATH = "resource_packages/custom/global_textures"
GlobalTextures.PACKAGE_HASH = 0x1234567890ABCDEF

-- Texture registry
GlobalTextures.TEXTURES = {
    -- Replacements (original paths - same hash as game)
    ["characters/avatar_warrior/warrior_diff"] = 0x67111D9E39E1CABC,
    
    -- New textures (custom paths - unique hashes)
    ["custom/global_textures/my_sword_diff"] = 0xABCDEF1234567890,
}

function GlobalTextures:init()
    print("[GlobalTextures] Loading global texture package...")
    
    local success = pcall(function()
        Game:load_package(self.PACKAGE_PATH, true)
    end)
    
    if success then
        print("[GlobalTextures] Package loaded successfully!")
        print("[GlobalTextures] " .. self:count_textures() .. " textures available")
    else
        print("[GlobalTextures] ERROR: Failed to load package")
        print("[GlobalTextures] Make sure bundle is in contents/ folder")
    end
    
    return success
end

function GlobalTextures:count_textures()
    local count = 0
    for _ in pairs(self.TEXTURES) do count = count + 1 end
    return count
end

-- Get a texture hash by name
function GlobalTextures:get(texture_name)
    return self.TEXTURES[texture_name]
end

-- Check if texture is loaded
function GlobalTextures:has(texture_name)
    return self.TEXTURES[texture_name] ~= nil
end

return GlobalTextures
```

---

## [X] Why Certain Things DON'T Work

### "Why can't I just put a DDS file in the game folder?"

Bitsquid doesn't load loose files. It ONLY loads from bundles.

```
What you expect:
  Game checks: "Is there a warrior_diff.dds file?" -> Uses it

What actually happens:
  Game checks: "Is hash 0x67111D9E in any loaded bundle?" -> Uses that
  (Never looks at filesystem for game resources)
```

**Solution:** Pack your texture into a bundle.

---

### "Why doesn't my texture show up even though the package loads?"

Your texture has a different hash than what materials expect.

```
Your texture path: "my_mod/textures/warrior_diff"
Your texture hash: 0xABCDEF123456789

Material expects:  0x67111D9E39E1CABC (the original)
Material gets:     0x67111D9E39E1CABC (finds original in game bundle)
                   ^ Your hash never matched!
```

**Solution:** Use the exact original path (Method 2) or modify materials.

---

### "Why does load order matter?"

When two bundles have the same resource hash, the LAST loaded wins:

```
1. Game loads bundle A with warrior_diff (hash 0x67111D9E)
2. You load bundle B with warrior_diff (hash 0x67111D9E)
3. Memory now has YOUR version (it overwrote the original)
```

But if order is reversed:
```
1. You load bundle B with warrior_diff (hash 0x67111D9E)
2. Game loads bundle A with warrior_diff (hash 0x67111D9E)
3. Memory now has GAME version (it overwrote yours!)
```

**Solution:** Load your packages AFTER the game's core packages.

---

### "Why can't I replace just the texture without a package?"

The bundle system is monolithic. You can't "patch" a single resource.

```
Bundle contains:
+-- texture A
+-- texture B
+-- material C
+-- package D

You can't say "just replace texture A" - you need a whole bundle
that contains your texture A, and it needs to load after the original.
```

**Solution:** Create a small bundle with just your textures + a package.

---

### "Why do materials reference textures by hash instead of name?"

Performance and reliability:
1. Hash comparison is O(1) - instant lookup
2. No string parsing at runtime
3. No filesystem access
4. Consistent across platforms (no path separator issues)
5. Smaller memory footprint (8 bytes vs variable-length string)

**This is by design, not a limitation.**

---

### "Can I create a material that uses ANY texture at runtime?"

Partially. You can:
- Create materials at edit-time with specific texture hashes
- Use Lua hooks to redirect texture lookups at runtime

You cannot:
- Modify a compiled material's texture references directly
- Create entirely new materials at runtime (no material compiler in-game)

---

##  Testing Your Global Package

### Test Script
```lua
-- test_global_textures.lua

local function test_package()
    local pkg = "resource_packages/custom/global_textures"
    
    print("=== Global Texture Package Test ===")
    
    -- Test 1: Can we load the package?
    print("\n[Test 1] Loading package...")
    local load_success = pcall(function()
        Game:load_package(pkg, true)
    end)
    print(load_success and "  PASS: Package loaded" or "  FAIL: Package not found")
    
    if not load_success then
        print("\nDEBUGGING:")
        print("  1. Is the bundle file in Gauntlet/contents/?")
        print("  2. Is the bundle filename the package hash?")
        print("  3. Does the bundle contain a package resource?")
        return
    end
    
    -- Test 2: Can we reference a texture?
    print("\n[Test 2] Checking texture availability...")
    local test_hash = 0x67111D9E39E1CABC  -- warrior_diff
    -- Note: There's no direct "does texture exist" API
    -- You'd need to try using it and catch errors
    print("  INFO: Texture hash registered: 0x" .. string.format("%016X", test_hash))
    
    -- Test 3: Package stays loaded?
    print("\n[Test 3] Package persistence...")
    print("  INFO: Package should remain loaded until explicitly unloaded")
    
    print("\n=== Test Complete ===")
end

return test_package
```

### Verifying Hash Collision Worked

```lua
-- If using Method 2 (replacement), verify the original is replaced
-- by checking if the texture looks different in-game

-- You can also add a subtle marker to your textures
-- (e.g., a 1-pixel colored dot in corner) to confirm they're loading
```

---

##  Complete Example: Replacing Warrior Textures

### 1. Prepare Your Textures

```
warrior_reskin/
+-- characters/
    +-- avatar_warrior/
        +-- warrior_diff.dds    # 512x512 DXT1 - Your new diffuse
        +-- warrior_norm.dds    # 512x512 ATI2 - Your new normal
        +-- warrior_spec.dds    # 256x256 DXT1 - Your new specular
```

**Important:** Folder structure MUST match original exactly!

### 2. Create the Package

```bash
python create_texture_package.py warrior_reskin warrior_reskin --prefix ""
```

Using `--prefix ""` ensures paths match originals for hash collision.

### 3. Check the Manifest

```json
{
  "textures": {
    "characters/avatar_warrior/warrior_diff": {
      "hash_hex": "0x67111D9E39E1CABC",  // Must match original!
      "original_file": "warrior_diff.dds"
    }
  }
}
```

### 4. Verify Hashes Match

```python
# Verify your hashes match the game's
EXPECTED_HASHES = {
    "characters/avatar_warrior/warrior_diff": 0x67111D9E39E1CABC,
    "characters/avatar_warrior/warrior_norm": 0xF8C23D1F8B219C6D,
    "characters/avatar_warrior/warrior_spec": 0x6A77D7C1FF442EE7,
}

for name, expected in EXPECTED_HASHES.items():
    actual = murmur_hash64(name)
    match = "[ok]" if actual == expected else "[X]"
    print(f"{match} {name}: 0x{actual:016X}")
```

### 5. Install

```powershell
copy warrior_reskin_bundle "C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\"
```

### 6. Load (in your mod's init)

```lua
-- Load early in boot sequence
Game:load_package("resource_packages/warrior_reskin", true)
-- That's it! Warrior now uses your textures everywhere
```

---

##  Integration with Custom Mod Framework

If you're building a larger mod framework:

```lua
-- mod_framework/resource_manager.lua

local ResourceManager = {
    loaded_packages = {},
    texture_overrides = {},
}

function ResourceManager:load_texture_pack(name, is_replacement)
    local path = "resource_packages/custom/" .. name
    
    if self.loaded_packages[path] then
        return true  -- Already loaded
    end
    
    local success = pcall(function()
        Game:load_package(path, true)
    end)
    
    if success then
        self.loaded_packages[path] = {
            name = name,
            is_replacement = is_replacement,
            load_time = os.time()
        }
    end
    
    return success
end

function ResourceManager:register_texture_override(original_hash, new_hash)
    self.texture_overrides[original_hash] = new_hash
end

function ResourceManager:get_texture(hash)
    return self.texture_overrides[hash] or hash
end

return ResourceManager
```

---

##  Summary: Global Texture Availability

```
+-----------------------------------------------------------------+
|                    GLOBAL TEXTURE SYSTEM                        |
+-----------------------------------------------------------------+
|                                                                 |
|  +--------------+                                               |
|  | Your Bundle  | --- contains ---> [Textures] + [Package]       |
|  +--------------+                                               |
|         |                                                       |
|         | copied to                                             |
|         v                                                       |
|  +------------------+                                           |
|  | Gauntlet/contents|                                           |
|  +------------------+                                           |
|         |                                                       |
|         | Game:load_package()                                   |
|         v                                                       |
|  +------------------+                                           |
|  | Resource Memory  | <-- Textures now GLOBALLY available       |
|  | (Hash -> Data)    |     by their hash values                  |
|  +------------------+                                           |
|         |                                                       |
|         | Materials request texture by hash                     |
|         v                                                       |
|  +------------------+                                           |
|  | Rendering System |                                           |
|  |                  |                                           |
|  | - If hash matches| --- Your texture is used! ---------------->|
|  |   yours, uses it |                                           |
|  |                  |                                           |
|  | - If hash differs| --- Original game texture used ----------->|
|  |   finds original |                                           |
|  +------------------+                                           |
|                                                                 |
+-----------------------------------------------------------------+
```

---

##  Key Takeaways

1. **Textures ARE global** once their package is loaded
2. **Hash matching is everything** - same path = same hash = replacement works
3. **Load order matters** - load your packages AFTER game packages for overrides
4. **Materials are the bridge** - they connect units to textures via hashes
5. **Bundle everything** - the engine only loads from bundles, not loose files
6. **Keep your manifest** - you need those hashes for Lua code

---

##  Troubleshooting Guide (Lessons Learned)

### Problem: Game Freezes When Loading Package

**Symptoms:**
- Game hangs on `ResourcePackage.load()` or `ResourcePackage.flush()`
- No error messages, just infinite hang

**Root Cause:** Package entries had `deps=2` format (two dependency hashes) but the engine couldn't find the referenced resources.

**Solution (corrected):** There is no `Dep Count` field. Package entries are
**28 bytes** with a 1-byte `0x01` trailer after the last entry (FINDINGS #9B):
```
Package Entry Format (CONFIRMED):
+-- Type Hash  (8 bytes) - MurmurHash64 of the type name
+-- Name Hash  (8 bytes) - MurmurHash64 of the resource path
+-- c1         (4 bytes) - ALWAYS 2
+-- c2         (4 bytes) - per-package constant; 0 is safe for custom bundles
+-- name_hi32  (4 bytes) - upper 32 bits of name_hash
then a single 0x01 trailer byte after the final entry
```

**Why This Works:** Textures are self-contained resources. They don't depend on other resources to load. The dependency system is for load ordering - telling the engine "load X before Y". For standalone textures, there are no dependencies.

---

### Problem: Bundle Not Found by Engine

**Symptoms:**
- `Application.can_get_resource()` returns false
- `Application.resource_package()` fails or returns nil
- Package path that should exist is not recognized

**Root Cause:** Bundle not registered in `bundle_database.data`.

**Solution:** Add bundle to database with correct format:
```
Entry Format:
+-- Bundle Name (variable length string, null terminated)
+-- Stream Name (variable length string, null terminated)  
+-- Entry Count (4 bytes, little-endian)
+-- NULL BYTE (0x00) - CRITICAL! Must end each entry
```

**Critical Bug We Fixed:** When parsing existing entries, must skip the null byte after stream_name:
```python
# WRONG - causes offset drift
offset = end_of_stream_name

# CORRECT - skip null terminator
offset = end_of_stream_name + 1  # Skip 0x00 after stream_name
```

---

### Problem: Package Path Hash Mismatch

**Symptoms:**
- Bundle exists in database but can't be loaded
- Hash in bundle doesn't match expected path

**Solution:** Ensure consistent path normalization:
1. Use forward slashes: `resource_packages/custom/global_textures`
2. No leading slash: NOT `/resource_packages/...`
3. No file extension: NOT `global_textures.package`
4. Lowercase everything for consistency

**Verify with:**
```python
# Requires `bundle_tools.py` (same folder) - mmh3 is NOT installed here.
from bundle_tools import murmur_hash64
path = "resource_packages/custom/global_textures"
hash_value = murmur_hash64(path)
print(f"0x{hash_value:016X}")  # Should match bundle filename
```

---

### Problem: Bundle Structure Invalid

**Symptoms:**
- Game crashes on load
- Resources don't appear even after successful package load

**Bundle Format Checklist:**
```
[ok] Signature at offset 0: 0xF0000004 (little-endian)
[ok] Resource count follows signature
[ok] Name hash table follows count (8 bytes per resource)
[ok] Entry table follows name hashes
[ok] For <=31 resources: pad to offset 0x104 before entries
[ok] For >31 resources: entries immediately follow name hashes
[ok] Each entry: type_hash(8) + name_hash(8) + size(4) + stream_size(4) + padding(16) + data(size)
[ok] Entries use zlib compression in 64KB chunks
[ok] Empty .stream file must exist alongside bundle
```

---

### Verification Commands

**Check if bundle is registered:**
```python
# add_bundle_to_db.py takes the bundle name as a POSITIONAL arg (there is no --verify flag):
python add_bundle_to_db.py d5ec4eb9fc5f3c88 --dry-run
```

**Verify bundle structure:**
```python
# NOTE: verify_bundle.py still parses the OLD 20-byte package format and is STALE.
# Prefer list_textures.py or replace_textures_v4.py's parse_bundle (authoritative):
python list_textures.py d5ec4eb9fc5f3c88
```

**Test in-game via Lua:**
```lua
-- In game console or script
print("Can load: " .. tostring(Application.can_get_resource("package", "resource_packages/custom/global_textures")))
```

---

##  Complete Workflow Summary

```
1. CREATE BUNDLE
   +-- python create_texture_package.py
       +-- Reads DDS textures from input folder
       +-- Computes MurmurHash64 for each
       +-- Creates package resource (28-byte entries + 0x01 trailer)
       +-- Compresses data in 64KB chunks
       +-- Outputs: bundle file + manifest.json

2. REGISTER IN DATABASE  
   +-- python add_bundle_to_db.py
       +-- Parses existing bundle_database.data
       +-- Adds new entry with null terminators
       +-- Rewrites database file

3. INSTALL FILES
   +-- Copy to Gauntlet/contents/
       +-- d5ec4eb9fc5f3c88 (bundle file)
       +-- d5ec4eb9fc5f3c88.stream (empty file)

4. LOAD VIA LUA
   +-- In-game script calls:
       local pkg = Application.resource_package("resource_packages/custom/global_textures")
       ResourcePackage.load(pkg)
       ResourcePackage.flush(pkg)
       
5. TEXTURES NOW GLOBAL!
   +-- Any material referencing same path/hash will use your textures
```

---

*This document explains the Bitsquid/Stingray resource system as used by Gauntlet. The same principles apply to Vermintide, Helldivers 2, and other Stingray-engine games.*

**Document last verified working: January 9, 2026**
