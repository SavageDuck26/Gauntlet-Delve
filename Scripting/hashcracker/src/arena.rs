//! Flattened, padded byte storage shared by the CPU and GPU evaluation paths.
//!
//! A candidate is a concatenation of literals and word-list entries. Keeping
//! those as `Vec<Vec<Vec<u8>>>` (list -> word -> its own heap allocation) costs
//! *two dependent pointer loads per slot* before a single byte is read, and
//! scatters the words across the heap — so the hot loop stalls on L2 and cannot
//! prefetch. The arena packs every byte a pattern can emit into one contiguous
//! blob addressed by `(offset, len)`, which is exactly the layout the GPU kernel
//! already used, so both paths now build it once with one builder.
//!
//! Entries are padded (see [`SLACK`]) so the tail of a candidate can be read as
//! one masked 8-byte load instead of a byte-at-a-time loop.
//!
//! Nothing here hashes anything by itself — `Compiled::emit` + `murmur::hash_bytes`
//! stay the reference implementation, and [`Arena::hash`] is required to agree
//! with them bit-for-bit (see the `arena_matches_reference` test).

use crate::pattern::Part;

/// Zero bytes kept after every entry (and at the end of the blob), so an 8-byte
/// load starting anywhere in an entry's final 8 bytes stays in the allocation.
pub const SLACK: usize = 8;

/// `part_pick` marker: this part is a literal, so no `picks` entry applies.
const NO_PICK: u32 = u32::MAX;

/// Every byte a pattern can emit, packed once.
pub struct Arena {
    /// All literal + word bytes, each entry padded out to an 8-byte boundary.
    pub blob: Vec<u8>,
    /// Per entry: byte offset into `blob` and byte length (parallel arrays, so a
    /// probe touches one line instead of chasing two `Vec`s).
    pub ent_off: Vec<u32>,
    pub ent_len: Vec<u32>,
    /// Per `parts` index: entry index of that part's pick-0 value. A literal has
    /// exactly one entry; a slot's pick `p` lives at `slot_first[pos] + p`.
    pub part_base: Vec<u32>,
    /// Per `parts` index: used-slot position to index `picks` with, or `NO_PICK`.
    pub part_pick: Vec<u32>,
    /// Per used-slot position: index of that slot's first word entry.
    pub slot_first: Vec<u32>,
    /// Per used-slot position: the longest word in that slot (so callers can
    /// size a stack buffer for [`Arena::fill`]).
    pub slot_max: Vec<u32>,
    /// Bytes the literals alone contribute, i.e. the length of the shortest
    /// candidate this pattern can emit.
    pub lit_len: u32,
}

impl Arena {
    /// Flatten `parts` (literals) plus the word lists named by `used` into one
    /// blob. Words are stored slot-major, so a slot's picks are contiguous.
    pub fn build(lists: &[Vec<Vec<u8>>], used: &[usize], parts: &[Part]) -> Arena {
        let mut a = Arena {
            blob: Vec::new(),
            ent_off: Vec::new(),
            ent_len: Vec::new(),
            part_base: Vec::new(),
            part_pick: Vec::new(),
            slot_first: Vec::new(),
            slot_max: Vec::new(),
            lit_len: 0,
        };

        // 1. literals, in part order (one entry each)
        for part in parts {
            match part {
                Part::Lit(bytes) => {
                    let e = a.push_entry(bytes);
                    a.part_base.push(e);
                    a.part_pick.push(NO_PICK);
                    a.lit_len += bytes.len() as u32;
                }
                Part::Slot(_) => {
                    // resolved in step 3, once the slot entry bases are known
                    a.part_base.push(u32::MAX);
                    a.part_pick.push(u32::MAX);
                }
            }
        }

        // 2. word entries, slot-major (matches the GPU's `ebase` layout)
        for &g in used {
            a.slot_first.push(a.ent_off.len() as u32);
            let mut longest = 0u32;
            for w in &lists[g] {
                longest = longest.max(w.len() as u32);
                a.push_entry(w);
            }
            a.slot_max.push(longest);
        }

        // 3. point every Slot part at its slot's entry base
        for (k, part) in parts.iter().enumerate() {
            if let Part::Slot(pos) = part {
                a.part_base[k] = a.slot_first[*pos];
                a.part_pick[k] = *pos as u32;
            }
        }

        // 4. tail slack: the last entry's tail read may reach 7 bytes past its
        //    end, and the blob is also read as packed u32 words by the GPU
        let end = a.blob.len() + SLACK;
        a.blob.resize(end, 0);
        a
    }

    fn push_entry(&mut self, bytes: &[u8]) -> u32 {
        let e = self.ent_off.len() as u32;
        self.ent_off.push(self.blob.len() as u32);
        self.ent_len.push(bytes.len() as u32);
        self.blob.extend_from_slice(bytes);
        while self.blob.len() % 8 != 0 {
            self.blob.push(0);
        }
        e
    }

    /// Upper bound on the bytes [`Arena::fill`] can write. Callers size a stack
    /// buffer with this (plus 8, for the padded tail read) and fall back to the
    /// building path if it is unreasonably large.
    pub fn max_len(&self) -> usize {
        let mut n = self.lit_len as usize;
        for k in 0..self.part_pick.len() {
            let pick = self.part_pick[k];
            if pick != NO_PICK {
                n += self.slot_max[pick as usize] as usize;
            }
        }
        n
    }

    /// Write the candidate selected by `picks` into `out` and return its length.
    ///
    /// Callers must guarantee (asserted in debug builds):
    ///
    /// * `picks[i] < lens[i]` for every used slot, which `decode`/`bump` maintain;
    /// * `out.len() >= max_len() + 8`.
    ///
    /// The copy moves eight bytes at a time and therefore *over-writes* up to
    /// seven bytes past each part. That is deliberate: the next part overwrites
    /// them, and for the last part the padded hasher masks them off. It is why
    /// every arena entry is padded to an 8-byte boundary — an 8-byte load never
    /// leaves `blob`, and an 8-byte store never leaves `out`.
    #[inline]
    pub fn fill(&self, picks: &[usize], out: &mut [u8]) -> usize {
        debug_assert!(out.len() >= self.max_len() + 8, "fill needs 8 bytes of slack");
        let mut n = 0usize;
        for k in 0..self.part_base.len() {
            // SAFETY: `k < part_base.len()`; `pick` is either NO_PICK or a used-slot
            // position, via the invariant above `picks[pick]` is in range and
            // `base + picks[pick]` stays inside the entry table; the entry offsets
            // and lengths are inside `blob` by construction, and its 8-byte padding
            // (plus SLACK at the end) makes the final wide load legal. `out` has
            // `max_len() + 8` bytes, and `max_len()` bounds everything this loop
            // writes including the over-write.
            unsafe {
                let base = *self.part_base.get_unchecked(k);
                let pick = *self.part_pick.get_unchecked(k);
                let e = if pick == NO_PICK {
                    base
                } else {
                    base.wrapping_add(*picks.get_unchecked(pick as usize) as u32)
                };
                let off = *self.ent_off.get_unchecked(e as usize) as usize;
                let len = *self.ent_len.get_unchecked(e as usize) as usize;

                let src = self.blob.as_ptr().add(off);
                let dst = out.as_mut_ptr().add(n);
                let mut i = 0usize;
                while i < len {
                    let w = (src.add(i) as *const u64).read_unaligned();
                    (dst.add(i) as *mut u64).write_unaligned(w);
                    i += 8;
                }
                n += len;
            }
        }
        n
    }

    /// Number of entries (literals + words) in the blob.
    #[allow(dead_code)] // the tests use it; the GPU builder reads the tables directly
    pub fn entries(&self) -> usize {
        self.ent_off.len()
    }

    /// Entry index holding `pick` of part `k`.
    #[inline(always)]
    fn entry_of(&self, k: usize, picks: &[usize]) -> u32 {
        let base = self.part_base[k];
        let pick = self.part_pick[k];
        if pick == NO_PICK {
            base
        } else {
            base + picks[pick as usize] as u32
        }
    }

    /// Copy the candidate built from `picks` into `out` — the cold path (a match,
    /// or the CPU re-hash of a GPU-reported index), kept independent of
    /// [`Arena::fill`] on purpose so the two can be cross-checked.
    pub fn emit_into(&self, picks: &[usize], out: &mut Vec<u8>) {
        out.clear();
        for k in 0..self.part_base.len() {
            let e = self.entry_of(k, picks) as usize;
            let off = self.ent_off[e] as usize;
            let len = self.ent_len[e] as usize;
            out.extend_from_slice(&self.blob[off..off + len]);
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use crate::murmur::{hash_bytes, hash_padded};

    fn lit(s: &str) -> Part {
        Part::Lit(s.as_bytes().to_vec())
    }

    /// Hash a candidate exactly the way the crack loop does: fill a buffer with
    /// slack, then hash its first `n` bytes with the padded hasher.
    fn fast_hash(a: &Arena, picks: &[usize]) -> u64 {
        let mut sbuf = vec![0u8; a.max_len() + 8];
        let n = a.fill(picks, &mut sbuf);
        hash_padded(&sbuf, n)
    }

    fn filled(a: &Arena, picks: &[usize]) -> Vec<u8> {
        let mut sbuf = vec![0u8; a.max_len() + 8];
        let n = a.fill(picks, &mut sbuf);
        sbuf.truncate(n);
        sbuf
    }

    /// Parts must concatenate exactly, at every split point — `ab` + `cdefghij`
    /// has to hash like the single literal `abcdefghij`, including across the
    /// 8-byte block boundary.
    #[test]
    fn concatenates_across_part_boundaries() {
        let head = "ab";
        let tail = "cdefghij";
        let whole = format!("{head}{tail}");

        let lists: Vec<Vec<Vec<u8>>> = Vec::new();
        let parts = [lit(head), lit(tail)];
        let a = Arena::build(&lists, &[], &parts);
        assert_eq!(filled(&a, &[]), whole.as_bytes());
        assert_eq!(fast_hash(&a, &[]), hash_bytes(whole.as_bytes()));

        // ...and with the second half coming from a word list
        let lists = vec![vec![tail.as_bytes().to_vec()]];
        let parts = [lit(head), Part::Slot(0)];
        let a = Arena::build(&lists, &[0], &parts);
        assert_eq!(fast_hash(&a, &[0]), hash_bytes(whole.as_bytes()));
    }

    /// Every candidate length modulo 8 is a shape the padded tail read has to
    /// get right.
    #[test]
    fn every_length_matches_the_reference() {
        let words: Vec<Vec<u8>> = ["a", "ab", "abcdefg", "abcdefgh", "abcdefghi", "abcdefghijklmnop"]
            .iter()
            .map(|s| s.as_bytes().to_vec())
            .collect();
        let lists = vec![words.clone()];
        let parts = [lit("pre/"), Part::Slot(0), lit("_x")];
        let a = Arena::build(&lists, &[0], &parts);
        for p in 0..words.len() {
            let expect = format!("pre/{}_x", String::from_utf8_lossy(&words[p]));
            assert_eq!(filled(&a, &[p]), expect.as_bytes(), "emit for {expect}");
            assert_eq!(fast_hash(&a, &[p]), hash_bytes(expect.as_bytes()), "hash for {expect}");
        }
    }

    /// A slot used twice must expand to the *same* word in both places (locked
    /// slots), and each list keeps its own picks.
    #[test]
    fn locked_and_independent_slots() {
        let lists = vec![
            vec![b"aa".to_vec(), b"bb".to_vec()],
            vec![b"ZZ".to_vec()],
        ];
        let parts = [Part::Slot(0), lit("/"), Part::Slot(1), lit("_"), Part::Slot(0)];
        let a = Arena::build(&lists, &[0, 1], &parts);
        for (p0, p1, expect) in [(0usize, 0usize, "aa/ZZ_aa"), (1, 0, "bb/ZZ_bb")] {
            assert_eq!(filled(&a, &[p0, p1]), expect.as_bytes());
            assert_eq!(fast_hash(&a, &[p0, p1]), hash_bytes(expect.as_bytes()), "{expect}");
        }
    }

    #[test]
    fn every_entry_is_padded_and_aligned() {
        let lists = vec![vec![
            b"a".to_vec(),
            b"bbbbbbb".to_vec(),
            b"cc".to_vec(),
            Vec::new(),
        ]];
        let parts = [Part::Slot(0)];
        let a = Arena::build(&lists, &[0], &parts);
        assert_eq!(a.entries(), 4);
        for e in 0..a.entries() {
            assert_eq!(a.ent_off[e] % 8, 0, "entry {e} is not 8-byte aligned");
        }
        assert_eq!(a.blob.len() % 8, 0);
        assert!(a.blob.len() >= SLACK);
        // max_len has to bound what fill can write, or the buffer overruns
        assert!(a.max_len() >= 7);
    }
}


