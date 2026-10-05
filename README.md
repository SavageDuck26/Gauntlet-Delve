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
├── .clinerules                  ← project rules (READ FIRST)
├── .gitignore                   ← what is NOT tracked (venv, outputs, downloads…)
├── .vscode/                     ← editor settings
├── .venv/                       ← Python virtualenv (untracked, do not edit)
│
├── Scripting/GauntletGameDigging/   ← Python RE toolchain (the main work area)
│   ├── docs/                        ← all documentation
│   │   ├── FINDINGS.txt                 ← MASTER format document
│   │   ├── CUSTOM_ASSET_LOADING_FINDINGS.md
│   │   ├── Hash Dictionary.txt
│   │   ├── DEP/                         ← dependency/guide docs (+ verify_bundle.py)
│   │   └── Stingray_Documentation/      ← reference images
│   ├── *.py                         ← ~80 tools (flat dir, imported as modules)
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
├── game-source/Gauntlet-SourceCode-LUA/   ← game Lua source (927 files)
├── reference/                             ← reference projects (downloads)
│   ├── Loremasters-Armoury-main/
│   ├── Vermintide-Mod-Framework-master/
│   └── Alloy/
└── assets/                                ← *.glb models + exported samples
```

## Key entry points

- **Catalogue everything**: `cd Scripting/GauntletGameDigging && python3 list_game_bundles.py`
  (writes `bundle_manifest/00…05`).
- **Brute-force names**: `python3 crack_bundle_names.py` /
  `python3 crack_resource_names.py` (write `*_overlay.json`, auto-merged by the catalogue).
- **Findings**: `Scripting/GauntletGameDigging/docs/FINDINGS.txt`.

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

Ignored (see [`.gitignore`](.gitignore)): `.venv/`, `__pycache__/`, generated
catalogues/overlays, `reference/` downloads, `wwise-unpacker-revamped/` binaries,
and bulk extract output.
