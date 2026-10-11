#!/usr/bin/env python3
"""Dump a Stingray *texture board* - the lookup table a GUI panel resolves its icons in.

`equippables_icons/equipment` is not icon art: it is the 100-entry table the
loadout screen uses to turn a shop-item icon name into the texture that draws it.
`hud/action_icons` and `equippables_icons/shop_action_icons` are the same shape for
the action bars, `equippables_icons/relics` for the relics.

The body is a 8-byte header (`u32 version`, `u32 count`) followed by `count`
fixed-size entries - 52 bytes for every board we hold - and the fields that matter
are always in the same places:

    [ 0: 4]  key low      - thin hash: the *top* 32 bits of murmur64("shop_" + id)
    [ 4:12]  key high     - constant 0x3d7a037c
    [ 8:16]  shader hash  - murmur64("shaders/shop_icon") for finished entries, else 0
    [24:32]  texture hash - murmur64(<texture resource name>)

The entries are sorted by the key.  For every one of the 84 *named* entries of the
equipment board the texture is exactly `equippables_icons/<item id>` and the key is
`murmur64("shop_" + <item id>)` >> 32 - i.e. the panel builds `shop_eq_warrior_head_e302`
(from `lua/settings/items.lua` + `lua/menu/avatar_loadout.lua`) and reads the texture
out of this table (FINDINGS 61.20).

That makes the key an oracle: an unresolved entry can be *labelled* by hashing the
shop names it might belong to and comparing their top 32 bits, even when the texture
name itself is still unknown.  Pass the shop ids (`--item-ids`, one per line) and the
tool prints them next to the unresolved rows.

    python3 tools/dump_board.py equippables_icons/equipment
    python3 tools/dump_board.py equippables_icons/equipment --item-ids ids.txt

`--item-ids` wants bare ids (`eq_valkyrie_talisman01`), not the `shop_` form.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
DIG = HC.parent / "GauntletGameDigging"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"
sys.path.insert(0, str(DIG))
import list_game_bundles as L                                          # noqa: E402
from hunt_unit_textures import find_body, murmur                       # noqa: E402

HDR = 8          # u32 version + u32 count
STRIDE = 52      # fixed entry size


def known_names() -> dict:
    """hash -> name, from the catalogue and our overlay."""
    out = {}
    for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                           errors="replace")):
        if r.get("name"):
            out[int(r["name_hash"], 16)] = r["name"]
    if OVERLAY.exists():
        for h, n in json.loads(OVERLAY.read_text()).items():
            out.setdefault(int(h, 16), n)
    return out


def shop_keys(ids: list[str]) -> dict:
    """top-32 -> id, for `shop_<id>` - the key the board sorts and looks up by."""
    return {murmur("shop_" + i) >> 32: i for i in ids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="board resource name, e.g. equippables_icons/equipment")
    ap.add_argument("--type", default="material", help="resource type (default material)")
    ap.add_argument("--stride", type=int, default=STRIDE)
    ap.add_argument("--item-ids", action="append", default=[],
                    help="file of bare shop ids used to label unresolved keys")
    ap.add_argument("--per-type", action="store_true",
                    help="list the file so a named entry also shows its type")
    args = ap.parse_args()

    row = next((r for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                                         errors="replace"))
                if r.get("name") == args.name and r.get("type") == args.type), None)
    if not row:
        print(f"not in the catalogue: {args.name} [{args.type}]", file=sys.stderr)
        return 1
    bundle = row["bundle"]
    root = L.find_install_root()
    path = root / "contents" / bundle
    _sig, _uz, data = L.decompress_bundle(path.read_bytes())
    idx, entry, body = find_body(data, murmur(args.name))
    if body is None:
        print("body not found", file=sys.stderr)
        return 1

    version = int.from_bytes(body[0:4], "little")
    count = int.from_bytes(body[4:8], "little")
    stride = args.stride
    if HDR + count * stride > len(body):
        stride = (len(body) - HDR) // count
    print(f"{args.name} [{args.type}]  bundle {bundle}  {len(body)} bytes")
    print(f"version {version}  entries {count}  stride {stride}")

    known = known_names()
    ids = []
    for f in args.item_ids:
        ids += [x.strip() for x in pathlib.Path(f).read_text().splitlines() if x.strip()]
    by_key = shop_keys(ids) if ids else {}

    unknown = 0
    for i in range(count):
        e = body[HDR + i * stride:HDR + (i + 1) * stride]
        if len(e) < 32:
            break
        key = int.from_bytes(e[0:4], "little")
        shader = int.from_bytes(e[8:16], "little")
        tex = int.from_bytes(e[24:32], "little")
        if tex in known:
            label = known[tex]
        else:
            unknown += 1
            label = f"<{tex:016x}> UNRESOLVED"
        if tex not in known and key in by_key:
            label += f"   shop name: shop_{by_key[key]}"
        sh = "shaders/shop_icon" if shader == murmur("shaders/shop_icon") else \
             (f"{shader:016x}" if shader else "-")
        print(f"{i:3d}  key {key:08x}  shader {sh:<19} {label}")

    print(f"\nunresolved values: {unknown} of {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
