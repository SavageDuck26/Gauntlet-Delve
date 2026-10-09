#!/usr/bin/env python3
"""Convert the export into file types you can just open.

    view/png/<resource path>.png     .texture is a DDS blob          -> PNG
    view/mp3/<resource path>.mp3     .ugg is 16 bytes + an Ogg stream -> MP3
    view/glb/<resource path>.glb     .unit                           -> glTF binary
    view/<kind>/_unresolved/<hash>.*  the unnamed ones too, so they can be looked at

The three formats, all verified: every `.texture` body starts with `DDS `; every
`.ugg` starts with a 4-byte size, 12 zero bytes, then `OggS` (so the Ogg stream is at
offset 16); and `.unit` is handled by `unit_to_gltf.py`, which uses the companion
`.bones` file of the same name when it exists.

    python3 convert_export.py                     # all three kinds
    python3 convert_export.py --kind png          # one kind (repeatable)
    python3 convert_export.py --kind glb --limit 20
    python3 convert_export.py --jobs 8 --overwrite

Failures are counted, not fatal: a few textures are cubemaps or BC6/BC7, which Pillow
cannot decode, and a handful of units are not meshes at all.
"""
import argparse
import concurrent.futures as futures
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

EXPORT = pathlib.Path.home() / "Documents/Coding/Gauntlet-Export"
VIEW = EXPORT / "view"
UGG_HEADER = 16


def convert_png(src, dst, _tmp):
    try:
        from PIL import Image
        im = Image.open(src)
        im.load()                       # DDS decodes lazily; force it here
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst)
        return None
    except Exception as exc:                                             # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def convert_mp3(src, dst, tmp):
    ogg = tmp / (src.stem + ".ogg")
    try:
        raw = src.read_bytes()
        if raw[:4] != b"OggS" and raw[UGG_HEADER:UGG_HEADER + 4] != b"OggS":
            return "not a UGG/Ogg stream"
        ogg.write_bytes(raw[UGG_HEADER:])
        dst.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(ogg),
             "-codec:a", "libmp3lame", "-q:a", "4", str(dst)],
            capture_output=True, timeout=300)
        if proc.returncode != 0 or not dst.exists():
            return (proc.stderr.decode(errors="replace").strip().splitlines() or
                    ["ffmpeg failed"])[-1]
        return None
    except Exception as exc:                                             # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    finally:
        ogg.unlink(missing_ok=True)


def convert_glb(src, dst, _tmp):
    try:
        import unit_to_gltf
        bones = src.with_suffix(".bones")
        dst.parent.mkdir(parents=True, exist_ok=True)
        unit_to_gltf.convert_unit_to_gltf(str(src),
                                          str(bones) if bones.exists() else None,
                                          str(dst))
        return None if dst.exists() else "no output written"
    except Exception as exc:                                             # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


KINDS = {
    "png": (".texture", convert_png),
    "mp3": (".ugg", convert_mp3),
    "glb": (".unit", convert_glb),
}


def sources(kind):
    ext = KINDS[kind][0]
    for area in ("named", "unresolved"):
        for src in sorted((EXPORT / area).rglob(f"*{ext}")):
            rel = src.relative_to(EXPORT).with_suffix("." + kind)
            if area == "unresolved":
                rel = pathlib.Path("_unresolved") / rel.relative_to("unresolved")
            yield src, VIEW / kind / rel


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", action="append", choices=sorted(KINDS),
                    help="convert only this kind (repeatable; default all)")
    ap.add_argument("--limit", type=int, help="stop after N files per kind")
    ap.add_argument("--jobs", type=int, default=6, help="parallel conversions (default 6)")
    ap.add_argument("--overwrite", action="store_true", help="redo files that exist")
    args = ap.parse_args()

    if not EXPORT.exists():
        sys.exit(f"no export at {EXPORT}")

    for kind in (args.kind or sorted(KINDS)):
        todo = [(s, d) for s, d in sources(kind)
                if args.overwrite or not d.exists()]
        if args.limit:
            todo = todo[:args.limit]
        done = failed = 0
        errors = []
        print(f"\n=== {kind}: {len(todo):,} to convert ===", flush=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            fn = KINDS[kind][1]
            with futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                jobs = {pool.submit(fn, s, d, tmp): s for s, d in todo}
                for i, job in enumerate(futures.as_completed(jobs), 1):
                    err = job.result()
                    if err:
                        failed += 1
                        if len(errors) < 12:
                            errors.append((jobs[job], err))
                    else:
                        done += 1
                    if i % 100 == 0 or i == len(todo):
                        print(f"  {i:,}/{len(todo):,}  ok {done:,}  failed {failed:,}",
                              flush=True)
        print(f"  {kind}: {done:,} written, {failed:,} failed -> {VIEW / kind}", flush=True)
        for src, err in errors:
            print(f"    ! {src.relative_to(EXPORT)}: {err.splitlines()[0][:110]}", flush=True)


if __name__ == "__main__":
    main()
