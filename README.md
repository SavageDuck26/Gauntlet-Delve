# Gauntlet-Reverse-Engineering — workspace layout

Reverse-engineering + modding workspace for **Gauntlet: Slayer Edition**
(Bitsquid/Stingray engine). This is a **git repo**. See [`.clinerules`](.clinerules)
for the project rules, solved/unsolved state, and conventions.

> Reorganized (2026-10): root renamed from `Gauntlet-Stuff`; the C++ loader moved
> out to `../GauntletModLoader`; regenerable output removed; databases, findings
> and all tools kept.

## Layout

```
Gauntlet-Reverse-Engineering/
├── .clinerules                  ← project rules (READ FIRST; local-only, not published)
├── .gitignore                   ← what is NOT tracked (venv, outputs, *.sh, downloads…)
├── .vscode/                     ← editor settings (local-only)
├── .venv/                       ← Python virtualenv (untracked, do not edit)
│
├── Scripting/GauntletGameDigging/   ← Python RE toolchain (the main work area)
│   ├── docs/                        ← all documentation
│   │   ├── FINDINGS.txt                 ← MASTER format document
│   │   ├── CUSTOM_ASSET_LOADING_FINDINGS.md
│   │   ├── Hash Dictionary.txt
│   │   ├── DEP/                         ← dependency/guide docs (+ verify_bundle.py)
│   │   └── Stingray_Documentation/      ← reference images
│   ├── *.py, SCRIPTS.md             ← ~80 tools (flat module dir) + script index
│   ├── resource_tools/              ← 16-type resource r/w suite
│   ├── database_extractor/          ← bundle_database.data extraction
│   ├── decoded_materials/           ← decoded material JSON
│   ├── Exports/                     ← kept databases (extracted_materials, texture_database)
│   ├── bundle_manifest/             ← generated catalogue (00_file_tree … 05_summary)
│   ├── hash_database.json / .txt    ← 142k name→hash database
│   ├── *_overlay.json               ← brute-forced names (bundle + resource)
│   ├── example_mod/ test_mod/ crane_mod/   ← mod projects (referenced by the loader)
│   └── wwise-unpacker-revamped/     ← bundled audio unpacker tool
│
├── Scripting/hashcracker/           ← Rust MurmurHash64A name brute-forcer (billions of candidates/s)
│   ├── src/                             ← Rust: murmur.rs, pattern.rs, gpu.rs (WGSL), main.rs
│   ├── tools/                           ← build_targets.py, make_*_vocab.py, merge_matches.py
│   │   └── (*.sh local-only)            ← hc.sh, status.sh, pull-gpu.sh, guard …
│   ├── generators/                      ← targeted_*.py (per-family candidate generators)
│   ├── sweeps/                          ← per-family driver scripts (LOCAL-ONLY, *.sh)
│   ├── legacy/                          ← superseded cartesian scripts (LOCAL-ONLY, *.sh)
│   ├── data/vocab/                      ← vocabularies + targets (see data/README.md)
│   ├── matches.tsv                      ← append-only hit log (tracked)
│   └── README.md, SCRIPTS.md
│
├── game-source/Gauntlet-SourceCode-LUA/   ← game Lua source (927 files; local-only)
├── reference/                             ← reference projects (downloads; local-only)
│   ├── Loremasters-Armoury-main/
│   ├── Vermintide-Mod-Framework-master/
│   └── Alloy/
└── assets/                                ← *.glb models + exported samples (local-only)
```

## Key entry points

- **Catalogue everything**: `cd Scripting/GauntletGameDigging && python3 list_game_bundles.py`
  (writes `bundle_manifest/00…05`).
- **Harvest names from the depots** (the biggest single lever, `FINDINGS.txt` §45–48):
  `hashcracker/tools/harvest_depot.py` decompresses every zlib block in the
  `Gauntlet-PreSlayer-*/` bundle bodies — which `grep` reports as string-free —
  and writes `work/harvest/{raw,*_ids}.txt`; `mine_harvest_{names,ids,paths}.py`
  hash those against the unresolved set.
- **Recover names (current workflow)**: build targets →
  `Scripting/hashcracker/tools/build_targets.py`; generate candidates →
  `Scripting/hashcracker/tools/make_*_vocab.py` /
  `make_atlas_patterns.py` / `make_chain_candidates.py`; **crack on the GPU**
  (≈20–50× the CPU path) via the `*.sh` drivers `sweeps/auto_run.sh` +
  `subst_run.sh` / `leaf_sweep.sh` / `chain_sweep.sh` / `num_derive.sh`, always
  through `tools/hc.sh` (the `flock` wrapper — one hashcracker at a time); fold
  hits back with `tools/merge_matches.py`, then re-run
  `list_game_bundles.py --only resources`.  Every engine is driven by the names we
  hold, so **re-run them after each batch** — see §48.7.  *(The `*.sh` drivers are
  local-only — see below; the `.py` builders they call are in this repo.)*
- **Script indexes**: `Scripting/hashcracker/SCRIPTS.md` and
  `Scripting/GauntletGameDigging/SCRIPTS.md` (every tool, grouped by purpose).
- **Findings / current state**: `Scripting/GauntletGameDigging/docs/FINDINGS.txt`
  (§17 history; **§18 = state of play**; **§44–48 = the level grammar, the depot
  harvest, and the reference/atlas/chain levers**).  The live numbers live in
  `.clinerules` → *Resource-name recovery state*.

## Notes

- **The C++ mod loader is a separate repo at `../GauntletModLoader/`** (a sibling of
  this folder). Its `rebuild_bundles.py` hardcodes the path to this repo's
  `Scripting/GauntletGameDigging/`, so keep that path. To build: `cd ../GauntletModLoader && ./build.sh`.
- `Scripting/GauntletGameDigging/` is a **flat module directory** — the `.py` tools
  import each other by module name, so keep them together in one folder.
- Regenerable outputs were deleted (`test_*`, `output_*`, `my_textures`, `CONTEXT`,
  bulk `Exports/*`); re-run the relevant tool to recreate them.

## Git

```bash
git status            # tracked files (venv/outputs/downloads are ignored)
git add -A && git commit -m "…"
```

Ignored (see [`.gitignore`](.gitignore)): `.venv/`, `__pycache__/`, **every `*.sh`**,
the generated catalogue (`bundle_manifest/`), `reference/` downloads, and
`wwise-unpacker-revamped/` binaries.

**Game-derived exports/assets are NOT versioned** (copyright + repo size) — they
stay on disk but are excluded from git: `assets/`, `Exports/`, `crane_mod/`,
`example_mod/`, `test_mod/`, `decoded_materials/`, `database_extractor/`,
`.unit orig/`, and the test/extract output dirs.

Versioned here: all tooling (`*.py`, `resource_tools/`), `docs/` (findings), the
name/hash databases (`hash_database.*`, `*_overlay.json`) and the resource
catalogue.  The game **Lua** source (`game-source/`) is **local-only**
(game-derived), like `reference/` and `assets/`.

## Shell scripts & privacy

**No shell script is published.** Every `*.sh` — the `sweeps/*` drivers, the
`tools/*.sh` helpers (`hc.sh`, `status.sh`, `pull-gpu.sh`, `setup-gpu-ssh.sh`,
`harden-box.sh`) and the personal-info guard — is **gitignored and local-only**
(`git ls-files '*.sh'` is empty). Shell drivers carry machine/host specifics
(absolute paths, ssh aliases, LAN addresses), so this repo ships the **Python**
tools and their data; the `.sh` plumbing lives on the machine that runs it.
`hashcracker/SCRIPTS.md` stays as the offline index for whoever has that `.sh` set.

The same rule keeps `.clinerules`, `.vscode/` and `.githooks/` local, and it is why
**no personal data is committed**: local **pre-commit and pre-push** hooks run a
guard that refuses any commit or push carrying a private IPv4 range, a VPN
service/interface, the host name, a hardcoded `/home/<user>` path, key material or
a secret.  Write tools so the personal part simply **isn't there** — a placeholder,
not redaction: `$HOME` / `os.path.expanduser('~/…')`, `"$(dirname "$0")"` for the
tool's own location, an env var for anything machine-specific (`GPU_HOST`,
`GPU_REPO`), or discovery.  A tool that can't be genericised stays off the repo.

## License

Licensed under the **GNU General Public License v3.0** (GPL-3.0) — see
[`LICENSE`](LICENSE).

```
Gauntlet-Reverse-Engineering — reverse-engineering & modding toolchain for
Gauntlet: Slayer Edition.
Copyright (C) 2026 SavageDuck26

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
```

> Game assets, the game Lua source (`game-source/`), `reference/` projects and
> `wwise-unpacker-revamped/` remain the property of their respective owners and
> are **not** covered by this license.
