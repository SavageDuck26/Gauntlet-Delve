#!/usr/bin/env python3
"""Mine names out of the exported game files for the cracker.

The export tree is a second name corpus.  `levels_glb/**` and `view/glb/**`
carry clean glTF JSON - every placed unit's **material, node and mesh names** -
and the named `.unit` / `.material` / `.bones` bodies carry the same names as
ASCII.  Those names are not all resource names (a material node is often
`m_<leaf>`), but the *leaf* is usually the missing sibling of a name we hold.

This builds the word lists the sweep in `sweeps/export_corpus.sh` uses:

    data/vocab/export/stems.txt    leaf names (mesh suffixes stripped, m_/s_/z_ stripped)
    data/vocab/export/dirs.txt     every directory a named resource lives in
    data/vocab/export/sufs.txt     map/part suffixes (incl. those named textures use)
    data/vocab/export/full.txt     path-like strings already containing '/'
    data/vocab/export/targets.txt  every unresolved hash
    data/vocab/export/numbers.txt  01..99

    python3 tools/make_export_vocab.py
    python3 tools/make_export_vocab.py --export ~/Documents/Coding/Gauntlet-Export

The capitalisation is kept for the report but the lists are lowercased: Gauntlet
folds resource paths before hashing (the one `m_Swamp_...` name is a source-asset
name from the cut Swamp set, and still hashes as `m_swamp_...`).
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import struct

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "Data"
DEFAULT_EXPORT = pathlib.Path.home() / "Documents" / "Coding" / "Gauntlet-Export"

LEAF = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{2,80}$")
PATH = re.compile(r"^[A-Za-z0-9_./:-]{4,120}$")
MESH = re.compile(r"_mesh\d+_shape\d+$", re.I)
BAD = re.compile(r"^(?:[0-9a-f]{8,}|\d{3}_shape_\d+|mesh\d+|shape\d+|\d+)$")
STR = re.compile(rb"[ -~]{4,100}")
PATH_PREFIXES = ("modules/", "props/", "blocks/", "characters/", "gameobjects/",
                 "materials/", "decals/", "effects/", "core/", "ui/", "audio/",
                 "textures/", "world/", "environment/", "items/", "weapons/",
                 "enemies/", "level/")
PREFIXES = ("m_", "s_", "z_", "mat_", "mesh_")
BASE_SUFFIXES = ["", "_diff", "_norm", "_spec", "_var01", "_var02", "_2c", "_4c",
                 "_1c", "_01", "_02", "_03", "_04", "_05", "_left", "_right",
                 "_mid", "_top", "_bottom", "_broken", "_damaged", "_open",
                 "_closed", "_start", "_end", "_a", "_b", "_c", "_d", "_e",
                 "_h", "_l", "_m", "_r", "_s", "_t", "_hi", "_lo", "_parts",
                 "_piece", "_pieces"]


def glb_json_names(path):
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        return []
    try:
        _magic, _ver, _len = struct.unpack_from("<III", raw, 0)
        clen, ctype = struct.unpack_from("<II", raw, 12)
        if ctype != 0x4E4F534A:                           # 'JSON'
            return []
        doc = json.loads(raw[20:20 + clen].decode("utf-8", "replace"))
    except Exception:                                     # noqa: BLE001
        return []
    out = []
    for key in ("materials", "nodes", "meshes", "scenes", "scene"):
        val = doc.get(key)
        if isinstance(val, dict):
            val = [val]
        for item in val or []:
            name = (item or {}).get("name") if isinstance(item, dict) else None
            if name:
                out.append(name)
    return out


def body_strings(path):
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    return [m.group(0).decode("latin1") for m in STR.finditer(raw)]


def add_name(raw, names, full):
    n = MESH.sub("", raw.strip()).lower()
    if "/" in n and PATH.match(n) and n.startswith(PATH_PREFIXES):
        full.add(n)
    if not LEAF.match(n) or BAD.match(n):
        return
    names.add(n)
    for pre in PREFIXES:
        if n.startswith(pre) and len(n) > len(pre) + 2:
            names.add(n[len(pre):])


def collect(export):
    names, full = set(), set()
    glbs = list((export / "levels_glb").rglob("*.glb")) + \
           list((export / "view" / "glb").rglob("*.glb"))
    for p in glbs:
        for raw in glb_json_names(p):
            add_name(raw, names, full)
        for raw in body_strings(p):                       # JSON + any extras
            add_name(raw, names, full)
    for pat in ("*.unit", "*.material", "*.bones", "*.level"):
        for p in (export / "named").rglob(pat):
            for raw in body_strings(p):
                add_name(raw, names, full)
    return names, full, len(glbs)


def catalogue():
    rows = list(csv.DictReader((DIG / "bundle_manifest" /
                                "04_bundle_resources.csv").open(
                                    newline="", encoding="utf-8", errors="replace")))
    overlay = json.loads((DIG / "resource_name_overlay.json").read_text())
    dirs = sorted({r["name"].rsplit("/", 1)[0] for r in rows
                   if r["name"] and "/" in r["name"]})
    targets = sorted({r["name_hash"].lower() for r in rows
                      if not r["name"] and r["name_hash"].lower() not in overlay})
    tex_suffixes = collections.Counter()
    for r in rows:
        if r["type"] == "texture" and r["name"]:
            leaf = r["name"].rsplit("/", 1)[-1]
            m = re.search(r"_([a-z][a-z0-9]{1,12})$", leaf)
            if m:
                tex_suffixes[m.group(1)] += 1
    return rows, dirs, targets, tex_suffixes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default=str(DEFAULT_EXPORT))
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "export"))
    args = ap.parse_args()

    export = pathlib.Path(args.export).expanduser()
    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    names, full, n_glb = collect(export)
    _rows, dirs, targets, tex_suffixes = catalogue()

    stems = set()
    for n in names:
        stems.add(n)
        stems.add(re.sub(r"_\d+$", "", n))
    stems = {s for s in stems if len(s) >= 4 and not BAD.match(s)}

    sufs = list(BASE_SUFFIXES)
    sufs += ["_" + s for s, _n in tex_suffixes.most_common(120)
             if "_" + s not in sufs]
    sufs = sorted(dict.fromkeys(sufs))

    (out / "stems.txt").write_text("\n".join(sorted(stems)) + "\n")
    (out / "dirs.txt").write_text("\n".join(dirs) + "\n")
    (out / "sufs.txt").write_text("\n".join(sufs) + "\n")
    (out / "full.txt").write_text("\n".join(sorted(full)) + "\n")
    (out / "targets.txt").write_text("\n".join(targets) + "\n")
    (out / "numbers.txt").write_text("\n".join(f"{i:02d}" for i in range(1, 100)) + "\n")
    report = (f"export        : {export}\n"
              f"glb files     : {n_glb:,}\n"
              f"leaf names    : {len(names):,}\n"
              f"stems         : {len(stems):,}\n"
              f"full paths    : {len(full):,}\n"
              f"directories   : {len(dirs):,}\n"
              f"suffixes      : {len(sufs):,}\n"
              f"targets       : {len(targets):,}\n")
    (out / "report.txt").write_text(report)
    print(report, end="")


if __name__ == "__main__":
    main()
