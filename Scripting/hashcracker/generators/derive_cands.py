#!/usr/bin/env python3
"""
Context-driven candidate generation from the shipped Lua tree.

The Lua is the naming authority for the game: it *is* the file set for the
`lua` resource type (paths minus `.lua`) and it references units, materials,
textures, decals, effects and resource packages by string. Everything here is
cheap and high-yield compared with blind cartesian sweeps:

  1. every `*.lua` file path minus the extension   (resolves the whole lua family)
  2. every string literal in the Lua
  3. every known resource directory x every Lua leaf token
  4. ...also with the usual `_01`/`_var01`/`_a` suffixes

Usage:
    python3 derive_cands.py [--out FILE] [--suffixes]
"""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
OVERLAY = REPO / "Scripting/GauntletGameDigging/resource_name_overlay.json"
LUA_ROOT = (Path.home() / ".local/share/Steam/steamapps/common/Gauntlet"
            / "Gauntlet-Source-DO_NOT_EDIT")
LIT = re.compile(r'"([^"\n]{2,90})"')
LEAF_OK = re.compile(r"[a-zA-Z0-9_.-]+$")
SUFFIXES = ("", "_01", "_02", "_03", "_var01", "_var02", "_a", "_b", "_l", "_r")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/derived.txt")
    ap.add_argument("--suffixes", action="store_true",
                    help="also emit _01/_var01/directional variants")
    args = ap.parse_args()

    ov = json.loads(OVERLAY.read_text())
    out = set()

    # 1. Lua file paths (the lua resource family is exactly this set)
    for p in LUA_ROOT.rglob("*.lua"):
        out.add(str(p.relative_to(LUA_ROOT))[:-4])

    # 2. every string literal in the Lua
    literals = set()
    for p in LUA_ROOT.rglob("*.lua"):
        literals.update(s.strip() for s in LIT.findall(p.read_text(errors="ignore")))
    literals = {s for s in literals if s}
    out |= literals

    # 3. known directories x Lua leaf tokens
    leaves = {s.rsplit("/", 1)[-1] for s in literals}
    leaves = {l for l in leaves if 1 < len(l) < 60 and LEAF_OK.fullmatch(l)}
    dirs = {"/".join(n.split("/")[:-1]) for n in ov.values()}
    dirs = {d for d in dirs if d}
    for d in dirs:
        for l in leaves:
            out.add(f"{d}/{l}")
            if args.suffixes:
                for suf in SUFFIXES[1:]:
                    out.add(f"{d}/{l}{suf}")

    Path(args.out).write_text("\n".join(sorted(out)) + "\n")
    print(f"lua files   : {sum(1 for _ in LUA_ROOT.rglob('*.lua'))}")
    print(f"literals    : {len(literals)}")
    print(f"dirs x leaf : {len(dirs)} x {len(leaves)}")
    print(f"candidates  : {len(out)} -> {args.out}")


if __name__ == "__main__":
    main()
