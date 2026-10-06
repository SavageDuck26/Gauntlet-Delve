# hashcracker

A multithreaded **MurmurHash64A** brute-forcer for Gauntlet resource/bundle
*names*. Bundle filenames and resource-name hashes are `MurmurHash64A(path, 0)`
(lowercase, little-endian); given a set of target hashes this tool enumerates
candidate paths from templates + word lists and reports the ones that match.

It is the fast complement to the Python toolchain
(`../GauntletGameDigging/crack_*_names.py`): where Python handles a few million
candidates, this handles **billions** in seconds.

## Layout

```
hashcracker/
├── src/                  Rust: murmur.rs, pattern.rs, gpu.rs (WGSL), main.rs
├── tools/                target + vocabulary builders (the maintainer entry points)
│   ├── build_targets.py      catalogue -> data/vocab/targets_<type>.txt
│   ├── merge_matches.py      matches.tsv -> resource_name_overlay.json
│   └── make_*_vocab.py       one word-list builder per family (tex/lvl/par/unit)
├── generators/           candidate generators (name-derived, context constrained)
│   ├── targeted_*.py         per-family generators (anim, unit, level, tex, gui…)
│   └── *_cands.py, *_check.py, scan_bundle_paths.py   supporting miners
├── sweeps/               driver scripts (loop a family set to a fixpoint)
├── legacy/               superseded scripts, kept for reference (see legacy/README.md)
├── data/vocab/           vocabularies + targets (see data/README.md)
├── matches.tsv           append-only hit log, `<hash>\t<name>` (tracked)
└── README.md, SCRIPTS.md
```

See **[SCRIPTS.md](SCRIPTS.md)** for every script and when to use it.

## Current state (2026-10-05)

* overlay: **5,087** names · **2,457** unique unresolved hashes
* catalogue: 20,000 resources, **13,070 named** (65.4%), 6,930 unresolved rows
* GPU: ~0.7–1.2 G candidates/s (AMD RX 6600 XT, RADV) vs ~0.15 G/s on 12 CPU threads

Remaining by family: `texture 709 · shader_library 538 · animation 415 ·
material 370 · particles 322 · unit 181 · level 175 · shader 49 · timpani_bank 37`.

That set is now limited by **missing source data**, not by generation strategy —
the shipped Lua, bundle bodies and binaries contain no further name material.
The audit of everything tried (and why it failed) is in
`../GauntletGameDigging/docs/FINDINGS.txt` §17.18–17.20 and §18.

## Build

```bash
cargo build --release            # (offline: cargo build --release --offline)
```

## Prepare inputs

Legacy (superseded by `tools/build_targets.py` + the `tools/make_*_vocab.py`
builders — kept in `legacy/` for reference):

```bash
python3 legacy/prepare.py \
  --csv  ../GauntletGameDigging/bundle_manifest/04_bundle_resources.csv \
  --lua  ~/.local/share/Steam/steamapps/common/Gauntlet/Gauntlet-Source-DO_NOT_EDIT \
  --binaries ~/.local/share/Steam/steamapps/common/Gauntlet/binaries \
  --out data
```

Current workflow — see [SCRIPTS.md](SCRIPTS.md) for the full index and
[`data/README.md`](data/README.md) for the vocabulary files:

```bash
python3 tools/build_targets.py          # targets_<type>.txt from the catalogue
python3 tools/make_tex_vocab.py         # one vocabulary per family (tex_*, lvl_*, …)
python3 generators/targeted_unit.py     # name-derived candidates
./sweeps/auto_run.sh 3                  # cycle every family to a fixpoint
```

## Crack

```bash
./target/release/hashcracker crack \
  --targets data/targets.txt \
  --list d=data/dirs.txt --list n=data/names.txt \
  --list p=data/prefixes.txt --list s=data/suffixes.txt \
  --pattern '%d/%n' --pattern '%d/%n%s' --pattern '%p/%n%s' --pattern '%n%s' \
  --matches matches.tsv
```

Matches are **streamed to `--matches` (default `matches.tsv`) the moment they are
found** — one TSV line each, `<hash-hex><TAB><name>`. The file is opened in
append mode and its hashes are loaded at start-up, so **re-runs never write a
duplicate**. Just sort it however you like:

```bash
sort -k2 matches.tsv
```

### Pattern language
`%X` is a slot bound to a word list via `--list X=FILE`; `%%` is a literal `%`.
A slot is **locked** within a pattern, so `characters/%n/%n_diff` expands to
`characters/<w>/<w>_diff` for each `w`. Generation is index-addressed
(mixed-radix) so the whole space is evaluated in parallel with rayon.

Common slots: `%d` dirs, `%n` names, `%p` prefixes, `%s` suffixes, `%k` numbers.

### Other options
`--threads N`, `--exclude F` (skip already-solved hashes), `--limit N` (cap per
pattern, for testing).

### Performance
The hot loop is division-free: each thread is handed one contiguous slice of the
index space, decodes its start index once (mixed-radix), then walks it with an
**odometer**. Target lookup uses a small open-addressed `u64` set (no SipHash),
and the build uses `-C target-cpu=native` (see `.cargo/config.toml`). Throughput
is typically **~150–200 M candidates/s** across ~12 cores.

## GPU acceleration (optional, automatic)

When a Vulkan adapter with 64-bit shader integers is available the pattern
evaluation runs on the **GPU** (wgpu + WGSL); otherwise it silently uses the
CPU. Force it with `--gpu` (fail if unavailable) or `--cpu`.

```bash
./target/release/hashcracker crack --targets data/vocab/unresolved_targets.txt \
  --list d=data/dirs.txt --list a=data/vocab/medium_dict.txt --list b=data/vocab/medium_dict.txt \
  --pattern '%d/%a_%b' --matches matches.tsv      # picks GPU automatically
```

Measured on an AMD RX 6600 XT (RADV): **~1.24 G candidates/s**, versus
~0.06–0.26 G/s on 12 CPU threads — i.e. roughly **5–12x** depending on how much
string assembly a pattern needs. A 42-billion-candidate sweep takes ~34 s.

Correctness: the kernel only ever reports candidate **indices**; the host
re-emits each index with the CPU emitter and re-hashes it before recording, so a
GPU arithmetic bug can never write a wrong name. `crack --gpu` output has been
diffed against `crack --cpu` on a 48,000-candidate space with 900 planted
targets and is byte-identical.

Implementation notes (src/gpu.rs):

* MurmurHash64A needs 64-bit multiplies -> the device must expose
  `wgpu::Features::SHADER_INT64`.
* Dispatches are sized to ~0.3 s of work because amdgpu's scheduler watchdog
  kills long-running dispatches (same batching trick as Duckomp-v5).
* WGSL gotchas worked around: `meta` is a reserved word; integer literals above
  `i64::MAX` cannot be represented (the 64-bit constants are stored as negative
  `i64` bit patterns and `bitcast` to `u64`); shift amounts must be `u32`;
  mixed-width literals need explicit `u64(...)` conversions.
* Patterns with more than 8 slots fall back to the CPU.


Keep only dictionary words that actually occur in a corpus (aho-corasick):

```bash
./target/release/hashcracker mine --dict data/names.txt --corpus some.bin ...
```

## Context-driven generation (preferred over cartesian sweeps)

Blind sweeps burn GPU time on candidate spaces of 1e12+. The shipped Lua is the
naming authority for the game, so constrain candidates with it instead —
millions of candidates, seconds of runtime, and hits the cartesian scripts miss
entirely (4-token clips like `axe_move_walk_left_back`, extension-less Lua
paths, unit/material names referenced as Lua strings).

```bash
./sweeps/context_sweep.sh 4     # merge -> rebuild targets -> regenerate -> crack
```

| tool | what it generates |
| --- | --- |
| `tools/build_targets.py` | `data/vocab/targets_<type>.txt` + `unresolved_targets.txt` |
| `generators/derive_cands.py` | Lua file paths, all Lua string literals, known dir x Lua leaf |
| `generators/lua_ability_cands.py` | `ability_selection` keys (bare Lua identifiers) x anim shapes |
| `generators/targeted_anim.py` | edit-distance-1 of each unit's own clips + cross-unit transfer |

### Two traps this tooling exists to avoid

1. **Never measure "unresolved" against the overlay.** The catalogue
   (`bundle_manifest/04_bundle_resources.csv`) resolves names from
   `hash_database.json` (142k entries) *plus* both overlays. A target file built
   as "hash absent from `resource_name_overlay.json`" overstates the unknown set
   by thousands of entries, and a stale target file silently reports
   `new matches: 0`. Targets = *rows whose catalogue `name` column is empty*
   (`tools/build_targets.py` does exactly this).
2. **Table keys, not just string literals.** Ability names, quilt pieces and
   status effects are bare Lua identifiers — invisible to string mining. Mine
   `^\t+key\s*=` inside the relevant tables as well.

`tools/merge_matches.py` folds `matches.tsv` into the overlay, then re-run
`list_game_bundles.py --only resources` (in `GauntletGameDigging/`) to refresh
`03_bundle_resources.txt` + `04_bundle_resources.csv` with the new names.

### What the Lua gave up

| family | result |
| --- | --- |
| `lua` | every `*.lua` path minus the extension resolves the whole family |
| `material` / `unit` | Lua string literals (paths referenced by tables) |
| `animation` | edit-distance-1 from a unit's own clips (`_backward`, `_enter/_exit/_init`) + cross-unit clip transfer + ability-table keys |
| leftovers | `texture`, `shader_library`, `particles`, `level` are not path-like; they need family-specific generators |

### Levels: the quilt naming schema (`modules/<env>/…`)

`lua/dungeon/quilt_builder.lua` decodes the level names:

```lua
name:match("^%w+_quilt_(%w+)__([^_]+)_([^_]+)_([^_]+)_([^_]+)__(.*)$")
local w = #u    -- quilt width  in cells
local h = #r    -- quilt height in cells
```

so a quilt name is `<env>_quilt_<shape>__<up>_<right>_<down>_<left>__<variant>`
where the four groups are the **cell rows of the four sides**, each cell being
`x` (wall), `e` (through), `i` (entrance) or `o` (exit), with
`len(up) == len(down) == w` and `len(right) == len(left) == h`.  Observed side
lengths are 1, 2, 3 and 5 cells (never 4).  The variant is `NN`, `NN_<mod>` or
`start_NN` (crypt entrances).

That rule is what makes the sweep work: enumerating the *observed groups* only
(38 codes) finds nothing, because several 1-cell sides (`o`, `i`) never appear
in the resolved corpus.  Enumerating the alphabet under the width/height rule
(`tools/make_level_vocab.py`) immediately produced new pieces such as
`crypt_quilt_smallroom__o_e_i_e__01`.

```bash
python3 tools/make_level_vocab.py          # lvl_env/sub/shape/edge/nn/mod vocab files
./target/release/hashcracker crack --gpu \
  --targets data/vocab/targets_level.txt \
  --list a=data/vocab/lvl_env.txt  --list b=data/vocab/lvl_sub.txt \
  --list s=data/vocab/lvl_shape.txt --list e=data/vocab/lvl_edge.txt \
  --list n=data/vocab/lvl_nn.txt   --list m=data/vocab/lvl_mod.txt \
  --pattern 'modules/d01_%a/%b/%a_quilt_%s__%e__%n' \
  --pattern 'modules/d01_%a/%b/%a_quilt_%s__%e__%n_%m' \
  --matches matches.tsv
```

Level bodies are compiled modules with **no embedded names** (checked with
`generators/level_body_strings.py`), and the module `package` blobs list dependency
**hashes only**, hash-sorted and not name-sorted (`generators/pkg_order_check.py`), so they
give no alphabetical bracketing either — the grammar is the only lever.

## Results

All hits accumulate in **`matches.tsv`** (append + dedup). To fold them into the
catalogue, merge that TSV into `../GauntletGameDigging/resource_name_overlay.json`
(which `list_game_bundles.py` loads automatically):

```bash
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path('../GauntletGameDigging/resource_name_overlay.json')
ov = json.loads(p.read_text())
for line in pathlib.Path('matches.tsv').read_text().splitlines():
    if '\t' in line:
        h, n = line.split('\t', 1); ov[h] = n
p.write_text(json.dumps(ov, indent=2, sort_keys=True))
EOF
```

So far it has recovered **90 resource names** the Python pass missed
(e.g. `equipment/warrior/set_01..09`, `decals/sand_0N`, `menu/shop/*`,
`effects/hit_*`, `core/rendering/util`, `characters/gib_generic/gibs_diff`).

## License

GPL-3.0-or-later (see repo root `LICENSE`).
