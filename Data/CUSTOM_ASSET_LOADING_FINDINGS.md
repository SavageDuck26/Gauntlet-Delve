# Gauntlet Custom Asset Loading - SOLVED

**Engine:** Gauntlet: Slayer Edition - Bitsquid / Autodesk Stingray (2015 build).
`gauntlet.exe` PE32, ImageBase `0x400000`.
**Goal:** load a custom model (crane) with a custom texture (checker) + custom
material, **without overriding** any native game asset.

**Status: * SOLVED 2026-07-05 * - full custom chain confirmed in-game:** custom
unit spawned and rendered with a custom material bound to a custom novel-hash
texture (magenta/cyan checker visible on the crane). Zero native overrides.
**See #10 for the complete working recipe.** Sections 1-9 are the historical
investigation (several of their conclusions are now known to be wrong - each is
annotated).

**The three real root causes (none of which was the novel hash):**
1. **Texture:** compiled texture resources need a **4-byte trailer** after the
   full mip chain. Ours omitted it -> GPU bring-in never completed -> stall/hang.
2. **Unit:** units need their **trailing sections** (collision actors, flow data,
   and a 32-byte footer). Our from-scratch builder emitted only the mesh -> the
   engine walked off the end -> native crash.
3. **Material binding:** a unit binds its material via the **footer hash** in its
   trailer, not the in-mesh material name string (that's just a slot label).

---

## 1. What actually works vs. what doesn't

| Thing | Result | Notes |
|---|---|---|
| Custom **unit** (novel hash `units/custom/crane_test/crane`) | [ok] loads + spawns | Units are CPU-only resources; they register and complete fine from a runtime-loaded bundle. |
| **Native-hash texture override** (ham_diff, `gameobjects/food/ham_diff`) | [ok] onlines + renders | `replace_textures_v4.py` in-place DDS swap = 100% reliable. Works because the hash is *already registered* by the base game at boot. |
| Custom **novel-hash texture** (`custom/crane_test/crane_diff`) | [X] never completes | File reads fully (`loaded==size`) but package never onlines. |
| Custom **novel-hash material** (`materials/m_crane_custom`) | [X] crashes or never completes | Hand-cloned from native `m_ham`. |

**The wall:** a *novel* (brand-new) texture/material hash never posts its
"completed" message during bring-in, so `has_loaded()` stays false forever.
A *native* hash (even with our custom bytes) works because its render-side slot
already exists.

---

## 2. Reverse-engineered loading mechanism (from `gauntlet.exe`)

Addresses are `ImageBase 0x400000`. Harness: capstone+pefile, `scratchpad/reutil.py` ([!] the `scratchpad/` harness is NOT present in this repo - historical reference only).

- **`PackageManager` (Lua, `package_manager.lua`)**: `load_package(path, flush)`.
  `is_package_online = package_infos[path] and not loading[path]`. `loading[path]`
  is cleared only when `ResourcePackage.has_loaded()` returns true (in `update`).
- **`ResourcePackage.has_loaded` @0x638240**: true only if *every* resource's
  `is_loaded` (`0x637a60`) is true. Per resource: state `[+0x38]==2/3`, **or** the
  loader progress counter `[loader+0x50] > resource.index [+0x3c]`.
- **Progress counter** `[loader+0x50]` advances **only** when the loader worker
  posts an **opcode-1 "completed" message** (`process-one` @0x635f80:
  `if msg[0]==1: inc [loader+0x50]`).
- **`ResourcePackage.flush` @0x6381f0** -> per-resource `0x6361f0`, a **busy-wait**
  that `WaitForSingleObject(sem, INFINITE)` until the worker posts that resource's
  completion. **If the completion never comes, the main thread hangs forever.**
- **Availability lookup** `0x635e80` -> hashmap at `[loader+0x48]` keyed by
  `(type, name, property@+0x68)`. On package load, `0x637aa0` looks up each
  resource here; a miss logs `"Failed loading %s named %s"` (a **release stub** at
  `0x4f9a60` - silent) and **skips** the resource.
- **Worker thread**: created @0x632480, proc `0x633100` -> loop `0x632a70`, dispatch
  `0x64fad0`/`0x64f5a0`. Producer/consumer via `EnterCriticalSection`/
  `WaitForSingleObject(INFINITE)`/`ReleaseSemaphore` (imports at
  `0x74611c/0x746120/0x7461cc/0x7461c8`).
- **`bundle_database.data`**: flat rows `{flags, bundle_hash, stream_name}` - it
  carries **no resource identities** (type/name). Rows-per-bundle != bundle's
  resource count (food_units: 189 DB rows vs 50 TOC resources), so the engine reads
  the resource count from the **bundle's own TOC header**, not the DB.

**Consequence:** for *textures/materials* the completion is posted after a
render-side (GPU) bring-in. Novel hashes never get that completion. CPU resources
(units) complete on the worker thread directly, which is why units work.

---

## 3. Bundle format (verified against working native bundles)

`replace_textures_v4.py:parse_bundle` is the authoritative parser (works 100% on
native textures):

```
[0:4]      u32 count
[4:0x104]  256-byte header region (native: non-zero; our hand-built: zeros - both accepted)
[0x104 ...]  TOC: count x { u64 type_hash, u64 name_hash }
[...]        resources, CONSECUTIVE, each:
             { u64 type, u64 name, u32 flags, u64 stream_size, u32 main_size, u32 unk }  (36-byte header)
             + main_size bytes of data      (textures/materials = raw DDS / material blob at offset 0)
```

- Resources are packed **back-to-back with NO alignment padding** (an earlier
  memory note claiming "4-byte alignment" was WRONG and caused a real bug - see 4f).
- Last zlib chunk in native bundles **is** zero-padded to 64 KB; header
  `uncompressed_size` = real (unpadded) length (so decompressed length can exceed it).
- Our texture-only bundle came out **byte-structurally identical** to the working
  ham bundle (same `count`, `is_simple`, `flags=1`, `stream_size=0`, `unk=0`, DDS
  data) - the **only** difference being native vs novel name hash.

---

## 4. Every approach tried, and why it failed

### a) Boot-overlay sync load (`[BootOverlay] Enabled=true`)
**Failed: deadlock.** Boot-phase load flushes synchronously at the boot barrier;
`state_splash.lua` also does its own sync flush -> collision/deadlock. Also
fundamentally, sync flush = infinite `WaitForSingleObject` (see #2).

### b) Load at main menu, async (`load_package(pkg, false)`)
**Failed: never completes.** The idle main menu doesn't pump background streaming;
loaded bytes freeze partway (native packages froze too - the menu test was
confounded). Confirmed via instrumentation: `loaded < size`, never onlines.

### c) Load at main menu, sync flush (`load_package(pkg, true)`) - the "ham recipe"
**Partial.** ham (1 tiny texture, native hash) onlines. The crane **hangs**: sync
flush busy-waits `WaitForSingleObject(INFINITE)` for a completion the novel
texture/material never posts -> hard hang, no crash, no log.

### d) Load during the level LOAD SCREEN (`StateLoadGame.on_enter`, async)
**Failed: never completes.** Instrumented result: `loaded=273294 / 273294,
online=false, loading=true` for 900+ frames. The file reads **fully** but the
per-resource bring-in never completes. Rules out: streaming pump, shader context,
multi-chunk - all present here, still stalls.

### e) Deferred load (wait for `are_all_packages_online(COMMON+AVATAR)` then load)
**Failed: crash then stall.** Concurrent load initially crashed (that was the bad
dependency, #4g). After fixing, still stalls like (d).

### f) Bundle structure fixes (dependency + alignment)
- **Bad package dependency:** the package resource listed the material's dep as a
  garbage hash (`0xe9a7453f9fcb18cc`, hand-copied) -> native segfault on bundle
  parse. **Fixed** by matching native convention: materials declare `depcount=0`
  (verified across 81 native bundles). Removed the crash, not the stall.
- **Alignment padding:** we had inserted 4-byte padding between resources; native
  bundles do not. **Fixed** (pack consecutively). Did **not** fix the stall - the
  texture-only bundle was already structurally identical to ham.

### g) Wrong-field / hook wiring bugs (fixed, not root causes)
- `Mods.hook:set("Game.update", ...)` at mod-load time -> `could not resolve target`
  because `Game` doesn't exist yet. Must hook `require` first, then install
  `Game.update`/`ScreenMainMenu.update`/`StateLoadGame.on_enter` once their chunk
  has run (the pattern every other mod uses).
- Inline `open(ini,"w").write(open(ini).read()...)` truncated `bundle.ini` to empty
  (loader then skips the bundle). `manifest.json` is load-bearing: the C++ loader
  skips a bundle if `manifest.json.resource_count` / `package_path` disagree with
  `bundle.ini`.

### h) HD2-style injection into a native bundle (`food_units`)
The community model (HD2 patches the base archive; VMB-compiled mod bundles are
loaded through the indexing path). We appended our unit+texture+material into
`resource_packages/food_units` (a `COMMON_GAME_PACKAGE` loaded every boot),
bumped its TOC count 50->53.
- **All three resources:** native **crash** during bring-in (material/unit).
- **Texture only (50->51):** **no crash, but the game HANGS.** food_units now
  contains our novel texture, which never completes -> food_units never onlines ->
  the boot sequence waits on `are_all_packages_online(COMMON)` **forever**.
- **Conclusion:** being inside an indexed, engine-loaded, at-boot native bundle
  does **not** make a novel-hash texture complete. **Placement is not the problem.**
  This is the strongest evidence that the blocker is render-side completion tied to
  the hash, not bundle registration/indexing.

---

## 5. What the same-engine communities do (VMF / Helldivers 2)

- **Vermintide (VMB/VMF):** custom textures load because the **Vermintide Mod
  Builder runs the real Stingray data compiler** and the bundle is loaded through
  the game's mod path that indexes new resources. For materials they **don't author
  custom ones** - **Material-Hijack** hooks unit spawns and calls
  **`Material.set_texture()` at runtime** on the instance, reusing an in-game
  material. (github.com/dalokraff/Material-Hijack)
- **Helldivers 2:** modders **patch the base archive** (`....patch_N` +
  `.gpu_resources` + `.stream`); GPU/texture data lives in the separate
  `.gpu_resources` section. New resources are added *into* the indexed archive set.
- **Takeaway:** neither community hand-rolls a standalone novel GPU resource and
  expects it to complete. They either (a) run the SDK compiler, or (b) reuse a
  native material and swap texture data at runtime, or (c) patch the base archive
  with a proper GPU-resource section.

---

## 6. Leading hypothesis for the wall

Novel-hash **GPU resources** (textures, materials) never post their opcode-1
completion because the render device only has resource slots for hashes present
when its resource database was built (base-game data at boot). A runtime-added
novel hash has no render slot, so the GPU bring-in never finalizes -> no completion
-> `has_loaded` false -> stall (or hang if something waits on it). Units are CPU-only
and don't need this. Native-hash overrides reuse the existing slot.

**Not yet found:** the code that *inserts* into the render-side slot table, i.e.
how a native texture's slot is created at boot. Patching that for our hashes is the
untried "proper" fix but requires more RE (the insert side of `[loader+0x48]` and
the RenderDevice per-type resource arrays).

---

## 7. Viable directions (not yet done)

1. **Render-slot RE:** find where native textures get their render-side
   registration at boot and replicate it for our hashes (deepest, most general).
2. **SDK-equivalent compilation:** produce a properly *compiled* Stingray texture
   resource (the `.gpu_resources`/stream split HD2 uses) rather than inline raw DDS.
3. **Material-Hijack style, but the texture problem remains:** a runtime
   `Material.set_texture` needs the custom texture *loaded*, which is the exact thing
   that stalls. Only viable once a novel texture can complete.
4. **Pragmatic fallback (works today):** ship the custom crane **unit** (loads
   fine) and give it a **native** material; put the checker into a **native texture
   hash** via `replace_textures_v4` (in-place). This renders but *does* override one
   native texture - contrary to the "no override" goal.

---

## 8. Key files / addresses

- Bundle tooling: `replace_textures_v4.py` (authoritative parser/compressor),
  `bundle_tools.py`, `add_bundle_to_db.py`.
- Crane assets: the crane test mod (unit `Medieval_Crane.unit`, `build/checker_diff.dds`,
  `build/m_crane_custom.material`).
- Loader: the loader's `bundle_manager.cpp` (manifest validation, DB patch,
  contents/ copy).
- exe: flush `0x6381f0`, has_loaded `0x638240`, per-resource wait `0x6361f0`,
  process-one `0x635f80`, availability `0x635e80`->`0x632730` (`[loader+0x48]`),
  package load `0x638270`->`0x637aa0`, worker `0x632480`/`0x633100`/`0x632a70`.
- Native texture hashes proven to work: `gameobjects/food/ham_diff`
  `0xdca96153a4ee0ccf`. food_units bundle `cd241d5192024482` (50 resources).

---

## 9. Leading hypothesis REVISED (2026-07-05): the wall is the MIP CHAIN, not the hash

Fresh RE + byte-level comparison suggests the "novel-hash GPU resources have no render
slot" theory (#6) is probably **wrong**, and the real blocker is that our custom
texture ships **only 1 mip level** while the engine expects/brings-in a full chain.

### Evidence
- **Byte diff (both decompressed, raw DDS at `offset+36` - wrapper format identical):**
  our checker = **128x128 DXT5, `mipMapCount=1`**; native ham = 256x256, `mipMapCount=9`.
  Our DDS sets the `DDSD_MIPMAPCOUNT` flag (`0xA1007`) but provides only the top mip.
- **0 of 23** native food_units textures are 1-mip. Every one carries the full chain
  (`mips = floor(log2(max(w,h)))+1`); even a 4x4 has 3 mips, a 128x128 has 8.
- **"Native override works" is confounded.** `replace_textures_v4.convert_to_dxt5`
  forces `orig_header.mip_count`, so *every* successful override already had a full
  chain. Novel-vs-native hash was never isolated from full-chain-vs-1-mip.
- **The #4h food_units hang refutes the registration/skip theory.** The load gate
  (`0x637aa0`) *skips* on an availability miss (release-stub log `0x4f9a60`) - a skip
  would let food_units online *without* the texture, i.e. **no hang**. It hung ->
  the texture **was queued and the worker never posted opcode-1 completion** -> a
  worker/bring-in (bytes) problem, which is where mip handling lives. Not a miss.
- Units (novel hash) complete because they're CPU-only - no mip bring-in. The novel
  hash is a red herring shared by the resources that *succeed*.

Plausible mechanism: texture bring-in signals completion per-mip (or sizes the read
from the full chain) and waits on mips that never arrive -> completion never posted ->
`has_loaded` false forever = the exact stall in #4c/#4d/#4h.

### Load-gate RE (new, verified)
- `0x638270` package.load -> iterates per-type resource **groups** `pkg[+0x40][i]`
  (`count pkg[+0x38]`); each group: `+0x30`=ResourceManager, `+0x34`=type,
  `+0x40`=res count, `+0x48`=entry array (stride `0x48`), `+0x50`=bypass ptr.
- `0x637aa0` per group: for each resource, if `grp[+0x50]==0` do avail-lookup
  `0x635e80`->`0x632730` (virtual, `[loader+0x48]` resource-DB); **miss -> skip+log**,
  **hit -> enqueue** `0x636480`. If `grp[+0x50]!=0`, enqueue unconditionally.
- `0x636480` looks up the **type handler** (`[loader+0x64]`, stride 0x80) and pushes
  the load request to the worker queue. So a resource that passes the gate *is* queued.
- Package-resource blob format (verified): `u32 entry_count` then
  `{ u64 type, u64 name, u32 dep_count[+deps] }` per entry, then trailing `u8` flag.
  **A package onlines only when every listed entry completes** - so a texture-only
  test MUST rebuild the package blob to list *only* the texture (else it waits on
  material/unit that aren't in the bundle - an independent hang).

### Fix applied + test staged
- Root defect in the crane mod's `build/checker_diff.dds`: built with `mip_count=1`.
- Generated `build/checker_diff_mips.dds` - 128x128 DXT5, **full 8-mip**
  magenta/cyan checker (byte-exact full-chain size, verified).
- Installed test bundle `mods/bundles/CraneTexTest/5bfdd50f98f5d0d9` was already a
  clean texture-only isolation (package lists exactly the 1 texture). Swapped its
  texture data 1-mip->8-mip in place (backups: `*.pre_mipfix`), manifest size->22000.
- **To test:** `mv bundle.ini.disabled bundle.ini`, launch, trigger the crane_test
  load (menu sync-flush path, #4c). Onlines => mips were the wall => regenerate unit
  textures + material with full chains. Still hangs => build control (novel name +
  ham's exact 9-mip body) to finally pin hash-vs-bytes before any render-slot RE.

**[POSTSCRIPT: the 8-mip checker still hung - mips alone were NOT the fix. The
control test (ham's body under our novel hash) ONLINED, disproving the novel-hash
theory and proving the wall was our texture bytes. The missing piece was the
4-byte trailer - see #10.]**

---

## 10. * THE COMPLETE WORKING RECIPE (2026-07-05, all confirmed in-game) *

End state achieved: `resource_packages/custom/crane_a` (package + custom unit +
custom texture) and `resource_packages/custom/crane_b` (package + custom material)
both online; `spawn_unit("units/custom/crane_test/crane")` renders the crane with
the magenta/cyan checker via the custom material. No native asset overridden.

### 10.1 Texture resource format (root cause #1: the 4-byte trailer)

A compiled Stingray texture resource (bundle `data` field, `stream_size=0`) is:

```
[128-byte DDS header][full mip chain, top mip -> 1x1][4-byte trailer]
```

- **The 4-byte trailer is MANDATORY.** All 23 food_units textures have exactly
  +4 bytes after the computed mip chain (values seen: `00000000`, `4a07531f`,
  `be0fc23f` - `00000000` works). Without it the loader worker never posts the
  opcode-1 completion -> `has_loaded` stays false -> package never onlines, and a
  flush/level-load waiting on it hangs. **This was "the wall" all along.**
- DDS header must match native conventions: flags `0x000A1007`
  (CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE), caps1 `0x401008`
  (COMPLEX|MIPMAP|TEXTURE), pitchLinear = top-mip linear size, pf_flags `0x4`
  (FOURCC), fourcc DXT1/DXT5/ATI2.
- **Full mip chain required by convention**: every native texture has
  `mips = floor(log2(max(w,h)))+1`. (A 1-mip texture also hangs; 8-mip without
  the trailer still hangs - the trailer is the decisive part, ship both.)
- Native textures carry an NVTT signature in the DDS reserved area
  (`[60:64]='UVER'`, `[68:72]='NVTT'`, `[72:76]=00010200` = v2.1.0). Not
  sufficient by itself; include it to stay native-identical.
- Our hand-rolled DXT1 encoder's pixel data is accepted fine (checker renders).

### 10.2 Unit resource format (root cause #2: trailing sections)

A native `.unit` is `[mesh section][trailing sections ~2KB][32-byte footer]`:

- Mesh section (what `gltf_to_unit.py` produces): sig `0x00010090`, mesh count,
  vertex buffer, elements, index buffer, shapes, bbox, then
  `material_count x {u32 len, name string}` - the strings are **slot labels
  only** (natives use short names like `m_ham`).
- Trailing sections (what our builder omitted): collision/physics actors
  (`a_collision`), FlowCallbacks data, sub-resource hash refs
  (`{u64 hash, ffffffff}`...). **A unit without these loads (bring-in is a CPU
  copy) but CRASHES natively at the later resolve/patch stage.**
- **Footer (last 32 bytes): `04000000` + 12 zero bytes + `u64 material_resource
  name-hash` + 8 zero bytes.** This hash IS the material binding (root cause #3):
  patch `unit[len-16:len-8]` to bind a different material. Every native unit ends
  in zeros - a unit ending mid-string is malformed.

**Working build path:** `glb_to_template_unit.py <native_template.unit>
<mesh.glb> <out.unit> [scale] [material_label]` - splices your geometry into a
native unit and preserves the template's trailer verbatim; then patch the footer
hash to your material. Template used: ham_plate unit (`0x8aeed77b10003a6c`,
8660 B, trailer 2134 B) from food_units. Pick a template whose material/shader
matches your needs (its physics/collision come along for the ride).

### 10.3 Material resource (needed NO format fix)

- Our material was a byte-clone of the template unit's own native material
  (ham_plate's, 460 B, shader id `0xcf752a73093fc934` at offset 8) with the
  **diffuse texture slot hash at offset 276** remapped to the custom texture.
  Slots at 288 (normal) / 300 (spec) left pointing at native ham textures.
  It onlined unmodified - materials have no trailer quirk. Head format:
  `0a000000` + u32 count + u64 shader id + ...float params.
- Cloning the *template unit's own* material guarantees shader/vertex-format
  compatibility with the spliced mesh.
- **Naming convention:** native material resources are named by their unit's
  path (`gameobjects/food/ham_plate` names both the unit and its material).
  A custom path (`materials/m_crane_custom`) works fine - the binding is the
  unit footer hash, nothing parses the path.

### 10.4 Package + bundle structure

- Package resource blob: `u32 count` + count x `{u64 type_hash, u64 name_hash,
  u32 depcount=0}` + trailing byte `0x01`. Materials/textures/units all declare
  depcount=0 (natives do).
- Bundle: `u32 count`, 256-byte header region (zeros OK), TOC `countx{type,name}`,
  then resources back-to-back, each `{u64 type, u64 name, u32 flags=1,
  u64 stream_size=0, u32 main_size, u32 unk=0}` + data. NO alignment padding.
  Multi-chunk zlib, 64 KB uncompressed chunks. `replace_textures_v4.py`
  (`parse_bundle` / `rebuild_simple_bundle` / `compress_bundle`) is the
  authoritative tooling.
- Install: `mods/bundles/<Mod>/{<hash>, <hash>.stream (empty ok), bundle.ini,
  manifest.json}` where `<hash>` = murmur64A(package path). bundle.ini
  ResourceCount and manifest resource_count/package_path MUST agree or the C++
  loader skips the bundle. Loader copies to `contents/<hash>` at boot.
- A package onlines only when EVERY resource in its blob completes - keep test
  packages minimal to isolate failures.

### 10.5 Loading method

- **Always async** (`Game:load_package(path, false)`). flush=true blocks the
  main thread on a worker completion (`WaitForSingleObject INFINITE`) - any
  problem = permanent freeze (#4c).
- Load screen (`StateLoadGame`) pumps the streamer and is the natural place
  (hook `on_enter`, poll in `pre_update` - install hooks via a `require` hook,
  and use `rawget(_G,"StateLoadGame")`: strict.lua throws on undeclared reads).
  **In-gameplay async loading also completes fine** (`Game.update` pumps
  `package_manager:update()` every frame - the crane_b material was loaded
  mid-gameplay). The idle MAIN MENU does not pump (#4b) - avoid it.
- `Game:is_package_online(path)` nil = never requested, false = loading,
  true = online. Spawn only when online.

### 10.6 Why every earlier theory was wrong (for posterity)

- **"Novel hashes have no render slot" (#6): WRONG.** Ham's exact texture bytes
  under a novel hash onlined instantly. Nothing needs registering at boot.
- **"Mip count was the wall" (#9): PARTIAL.** Full chain is the native norm, but
  the 8-mip checker still hung without the trailer.
- **"Placement/indexing matters" (#4h): WRONG-ISH.** The food_units injection
  hung because the injected texture lacked the trailer, not because of placement.
- **The great confound:** overriding a NATIVE hash "works" because the engine
  reuses the already-resident boot copy - your bytes never go through bring-in.
  So byte-level format bugs stayed invisible until a truly novel resource forced
  a real bring-in. (Also why the magenta ham override "onlined but didn't change
  appearance".)
- Debugging method that finally cracked it: **swap known-good native bytes under
  the novel name (isolates name vs bytes), then binary-search the byte diff**
  (header vs pixels vs trailer). And byte-diff EVERYTHING against natives:
  all three root causes were visible as plain byte differences.

### 10.7 Current live artifacts

- `mods/bundles/CraneA/d9341afba97a8158` - pkg `resource_packages/custom/crane_a`
  + unit `units/custom/crane_test/crane` (`0x825f664e8e6c7eb8`, template-spliced,
  footer->`0xda9a7e147dbaa1e0`) + texture `custom/crane_test/crane_diff`
  (`0x9fcb18ccc16a2347`, 256x256 DXT1 9-mip checker + trailer).
- `mods/bundles/CraneB/e9cfd890c6f1a023` - pkg `resource_packages/custom/crane_b`
  + material `materials/m_crane_custom` (`0xda9a7e147dbaa1e0`, ham_plate clone,
  diffuse->checker).
- Loader Lua: `mods/functions/RuntimeTexLoad/script_main.lua` (loads A on load
  screen, B sequenced after) + Duckmode `test any` (self-issues B if missing,
  spawns the crane when both online).
- Backups of every intermediate bundle state: `*.pre_mipfix`, `*.mipfix`,
  `*.texonly`, `*.allslots`, `*.scratchunit`, `*.hammat` in the bundle dirs.
- Next consolidation step (untested): merge into ONE 4-resource bundle now that
  every resource type is proven.
