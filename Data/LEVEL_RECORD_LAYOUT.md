# The `.level` unit record — the authoritative field map

**Status: read out of `gauntlet.exe` and confirmed against the running engine** (FINDINGS
§9H.34 for the quaternion, §9H.36 for the layout).  Read this before touching a level, a
placement or a rotation.  Every claim below is either *measured in the binary*, *measured
in game* (the engine's own per-unit capture) or, where marked, *inferred*.

## The short version

A level is a header, a table of **72-byte unit records**, and a few fixed sections.  Each
record holds a unit's metadata (id, template hash, material) and its transform — but **the
transform is 48 bytes and does not fit inside its own record**: it starts at offset 0x30
and its last 24 bytes (`rotation.w`, `scale`, 8 padding) spill into the *next* record's
first 24 bytes.  The last unit's spill goes in the 24 bytes reserved after the table.

So, for unit *i* at `record_i = 128 + i*72`:

| offset | size | field | whose |
| --- | --- | --- | --- |
| 0x00 | 4 | rotation `w` | unit **i-1** |
| 0x04 | 12 | scale xyz | unit **i-1** |
| 0x10 | 8 | unused / padding | unit **i-1** |
| 0x18 | 8 | entity id (per instance) | unit i |
| 0x20 | 8 | template hash (MurmurHash64A of the unit path, lowercase) | unit i |
| 0x28 | 8 | material override hash (0 = none) | unit i |
| 0x30 | 12 | position xyz | unit i |
| 0x3c | 4 | rotation `x` | unit i |
| 0x40 | 4 | rotation `y` | unit i |
| 0x44 | 4 | rotation `z` | unit i |
| 0x48 | 4 | rotation `w` | unit i — **this is `record_{i+1}` offset 0x00** |
| 0x4c | 12 | scale xyz | unit i — **`record_{i+1}` offset 0x04** |

Read as the engine does — **four consecutive floats at 0x3c** — the rotation is a normal
unit quaternion `(x, y, z, w)`; `q` and `-q` are the same rotation.

### The table around the records

```
0x00 .. 0x80   the 32 x u32 header (counts and section offsets; u32[0] = 128 = the table)
0x80 .. 0x98   the table's 24-byte PROLOGUE - its first u32 is the byte COUNT the loader
               allocates (0 in all 255 shipped levels; a rotation there is a crash, 9H.23.3)
0x98 + i*0x48  unit i's 64-byte block: id, template, material, position, quat(4), scale(3)
               + 8 bytes of padding to the next 72-byte boundary
               (equivalently: record_i + 0x18 .. record_i + 0x58, so it straddles records)
```

The table's declared end is `128 + 72 * count` (`u32[3] = that + 24` in every shipped
level), and the last unit's block overruns it by 16 bytes — which is exactly why the
24-byte block after the table exists.  In every shipped level those 24 bytes read
`1.0, 1.0, 1.0, 1.0, 0, 0, 0, 0`: the last unit's `w = 1.0` and `scale = (1,1,1)`.

## Where this comes from (measured in the binary)

`FUN_00430440` is the per-unit pass.  It walks the instance array at

```c
entry_i = *(data + 8) + i * 0x48 + 0xb0;      /* data + 0x80 is the unit table */
```

and for every unit that resolves it builds that placement's matrix:

```c
FUN_0042db10(out, entry_i + 0xc, entry_i + 0, entry_i + 0x1c)
  -> FUN_0042d7f0(out, quaternion, position, scale)
```

* dumped at `0x4305b0` (it pushes `esi+0x1c`, `esi`, `esi+0xc`, `out` in that order, and
  `FUN_0042db10` re-pushes its arguments), so `FUN_0042d7f0` receives
  `(out, +0xc, +0x00, +0x1c)`;
* `FUN_0042d7f0` reads **four consecutive floats** from the quaternion pointer and
  normalises them: `k = 2/|q|^2`, `m00 = 1 - k(y^2+z^2)`, `m01 = k(xy + wz)`, ... - the
  ordinary unit-quaternion to matrix form.  Its 3rd argument is the translation (written
  into the matrix's last column), its 4th the scale (dividing the basis rows);
* the same function reads id / template / material at `entry-0x18 / -0x10 / -8`, i.e. at
  `record+0x18 / 0x20 / 0x28` - which is what pins `entry = record + 0x30`.

`entry_i` is `record_i + 0x30`, so the quaternion pointer `entry+0xc` is `record+0x3c` and
its fourth float is `record+0x48` = **the next record's offset 0**.  Nothing else is needed:
the stride is 72 (`iVar13 += 0x48`), the table starts at 128 (`u32[0]`), and
`u32[3] - (128 + 72*count) == 24` in every level.

## Why it hid (§9H.36)

Every offline check compared the toolkit with itself, and every one of them agrees with
itself under either reading:

* decode -> encode stayed **byte-exact** (the encoder wrote the `w` and scale into the
  record's own first 24 bytes, and the reader read them back from there) - 21/21 level
  files still round-trip byte-exactly after the fix;
* the ids, template hashes, material hashes and positions were **all at the right
  offsets**, so every name / position / identity check passed;
* the engine's own capture *did* say so - its values look like "one foot in the next
  record" - and §9H.32 dismissed exactly that as a decoding artifact.  It was the ground
  truth: `check_level_capture_rotation.py` is the check that uses it;
* identity placements (floors) are **immune** - `xyz = 0`, so any `w` is the same rotation -
  so only rotated, *repeated* kinds showed it, which is why it read as "the duplicate
  models are messed up".

## How to check a level against the engine

```bash
# the engine's own capture vs the file: prints BOTH readings, so it cannot pass by accident
python3 scripts/check_level_capture_rotation.py <level file> <capture json> [--max-bad N]

# our own level, against the deployed bytes, using the engine's own arithmetic
python3 scripts/check_deployed_placement.py <level> <glb> [<unit file>=<base name> ...]

# decode -> encode must stay byte-exact
python3 -c "import sys;sys.path.insert(0,'scripts');from resource_tools.level_tools import *;
b=open('<level>','rb').read();print(encode_level(decode_level(b))==b)"
```

Measured numbers (all in §9H.36): the shipped crypt room **177/177 exact** under the
engine's reading and 44 wrong under the old one; the hub **460/461** vs 207/461; our own
arena **12/12 exact, worst 0.000 deg** - and the engine's own capture of that arena, taken
after the fix, reports the authored quaternions exactly (`Data/runtime_units/`).

## The toolkit API (`scripts/resource_tools/level_tools.py`)

* `decode_level(blob)` / `encode_level(data)` - the record dicts carry each unit's **own**
  `rotation` (a quaternion `[x,y,z,w]`), `rotation_vector` (its original three floats, kept
  only so an untouched round trip stays byte-exact), `scale`, `flag` (the unit's own `w`)
  and `_unused`.  `encode_level` runs `shift_leads_forward` as its last step, so a record
  dict always means "this unit's data" - the file's layout is the encoder's problem.
* `unit_transform_lead(blob, ent_off, count, i)` - unit *i*'s 24-byte lead.
* `table_prologue(blob, ent_off)` - the table's 24-byte header (its first u32 is the count).
* `shift_leads_forward(blob, ent_off, count, prologue)` - move every lead one record on.
* `set_record_rotation(entity, quat)` - **use this, never `e['rotation'] = ...`**: it also
  drops the cached `rotation_vector` and `flag`, without which the encoder silently writes
  the rotation the record already had (the donor-path bug, §9H.36).

## Rules to work by

1. **Never read a record's own offset 0 as its rotation `w`**, and never its offset 4 as
   its scale.  Use the four consecutive floats at `0x3c`, and the next record's offset 4.
2. **Never write a rotation by setting `rotation` alone** - `set_record_rotation`.
3. The table's **prologue is not unit 0's data**: its first u32 is the load's byte count
   and must be 0.
4. **The scale's position is code-measured, not corpus-measured** (§9H.36, "still open"):
   no capture carries a scale, and the shipped scales are the same multiset under either
   reading.  The encoder writes it where the engine's pointer arithmetic reads it.
