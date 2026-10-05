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
  --out rust_matches.json --tsv rust_matches.tsv
```

### Pattern language
`%X` is a slot bound to a word list via `--list X=FILE`; `%%` is a literal `%`.
A slot is **locked** within a pattern, so `characters/%n/%n_diff` expands to
`characters/<w>/<w>_diff` for each `w`. Generation is index-addressed
(mixed-radix) so the whole space is evaluated in parallel with rayon.

Common slots: `%d` dirs, `%n` names, `%p` prefixes, `%s` suffixes, `%k` numbers.

### Other options
`--threads N`, `--show N`, `--limit N` (cap per pattern, for testing).

## mine (word-list pruning)

Keep only dictionary words that actually occur in a corpus (aho-corasick):

```bash
./target/release/hashcracker mine --dict data/names.txt --corpus some.bin ...
```

## Results

Matches are written as `{"<hash-hex>": "<name>"}` (JSON) / TSV. Merge the TSV
into `../GauntletGameDigging/resource_name_overlay.json`, which
`list_game_bundles.py` loads automatically.

So far it has recovered **50+ resource names** the Python pass missed
(e.g. `equipment/warrior/set_01..09`, `decals/sand_01`, `core/rendering/util`,
`characters/gib_generic/gibs_diff`).

## License

GPL-3.0-or-later (see repo root `LICENSE`).
