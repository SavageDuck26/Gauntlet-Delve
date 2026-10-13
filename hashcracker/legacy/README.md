# legacy/ — superseded scripts

Kept for reference only; the current equivalents are in `../tools/` and
`../generators/`. These are **cartesian** drivers and the inputs they need
(the flat `data/` word lists) predate `data/vocab/`, so they are not expected to
run as-is.

| file | superseded by |
| --- | --- |
| `prepare.py` | `../tools/build_targets.py` + the `../tools/make_*_vocab.py` builders (targets now come from the catalogue's blank `name` column, not from "hash absent from the overlay"). |
| `make_vocab.py`, `derive_textures.py` | `../tools/make_tex_vocab.py`, `../tools/make_unit_vocab*.py`. |

Why they were retired: at 10¹²+ candidates they spent GPU-minutes per hit and
still missed everything whose *shape* was wrong (4-token clips, extension-less
Lua paths, table keys). The replacements generate from known names and structured
schemas, which is ~4 orders of magnitude cheaper per hit — see
`../../Data/FINDINGS.txt` §17.18.
