#!/usr/bin/env python3
"""
Full-grammar vocabularies for the `.level` family.

Every level name we have resolved follows one of a handful of mechanical
schemas, so this family is cracked by *enumerating the schemas* rather than by
guessing words:

    modules/d01_<env>/<sub>/<env>_quilt_<shape>__<cells>__<nn>[_<mods>]
    modules/d01_<env>/<env>_quilt_<shape>__<cells>__<nn>[_<mods>]     (no <sub>)
    modules/d01_<env>/quilts/entrances/<env>_quilt_entrance__<cells>__start_<nn>
    modules/d01_<env>/quilts/exits/<env>_quilt_exit__<cells>__end_<nn>
    modules/d01_<env>/arena/<env>_arena<nn>
    modules/d01_<env>/colosseum/<env>_colosseum_<nn>_<mod>
    modules/d01_<env>/dungeon_tiles/<rock>_<w>_<h>_<a>_<b>_<c>_<d>_<nn>[_corridor]
    modules/d01_<env>/room_<tokens>
    modules/d01_<env>/prefabs/prefab_<tokens>
    modules/d01_<env>/{resources,room_dummy,shading_environment}

`cells` is the up/right/down/left cell-row signature decoded from
`lua/dungeon/quilt_builder.lua`: four `_`-separated groups over one alphabet
(`x` wall, `e` through, `i` entrance, `o` exit), with len(u) == len(d) (quilt
width) and len(r) == len(l) (quilt height).  This tool emits the codes we have
actually seen *plus* their one-character neighbourhood, and - separately - the
legal codes over the small alphabets, so the cheap codes can be crossed with the
whole mod vocabulary and the wide codes with a trimmed one.

    python3 tools/make_level_full.py [--out data/vocab/lvl]

Re-run this after every merge round: every name we crack feeds new cells codes,
mods and tokens into the next round's vocabularies (`spider_02_1` was only
discovered once such a token existed to build it from).
"""
import argparse
import collections
import csv
import itertools
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
HC = HERE.parent
REPO = HERE.parent.parent
DIG = REPO / "Data"
SOURCE = REPO / "game-source"
CATALOGUE = DIG / "bundle_manifest" / "04_bundle_resources.csv"
OVERLAY = DIG / "resource_name_overlay.json"

# `quilts/base/`, `quilts/encounters/`, ... or nothing for the bare form.
QUILT = re.compile(r"^modules/d01_([a-z_]+)/((?:[a-z0-9]+/)*)"
                   r"([a-z0-9_]+)_quilt_([a-z]+)__([a-z_]+)__(.+)$")
DUNGEON = re.compile(r"^modules/d01_([a-z_]+)/dungeon_tiles/([a-z0-9_]+)$")
ARENA = re.compile(r"^modules/d01_([a-z_]+)/arena/([a-z0-9_]+)$")
COLOSSEUM = re.compile(r"^modules/d01_([a-z_]+)/colosseum/([a-z0-9_]+)$")
ROOM = re.compile(r"^modules/d01_([a-z_]+)/(room_[a-z0-9_]+)$")
LEAF = re.compile(r"^modules/([a-z0-9_]+)/(?:d01_([a-z_]+)/)?([a-z0-9_]+)$")

CELLS = "xeio"          # x wall, e through, i entrance, o exit (`g` is internal only)
CELLS_MUT = "xeiog"     # alphabet used for the one-character neighbourhood (g shows
                        # up in *tile* names, so allow it as a near-miss here)
CELLS_WIDE = "xeiogucdw"  # the dungeon-tile alphabet too - worst case, cheap to try
NN = [f"{i:02d}" for i in range(1, 41)]

# subdirs we have seen; the extras are the plural/singular and role variants a
# dungeon generator of this kind ships
SUBS_SEEN = ["quilts/base", "quilts/encounters", "quilts/entrances",
             "quilts/exits", "quilts/saferooms"]
SUBS_EXTRA = ["quilts/encounter", "quilts/entrance", "quilts/exit", "quilts/saferoom",
              "quilts/boss", "quilts/bosses", "quilts/start", "quilts/end",
              "quilts/entry", "quilts/entries", "quilts/treasure", "quilts/secret",
              "quilts/keyrooms", "quilts/rooms", "quilts/corridors", "quilts/junctions",
              "quilts/setpieces", "quilts/specials", "quilts/filler", "quilts/arena",
              "quilts/traps", "quilts/shops", "quilts/spawn", "quilts/stairs"]

# shapes we have seen; the extras are the shapes a quilt builder of this kind
# would plausibly ship (cheap to try, they only multiply one slot)
SHAPES_SEEN = ["straight", "turn", "mediumroom", "largeroom", "smallroom",
               "blackbox", "entrance", "exit", "saferoom", "encounter"]
SHAPES_EXTRA = ["corner", "cross", "tee", "junction", "deadend", "end", "hub",
                "fourway", "hall", "room", "bend", "split", "fork", "arena",
                "start", "straightaway", "longroom", "bigroom", "tinyroom"]

# tokens that may follow a mod (`sarcophagus_sand`, `keydoorseast_lobbers`, ...)
SECOND = ["sand", "slaves", "skeleton", "temple", "fancy", "mixed", "lobbers",
          "spawner", "queen", "endless", "rocks", "floor02", "floor05", "floor08"]
PARTS = [str(i) for i in range(1, 9)]


def load_known():
    """Every level name we know: catalogue rows of type `level` + the overlay."""
    rows = [r for r in csv.DictReader(CATALOGUE.open(newline="", encoding="utf-8",
                                                     errors="replace"))
            if r["type"] == "level"]
    named = {r["name"] for r in rows if r["name"]}
    targets = {r["name_hash"] for r in rows if not r["name"]}
    overlay = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
    # the overlay has no type column, so take anything that lives under a
    # `modules/` prefix - extra tokens are harmless, the schemas below are strict
    named |= {n for n in overlay.values() if n.startswith("modules/")}
    return sorted(named), sorted(targets)


def decompose(names):
    """Pull every component out of the known names, per family."""
    s = {k: set() for k in ("env", "sub", "shape", "code", "nn", "mod", "rock",
                            "dim", "quad", "quadchar", "tile_nn", "tile_extra",
                            "colos", "colos_nn", "arena_nn", "token", "suffix",
                            "roomtok", "prefableaf", "basesuf")}
    subs = collections.Counter()
    for n in names:
        for t in n.rsplit("/", 1)[-1].split("_"):
            s["token"].add(t)
        if "/" in n:
            s["suffix"].add("_" + n.rsplit("_", 1)[-1])

        m = QUILT.match(n)
        if m:
            env, sub, _base, shape, cells, tail = m.groups()
            s["env"].add(env)
            s["shape"].add(shape)
            s["code"].add(cells)
            if sub:
                s["sub"].add(sub.rstrip("/"))
                subs[(env, sub.rstrip("/"))] += 1
            p = tail.split("_")
            s["nn"].add(p[0])
            for m_ in ("_".join(p[1:]),):
                if m_:
                    s["mod"].add(m_)
            if len(p) > 1:
                s["mod"].add(p[1])
                s["basesuf"].add(p[1])
            continue

        m = DUNGEON.match(n)
        if m:
            env, leaf = m.groups()
            s["env"].add(env)
            p = leaf.split("_")
            s["rock"].add(p[0])
            if len(p) >= 3:
                s["dim"].add(f"{p[1]}_{p[2]}")
            rest = p[3:]
            if len(rest) >= 4:
                quad = "_".join(rest[:4])
                s["quad"].add(quad)
                for ch in "".join(rest[:4]):
                    s["quadchar"].add(ch)
            if len(rest) >= 5:
                s["tile_nn"].add(rest[4])
                if len(rest) > 5:
                    s["tile_extra"].add("_".join(rest[5:]))
            continue

        m = ARENA.match(n)
        if m:
            s["env"].add(m.group(1))
            s["arena_nn"].add(m.group(2).replace(f"{m.group(1)}_arena", ""))
            continue

        m = COLOSSEUM.match(n)
        if m:
            s["env"].add(m.group(1))
            p = m.group(2).replace(f"{m.group(1)}_colosseum_", "").split("_")
            s["colos_nn"].add(p[0])
            if len(p) > 1:
                s["colos"].add("_".join(p[1:]))
            continue

        m = ROOM.match(n)
        if m:
            s["env"].add(m.group(1))
            for t in m.group(2).split("_"):
                s["roomtok"].add(t)
            continue

        if "/prefabs/" in n:
            for t in n.rsplit("/", 1)[-1].split("_"):
                s["prefableaf"].add(t)
            continue

        m = LEAF.match(n)
        if m:
            for g in m.groups():
                if g:
                    s["env"].add(g)
                    for t in g.split("_"):
                        s["token"].add(t)
    return s, subs


def expand_codes(observed, alphabet=CELLS_MUT):
    """Observed cell codes plus their one-character neighbourhood."""
    out = set(observed)
    for c in observed:
        for i, ch in enumerate(c):
            if ch not in alphabet:
                continue
            for alt in alphabet:
                if alt != ch:
                    out.add(c[:i] + alt + c[i + 1:])
    return sorted(out)


def group_lists(observed):
    """
    Per side length, the cell-group vocabulary used by the exhaustive tier.

    Lengths 1-3 are enumerated *completely* over the cell alphabet (a quilt side
    is 1, 2 or 3 cells in every name we have); length 5 only ever appears as
    `xxxxx` with at most one opening, so it gets the observed groups plus their
    one-character neighbourhood instead of the full 4**5.
    """
    g = {n: sorted("".join(t) for t in itertools.product(CELLS, repeat=n))
         for n in (1, 2, 3)}
    obs5 = {c.split("_")[i] for c in observed for i in range(4)
            if len(c.split("_")) == 4 and len(c.split("_")[i]) == 5}
    if obs5:
        mut = set(obs5)
        for grp in obs5:
            for i, ch in enumerate(grp):
                for alt in CELLS:
                    if alt != ch:
                        mut.add(grp[:i] + alt + grp[i + 1:])
        g[5] = sorted(mut)
    return g


def wide_codes(observed, cap=400_000):
    """Every legal code over the group alphabets we have seen at each side length."""
    groups = collections.defaultdict(set)
    for c in observed:
        p = c.split("_")
        if len(p) != 4:
            continue                        # `xox_xex__xix_xex`-style oddities
        for g in p:
            groups[len(g)].add(g)
    for w in (1, 2):                        # fully enumerate the tiny sides
        groups[w] |= {"".join(t) for t in itertools.product(CELLS, repeat=w)}
    out = set(observed)
    lens = sorted(groups)
    for w in lens:
        for h in lens:
            for u in groups[w]:
                for d in groups[w]:
                    for r in groups[h]:
                        for l in groups[h]:
                            out.add(f"{u}_{r}_{d}_{l}")
    codes = sorted(out)
    return codes[:cap], len(codes)


def expand_mods(observed):
    """Observed mods, + two-token mods, + `<mod>_<nn>` and `<mod>_<nn>_<part>`."""
    seen = {m for m in observed if m}
    bases = set()
    for m in seen:
        p = m.split("_")
        bases.add(p[0])
        if len(p) > 1:
            bases.add("_".join(p[:-1]))
    two = {f"{b}_{s}" for b in bases for s in SECOND}
    num = {f"{b}_{n}" for b in bases for n in NN}
    numpart = {f"{b}_{n}_{p}" for b in bases for n in NN for p in PARTS}
    return sorted(seen), sorted(seen | two), sorted(seen | two | num | numpart)


def themes_from_source(root: pathlib.Path):
    """
    Theme words the dungeon generator knows about, mined from the Lua source tree.

    The layouts are named `<env>_<mode>_<nn>_<theme>[_<theme>]`
    (`caves_endless_02_ruins`) and carry `floor_type = "..."` /
    `shading_environment = "..."` fields (`spider_campaign`, `mummy_campaign`,
    `endless_spider_02`, `crypt_procedural_fancy_01`).  Those words are the
    generator's theme vocabulary, and quilt mods are themes (`...__01_spider`) -
    so this is exactly where `mummy`/`ruins`/`demon` style mods come from.
    """
    words: set = set()
    layouts = root / "Gauntlet-SourceCode-LUA" / "lua" / "dungeon" / "layouts"
    skip = {"caves", "crypt", "lava", "endless", "floor", "colosseum", "start",
            "levels", "campaign", "procedural", "only"}
    for f in sorted(layouts.glob("*.lua")) if layouts.exists() else []:
        for p in f.stem.split("_"):
            if not p.isdigit() and p not in skip and len(p) > 2:
                words.add(p)
    rx = (re.compile(r'floor_type\s*=\s*"([^"]+)"'),
          re.compile(r'shading_environment\s*=\s*"([^"]+)"'))
    for f in root.rglob("*.lua"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for r in rx:
            for m in r.finditer(text):
                for t in m.group(1).split("_"):
                    if not t.isdigit() and t not in skip and len(t) > 2 and "/" not in t:
                        words.add(t)
    return sorted(words)


def mod_words(root: pathlib.Path, names):
    """
    The mod vocabulary: the game's enemy groups, creatures and set pieces.

    A quilt mod names the group (or feature) its room is themed with -
    `...__01_spider`, `...__03_cultists`, `...__04_statues_mixed` - and the
    *plural* is what the names use (`orc_juggernaut` -> `juggernauts`,
    `living_statue` -> `statues`; both were found exactly this way).  Sources:

      * `characters/`, `gameobjects/`, `ability_units/`, `props/` resource names
        (the source tree ships one file per resource, so the paths *are* names)
      * `lua/settings/encounter_settings.lua` - floor types (themes) mapped to
        enemy groups and the `unit_path` each group spawns
      * `lua/settings/spawned_entity_tags.lua` - spawn-animation tags

    Returns singular and plural forms of every word and compound.
    """
    stop = {"base", "template", "generic", "abilities", "ability", "reacts", "hit",
            "summoned", "enemy", "avatar", "boss", "weapon", "projectile", "spawner",
            "projectiles", "body", "parts", "lua", "tables", "properties", "test",
            "default", "shared", "melee", "ranged", "heavy", "mini", "small", "big",
            "armor", "unit", "units", "props", "prop", "decal", "settings", "blob",
            "cost", "max", "min", "spawn", "t1", "t2"}
    raw: set = set()

    def add(value: str):
        if len(value) < 4 or value.isdigit() or value in stop:
            return
        raw.add(value)
        for t in value.split("_"):
            if len(t) > 3 and not t.isdigit() and t not in stop:
                raw.add(t)

    for sub in ("characters", "gameobjects", "ability_units", "props"):
        d = root / "Gauntlet-SourceCode-LUA" / sub
        if not d.exists():
            continue
        for f in d.rglob("*.lua"):
            for part in str(f.relative_to(d))[:-4].split("/"):
                add(part)
    for n in names:
        if n.startswith(("characters/", "gameobjects/", "ability_units/", "props/")):
            add(n.rsplit("/", 1)[-1])
    settings = root / "Gauntlet-SourceCode-LUA" / "lua" / "settings"
    keyw = re.compile(r'^\s*([a-z0-9_][a-z0-9_]{3,})\s*=')
    strw = re.compile(r'"([a-z0-9_]{3,})"')
    for f in sorted(settings.glob("*.lua")) if settings.exists() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            for rx in (keyw, strw):
                for m in rx.finditer(line):
                    add(m.group(1))

    out: set = set()
    for w in raw:
        out.add(w)
        # pluralise the word and, for compounds, its last token:
        #   orc_juggernaut -> orc_juggernauts, living_statue -> living_statues
        for cand in (w, w.rsplit("_", 1)[-1]):
            if cand.endswith("y"):
                out.add(cand[:-1] + "ies")
            elif cand.endswith(("s", "x", "ch", "sh")):
                out.add(cand + "es")
            elif cand.endswith("f"):
                out.add(cand[:-1] + "ves")
            out.add(cand + "s")
            if cand != w:
                out.add(w[: len(w) - len(cand)] + cand + "s")
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HC / "data" / "vocab" / "lvl"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    names, targets = load_known()
    s, subs = decompose(names)

    qenv = sorted({n.split("/")[1].replace("d01_", "")
                   for n in names if QUILT.match(n)})
    shapes_seen = SHAPES_SEEN + sorted(s["shape"] - set(SHAPES_SEEN))
    nn = sorted(s["nn"] | set(NN) | {"end", "start", "loop"})
    code1 = expand_codes(s["code"])
    codeg = expand_codes(s["code"], CELLS_WIDE)
    codew, codew_all = wide_codes(s["code"])
    groups = group_lists(s["code"])
    themes = themes_from_source(SOURCE)
    nouns = mod_words(SOURCE, names)
    mod, mod2, modbig = expand_mods(s["mod"])
    # themes and creature/group words are mods too: `...__01_mummy`,
    # `...__03_cultists_mixed`, `...__02_statues`, `...__01_juggernauts`
    bases_mod = set(themes) | set(nouns)
    modsmall = sorted(set(mod2) | bases_mod |
                      {f"{t}_{x}" for t in bases_mod for x in SECOND})
    modbig = sorted(set(modbig) | set(modsmall) |
                    {f"{t}_{x}" for t in bases_mod for x in NN} |
                    {f"{t}_{x}_{p}" for t in bases_mod for x in NN for p in PARTS})
    quads = sorted(s["quad"] | {"_".join(t) for t in
                                itertools.product(sorted(s["quadchar"] or "gu"), repeat=4)})
    rocks = sorted(s["rock"] | {"rock", "caverock", "lavarock", "cryptrock",
                               "hubrock", "dungeonrock"})
    dims = sorted(s["dim"] | {"8c_8c", "4c_4c", "6c_6c", "10c_10c", "12c_12c", "16c_16c"})
    colos = sorted(s["colos"] | {"template", "poison", "freeze", "laser", "exploding",
                                 "mortar", "twister", "beam", "fire", "spikes", "lightning",
                                 "skulls", "boulders", "sandstorm"})

    def w(fname, vals):
        vals = [v for v in vals if v != ""]
        (out / fname).write_text("\n".join(vals) + ("\n" if vals else ""))
        print(f"  {fname:16s} {len(vals):>9}")

    print("level vocabularies:")
    w("env.txt", qenv)
    w("sub.txt", sorted(s["sub"]))
    w("sub_wide.txt", SUBS_SEEN + sorted(set(s["sub"]) - set(SUBS_SEEN)) + SUBS_EXTRA)
    w("shape.txt", shapes_seen + SHAPES_EXTRA)
    w("shape_seen.txt", shapes_seen)
    w("code.txt", sorted(s["code"]))
    w("code1.txt", code1)
    w("codeg.txt", codeg)
    w("codew.txt", codew)
    for n, gl in sorted(groups.items()):
        w(f"g{n}.txt", gl)
    w("theme.txt", themes)
    w("modnoun.txt", nouns)
    w("modsmall.txt", modsmall)
    w("nn.txt", nn)
    w("mod.txt", mod2)
    w("modbig.txt", modbig)
    w("rock.txt", rocks)
    w("dim.txt", dims)
    w("quad.txt", quads)
    w("tile_nn.txt", sorted(s["tile_nn"] | set(NN[:12])))
    w("tile_extra.txt", sorted(s["tile_extra"] | {"corridor"}))
    w("colos.txt", colos)
    w("colos_nn.txt", sorted(s["colos_nn"] | set(NN[:12])))
    w("arena_nn.txt", sorted(s["arena_nn"] | set(NN[:12])))
    w("roomtok.txt", sorted(s["roomtok"] | s["token"]))
    w("prefabtok.txt", sorted(s["prefableaf"] | s["token"]))
    w("leaf.txt", sorted(LEAF.match(n).group(3) for n in names if LEAF.match(n)))
    w("module.txt", sorted(LEAF.match(n).group(1) for n in names if LEAF.match(n)))
    w("tokens.txt", sorted(t for t in s["token"] | set(s["mod"]) if t))
    w("suffixes.txt", sorted(s["suffix"] | {"_" + m for m in mod}))
    w("names.txt", names)
    w("targets.txt", targets)

    (out / "info.txt").write_text(
        f"known level names   : {len(names)}\n"
        f"unresolved levels   : {len(targets)}\n"
        f"quilt envs          : {qenv}\n"
        f"cells codes seen    : {len(s['code'])}  (1-char expansion {len(code1)})\n"
        f"cells codes legal   : {codew_all} (capped {len(codew)})\n"
        f"mods seen/2tok/big  : {len(mod)} / {len(mod2)} / {len(modbig)}\n"
        f"themes (source tree): {len(themes)}  {themes[:12]}\n"
        f"creature words      : {len(nouns)}  {nouns[:12]}\n"
        f"cell groups         : " +
        ", ".join(f"len{n} {len(g)}" for n, g in sorted(groups.items())) + "\n" +
        f"shapes seen/extra   : {len(s['shape'])} / {len(SHAPES_EXTRA)}\n"
        f"headroom by subdir  : " +
        ", ".join(f"{e}/{d} {c}" for (e, d), c in sorted(subs.items())) + "\n")
    print(f"\nknown level names {len(names)}   unresolved {len(targets)}")
    print(f"cells {len(s['code'])} seen -> {len(code1)} near / {codew_all} legal"
          f"   mods {len(mod)}/{len(mod2)}/{len(modbig)}")


if __name__ == "__main__":
    main()
