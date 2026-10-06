# hashcracker scripts

Everything that drives the brute-forcer. **Workflow:** build targets →
build/flatten vocabularies → generate candidates → `hashcracker crack` →
merge hits. Run `./sweeps/*.sh` to loop that to a fixpoint.

## tools/ — targets and vocabularies

| script | purpose |
| --- | --- |
| `build_targets.py` | Reads `bundle_manifest/04_bundle_resources.csv` and writes `data/vocab/targets_<type>.txt` + `unresolved_targets.txt`. **Targets = rows whose catalogue `name` column is empty** (or whose hash our overlay lacks) — never "absent from the overlay alone". |
| `merge_matches.py` | Folds `matches.tsv` into `../GauntletGameDigging/resource_name_overlay.json`. |
| `make_tex_vocab.py` | `tex_{dir,leaf,suf,root}.txt` — texture/material sweep (`%d/%l%s`). |
| `make_level_vocab.py` | `lvl_*.txt` — quilt code alphabet under the `len(up)==len(down)` / `len(right)==len(left)` rule from `quilt_builder.lua`. |
| `make_particles_vocab.py` | `par_*.txt` — `effects/<pre>_<subject>_<verb>[_<mod>]`. |
| `make_unit_vocab.py` | `unit_*.txt` — block piece grammar `<root>/d01_<env>/<cat>/<style>_<part>…`. |
| `make_unit_vocab_big.py` | `ub_*.txt` — the same with vocabularies mined from resolved names. |
| `make_recovered_vocab.py` | `recovered_names.txt` (every resolved name) + `tokens_ext.txt` (`data/names.txt` plus leaf/path tokens mined from those names) — the inputs for the per-cycle `hashcracker mutate` phase (`FINDINGS.txt` §33). |
| `make_tokens_big.py` | The wide token list for big runs: mines `recovered_names.txt` + `data/names.txt` + `lua_strings.txt` + `events.txt` + `bundle_words.txt` + the Stingray docs into `tokens_big.txt` (ranked by frequency, `--max-tokens`, default 80k). Cost of a mutate run grows linearly with this list (`FINDINGS.txt` §34). |

## generators/ — candidate generation

| script | purpose |
| --- | --- |
| `targeted_unit.py` | Edit-distance-1 inside a unit's own directory + cross-dir re-pointing. |
| `targeted_block_texture.py` | Unit leaves → block dirs × map suffixes (the compounding lever), `--reverse` pushes texture leaves back at unit dirs. |
| `anim_deep.py` | Per-unit clip rebuild + two-token insertions (both saturated; see `FINDINGS.txt` §25). |
| `tex_bundle_deep.py` | Per-bundle texture deepening: each bundle's OWN leaves/dirs/tokens rather than global top-N (`FINDINGS.txt` §24). |
| `targeted_tex_edit.py` | Edit-distance-1 of texture leaves, scoped to the bundle that owns them. |
| `targeted_level.py` | Quilt cross-env transfer + NN×modifier expansion + hazard/arena/room completion. |
| `targeted_anim.py` | Edit-distance-1 of each unit's own clips (insert/replace/delete) + cross-unit transfer. |
| `targeted_gui_css.py` | UI texture names from the `gui/*_css.lua` style sheets. |
| `targeted_lua_keys.py` | Bare Lua table keys (perks, achievements, gui ids) at icon/hud namespaces. |
| `bundle_scoped_cands.py` | Directories seen in a resource's own bundle × global leaf vocabulary. |
| `derive_cands.py` | Lua file paths, every Lua string literal, known-dir × Lua-leaf. |
| `lua_ability_cands.py` | `ability_selection` bare keys × animation shapes. |
| `level_lua_cands.py` | Dungeon layout keys/strings × level directories. |
| `scan_bundle_paths.py` | Harvests path-like strings from bundle **bodies** (shader/settings manifests embed them). |
| `seed_derive.py` | Derives new candidates from names we already hold: dungeon tiles, unit<->map textures, per-unit clip variants, `<base>:<flag>` shader chains (see `FINDINGS.txt` §21). |
| `scan_depot_names.py` | Full name harvest from a game install/depot (bundles + binaries), **colon-tolerant**; work the Pre-Slayer depot this way (`FINDINGS.txt` §19). |
| `snapshot_gather.py` | Per-snapshot artefact set for a pulled depot folder (`--root Gauntlet-PreSlayer-<date>`): writes `_names.txt` (bundles + binaries + the **`.ini` configs scan_depot_names skips**), `_all_hashes.txt`, `_unresolved_hashes.txt`, and with `--crack` a `_matches.tsv` (`FINDINGS.txt` §31). |
| `shader_chains.py` | Enumerates `shader_library` names as `<technique>:[flags…]` — flags are **alphabetically sorted** in 839/851 known chains, so the unknown ones are enumerable subsets. `--global-flags N` mixes flag vocabularies across techniques, `--composite-depth N` adds `psvita_`/`mobile_`/`_debug_lights`-style composite techniques, `--flag-variants` adds numbered/paired flag siblings (`step0-9`, `iter0-9`, `_x/_y`, `_hq/_lq`) (`FINDINGS.txt` §32; found the `psvita_*`, `mobile_*` and `character:double_sided:*` families). |
| `level_body_strings.py` | Dumps printable strings from a bundle's bodies (inspection). |
| `pkg_order_check.py` | Checks whether a package blob lists dependencies in name order (it does not). |

## sweeps/ — drivers

| script | what it loops |
| --- | --- |
| `auto_run.sh [cycles]` | All families (particles → bundle-scoped → lua keys → blocks → textures → **mutate**) until a cycle finds nothing. |
| `big_run.sh [rounds]` | The wide battery: shader grammar → 80k-token mutate → `auto_run` → every specialist sweep (blocks/tex/unit/level/context), each stage wrapped in `timeout` so no oversized vocabulary can run away (`FINDINGS.txt` §34). |
| `blocks_pipeline.sh [rounds]` | Unit grammar → unit edit-1 → unit→map-texture derivation. |
| `tex_pipeline.sh [rounds]` | `tex_*` vocab sweep → block derivation → unit edit-1. |
| `unit_big.sh [rounds]` | The wide unit grammar sweep. |
| `unit_medium.sh [rounds]` | Medium unit sweep: grammar + double widths + modifiers, edit-1 and unit<->texture derivation, looped (`FINDINGS.txt` §22). |
| `level_phase2.sh [rounds]` | Quilt `start_`/`NN 01-24`/mod patterns. |
| `context_sweep.sh [rounds]` | Lua-derived candidates (derive/anim/ability). |

## legacy/ — superseded, kept for reference

`prepare.py`, `make_vocab.py`, `derive_textures.py` and the old `*_sweep*.sh` /
`big_run.sh` / `ui_sweep.sh` cartesian drivers. Superseded by `tools/build_targets.py`,
the `tools/make_*_vocab.py` builders and the `generators/` + `sweeps/` set. See
`legacy/README.md`.
