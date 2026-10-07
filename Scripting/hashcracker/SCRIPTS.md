# hashcracker scripts

Everything that drives the brute-forcer. **Workflow:** build targets →
build/flatten vocabularies → generate candidates → `hashcracker crack` →
merge hits. Run `./sweeps/*.sh` to loop that to a fixpoint.

## tools/ — targets and vocabularies

**Always start the binary through `tools/hc.sh`** (wraps it in `flock` so only one
hashcracker ever runs — two at once halve each other's GPU/CPU throughput).

| script | purpose |
| --- | --- |
| `hc.sh` | `flock` wrapper around `./target/release/hashcracker`; same arguments, queues instead of racing. Every sweep calls this, never the binary. |
| `build_targets.py` | Reads `bundle_manifest/04_bundle_resources.csv` and writes `data/vocab/targets_<type>.txt` + `unresolved_targets.txt`. **Targets = rows whose catalogue `name` column is empty** (or whose hash our overlay lacks) — never "absent from the overlay alone". |
| `merge_matches.py` | Folds `matches.tsv` into `../GauntletGameDigging/resource_name_overlay.json`. |
| `make_tex_vocab.py` | `tex_{dir,leaf,suf,root}.txt` — texture/material sweep (`%d/%l%s`). |
| `make_level_vocab.py` | `lvl_*.txt` — quilt code alphabet under the `len(up)==len(down)` / `len(right)==len(left)` rule from `quilt_builder.lua`. |
| `make_level_full.py` | `data/vocab/lvl/*` — the whole `.level` grammar (`FINDINGS.txt` §37): env/subdir/shape/cells/nn/mod vocabularies, the **exhaustive** per-side cell-group lists (`g1`/`g2`/`g3`/`g5`), themes mined from the dungeon Lua (`floor_type`, layout filenames) and the game's enemy-group/creature vocabulary (`lua/settings/encounter_settings.lua`, `characters/`, `props/`, …) **with plurals** — quilt mods are group names (`...__01_juggernauts`, `...__02_statues_mixed`). |
| `make_level_context.py` | `data/vocab/lvlctx/*` — the concrete-prefix trick: one row per (env, sub) holding only the values **seen in that context** (e.g. `crypt/quilts/base` = 4 codes × 5 nn × 20 mods). The pattern literal pins env/sub/leaf, so `sweeps/level_context.sh` can escalate one field at a time instead of crossing everything (68 G candidates → 1,780 closed form). |
| `mine_lua_modules.py` | Reassembles resource names out of the decompiled Lua tree: bare table keys are written **relative to the `path = "modules/…"` field in scope**, so they must be re-joined. Writes one candidate per line for `crack --candidates`. |
| `make_particles_vocab.py` | `par_*.txt` — `effects/<pre>_<subject>_<verb>[_<mod>]`. |
| `make_unit_vocab.py` | `unit_*.txt` — block piece grammar `<root>/d01_<env>/<cat>/<style>_<part>…`. |
| `make_unit_vocab_big.py` | `ub_*.txt` — the same with vocabularies mined from resolved names. |
| `make_recovered_vocab.py` | `recovered_names.txt` (every resolved name) + `tokens_ext.txt` (`data/names.txt` plus leaf/path tokens mined from those names) — the inputs for the per-cycle `hashcracker mutate` phase (`FINDINGS.txt` §33). |
| `derive_tex_siblings.py` | `derived_tex.txt` — every unit/decal/prop/block we hold **plus its `_diff`/`_norm`/`_spec` maps**, and the parent of every map (both directions). Seeds and namespaces are discovered from the data, and the suffix list is the canonical `data/suffixes.txt`, so it is never narrower than `mutate`'s suffix step — but it costs ~1 s instead of a mutate cycle, so it runs as phase 0 of `auto_run.sh` and `sweeps/tex_derive.sh`. Validated by re-deriving the map names we already hold: **100 % recall** (511/511). |
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
| `auto_run.sh [cycles]` | All families (map-siblings → particles → bundle-scoped → lua keys → blocks → textures → **mutate**) until a cycle finds nothing. Phase 0 re-derives every unit/decal map sibling, so a name recovered by any other phase gets its `_diff`/`_norm` tried in the same cycle. |
| `tex_derive.sh [rounds]` | The map-sibling derivation on its own (`derive_tex_siblings.py` → `crack --candidates`), looped to fixpoint; log `work/texderive/status.log`. Cheap enough to run after *every* merge. |
| `big_run.sh [rounds]` | The wide battery: shader grammar → 80k-token mutate → `auto_run` → every specialist sweep (blocks/tex/unit/level/context), each stage wrapped in `timeout` so no oversized vocabulary can run away (`FINDINGS.txt` §34). |
| `blocks_pipeline.sh [rounds]` | Unit grammar → unit edit-1 → unit→map-texture derivation. |
| `tex_pipeline.sh [rounds]` | `tex_*` vocab sweep → block derivation → unit edit-1. |
| `unit_big.sh [rounds]` | The wide unit grammar sweep. |
| `unit_medium.sh [rounds]` | Medium unit sweep: grammar + double widths + modifiers, edit-1 and unit<->texture derivation, looped (`FINDINGS.txt` §22). |
| `level_phase2.sh [rounds]` | Quilt `start_`/`NN 01-24`/mod patterns. |
| `level_full.sh [rounds]` | The whole `.level` family, tier by tier (`FINDINGS.txt` §37): schema → 1-char cell neighbourhood → legal codes → other families (tiles/arena/colosseum) → rooms/prefabs → mutate, plus a **deep tier** that enumerates every cells code with 1-3 cell sides in full (4 locked slots, no huge word list). `DEEP=n` controls how many rounds get the deep tier. |
| `level_context.sh [rounds]` | The **context-conditioned** level ladder (`FINDINGS.txt` §37): 18 (env, sub) contexts, pattern literals pinning the prefix, then 10 cheap stages widening one field at a time + (with `DEEP=1`) three deep stages that cross new cell codes / all variant numbers with the whole enemy-group vocabulary. This is the tier that finds the group-name mods (`juggernauts`, `statues_mixed`). |
| `pack_sweep.sh <pack> [rounds]` | Hyper-targeted sweep of ONE resource package: mutate inside its own names + dir×token + token pairs/triples, looped to fixpoint (`FINDINGS.txt` §36). |
| `pack_sweep_all.sh [rounds]` | `pack_sweep.sh` over the 20 packs with the most unresolved hashes, biggest first. |
| `big_mutate.sh [cycles]` | Loop `hashcracker mutate` over the whole corpus, escalating the token budget every 4th cycle (80k→400k) — status in `work/bigmutate/status.log` (`FINDINGS.txt` §34). |
| `audio_hunt.sh` | The quad-pattern audio bank hunt (`FINDINGS.txt` §36, closed: the bank names need Arrowhead's Wwise metadata). |
| `context_sweep.sh [rounds]` | Lua-derived candidates (derive/anim/ability). |

## legacy/ — superseded, kept for reference

`prepare.py`, `make_vocab.py`, `derive_textures.py` and the old `*_sweep*.sh` /
`big_run.sh` / `ui_sweep.sh` cartesian drivers. Superseded by `tools/build_targets.py`,
the `tools/make_*_vocab.py` builders and the `generators/` + `sweeps/` set. See
`legacy/README.md`.
