# GauntletGameDigging — script index

The Python RE toolchain. Files are imported as modules by their neighbours, so
they stay in a flat directory (the 7 files marked **lib** are imported by
others — don't move them without updating importers).

Read first: [`docs/FINDINGS.txt`](docs/FINDINGS.txt) (master format document,
§17–18 = current state) and [`docs/DEP/`](docs/DEP/).

## Name recovery (the pipeline that produced the overlays)

| script | purpose |
| --- | --- |
| `crack_resource_names.py` | The original brute-forcer: 8 generators (lua paths, exe/ini strings, dir×stem×suffix…) → `resource_name_overlay.json`. |
| `crack_bundle_names.py` | Same idea for *bundle* names → `bundle_name_overlay.json`. |
| `build_hash_database.py` / `build_complete_hash_database.py` | Build `hash_database.json` / `.txt` (the 142k-entry dictionary the catalogue resolves against). |
| `make_family_vocab.py` | Per-family token/dir vocabularies (used by the older sweeps). |
| `mine_localization.py` | Mines the localization bundle (English block) into a name dictionary. |
| `scan_binaries.py` | Path-like strings from `binaries/*.exe|dll` → `bin_strings.txt`. |
| `scan_bundle_strings.py` | Strings from bundle bodies → `bundle_strings.txt`. |
| `extract_anim_refs.py` | Maps unresolved animation resources to their owning unit via `state_machine` bodies. |
| `catalog_bundles.py`, `add_bundle_to_db.py`, `bundle_database_manager.py` | Bundle catalogue + `bundle_database.data` bookkeeping. |
| `render_config_tools.py` | `render_config` resource handling. |

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

## Extraction / decoding

`extract_all_textures.py`, `extract_textures.py`, `extract_textures_named.py`,
`extract_materials.py`, `extract_resource_samples.py`, `decode_materials.py`,
`decode_pkg.py`, `batch_export_glb.py`, `gauntlet_unit_parser.py`.

## Modding / packaging

`create_custom_bundle.py`, `create_full_bundle_system.py`, `create_material.py`,
`make_mod_bundle.py`, `make_and_install_bundle.py`, `mod_bundle_builder.py`,
`bundle_rebuilder.py`, `bundle_repacker.py`, `rebuild_bundles.py`,
`replace_all_with_one.py`, `replace_textures_v4.py`, `texture_injector.py`,
`register_custom_bundle.py`, `clone_material.py` **(lib)**,
`clone_native_material.py`, `cubify_unit_template.py`,
`glb_to_template_unit.py`, `obj_to_glb.py`.

## Libraries (imported by the above)

`list_game_bundles.py` **(lib)** — bundle/database parser + **the catalogue
builder** (`--only resources` regenerates `bundle_manifest/03_…txt` and
`04_…csv`); `bundle_tools.py` **(lib)**; `unit_to_obj.py` **(lib)**;
`unit_to_gltf.py` **(lib)**; `gltf_to_unit.py` **(lib)**;
`create_texture_package.py` **(lib)**; `clone_material.py` **(lib)**.

## Subdirectories

`resource_tools/` (16-type resource read/write suite), `database_extractor/`,
`wwise-unpacker-revamped/`, `docs/` (findings + DEP guides + reference images),
`Exports/` (kept databases: extracted materials, texture database),
`bundle_manifest/` (generated catalogue), `example_mod/`, `test_mod/`,
`crane_mod/`.

## Regenerating the catalogue after recovery work

```bash
python3 ../hashcracker/tools/merge_matches.py ..   # matches.tsv -> overlay
python3 list_game_bundles.py --only resources      # overlay -> 03_txt + 04_csv
python3 ../hashcracker/tools/build_targets.py      # catalogue -> targets_*.txt
```

Current state: overlay **5,940** names · catalogue **16,371/20,000 rows named**
· **1,604** unique unresolved hashes (see `docs/FINDINGS.txt` §18–33).

Note: `list_game_bundles.decompress_bundle` now tolerates the **Pre-Slayer
packing** (raw 64 KiB chunks mixed with zlib chunks), so the older depot's art
bundles can be parsed too. `hashcracker/generators/scan_depot_names.py` harvests
names from any install/depot with a colon-tolerant filter — that is how 549 more
names were recovered from `Gauntlet-PreSlayer-2015-01-21/` (the 549-name depot
snapshot).  Snapshots live in the repo root named `Gauntlet-PreSlayer-<date>/`,
one per SteamDB manifest; the 2014-10-10 build is also there.
