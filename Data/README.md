# Data/ - every finding, in one place

Everything the reverse-engineering produced. None of it is derivable from the repo
alone - the databases, the overlays and the catalogue are built from the game - so
it is all versioned here.

## Sources (canonical)

| file | what it holds | built by |
| --- | --- | --- |
| `hash_database.json` | 142,060 `name -> hash` pairs - the name dictionary the catalogue resolves against | `scripts/build_hash_database.py` |
| `matches.tsv` | the append-only hit log every crack appends to (`<hash>` TAB `<name>`) | the `hashcracker` engine |

## Derived from the sources + the game

| file | what it holds |
| --- | --- |
| `resource_name_overlay.json` | recovered resource names (`hash -> name`); the tooling loads this |
| `bundle_name_overlay.json` | recovered *bundle* names |
| `bundle_manifest/` | the resource catalogue: `00_file_tree` ... `12_names_by_bundle` |
| `runtime_units/` | per-level engine capture: one JSON per level - what the running engine reports for each unit's position and rotation. 27 levels, 67,682 units. This is what settled the `.level` rotation decode (FINDINGS §9H.6) and what the manifest is for |

## Documents

| file | what it is |
| --- | --- |
| `FINDINGS.txt` | the master document - every format finding, in order (the research log) |
| `CUSTOM_ASSET_LOADING_FINDINGS.md` | the in-game-proven custom unit / material / texture recipe |
| `DEP/` | archived, superseded modding docs - see [`DEP/README.md`](DEP/README.md) |

## Capturing `runtime_units/` (needs a game run, not a script)

The engine has to be run with the `LevelProbe` mod from `GauntletModLoader`. Loading
a level makes the engine report that level's units through its own API, and the
loader writes one JSON per level under `<game>/binaries/levels/`. Copy them here:

```bash
cp "<game>/binaries/levels/"*.json Data/runtime_units/
```

Each file is named after the level the engine loaded and holds `index`, `pos`, `rot`
and `name_hash` per unit - the values are exactly what the engine returned, nothing
recomputed. `name_hash` is `Unit.debug_name(unit)`, the same value a `.level` carries
at record offset 32, which is what makes the join possible.

The captured set is the campaign: all crypt / caves / lava rooms and arenas plus the
campaign's menu and loadout screens. Not captured, because they never came up in
play: the four `room_crypt_floor3_*_wing` rooms, `room_lava_floor3` and
`room_lava_floor_10_boss_felix`.

## Regenerating the catalogue

From `scripts/` (order matters - `09_`/`10_` feed `08_`):

```bash
python3 ../hashcracker/tools/merge_matches.py ..   # matches.tsv -> overlay
python3 list_game_bundles.py                       # install + overlay -> 00..05
python3 make_name_index.py                         # 04 + overlay      -> 06 / 07
python3 reachability_audit.py                      # named refs        -> 09 / 10
python3 make_progress_report.py                    # everything        -> 08 (+ 11 / 12)
python3 ../hashcracker/tools/build_targets.py      # catalogue         -> targets_*.txt
```
