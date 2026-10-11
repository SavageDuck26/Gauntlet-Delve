#!/usr/bin/env python3
"""Enumerate shader_library chains: `technique:flag:flag:...` with flags SORTED.

    python3 tools/enumerate_chains.py | python3 tools/check_names.py --write

A chain name is a technique plus a *sorted subset* of flags.  `mutate --chain-depth`
walks that space per seed name, which repeats the same subset enumeration once for
every chain we hold (448 of them).  Enumerating it once here instead - technique x
subsets of size 0..N over the flag pool - is the same space at a fraction of the
work, and it can afford a deeper subset than the walk does.

The flag pool is every `:`-separated segment of every shader_library name we hold
(plus the shader_library_group and render_config tokens, which describe the same
machinery), because those segments are exactly the engine's shader_pass_flags
(FINDINGS 60.14).  Techniques are the known ones plus a handful of names the engine
famously has (`billboard`, `decal_projector`, `psvita_gbuffer_stencil`, ...).
"""
from __future__ import annotations

import itertools
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mine_type_tokens import known_by_type                            # noqa: E402
from named_textures import load_names                                 # noqa: E402

EXTRA_TECHNIQUES = ["base", "billboard", "decal_projector", "psvita_gbuffer_stencil",
                    "depth_only", "shadow", "outline", "ui", "menu", "water",
                    "terrain", "sky", "particle", "sprite", "flipbook"]

# A flag is a word the engine can turn on, and the engine's words are recognisable:
# shader-y tokens from anywhere in the corpus make the pool wider than the flags we
# happen to hold.  `enemy` and `silhouette` were needed for the first new chain
# (`character:enemy:silhouette:silhouette_decals_group_level`, 61.9) and neither was
# in a held chain name.
FLAGISH = ("map", "group", "pass", "flag", "blend", "proj", "tint", "scale", "alpha",
           "mask", "light", "invert", "swap", "depth", "stencil", "blur", "fade",
           "decal", "instance", "vertex", "rotation", "clip", "cutout", "fresnel",
           "rim", "glow", "emissive", "specular", "normal", "diffuse", "detail",
           "macro", "parallax", "uv", "world", "local", "screen", "additive",
           "multiply", "silhouette", "enemy", "character", "outline", "gray", "grey",
           "color", "colour", "rgb", "one", "bit", "two", "sided", "double", "show")


def main() -> int:
    max_flags = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    wide = "--wide" in sys.argv[2:] or "-w" in sys.argv[2:]
    bytype = known_by_type()
    names = set(load_names(all_types=True).values())
    seeds = set(bytype.get("shader_library", ())) | set(bytype.get("shader_library_group", ()))

    techs: set[str] = set()
    flags: set[str] = set()
    for n in seeds:
        leaf = n.rsplit("/", 1)[-1]
        if ":" not in leaf:
            continue
        parts = leaf.split(":")
        techs.add(parts[0])
        flags.update(p for p in parts[1:] if p)
    # the group/render_config vocabularies name the same flags
    for t in ("shader_library_group", "render_config"):
        for n in bytype.get(t, ()):
            flags.update(x for x in n.rsplit("/", 1)[-1].split("_") if len(x) > 2)
    if wide:
        # whole-corpus tokens that look like engine flag words, alone or compounded
        cand: set[str] = set()
        for n in names:
            leaf = n.rsplit("/", 1)[-1]
            for tok in leaf.replace(":", "_").split("_"):
                if len(tok) > 2:
                    cand.add(tok)
        flags.update(c for c in cand if any(f in c for f in FLAGISH))
    flags = {f for f in flags if f and not f.isdigit()}
    for x in EXTRA_TECHNIQUES:
        techs.add(x)
    techs = {t for t in techs if t}

    out = sys.stdout
    seen: set[str] = set()
    pool = sorted(flags)
    for tech in sorted(techs):
        for k in range(0, max_flags + 1):
            for combo in itertools.combinations(pool, k):
                name = ":".join((tech,) + combo) if combo else tech
                if name not in seen:
                    seen.add(name)
                    out.write(name + "\n")
    print(f"{len(seen)} chains ({len(techs)} techniques x subsets<= {max_flags} of "
          f"{len(pool)} flags)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
