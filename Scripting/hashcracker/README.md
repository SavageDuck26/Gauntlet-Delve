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

## mine (word-list pruning)

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
