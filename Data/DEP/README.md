# DEPS - Deprecated / Superseded Documentation

This folder holds **truly old** Gauntlet modding docs that have been superseded
by the July 2026 research. They are kept for historical reference only - **do
not treat them as current.**

> **[!] Note on relative paths:** these files were written for the toolchain root
> (`scripts/`). The paths they mention are now elsewhere, so many commands inside
> are broken - see each file's deprecation banner.

## Archived here

| File | Dated | Why it's here | Superseded by |
|------|-------|---------------|---------------|
| `GLOBAL_TEXTURE_PACKAGE_GUIDE.md` | Jan 9, 2026 | Central claim - "custom texture packages just work" - was **disproven** (7 controlled experiments). | `FINDINGS.txt` #15J (disproof) & #16 (working recipe) |
| `CUSTOM_TEXTURE_MODDING_GUIDE.md` | Jan 9, 2026 | "Approach 1: custom texture packages" is unreliable as written; references a non-existent `texture_loader.lua`. (Approach 2, `replace_textures_v4.py` slot injection, is still valid but is covered by current docs.) | `FINDINGS.txt` #15J/#16; `CUSTOM_ASSET_LOADING_FINDINGS.md` |
| `GAUNTLET_RESOURCE_STRUCTURE.md` | Jan 9, 2026 | Documents the **obsolete 20-byte package-entry format** (`dependency_count`/`dependency_refs`). (Its folder-hierarchy / hash tables are still handy reference.) | `FINDINGS.txt` #9B, #16 |

## Archived scripts

| File | Dated | Why it's here | Superseded by |
|------|-------|---------------|---------------|
| `verify_bundle.py` | Jan 9, 2026 | Parses the **obsolete 20-byte package-entry format** (`off2 += 20 + dep_cnt*4`); only referenced by the archived guide above. | `replace_textures_v4.py::parse_bundle` (authoritative) / `list_textures.py` |

## Current / authoritative docs (one level up, in `Data/`)

- **`FINDINGS.txt`** - the master document (all format findings, #15J/#16 = the
  definitive custom-asset recipe).
- **`CUSTOM_ASSET_LOADING_FINDINGS.md`** - the in-game-proven custom
  unit + material + texture recipe (#10).
- The toolchain that implements it is indexed in
  [`scripts/SCRIPTS.md`](../../scripts/SCRIPTS.md).
