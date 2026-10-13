#!/usr/bin/env python3
"""Build labelled contact sheets (montages) out of PNG files.

Used to *look at* unresolved textures in bulk: a grid of tiles, each labelled
with the resource name (or hash) so that a candidate name can immediately be
hash-verified afterwards.

Usage:
  montage_png.py OUT.png TILE SIZE \
      [--cols N] [--label-mode stem|hash|index|path] [--max N] \
      [FILE ... | --from-list FILE | --from-dir DIR [--glob '*.png']]

Examples:
  tools/montage_png.py /tmp/m_icons.png 176 256 \
      --from-dir ~/Documents/Coding/Gauntlet-Export/view/png/_unresolved/texture \
      --glob '*256x256*.png'
  tools/montage_png.py /tmp/m_norm.png 256 256 --from-list /tmp/norms.txt
"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw


def collect(args) -> list[str]:
    files: list[str] = list(args.files)
    if args.from_list:
        with open(os.path.expanduser(args.from_list), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    files.append(line)
    if args.from_dir:
        d = os.path.expanduser(args.from_dir)
        for name in sorted(os.listdir(d)):
            if args.glob == "*" or _glob_match(name, args.glob):
                files.append(os.path.join(d, name))
    return files[: args.max] if args.max else files


def _glob_match(name: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(name, pattern)


def label_for(path: str, mode: str, index: int) -> str:
    stem = os.path.basename(path).rsplit(".", 1)[0]
    if mode == "hash":
        return stem[:16]
    if mode == "index":
        return str(index)
    if mode == "path":
        return os.path.splitext(os.path.relpath(path, os.path.expanduser("~")))[0]
    return stem


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("tile", type=int, help="tile size in pixels (square)")
    ap.add_argument("size", nargs="?", default="",
                    help="optional filter: 'N' (square) or 'WxH' - only include matching images")
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--label-mode", default="hash", choices=["stem", "hash", "index", "path"])
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--checker", action="store_true", help="draw a checkerboard behind transparency")
    ap.add_argument("--sort", default="name", choices=["name", "size", "path"])
    ap.add_argument("--from-list")
    ap.add_argument("--from-dir")
    ap.add_argument("--glob", default="*")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()

    files = collect(args)
    if args.size:
        want = None
        if "x" in args.size.lower():
            w, h = args.size.lower().split("x", 1)
            want = (int(w), int(h))
        else:
            want = (int(args.size), int(args.size))
        keep = []
        for f in files:
            try:
                with Image.open(f) as im:
                    if im.size == want:
                        keep.append(f)
            except Exception:
                pass
        files = keep
    if not files:
        print("no files", file=sys.stderr)
        return 2

    if args.sort == "size":
        def key(f: str) -> tuple:
            try:
                return (os.path.getsize(f), f)
            except OSError:
                return (0, f)
        files.sort(key=key)
    elif args.sort == "path":
        files.sort()

    cols = max(1, args.cols)
    rows = (len(files) + cols - 1) // cols
    bar = 14
    tile = args.tile
    sheet = Image.new("RGB", (cols * tile, rows * (tile + bar)), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)

    for i, path in enumerate(files):
        cx = (i % cols) * tile
        cy = (i // cols) * (tile + bar)
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail((tile - 4, tile - 4), Image.LANCZOS)
        except Exception as exc:  # pragma: no cover
            draw.text((cx + 2, cy + 2), "ERR", fill=(255, 80, 80))
            continue
        px = cx + (tile - im.width) // 2
        py = cy + (tile - im.height) // 2
        if args.checker and im.mode == "RGBA":
            bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
            for yy in range(0, im.height, 8):
                for xx in range(0, im.width, 8):
                    if ((xx // 8) + (yy // 8)) % 2:
                        for bx in range(xx, min(xx + 8, im.width)):
                            for by in range(yy, min(yy + 8, im.height)):
                                bg.putpixel((bx, by), (70, 70, 78, 255))
            im = Image.alpha_composite(bg, im)
        sheet.paste(im.convert("RGB"), (px, py))
        draw.text((cx + 2, cy + tile), label_for(path, args.label_mode, i), fill=(220, 220, 120))

    sheet.save(os.path.expanduser(args.out))
    print(f"wrote {args.out}: {len(files)} tiles, {cols}x{rows}, {sheet.size[0]}x{sheet.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
