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

## Documents

| file | what it is |
| --- | --- |
| `FINDINGS.txt` | the master document - every format finding, in order (the research log) |
| `CUSTOM_ASSET_LOADING_FINDINGS.md` | the in-game-proven custom unit / material / texture recipe |
| `DEP/` | archived, superseded modding docs - see [`DEP/README.md`](DEP/README.md) |

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
