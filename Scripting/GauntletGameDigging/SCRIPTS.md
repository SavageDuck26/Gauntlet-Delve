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

## Reading a resource for what it uses

`hunt_unit_textures.py` — point it at a depot `contents/<bundle-id>` file and a
resource, and it lists what that resource references.  It picks the right entry
when one name hash carries several types (bones/unit/material, `--type`), matches
body references against the **bundle's own TOC** (so references we cannot name
yet show up as targets), names what it can by convention (including Stingray's
`m_<name>` material form), and with `--materials` decodes referenced materials
for their texture slots.  This is how `characters/demon_overlord_mini` was shown
to inherit `characters/demon_heavy`'s maps (`FINDINGS.txt` §38).

```bash
python3 hunt_unit_textures.py \
  --bundle ../../Gauntlet-PreSlayer-2015-08-11/depot_258972/contents/1bbcb9610a009446 \
  --name characters/demon_overlord_mini/demon_overlord_mini --type unit
```

## Probing one resource directly

`probe_resource.py` — the one-shot version of the above: give it a name and it
dumps what the resource *says* (printable strings) and what it *points at*
(every 8-byte window matched against **every name we hold**, not just the
bundle's TOC, so cross-bundle references resolve too).  Use it to ask whether a
body is text or binary before building a vocabulary around it.

```bash
python3 probe_resource.py --name characters/mummy_priest/mummy_priest \
  --type state_machine --strings 20 --refs 25
```

## Subdirectories

`resource_tools/` (16-type resource read/write suite), `database_extractor/`,
`wwise-unpacker-revamped/`, `docs/` (findings + DEP guides + reference images),
`Exports/` (kept databases: extracted materials, texture database),
`bundle_manifest/` (generated catalogue), `example_mod/`, `test_mod/`,
`crane_mod/`.

## The name indexes (`bundle_manifest/06_`, `07_`)

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

```bash
python3 ../hashcracker/tools/merge_matches.py ..   # matches.tsv -> overlay
python3 list_game_bundles.py --only resources      # overlay -> 03_txt + 04_csv
python3 make_name_index.py                         # 04_csv + overlay -> 06_/07_ indexes
python3 ../hashcracker/tools/build_targets.py      # catalogue -> targets_*.txt
```

Current state: overlay **5,990** names · catalogue **16,507/20,000 rows named**
· **1,554** unique unresolved hashes (see `docs/FINDINGS.txt` §18–34).

Note: `list_game_bundles.decompress_bundle` now tolerates the **Pre-Slayer
packing** (raw 64 KiB chunks mixed with zlib chunks), so the older depot's art
bundles can be parsed too. `hashcracker/generators/scan_depot_names.py` harvests
names from any install/depot with a colon-tolerant filter — that is how 549 more
names were recovered from `Gauntlet-PreSlayer-2015-01-21/` (the 549-name depot
snapshot).  Snapshots live in the repo root named `Gauntlet-PreSlayer-<date>/`,
one per SteamDB manifest; the 2014-10-10 build is also there.
