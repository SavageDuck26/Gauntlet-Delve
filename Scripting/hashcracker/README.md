# hashcracker

A multithreaded **MurmurHash64A** brute-forcer for Gauntlet resource/bundle
*names*. Bundle filenames and resource-name hashes are `MurmurHash64A(path, 0)`
(lowercase, little-endian); given a set of target hashes this tool enumerates
candidate paths from templates + word lists and reports the ones that match.

It is the fast complement to the Python toolchain
(`../GauntletGameDigging/crack_*_names.py`): where Python handles a few million
candidates, this handles **billions** in seconds.

## Build

```bash
cargo build --release            # (offline: cargo build --release --offline)
```

## Prepare inputs

```bash
python3 prepare.py \
  --csv  ../GauntletGameDigging/bundle_manifest/04_bundle_resources.csv \
  --lua  ~/.local/share/Steam/steamapps/common/Gauntlet/Gauntlet-Source-DO_NOT_EDIT \
  --binaries ~/.local/share/Steam/steamapps/common/Gauntlet/binaries \
  --out data
```

This writes `data/{targets,dirs,names,prefixes,suffixes}.txt`.

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
