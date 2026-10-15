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

The rotation decode is **settled against the running engine** (FINDINGS 9H.6):
the record stores the quaternion's vector part, `(x,y,z) = (f15,f16,f17)`, and
`w = -sqrt(1 - |v|^2)` is reconstructed.  Offset 0 is not a component.  That
reproduces 100% of the engine's `crypt_wall_4c` orientations over 633 captured
instances; the old four-component reading managed 65%.  `--pivot`, `--rotation-snap`,
`--yaw-scale`, `--yaw-offset`, `--swap-zw` and `--apply-scale` are therefore
**diagnostic only** - they existed to work around the wrong reading, and a fitted
export with none of them was verified correct in Blender by eye.

The captures themselves are versioned in `Data/runtime_units/` - one JSON per level,
27 levels / 67,682 units, straight from the engine, nothing recomputed. That is the
manifest; the combined `runtime_units.tsv` has the same fields per unit but merges
levels by the engine's index.

`compare_runtime_units.py <level> <runtime_units.tsv>` joins the engine's runtime
units to a `.level`'s 72-byte records.  The join key is the **template hash**: 
`Unit.debug_name(unit)` returns the unit's resource-name hash, which is the value
at record offset 32.  It prints the worst position disagreement and, when the
capture carries rotations, the engine's rotation beside each record's fields -
that comparison is what settled 9H.6.

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
