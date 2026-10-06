#!/usr/bin/env python3
"""
Enumerate shader_library names as <technique>:[flags...].

The engine names a compiled shader library as a technique followed by its flags,
and the flags are sorted alphabetically:

    billboard:blend_additive:diffuse_map:rotation:vertex_color
    base:deferred_decals_group_prop:diffuse_map:normal_map:one_bit_alpha
    skin_filter:direction_x:step1

839 of our 851 known shader_library names follow that rule exactly, so the
unresolved ones are enumerable instead of guessable: for every technique, take
the flag vocabulary that technique is actually seen with and emit every sorted
subset up to the longest chain that technique is known to use.  The whole space
over the shipped catalogue is ~200k candidates (milliseconds on the GPU).

    python3 generators/shader_chains.py                    # -> /tmp/shader_chains.txt
    python3 generators/shader_chains.py --global-flags 3   # also mix flags across
                                                           # techniques (bigger space)

Workflow:
    ./target/release/hashcracker crack --gpu \
        --targets data/vocab/targets_shader_library.txt \
        --candidates /tmp/shader_chains.txt --matches matches.tsv
"""
import argparse
import csv
import itertools
import pathlib
import re
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
CATALOGUE = (HERE.parent.parent / "GauntletGameDigging" / "bundle_manifest"
             / "04_bundle_resources.csv")

# The technique names are themselves composites: the shipped set contains
# psvita_omni_light / psvita_spot_light / psvita_gbuffer_stencil (PS Vita
# emulation renderer), mobile_blend / mobile_copy / mobile_light, and
# spot_light_debug_lights / omni_light_debug_lights / resource_blend_debug_lights.
# --composite-depth widens the technique pool with those shapes.
TECH_PREFIXES = ("", "psvita_", "mobile_", "emulate_", "ps4_", "xbox1_", "pc_")
TECH_SUFFIXES = ("", "_debug_lights", "_cheap", "_marker", "_far", "_hq", "_lq")


def flag_variants(flags) -> list[str]:
    """Siblings of the known flags: the shipped set uses numbered/paired flags
    (step0-2, iter1-3, octave_2-3, separable_gaussian_13tap_x/_y, ssao_hq/_lq,
    nv_dof_compute_radius/_far), so close variants are worth testing."""
    out = set(flags)
    for f in flags:
        m = re.match(r"^(.*?)(\d)$", f)
        if m:
            out.update(f"{m.group(1)}{d}" for d in "0123456789")
        if f.endswith("_x"):
            out.add(f[:-2] + "_y")
        elif f.endswith("_y"):
            out.add(f[:-2] + "_x")
        for a, b in (("_far", "_near"), ("_near", "_far"), ("_hq", "_lq"),
                     ("_lq", "_hq"), ("_hi", "_lo"), ("_lo", "_hi")):
            if f.endswith(a):
                out.add(f[: -len(a)] + b)
    return sorted(out)


def load(catalogue: pathlib.Path):
    """Return {technique: {flag: count}} plus the ordered flag vocabulary."""
    rows = csv.DictReader(catalogue.open(newline="", encoding="utf-8",
                                          errors="replace"))
    per_tech: dict[str, Counter] = defaultdict(Counter)
    global_flags: Counter = Counter()
    for r in rows:
        if r.get("type") != "shader_library" or not r.get("name"):
            continue
        parts = r["name"].split(":")
        tech, flags = parts[0], parts[1:]
        per_tech[tech].update(flags)
        global_flags.update(flags)
    return per_tech, global_flags


def chains(per_tech, global_flags, global_depth: int = 0, only: str | None = None,
           composite_depth: int = 0, variants: bool = False):
    """Yield candidate names; global_depth > 0 widens each technique's flag pool
    with the vocabulary seen on *other* techniques (sorted subsets only).
    composite_depth > 0 additionally explores prefixed/suffixed technique names.
    variants expands the cross-technique flag pool with numbered/paired siblings."""
    wide = flag_variants(global_flags) if variants else sorted(set(global_flags))
    for tech, flags in per_tech.items():
        if only and tech != only:
            continue
        own = list(flags)
        longest = max(
            (len(n.split(":")) - 1 for n in _KNOWN_CACHE.get(tech, [0])),
            default=0)
        yield tech
        for k in range(1, longest + 1):
            for combo in itertools.combinations(own, k):
                yield ":".join((tech, *combo))
        if global_depth:
            pool = sorted(set(own) | set(wide))
            for k in range(1, global_depth + 1):
                for combo in itertools.combinations(pool, k):
                    yield ":".join((tech, *combo))
        if composite_depth:
            for pre in TECH_PREFIXES:
                for suf in TECH_SUFFIXES:
                    variant = pre + tech + suf
                    if variant == tech or variant in per_tech:
                        continue
                    yield variant
                    for k in range(1, composite_depth + 1):
                        for combo in itertools.combinations(wide, k):
                            yield ":".join((variant, *combo))


_KNOWN_CACHE: dict[str, list[str]] = {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default=str(CATALOGUE))
    ap.add_argument("--out", default="/tmp/shader_chains.txt")
    ap.add_argument("--global-flags", type=int, default=0,
                    help="also emit global-flag subsets up to this length")
    ap.add_argument("--technique", default=None,
                    help="only emit for this technique (loop-friendly)")
    ap.add_argument("--composite-depth", type=int, default=0,
                    help="also try prefixed/suffixed technique names "
                         "(psvita_, mobile_, _debug_lights, _cheap, ...)")
    ap.add_argument("--flag-variants", action="store_true",
                    help="expand the cross-technique flag pool with numbered/"
                         "paired siblings (step0-9, iter0-9, _x/_y, _hq/_lq, ...)")
    args = ap.parse_args()

    catalogue = pathlib.Path(args.catalogue)
    # remembers how long the chains of each technique get
    rows = csv.DictReader(catalogue.open(newline="", encoding="utf-8",
                                         errors="replace"))
    for r in rows:
        if r.get("type") == "shader_library" and r.get("name"):
            _KNOWN_CACHE.setdefault(r["name"].split(":")[0], []).append(r["name"])

    per_tech, global_flags = load(catalogue)
    n = 0
    seen = set()
    with open(args.out, "w", encoding="utf-8") as fh:
        for name in chains(per_tech, global_flags, args.global_flags, args.technique,
                           args.composite_depth, args.flag_variants):
            if name not in seen:
                seen.add(name)
                fh.write(name + "\n")
                n += 1
    print(f"techniques {len(per_tech)}  flags(global) {len(global_flags)}  "
          f"candidates {n} -> {args.out}")


if __name__ == "__main__":
    main()
