#!/usr/bin/env python3
"""Enumerate the spaces whose grammar is *parseable* rather than guessable.

    python3 tools/enumerate_spaces.py | python3 tools/check_names.py --write

Four of the eleven resource types name things by rules we can read off the names
we already hold, so there is no reason to guess words at them:

  level (quilts)  modules/<mod>/quilts/<cat>/<lvl>_quilt_<shape>__<grid>__<NN>[_<sfx>]
                  The grid is rows of single-letter cells (`xox_xex_xix_xex`,
                  `oo_ee_ii_ee`, `o_e_i_e`), so every held grid is a valid fill for
                  another quilt of the same shape; NN is 01..12 and the suffix pool
                  (civilization, spider, spawner, floor05, keydoorseast, ...) comes
                  from the held names of the same module.
  timpani_bank    audio/<group> - a closed vocabulary: enemy_<unit> for every unit
                  we hold, heroes_<class>, and the music/ambience/sfx/vo families.
  flow            flow/status_effect_<word> and flow/weapon_<type>.
  shader          shaders/<name> and shaders/<name>_<variant>.

No vocabulary guesswork - just the space, so it is exact and cheap.
"""
from __future__ import annotations

import collections
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mine_type_tokens import known_by_type                            # noqa: E402
from named_textures import load_names                                 # noqa: E402

NUMS = [f"{i:02d}" for i in range(1, 13)]
LEVELS = ["caves", "crypt", "lava", "swamp", "forest", "castle", "hub",
          "d01_caves", "d01_crypt", "d01_lava", "d01_swamp", "d01_forest",
          "d01_castle", "d01_hub_room"]
STATUS_EFFECTS = [
    "burning", "charmed", "chilled", "ethereal", "frozen", "haste", "invincible",
    "invisible", "petrified", "poisoned", "rooted", "slowed", "stunned", "shocked",
    "bleeding", "blinded", "silenced", "cursed", "weakened", "enraged", "feared",
    "regenerating", "shielded", "marked", "doomed", "ignited", "drenched",
    "corroded", "confused", "sleeping", "polymorph", "berserk", "burning_heavy",
    "frozen_solid", "chilled_brittle", "stun", "stasis", "time_warp", "soul_burn",
    "soul_reap", "vampiric", "life_leech", "maddened", "enfeebled", "crippled",
    "empowered", "hardened", "slippery", "magnetic", "dazzled", "terrified",
]
WEAPON_TYPES = [
    "axe", "book", "spear", "sword", "bow", "staff", "wand", "dagger", "mace",
    "hammer", "crossbow", "shield", "orb", "scepter", "talisman", "relic",
    "chakram", "javelin", "halberd", "glaive", "katana", "scythe", "flail",
    "morningstar", "club", "trident", "fist", "claw", "gun", "cannon", "blade",
]
AUDIO_PREFIX = ["enemy", "heroes", "music", "mus", "ambience", "amb", "sfx", "ui",
                "player", "weapon", "vo", "voice", "boss", "level", "menu", "title",
                "arena", "hub", "chest", "loot", "coin", "gate", "door", "trap",
                "footstep", "impact", "explosion", "spell", "hit", "death", "spawn",
                "monster", "creature", "ambient", "stinger", "jingle", "sting",
                "combat", "objective", "victory", "defeat", "treasure", "talisman",
                "potion", "secret", "bonus", "score", "credits", "tutorial"]
SHADER_EXTRA = ["blacktop", "blacktop_secret", "effects_sphere", "fire_plane",
                "ice_shard", "lava_flow", "water_flow", "mud_flow", "goo_flow",
                "cloud", "fog", "smoke", "glass", "crystal", "portal", "waterfall",
                "fountain", "banner", "cloth", "hair", "fur", "leaves", "grass",
                "particles", "sprite", "trail", "beam", "light", "glow", "sky",
                "skybox", "skysphere", "clouds", "stars", "moon", "sun", "gib",
                "blood", "slime", "acid", "poison", "shadow", "reflection", "water",
                "lava", "ice", "snow", "sand", "dust", "fire", "flame", "ember"]




def quilt_parts(leaf: str):
    """`crypt_quilt_straight__e_xx_e_xx__01_fancy` -> (head, grid, nn, suffix)."""
    if leaf.count("__") < 2:
        return None
    head, grid, tail = leaf.split("__", 2)
    toks = tail.split("_")
    nn = toks[0] if toks[0].isdigit() else ""
    suffix = "_".join(toks[1:]) if nn else tail
    return head, grid, nn, suffix


def main() -> int:
    bytype = known_by_type()
    names = sorted(set(load_names(all_types=True).values()))
    toks: set[str] = set()                       # every leaf token we know
    for n in names:
        leaf = n.rsplit("/", 1)[-1]
        toks.update(x for x in leaf.split("_") if x)
        if ":" in leaf:
            toks.update(x for x in leaf.split(":") if x)
    toks = {t for t in toks if len(t) > 1 and not t.isdigit()}

    out = sys.stdout
    seen: set[str] = set()

    def emit(name: str) -> None:
        if name not in seen:
            seen.add(name)
            out.write(name + "\n")

    # --- level: quilts ---------------------------------------------------------
    quilts = [l for l in bytype.get("level", ()) if "quilt" in l]
    grids: dict[tuple, set[str]] = collections.defaultdict(set)   # shape -> grids
    heads: dict[str, set[str]] = collections.defaultdict(set)     # lvl -> heads
    cats: dict[str, set[str]] = collections.defaultdict(set)      # lvl -> dirs
    sfxs: dict[str, set[str]] = collections.defaultdict(set)      # lvl -> suffixes
    hshape: dict[str, tuple] = {}
    for q in quilts:
        mod, _, rest = q.partition("/quilts/")
        cat, _, leaf = rest.partition("/")
        p = quilt_parts(leaf)
        if not p:
            continue
        head, grid, _nn, suffix = p
        shape = tuple(len(row) for row in grid.split("_"))
        lvl = head.split("_")[0]
        grids[shape].add(grid)
        hshape[head] = shape
        heads[lvl].add(head)
        cats[lvl].add(f"{mod}/quilts/{cat}/")
        if suffix:
            sfxs[lvl].add(suffix)
    for lvl, hs in heads.items():
        for d in sorted(cats[lvl]):
            for h in sorted(hs):
                for g in sorted(grids[hshape[h]]):
                    for nn in NUMS:
                        for sfx in [""] + sorted(sfxs[lvl]):
                            emit(f"{d}{h}__{g}__{'_'.join(x for x in (nn, sfx) if x)}")

    # ... and the modules whose heads we do NOT hold.  Only a third of the quilt
    # heads are known (caves, crypt) while the missing level names sit in
    # modules/d01_lava - and a head is just `<module>_quilt_<shape>`, so synthesize
    # the missing module's heads from the shape vocabulary.  Grids come from the
    # global pool, so this stays inside the real grammar.
    mods = {c.split("/quilts/")[0] for cs in cats.values() for c in cs}
    shapes = {h.split("quilt_", 1)[1] for hs in heads.values() for h in hs}
    catshort = {c.split("/quilts/")[1].rstrip("/") for cs in cats.values() for c in cs}
    allgrids = {g for gs in grids.values() for g in gs}
    for mod in sorted(mods):
        lvl = mod.split("/")[-1].replace("d01_", "")
        if heads.get(lvl):
            continue                                   # heads known for this module
        for cat in sorted(catshort):
            for shape in sorted(shapes):
                for g in sorted(allgrids):
                    for nn in NUMS[:6]:
                        for sfx in sorted(sfxs.get(lvl) or {s for v in sfxs.values() for s in v}):
                            emit(f"{mod}/quilts/{cat}/{lvl}_quilt_{shape}__{g}__{nn}_{sfx}")
                        emit(f"{mod}/quilts/{cat}/{lvl}_quilt_{shape}__{g}__{nn}")


    # --- level: colosseum and room_* names -------------------------------------
    for l in bytype.get("level", ()):
        if "/colosseum/" not in l:
            continue
        mod, _, leaf = l.partition("/colosseum/")
        lvl = mod.split("/")[-1]
        for nn in NUMS:
            for mode in ["", "normal", "exploding", "silver", "gold", "boss",
                         "bossfight", "arena", "adventure", "challenge"]:
                emit(f"{mod}/colosseum/{lvl}_colosseum_{nn}_{mode}".rstrip("_"))
        if leaf.endswith("_exploding"):
            head = leaf.rsplit("_", 1)[0]
            for mode in ["", "normal", "silver", "gold", "boss", "arena"]:
                emit(f"{mod}/colosseum/{head}_{mode}".rstrip("_"))

    # --- timpani_bank: audio/<group> -------------------------------------------
    units = {n.split("/")[2] for n in names
             if n.startswith("characters/") and n.count("/") > 2}
    for u in sorted(units):
        for pre in ["enemy", "monster", "creature", "boss"]:
            emit(f"audio/{pre}_{u}")
    for hero in ["elf", "necromagus", "valkyrie", "warrior", "wizard", "base", "all",
                 "male", "female", "select", "title", "hero", "shop", "lobby"]:
        for pre in ["heroes", "hero", "player"]:
            emit(f"audio/{pre}_{hero}")
    for pre in AUDIO_PREFIX:
        emit(f"audio/{pre}")
        for lvl in LEVELS:
            emit(f"audio/{pre}_{lvl}")
        for t in sorted(toks):
            emit(f"audio/{pre}_{t}")
    # every held audio group also takes a number / variant: `audio/enemy_cultist_01`
    held_audio = [n for n in names if n.startswith("audio/")]
    for a in held_audio:
        leaf = a.rsplit("/", 1)[-1]
        for nn in NUMS:
            emit(f"{a}_{nn}")
        for v in ["var01", "var02", "var03", "boss", "elite", "champion", "hard",
                  "silver", "gold", "loop", "intro", "outro", "victory", "defeat"]:
            emit(f"{a}_{v}")
    for hero in ["elf", "necromagus", "valkyrie", "warrior", "wizard"]:
        for pre in ["heroes", "hero", "player"]:
            for nn in NUMS:
                emit(f"audio/{pre}_{hero}_banks_{nn}")
                emit(f"audio/{pre}_{hero}_{nn}")
        emit(f"audio/{hero}_banks")
        emit(f"audio/{hero}_bank")
        for pre in ["banks", "bank"]:
            emit(f"audio/{hero}_{pre}")
    for lvl in LEVELS:
        for nn in NUMS:
            emit(f"audio/music_{lvl}_{nn}")
            emit(f"audio/{lvl}_music_{nn}")
            emit(f"audio/d01_{lvl}_{nn}")
        for v in ["music", "ambience", "ambient", "battle", "boss", "explore", "calm"]:
            emit(f"audio/{lvl}_{v}")
            emit(f"audio/{v}_{lvl}")


    # --- flow: status effects, weapons, the rest of the namespace ---------------
    for w in STATUS_EFFECTS:
        emit(f"flow/status_effect_{w}")
        for nn in NUMS[:6]:
            emit(f"flow/status_effect_{w}_{nn}")
    for w in WEAPON_TYPES:
        emit(f"flow/weapon_{w}")
        emit(f"flow/weapon_{w}_01")
    for t in sorted(toks):
        emit(f"flow/{t}")

    # --- shader: shaders/<name> -------------------------------------------------
    for base in SHADER_EXTRA:
        for sfx in ["", "_01", "_02", "_diff", "_norm", "_lava", "_ice"]:
            emit(f"shaders/{base}{sfx}")
    for t in sorted(toks):
        if len(t) > 2:
            emit(f"shaders/{t}")
            emit(f"shaders/{t}_diff")
    # 23 of the 36 missing `shader` rows live in resource_packages/menu, so the UI
    # vocabulary belongs here: every held `shaders/<name>` takes a variant, and the
    # menu words are tried as shader names in their own right.
    for n in names:
        if n.startswith("shaders/"):
            for sfx in ["_01", "_02", "_03", "_diff", "_norm", "_mask", "_glow",
                        "_lava", "_ice", "_moss", "_secret", "_alpha", "_ui", "_3d"]:
                emit(f"{n}{sfx}")
            for sfx in ["_shader", "_shader_diff", "_shader_norm"]:
                emit(f"{n}{sfx}")
    MENU = ["menu", "ui", "hud", "button", "buttons", "listitem", "checkbox", "panel",
            "background", "blur", "fade", "vignette", "gloss", "gradient", "mask",
            "alpha", "logo", "text", "font", "cursor", "arrow", "selection",
            "highlight", "shadow", "outline", "glow", "tooltip", "dialog", "popup",
            "tab", "bar", "ring", "icon", "sprite", "atlas", "frame", "border",
            "level_select", "hub_map", "titlescreen", "loading", "lobby", "shop",
            "talent", "skill", "stats", "inventory", "map", "portrait", "health",
            "mana", "energy", "cooldown", "progress", "circle", "square", "flipbook"]
    for w in MENU:
        for pre in ["", "menu_", "ui_"]:
            for sfx in ["", "_shader", "_ui", "_diff", "_norm", "_mask", "_glow"]:
                emit(f"shaders/{pre}{w}{sfx}")
                emit(f"menu/shaders/{pre}{w}{sfx}")
        emit(f"shaders/{w}_01")
        emit(f"shaders/{w}_02")

    # flow: one hash left, so enumerate the held flow names with variants as well
    for n in names:
        if n.startswith("flow/"):
            for nn in NUMS[:4]:
                emit(f"{n}_{nn}")
            for v in ["01", "loop", "start", "end", "enter", "exit"]:
                emit(f"{n}_{v}")


    print(f"{len(seen)} candidates", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


