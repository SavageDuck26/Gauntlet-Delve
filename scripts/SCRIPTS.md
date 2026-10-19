# scripts/ - RE toolchain index

The Python RE toolchain. Files are imported as modules by their neighbours, so
they stay in a flat directory (the 7 files marked **lib** are imported by
others - don't move them without updating importers).

Read first: [`../Data/FINDINGS.txt`](../Data/FINDINGS.txt) (master format document;
sections 17-18 = current state) and [`../Data/DEP/`](../Data/DEP/).

## Name recovery (the pipeline that produced the overlays)

| script | purpose |
| --- | --- |
| `crack_resource_names.py` | The original brute-forcer: 8 generators (lua paths, exe/ini strings, dirxstemxsuffix...) -> `resource_name_overlay.json`. |
| `crack_bundle_names.py` | Same idea for *bundle* names -> `bundle_name_overlay.json`. |
| `build_hash_database.py` / `build_complete_hash_database.py` | Build `hash_database.json` (the 142k-entry name dictionary the catalogue resolves against). |
| `make_family_vocab.py` | Per-family token/dir vocabularies (used by the older sweeps). |
| `mine_localization.py` | Mines the localization bundle (English block) into a name dictionary. |
| `scan_binaries.py` | Path-like strings from the game's `binaries/*.exe|dll` -> `bin_strings.txt`. |
| `scan_bundle_strings.py` | Strings from bundle bodies -> `bundle_strings.txt`. `--grep` also reports *which* bundle and entry hash holds a string (how a cut name is told from a name live code still references). |
| `make_progress_report.py` | The overall progress view -> `../Data/bundle_manifest/08_progress.txt`: live coverage (headline, by type, by package), the recovery timeline from git, and pointers to everything else. `05_summary.txt` is catalogue-only and its `Unresolved` line is the static `hash_database.json` metric, not ours - the note in `08_progress.txt` reads that number out of the file so it cannot go stale. |
| `make_missing_report.py` | `../Data/bundle_manifest/11_missing_by_bundle.tsv` - the missing view **grouped**: one row per `(package, bundle, type)` with the missing-row count, the distinct-hash count, the bytes, and the hashes themselves (size-ordered) in the last column. The missing rule is the sweeps' own (catalogue `name` empty **and** the hash absent from `resource_name_overlay.json`), so its totals are exactly the score line's complement - 162 groups, 2,092 rows, 900 hashes at the time of writing, per type: texture 672/252, animation 539/303, shader_library 350/137, material 205/89, particles 159/76, shader 64/36, unit 48/39, timpani_bank 37/37, level 12/10, flow 4/1, package 2/2. `make_progress_report.py` calls `write_missing_by_bundle()`, so every progress run refreshes it next to `08_progress.txt` (`--stdout` prints instead). |
| `make_names_by_bundle.py` | `../Data/bundle_manifest/12_names_by_bundle.txt` - every name we hold **grouped by the bundle it ships in**, alphabetical inside each bundle, names only (no hashes): a `### <bundle>   <package>   (N names)` header then one name per line. 13,972 name-rows in 76 bundles, which is more than the 6,932 distinct names because duplicated resources appear under each bundle that carries them - that duplication is the point of the view. `make_progress_report.py` calls it, so it refreshes with 08/11. |
| `reachability_audit.py` | Walks every bundle body, records which resources reference which (8-byte-aligned catalogue hashes), and reports per unresolved hash how many **named** resources point at it -> `../Data/bundle_manifest/09_reachability.tsv`. 1,044 of the 1,096 are referenced; 52 are orphaned (FINDINGS 60.14). |
| `hunt_shader_subsets.py` | Shader chains scoped by body size: each technique has its own size band and, within a technique, size predicts the flag count (`base` 1 flag ~ 68.6 KB ... 9 flags ~ 131.4 KB), so the sorted-subset enumeration is bounded. Pair it with the `shader_pass_flags` mined out of `render_config` (FINDINGS 60.14). |
| `extract_anim_refs.py` | Maps unresolved animation resources to their owning unit via `state_machine` bodies. |
| `catalog_bundles.py`, `add_bundle_to_db.py`, `bundle_database_manager.py` | Bundle catalogue + `bundle_database.data` bookkeeping. |
| `render_config_tools.py` | `render_config` resource handling. |

## Cross-build hunting (deprecated and renamed content)

| script | purpose |
| --- | --- |
| `hunt_old_names.py` | Mines a snapshot's own harvested strings against that snapshot's *own* resource hashes (2014: 2,785 names, 2015-01: 3,102). |
| `hunt_build_diff.py` | Diffs one bundle between two snapshots and pairs resources whose **bytes are identical while their hashes differ** - a rename (341 moves 2015-01->2015-08). `--report-changed` also lists the opposite case: same name hash, different bytes, i.e. an asset that was reworked in place (4,298 between 2014-10-10 and 2015-08-11). |
| `check_build_liveness.py` | **Was this name ever a live resource, and in which build?** Walks each snapshot's real entries and tests a name's hash against them, plus the shipped catalogue's status. |
| `tools/apply_renames.py` (hashcracker) | Joins the two above: old name -> new name, and a token-translation pass over the old corpus. |

A harvest (`_names.txt`) is evidence of a *string*, never of a live resource, so it
always needs `check_build_liveness.py` (or `hunt_old_names.py`) behind it. Keep a
control name in every batch: `characters/gator_brute/gator_brute` should read live in
2014 and 2015-01 and absent in 2015-08.

## Runtime name capture

| script | purpose |
| --- | --- |
| `hunt_runtime_names.py` | Turns a `runtime_names.tsv` capture from the loader's name mining into three classes - **KNOWN** (the hash is a row we had already named: the control that proves the capture-and-hash chain end to end), **RECOVERED** (a previously unresolved row, now named by the engine itself) and **NEW** (no catalogue row at all). Reads the catalogue and `10_unresolved_master.tsv` read-only and writes its report *next to the capture*, so a session can be gone over before anything is folded into the overlay. `--list known|recovered|new`, `--out`. |

A runtime capture is a TSV of hash/name pairs produced by the C++ loader's name
mining; `hunt_runtime_names.py` reads one and classifies it. The engine's string
hasher for this build is at RVA `0xBCD0` (`HashNameAbi=3`) - see FINDINGS 60.15
for how it was located.


## Bundle inspection / analysis

`analyze_bundle.py`, `analyze_bundles.py`, `analyze_bundle_db.py`,
`analyze_bundle_structure.py`, `analyze_stream.py`, `analyze_database.py`,
`analyze_52byte_mat.py`, `analyze_material_format.py`, `analyze_mesh.py`,
`analyze_package_dependencies.py`, `analyze_real_material.py`,
`analyze_real_package.py`, `analyze_unit_bytes.py`, `inspect_bundle.py`,
`inspect_bundle_diag.py`, `inspect_material_layout.py`, `debug_bundle.py`,
`diagnose_texture.py`, `check_bundle_db.py`, `check_db_format.py`,
`check_hashes.py`, `check_dds.py`, `list_textures.py`, `find_material_names.py`,
and the scratch `_check_db.py`, `_check_entry_table.py`, `_compare_db.py`,
`_deep_compare.py`.

## Dumping the whole game

| script | purpose |
| --- | --- |
| `export_all_resources.py` | Walks every bundle and writes each resource body to a file named after it, with the type name as its extension (`named/<resource path>.unit`, `named/lua/managers/x.lua`, ...). Rows we could not name go to `unresolved/<type>/<hash>.<ext>`, one file per distinct hash - the gaps, kept visible. Also writes `index.tsv` (every catalogue row: status, type, name, hash, package, size, bundle, index, path) and `summary.txt`. `--dds-view` adds `view/dds/**`, a hardlink per texture whose body really is a DDS, so image viewers open them at no disk cost. `--convert` then runs `convert_export.py` in the same command, so the dump also grows the openable `view/` trees. `--only TYPE`, `--limit N`, `--named-only`, `--view-only`, `--jobs N`. |
| `convert_export.py` | Turns the dump into types you can just open: `view/png/**` (a `.texture` body is a DDS blob), `view/mp3/**` (`.ugg` is 16 bytes then an Ogg stream, through ffmpeg), `view/glb/**` (`.unit` -> glTF, using its companion `.bones` when it has one) and `view/level/**` (`.level` -> glTF, via `level_to_glb.py`: the scene is composed by walking the level's placed sub-levels - a room level is only its decoration layer and places its shell as `..._template` plus door-wall prefabs, so merging them turns a scatter of props into the full dungeon - editor/logic units such as the ~16,000-unit skydome are dropped, and the record's region-box field is not applied as a scale; see `--max-depth` / `--include-helpers` / `--apply-scale` on that tool). Unnamed rows land under `view/<kind>/_unresolved/`. The output extension is the kind's own, so `level` writes `.glb` too. Failures are counted, not fatal - cubemaps and BC6/BC7 defeat Pillow. A unit with `mesh_count == 0` (the logic-only `player`, blood decals, `carry_lights`, `ceiling_collisionbox`) is counted as **skipped**, not failed: there is no geometry to write. Each job gets its **own** temp file: `named/elias/*/audio/` is full of identical stems (`1_0_1.ugg`, `completed.ugg`, ...) and a stem-keyed temp path let parallel workers clobber and unlink each other's stream, which silently lost 10 of the 144 tracks on a clean rebuild. |

What the dump actually contains, learned the hard way: `.texture` bodies begin with
`DDS `, so they are real DDS files; `.lua` bodies are **LuaJIT bytecode** behind a
12-byte resource header, not source (the chunk name is embedded, which is why the
runtime capture named Lua so well); `.shader_library` names carry the chain form
(`base:...:diffuse_map:normal_map:static_lighting`); only 40 catalogue rows have a
`.stream` sidecar, so the dump is otherwise self-contained. 8,891 of the 17,880 named
rows are distinct resources - the rest are the same resource shipped in more than one
package - and the 2,124 unnamed rows are 915 distinct hashes, kept as 999 files (one
per (type, hash) pair).


## Extraction / decoding

`extract_all_textures.py`, `extract_textures.py`, `extract_textures_named.py`,
`extract_materials.py`, `extract_resource_samples.py`, `decode_materials.py`,
`decode_pkg.py`, `batch_export_glb.py`, `gauntlet_unit_parser.py`,
`level_to_glb.py`, `compare_runtime_units.py`.

`level_to_glb.py` exports a whole `.level` to one `.glb`: it decodes the 72-byte
entity table, resolves each entity's template hash to a `.unit`, builds each
unique unit's mesh once, then drops one glTF node per placed entity carrying its
position/rotation (FINDINGS 9H.2 and 9H.6).  Single file, a directory, or
`--export <root>` (every `named/**/*.level`); `selftest` checks the 371-entity
crypt room.

The rotation decode is **settled against the code and the running engine** (FINDINGS
9H.34, layout corrected in 9H.36).  A unit's transform is 48 bytes inside its 72-byte
record: the position is at record+0x30, the rotation is **four consecutive floats at
60/64/68/72** - so the quaternion's `w` is the NEXT record's offset-0 float, and the
scale is that record's offset-4 fields - and the engine normalises all four
(`k = 2/|q|^2`, FUN_0042d7f0, reached from FUN_00430440's per-unit walk at
`data + 0xb0 + i*0x48`).  A record's OWN offsets 0 and 4 therefore hold the PREVIOUS
unit's `w` and scale, which is what every earlier reading got wrong: the round trips
stayed byte-exact and the ids, names and positions all matched, while every rotated
placement was built from its successor's `w`.  The last unit's `w`/scale live in the
24 bytes reserved after the table (`u32[3] = table_end + 24`).  The old reading
("`w = -sqrt(1 - |v|^2)` reconstructed, offset 0 not a component") reproduced the
engine's `crypt_wall_4c` orientations only because a wall's yaw survives it; it was
wrong about the angle and invisible on identity placements.  `--pivot`,
`--rotation-snap`, `--yaw-scale`, `--yaw-offset`, `--swap-zw` and `--apply-scale`
remain **diagnostic only**.

The captures themselves are versioned in `Data/runtime_units/` - one JSON per level,
27 shipped levels / 67,682 units, straight from the engine, nothing recomputed, plus
`modules_d01_hub_room_custom_duckomp_room.json` (our own arena, captured after the 9H.36
fix, which reports the authored quaternions exactly). That is the
manifest; the combined `runtime_units.tsv` has the same fields per unit but merges
levels by the engine's index.

`compare_runtime_units.py <level> <runtime_units.tsv>` joins the engine's runtime
units to a `.level`'s 72-byte records.  The join key is the **template hash**: 
`Unit.debug_name(unit)` returns the unit's resource-name hash, which is the value
at record offset 32.  It prints the worst position disagreement and, when the
capture carries rotations, the engine's rotation beside each record's fields -
that comparison is what settled 9H.6.

`compare_level_capture.py <level file> <capture json>` is the same comparison for a
level of OUR OWN, where the hash join drifts (24 distinct kinds, and the engine's unit
order is not the file's).  It joins on **(rounded world position, template hash)
together** - unique for 192 of 194 records - auto-detects the sub-level's world offset
`(4, 4, 0)`, and reports how many rotations come back exactly as written plus the
distribution of the differences.  That is the tool that found 9H.24: our `--scratch`
level loses 20% of its rotations to the engine's own re-derivation, while the same
kinds written into a donor body lose 4.3% - the difference is the room sections, which
the 6-unit sample skeleton does not have.

`check_level_symmetry.py <level file> [--skip-last=N]` is the offline validation that
came out of the author's symmetric test arena: it finds the x that pairs the most
placements and checks that every mirrored pair's yaw is mirrored too (a reflection in
x = c negates a yaw).  51 of 51 pairs correct on that level, so the baked-export
recovery's handedness is right - FINDINGS 9H.25.  Pass `--skip-last=N` to leave out
diagnostic fixtures (the rotation ruler is the last 16 records) so they are not paired
with unrelated units.

`check_level_capture_rotation.py <level file> <capture json> [--offset X,Y,Z]` is the
check that was missing (FINDINGS 9H.36): it joins a level file to the engine's own
per-level capture and reports **both** readings of every record's rotation - the
engine's (`w` = the next record's offset 0) and the old one (`w` = this record's own
offset 0) - so a wrong reading cannot pass by accident.  On the shipped crypt room the
correct reading is exact on 177/177 joined units and the old one is wrong on 44; on the
hub it is 460/461 against 207/461.  The single hub miss is a file/capture disagreement
(record 330's `xyz.x` differs between our copy and the captured file), which is what
`--max-bad` exists to acknowledge - never to widen.

The engine side of that capture lives in the loader repo:
`../GauntletModLoader/src/level_mining.cpp` and
`../GauntletModLoader/mods/functions/LevelProbe/script_main.lua`.  Its call shapes
are copied from the game's own Lua (`Gauntlet-Source-DO_NOT_EDIT/lua`), not
inferred - `LevelAux.units_recursive(level)` for the unit list,
`Unit.local_position(unit, 0)` / `Unit.local_rotation(unit, 0)` for transforms (the
node index 0 is required), `Quaternion.to_elements(q)` for a quaternion's four
components, and `Level.unit_index(level, unit)` for the level's own numbering.

## Modding / packaging

`create_custom_bundle.py`, `create_full_bundle_system.py`, `create_material.py`,
`make_mod_bundle.py`, `make_and_install_bundle.py`, `mod_bundle_builder.py`,
`bundle_rebuilder.py`, `bundle_repacker.py`, `rebuild_bundles.py`,
`replace_all_with_one.py`, `replace_textures_v4.py`, `texture_injector.py`,
`register_custom_bundle.py`, `clone_material.py` **(lib)**,
`clone_native_material.py`, `cubify_unit_template.py`,
`glb_to_template_unit.py`, `obj_to_glb.py`.

## Mod bundles: the container format, and how to validate one

`mod_bundle_builder.py` writes these.  The engine's reader is strict and completely
**silent** when the container is wrong: the bundle is registered, the package resolves, the
game's own `PackageManager` asks for it, and then the load never completes -
`ResourcePackage.has_loaded()` stays false forever and the boot hangs on
`Game:are_all_packages_online(_G.COMMON_GAME_PACKAGES)`.  Nothing is logged.  The
measurements are in FINDINGS 9H.12.

Authoritative layout, per `analyze_package_dependencies.py:parse_bundle`:

| offset | content |
| --- | --- |
| `0x000` | `uint32` resource count N |
| `0x004` | 256 bytes of preamble/padding to `0x104` |
| `0x104` | TOC: **exactly N** x 16 bytes `{u64 typeHash, u64 nameHash}` - **no sentinel** |
| `0x104 + N*16` | payloads back to back, **no alignment padding** |

Every payload, **the first included**, carries the same 36-byte header
`{u64 type, u64 name, u32 flags, u64 streamSize, u32 dataSize, u32 unknown}` followed by
`dataSize` bytes; the next header begins immediately at the end of that data.

Resource 0 being special (a 20-byte header with no type/name) and a repeated (N+1)th TOC
entry are both **wrong**.  They were believed for a long time and are still asserted by
`bundle_inspect.py` and by the loader's `src/bundle_diagnostics.cpp`, which is exactly why
a bundle the engine could not read was reported as having "no structural problems".

The package resource blob (`type 0xAD9C6D9ED1E5E77A`) lists the bundle's resources:
`uint32 entryCount`, then per entry `{u64 type, u64 name, u32 dependencyCount}` followed by
`dependencyCount` x `uint32`, then a one-byte `0x01` trailer.  Shipped entries all use
`dependencyCount` 2, where `dep[1]` is the entry name's high 32 bits and `dep[0]` is a
per-package constant.

### Validating a bundle without launching the game

`analyze_package_dependencies.py` parses shipped bundles correctly, so it is a free
oracle.  If a new bundle's numbers do not look like a shipped bundle's, the engine will
not read it either:

```
python3 analyze_package_dependencies.py <bundle> --sample-entries 2

  SHIPPED b22560b172a4cff8 : count=13 off=0x104 parsed=13 packages=13
  BROKEN                   : count=2  off=0x14  parsed=2  packages=0   <- fell back
```

`off=` must be `0x104` and every resource's type/name must decode.  A fallback offset is
the signature of a malformed container.

`check_mod_sources.py` is the first check, before anything is built: it compares every
resource a `mod.json` lists against the game's own copy of the same resource and reports
which are unchanged.  An "edited" file that is byte-identical to the export builds, loads,
comes online and renders exactly as vanilla - it cost a month once.  It exits 1 when a mod
overrides shipped resources and none differ:

```
python3 check_mod_sources.py room_edit_mod/mod.json
   1 of 8 resource(s) differ from the shipped original
```

The chain for any mod, in order, all offline: **`check_mod_sources.py`** (something must
differ) -> **`mod_bundle_builder.py`** (build) -> **`analyze_package_dependencies.py`**
(`off=0x104`, `parse_status ok`) -> **md5 the bundle's blob for the edited resource against
the edited source** (must match, must differ from the export).  Only then deploy.

**And then verify the DEPLOY with md5 too.**  `bundle_control.py --only <Name>` reports
`STATE MATCHES REQUEST` whether or not it actually replaced the file, and the loader
faithfully re-copies whatever is in the game's `mods/bundles/<Name>/` into
`contents/<hash>` - so a stale bundle in the game's mods folder is served as if it were the
new one, with no error anywhere.  That happened here: a rebuild landed in the dev tree
(`FlatPlaneLevel/cf206f623df8eba0`, md5 `47a1ba93...`) while the game still had the previous
build (`md5 43910d7a...`), and a whole test round was spent judging geometry that was not
deployed.  The check is two md5s, and it must be three:

    md5sum <dev>/cf206f623df8eba0  <game>/mods/bundles/FlatPlaneLevel/cf206f623df8eba0
    md5sum <game>/contents/cf206f623df8eba0        # after a launch: the loader's own copy

The `contents/` copy is the one the engine actually reads.  If the game's `mods/bundles`
copy and the dev copy differ, `cp -f` the dev bundle over it and relaunch - that is more
reliable than trusting the deploy summary.

### Authoring level content

| tool | purpose |
| --- | --- |
| `make_plane_glb.py` | writes a flat quad as GLB **in engine space** (XY plane, +Z normal).  `glb_to_template_unit.py` does no axis conversion, so a Blender export arrives standing on edge.  `--grid N` subdivides: `--grid 2` emits a 3x3 grid of 9 verts / 8 triangles, which is **exactly** the native floor block's mesh - the knob to reach for when a collider turns out to be derived from the mesh rather than authored. |
| `glb_to_template_unit.py` | splices a mesh into a native unit and keeps that unit's **trailer** - which carries its physics actor.  Pick the template by what the thing IS: the trailer's actor is imported whole, behaviour included. |
| `level_set_entities.py` | replaces a level's entity table, or one entity (`--replace-at`), and can drop sub-level placements (`--zero-sublevels`).  Verifies that nothing outside the table - and outside the header's own entity-count field - changed.  Rotations it writes are now correct: the quaternion's vector part goes to offsets 60/64/68 and `w` is reconstructed, with offset 0 written as the negative-branch `w`.  Before FINDINGS 9H.18 the last two slots were swapped, so a spec of `[0,0,0,-1]` wrote a 180-degree rotation. |
| `level_decode.py` | reads a `.level` structurally and prints it: the 32-field header, the unit table, the metadata list, the sub-level placements and every section with its size and content profile.  Read-only, and it asserts the format invariants so a file that stops fitting says so.  See FINDINGS 9H.16 - the header is counts interleaved with offsets, not 16 opaque pairs. |
| `build_own_units.py` | splices each of the author's meshes into the native template that decides its physics and material, grouping by the node's base name (one unit = one shape).  A unit's collider IS the template's trailer, so where it *sits* is fixed too: on the TEMPLATE's own mesh box, which is corner-anchored, while a Blender object's origin is usually at its centre - so a centred 8x8 tile had its 8x8 collider patch four units away and three quarters of the tile was thin air (FINDINGS 9H.41).  The builder moves each mesh onto that box (x and y only) and writes the vector to `--offsets`; `level_from_glb.py --unit-offsets` then moves every placement back by it, rotated and scaled into the record's frame, so nothing visible moves.  `--no-collider-shift` builds the old way. |
| `build_level_mod.py` | one command from the `.blend` to a deployed, verified bundle: export (optional), one `build_own_units.py` run per own kind, `level_from_glb.py --scratch`, `mod_bundle_builder.py --flat`, `check_deployed_bundle.py`.  It refuses when the `.blend` is newer than the GLB unless `--export` or `--force` (what you are looking at in Blender must be what is built), and it threads the collider-offset file through both halves. |
| `check_deployed_placement.py` | does the deployed level reproduce the GLB, computed with the engine's own arithmetic - every record's rotation against its node (FUN_0042d7f0's matrix) and every unit's mesh against the GLB's in the engine frame.  Pass `--unit-offsets <the build's build/unit_offsets.json>` when the units were moved onto their template's collider box, or the shifted ones report a mismatch of exactly that vector (FINDINGS 9H.41). |
| `glb_to_level.py` | the reverse direction: patches a `.glb`'s transforms back into an existing `.level` against its original bytes, reporting rotation-only diffs rather than writing them. |
| `level_from_glb.py` | builds a level FROM a Blender file: one 72-byte entity record per GLB node, written into a donor's table with every other section byte-identical and the entity count unchanged, and the donor's leftover scenery moved 100 km up rather than deleted.  It keeps the donor's LOGIC (spawn fields, markers, doors, nav blockers) bit-for-bit and only overwrites decoration - overwriting the logic leaves the encounter waiting for waves that never come, which is a hang, not a crash (FINDINGS 9H.21).  The axis handling is two questions, not one: positions follow the LAYOUT's frame (the axis the floors are flat on) and rotations follow the MESH's frame (the averaged vertex normals of the flat meshes), combined as `R_record = F^-1 * R_node * F'`; collapsing them into one flag is what shipped three custom levels with every unit on its side (FINDINGS 9H.22).  `--scratch` writes a level with NO donor at all - our entity table, our metadata, the section skeleton every shipped level shares - so none of the donor's flow, volumes or markers come with it (FINDINGS 9H.23).  A BAKED export (one where Blender applied scale/rotation/location into the meshes, so no node has a transform) is refused with instructions unless `--reference <level export .glb>` is given, in which case the transforms are recovered from the geometry - exactly by a vertex-for-vertex fit where the mesh is the game's own, and from bounding boxes elsewhere (FINDINGS 9H.22.3, 9H.23.1).  Nodes the author marked as scratch - a name containing `IGNORE_NAME_SUBSTRINGS`, default `throwaway`, or any `--ignore SUBSTR` - are not placed, do not vote in the up-axis measurements and never become one of our units (`build_own_units.py` shares the filter); they are reported as IGNORED, not as an unresolved unit name (FINDINGS 9H.37). |
| `plane_mod/` | the worked example: a flat plane as a campaign room.  **Read its README before reusing any file in it** - several are superseded and one is the build that crashed the level load. |

`bundle_control.py` puts the game's bundle state into exactly a declared set.  There are
three places per bundle - the folder, the `contents/<hash>` copy, and the
`bundle_database.data` rows - and removing the folder alone leaves the other two live, so
always drive it with `--none` then `--only <Name>` for a single-variable test.

`level_probe_mod/mod.json` is a one-resource bundle for testing the pipeline itself rather
than any particular asset; `room_edit_mod/mod.json` is the real one.


## Libraries (imported by the above)

`list_game_bundles.py` **(lib)** - bundle/database parser + **the catalogue
builder** (`--only resources` regenerates `../Data/bundle_manifest/03_...txt` and
`04_...csv`); `bundle_tools.py` **(lib)**; `unit_to_obj.py` **(lib)**;
`unit_to_gltf.py` **(lib)**; `gltf_to_unit.py` **(lib)**;
`create_texture_package.py` **(lib)**; `clone_material.py` **(lib)**.

## Reading a resource for what it uses

`hunt_unit_textures.py` - point it at a depot `contents/<bundle-id>` file and a
resource, and it lists what that resource references.  It picks the right entry
when one name hash carries several types (bones/unit/material, `--type`), matches
body references against the **bundle's own TOC** (so references we cannot name
yet show up as targets), names what it can by convention (including Stingray's
`m_<name>` material form), and with `--materials` decodes referenced materials
for their texture slots.  This is how `characters/demon_overlord_mini` was shown
to inherit `characters/demon_heavy`'s maps (`FINDINGS.txt` #38).

```bash
python3 hunt_unit_textures.py \
  --bundle <game install>/contents/<bundle-id> \
  --name characters/demon_overlord_mini/demon_overlord_mini --type unit
```

## Probing one resource directly

`probe_resource.py` - the one-shot version of the above: give it a name and it
dumps what the resource *says* (printable strings) and what it *points at*
(every 8-byte window matched against **every name we hold**, not just the
bundle's TOC, so cross-bundle references resolve too).  Use it to ask whether a
body is text or binary before building a vocabulary around it.

```bash
python3 probe_resource.py --name characters/mummy_priest/mummy_priest \
  --type state_machine --strings 20 --refs 25
```

## Subdirectories

`resource_tools/` - the 16-type resource read/write suite.

The findings and the catalogue no longer live here - they are in the repo's
**`Data/`** tree: `Data/FINDINGS.txt`, `Data/DEP/`, `Data/*_overlay.json`,
`Data/hash_database.*`, `Data/bundle_manifest/` and `Data/matches.tsv`.

## The name indexes (`../Data/bundle_manifest/06_`, `07_`)

`make_name_index.py` writes two readable views of the recovered names alongside the
catalogue, which is keyed by hash and therefore the wrong way round for reading:

```bash
python3 make_name_index.py                 # 06_names_by_name.txt  (alphabetical by name)
                                           # 07_names_by_type.txt  (grouped by type)
python3 make_name_index.py --mode type     # only the grouped index
python3 make_name_index.py --stdout        # print instead of writing
python3 make_name_index.py --all           # see below
```

One row per name: the name, the hash, and every type the name carries - a unit, its
bones, its material, its lua and its state machine all share a hash, because the
hash *is* the name.

Output is column-aligned for reading.  `--tsv` gives tab-separated rows instead,
for `grep`/`cut`/`sort`.  The name column is sized to the 90th percentile of name
lengths rather than the longest name, because one 150-character shader chain would
otherwise pad most of the file into blankness.

`--all` merges in whatever the catalogue's own `name` column holds as well as the
overlay.  In practice that changes nothing, because `list_game_bundles.py` builds
that column *from* this same overlay; it exists for a catalogue built fresh from
the game without it.

It reads only `04_bundle_resources.csv` and `resource_name_overlay.json`, so it
needs neither the game installed nor any of the mining state, and it can be
regenerated after every batch of new names.

## Regenerating the catalogue after recovery work

The manifest is a *derived* artefact: everything under `../Data/bundle_manifest/` is built from
the game install, `resource_name_overlay.json` and `matches.tsv`, and the whole lot can
be rebuilt in about a minute.  Run it in this order - `09_`/`10_` must precede `08_`,
which reads the master list to count the unreachable.

```bash
python3 ../hashcracker/tools/merge_matches.py ..   # matches.tsv -> overlay
python3 list_game_bundles.py                       # install + overlay -> 00_..05_
python3 make_name_index.py                         # 04_csv + overlay -> 06_/07_ indexes
python3 reachability_audit.py                      # named refs        -> 09_/10_
python3 make_progress_report.py                    # everything        -> 08_progress.txt
python3 ../hashcracker/tools/build_targets.py      # catalogue         -> targets_*.txt
```

`list_game_bundles.py` writes `00_file_tree.txt`, `01_bundle_files.txt`,
`02_bundle_database.txt`, `03_bundle_resources.txt`, `04_bundle_resources.csv` and
`05_summary.txt`; `--only resources` is the shortcut when only `03_`/`04_` need moving.
The two exports are the other half of the same idea:

```bash
# one command: dump + decode every openable view (dds hardlinks, png, mp3, glb, level)
python3 export_all_resources.py --dds-view --convert --jobs 8

# or the two steps on their own
python3 export_all_resources.py --dds-view         # -> <the export dir you pass>
python3 convert_export.py --jobs 8 --overwrite     # -> that folder's view/{png,mp3,glb,level}
```

Current state of the view tree: **478** dds, **579** png, **7** mp3, **359** unit
glb (`view/glb`) and **256** level glb (`view/level`; 151,948 nodes, 6.28 M
triangles). The 7 `.unit` files with no `.glb` are genuinely `mesh_count == 0`
(logic-only units).

`export_all_resources.py` skips files that already exist, so a re-run only writes what a
new name has changed; delete the folder (or move it aside) for a genuinely clean tree,
because a resource whose name changed would otherwise leave its old file behind.

Current state: overlay **6,893** names - catalogue **17,880/20,004 rows named (89.38%)**
- **915** unique unresolved hashes (see `../Data/FINDINGS.txt` #61-63).

Note: `list_game_bundles.decompress_bundle` tolerates the older **Pre-Slayer
packing** (raw 64 KiB chunks mixed with zlib chunks), so older depot snapshots can
be parsed too. `hashcracker/generators/scan_depot_names.py` harvests names from any
install/depot with a colon-tolerant filter - that is how 549 more names were
recovered from a 2015-01-21 depot snapshot.

## The engine binary (Ghidra)

`gauntlet.exe` is already imported and analysed in `~/tools/ghproj/Gauntlet.gpr`.  Ghidra 12 runs
`.py` scripts through PyGhidra, which needs its own venv, so use the launcher (on first run it
creates `~/.config/ghidra/ghidra_12.1.4_PUBLIC/venv` and asks to install PyGhidra - answer `y`):

    JAVA_HOME=~/tools/jdk python3 ~/tools/ghidra_12.1.4_PUBLIC/Ghidra/Features/PyGhidra/support/pyghidra_launcher.py \
        ~/tools/ghidra_12.1.4_PUBLIC -H ~/tools/ghproj Gauntlet -process gauntlet.exe -noanalysis \
        -scriptPath scripts/ghidra -postScript <script>.py

`-noanalysis` reuses the existing analysis, so a run is seconds, not minutes.  Output is plain
stdout: redirect it to a log and grep it.

| script | purpose |
| --- | --- |
| `xref_strings.py` | find engine strings, their xrefs, and decompile the functions referencing them.  How the collision vocabulary (`Dynamic physics enabled ...`, `Invalid actor ...`, `collision_filter`) was read. |
| `binding_lookup.py` | resolve a **Lua binding name** to the function it registers and decompile *that*.  Finding the string only lands you in a hundred-line registration table; the third argument of the matching line is what you want.  This is how `World.load_level` -> the level loader was reached. |
| `decompile_at.py` | decompile the function containing an address and list its callees.  The navigation tool: edit `TARGETS`, re-run, walk the call graph one hop at a time.  It disassembles and creates a function when the address is still a bare label, which registered binding implementations usually are. |
| `physics_probe.py` | search every instruction for scalar constants (that is how the unit signature `0x00010090` located the unit *writer*), plus actor-field string xrefs. |
| `scan_offsets.py` | scan every instruction for a set of struct offsets and report the functions that reference two or more.  Used to hunt the unit loader by its own array offsets (`+0xbc`/`+0xc4` actor table, `+0x14c`/`+0x154` meshes).  Effective but noisy - unrelated structs share small offsets - so it is a pointer to candidate functions, not a proof. |
| `find_typehash_refs.py` | locate a 64-bit resource **type hash** in the binary's data and decompile what references it.  Result on this build: **no type hash appears as an 8-byte constant at all** - the engine hashes the type NAME at runtime (which is what `FUN_0062a040("level")` in the level loader is doing), so this route is closed and is recorded so it is not retried. |

A scalar scan over every function in the binary takes under a minute, so whole-program searches are
practical.  Findings worth keeping go into FINDINGS 9H.17, not into the log.

