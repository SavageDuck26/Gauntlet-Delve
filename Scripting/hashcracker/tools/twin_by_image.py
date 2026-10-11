#!/usr/bin/env python3
"""Name an unresolved texture from the *named* texture it looks like.

Same idea as `twin_by_refs.py`, but the twin is found by pixels instead of by
reference: the export decodes both the named and the unresolved textures to PNG,
so two textures of the same dimensions can simply be compared.  A named texture
that is pixel-identical (or nearly) to an unresolved one is its spelling - and a
near-twin tells you the *family* (dir/stem) to mutate.

    python3 tools/twin_by_image.py [--export DIR] [--top 5] [--json OUT]
                                   [--only-hash HEX] [--min-dim 256]

Writes a table of `unresolved-hash  dims  distance  named-name` and, with
`--json`, the same as JSON for later stages.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DEFAULT_EXPORT = pathlib.Path.home() / "Documents" / "Coding" / "Gauntlet-Export"


def load(path: str, n: int = 48) -> np.ndarray | None:
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA").resize((n, n), Image.BILINEAR)
            a = np.asarray(im).astype(np.float32) / 255.0
    except Exception:
        return None
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default=str(DEFAULT_EXPORT))
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--json", default="")
    ap.add_argument("--only-hash", default="")
    ap.add_argument("--min-dim", type=int, default=0,
                    help="skip images whose area is smaller than this")
    args = ap.parse_args()

    root = pathlib.Path(args.export).expanduser()
    named_dir = root / "view" / "png" / "named"
    un_dir = root / "view" / "png" / "_unresolved" / "texture"
    if not named_dir.is_dir() or not un_dir.is_dir():
        sys.exit("no exported PNG trees - run export_all_resources.py first")

    named: dict[tuple[int, int], list[tuple[str, np.ndarray]]] = collections.defaultdict(list)
    for dp, _dn, fn in os.walk(named_dir):
        for f in fn:
            if not f.endswith(".png"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, named_dir)[:-4]
            try:
                with Image.open(p) as im:
                    w, h = im.size
            except Exception:
                continue
            if w * h < args.min_dim:
                continue
            arr = load(p)
            if arr is None:
                continue
            named[(w, h)].append((rel.replace(os.sep, "/"), arr))
    print(f"named PNGs {(sum(len(v) for v in named.values())):,} in {len(named)} sizes")
    for (w, h), v in sorted(named.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"   {w}x{h}  x{len(v)}")

    out = []
    for f in sorted(os.listdir(un_dir)):
        if not f.endswith(".png"):
            continue
        h = f[:-4]
        if args.only_hash and h != args.only_hash:
            continue
        p = str(un_dir / f)
        arr = load(p)
        if arr is None:
            continue
        try:
            with Image.open(p) as im:
                dims = im.size
        except Exception:
            continue
        if dims[0] * dims[1] < args.min_dim:
            continue
        cands = named.get(dims, [])
        scores = []
        for name, ref in cands:
            d = float(np.abs(arr - ref).mean())
            scores.append((d, name))
        scores.sort()
        out.append({"hash": h, "dims": f"{dims[0]}x{dims[1]}",
                    "twins": [{"name": n, "dist": round(d, 4)}
                              for d, n in scores[: args.top]]})
    print(f"compared {len(out)} unresolved textures")
    for rec in out:
        if not rec["twins"]:
            print(f"  {rec['hash']}  {rec['dims']:<10} (no named texture of that size)")
            continue
        best = rec["twins"][0]
        flag = "==" if best["dist"] < 0.002 else ("~" if best["dist"] < 0.05 else " ")
        print(f"  {rec['hash']}  {rec['dims']:<10} {flag} {best['dist']:.4f}  {best['name']}")
        for t in rec["twins"][1:]:
            print(f"        {t['dist']:.4f}  {t['name']}")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
