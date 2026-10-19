# Gauntlet Delve

Reverse-engineering for **Gauntlet: Slayer Edition**
(Bitsquid/Stingray engine): two tool trees (`scripts/`, `hashcracker/`) and one
data tree (`Data/`).

```
Gauntlet-Reverse-Engineering/
+-- scripts/                     <- Python RE toolchain
|   +-- *.py, SCRIPTS.md             <- the tools (flat module dir) + script index
|   +-- resource_tools/              <- 16-type resource read/write suite
|
+-- hashcracker/                 <- Rust MurmurHash64A name brute-forcer (GPU/CPU)
|   +-- src/                         <- murmur.rs, pattern.rs, arena.rs, gpu.rs (WGSL), main.rs
|   +-- tools/                       <- build_targets.py, make_*_vocab.py, merge_matches.py, ...
|   +-- generators/                  <- per-family candidate generators
|   +-- legacy/                      <- superseded scripts (legacy/README.md)
|   +-- data/                        <- generated vocabularies + targets (data/README.md)
|   +-- Cargo.toml, Cargo.lock
|   +-- README.md, SCRIPTS.md
|
+-- Data/                        <- every finding, in one place (see Data/README.md)
    +-- FINDINGS.txt                 <- MASTER format document (all discoveries)
    +-- LEVEL_RECORD_LAYOUT.md       <- the authoritative .level record field map (9H.36)
    +-- CUSTOM_ASSET_LOADING_FINDINGS.md
    +-- DEP/                         <- archived + guide docs (DEP/README.md)
    +-- hash_database.json           <- 142k name->hash dictionary
    +-- bundle_name_overlay.json     <- recovered bundle names
    +-- resource_name_overlay.json   <- recovered resource names
    +-- bundle_manifest/             <- the resource catalogue (00_file_tree ... 12_...)
    +-- matches.tsv                  <- append-only hit log from every sweep
```

## Key entry points

- **Catalogue everything**: `cd scripts && python3 list_game_bundles.py`
  (writes `Data/bundle_manifest/00...05`).
- **Recover names**: build targets with `hashcracker/tools/build_targets.py`,
  generate candidates with the `hashcracker/tools/make_*_vocab.py` /
  `make_*_patterns.py` builders and the `hashcracker/generators/` set, then crack
  with the `hashcracker` engine (`crack`, `mutate`, `substitute`, `mine`) and fold
  hits back with `hashcracker/tools/merge_matches.py`, then re-run
  `list_game_bundles.py --only resources`.  Every engine is driven by the names we
  hold, so re-run them after each batch of newly recovered names.
- **Harvest names from bundle bodies**: `hashcracker/tools/harvest_depot.py`
  decompresses every zlib block in a bundle body - which `grep` reports as
  string-free - and `mine_harvest_{names,ids,paths}.py` hash those strings against
  the unresolved set.
- **Script indexes**: `scripts/SCRIPTS.md` and `hashcracker/SCRIPTS.md`
  (every tool, grouped by purpose).
- **Findings / current state**: `Data/FINDINGS.txt` (#17 history;
  #18 = state of play; #44-48 = the level grammar and the atlas/chain levers).
- **Data index**: [`Data/README.md`](Data/README.md) - which files are canonical
  sources and which are derived from them.

## Notes

- `scripts/` is a **flat module directory** - the `.py` tools import each other by
  module name, so keep them together in one folder.
- `Data/bundle_manifest/` is built by `scripts/list_game_bundles.py` from the game
  install plus the recovered-name overlays; `Data/matches.tsv` is the append-only
  hit log the cracker writes.
