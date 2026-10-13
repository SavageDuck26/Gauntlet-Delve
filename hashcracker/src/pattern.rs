//! Candidate generation from patterns + per-slot word lists.
//!
//! A pattern is literal text with `%X` slot placeholders (`%%` = literal `%`).
//! Each slot letter is bound to a word list (via `--list X=FILE`). Within one
//! pattern a slot is *locked*: every occurrence of `%X` expands to the same
//! value, which keeps the search space small and matches real naming schemes,
//! e.g. `characters/%n/%n_diff`.
//!
//! Generation is index-addressed (mixed-radix) so the whole space can be split
//! across threads and evaluated in parallel.
//!
//! Compiling also flattens every byte the pattern can emit into an [`Arena`]
//! (`arena.rs`) - the CPU hot loop hashes candidates straight out of it without
//! ever building a string, and the GPU kernel reads the same bytes.

use crate::arena::Arena;

/// One piece of a compiled pattern.
pub enum Part {
    Lit(Vec<u8>),
    /// Reference to a *used-slot* position (index into `used`).
    Slot(usize),
}

/// Most slots a pattern may use. The hot paths decode picks into a fixed
/// `[usize; 16]` on the stack, so this is a hard limit rather than a preference;
/// the GPU additionally falls back to the CPU above its own limit of 8.
pub const MAX_SLOTS: usize = 16;

/// A pattern compiled against the slot bindings of a [`Compiler`].
pub struct Compiled {
    pub parts: Vec<Part>,
    /// global word-list index for each used-slot position
    pub used: Vec<usize>,
    /// per used-slot list length
    pub lens: Vec<u64>,
    /// Every byte this pattern can emit, flattened once - shared with the GPU
    /// kernel, so the CPU no longer walks `Vec<Vec<Vec<u8>>>` per candidate.
    pub arena: Arena,
}

impl Compiled {
    /// Number of candidates this pattern expands to.
    pub fn total(&self) -> u64 {
        self.lens.iter().fold(1u64, |a, &b| a.saturating_mul(b))
    }

    /// Number of used slots (== `lens.len()`).
    pub fn slots(&self) -> usize {
        self.lens.len()
    }

    /// Decode a flat index into per-slot picks (mixed radix, slot 0 = least
    /// significant). Called once per thread chunk, so the divisions here are
    /// amortised over the whole chunk.
    #[inline]
    pub fn decode(&self, idx: u64, picks: &mut [usize]) {
        debug_assert!(picks.len() >= self.lens.len(), "picks must cover every slot");
        let mut rem = idx;
        for i in 0..self.lens.len() {
            // SAFETY: lens.len() == used.len() <= MAX_SLOTS (enforced in
            // `compile`), and `picks` covers at least that many entries - the
            // debug assertion above states it.
            unsafe {
                let l = *self.lens.get_unchecked(i);
                *picks.get_unchecked_mut(i) = (rem % l) as usize;
                rem /= l;
            }
        }
    }

    /// Odometer-increment `picks` to the next candidate (slot 0 first).
    /// Returns false when it wraps past the end.
    #[inline]
    pub fn bump(&self, picks: &mut [usize]) -> bool {
        debug_assert!(picks.len() >= self.lens.len(), "picks must cover every slot");
        for i in 0..self.lens.len() {
            // SAFETY: as in `decode` - the bounds are a compile-time invariant
            // (MAX_SLOTS), asserted in debug builds.
            unsafe {
                let l = *self.lens.get_unchecked(i);
                let p = picks.get_unchecked_mut(i);
                *p += 1;
                if (*p as u64) < l {
                    return true;
                }
                *p = 0;
            }
        }
        false
    }

    /// Emit the candidate for the given `picks` into `out` (no decoding).
    #[inline]
    pub fn emit(&self, lists: &[Vec<Vec<u8>>], picks: &[usize], out: &mut Vec<u8>) {
        out.clear();
        for part in &self.parts {
            match part {
                Part::Lit(b) => out.extend_from_slice(b),
                Part::Slot(pos) => out.extend_from_slice(&lists[self.used[*pos]][picks[*pos]]),
            }
        }
    }

    /// Write candidate #`idx` into `out` (cleared first). No longer on the hot
    /// path - the crack loop hashes with `hash_fast` - but kept as the reference
    /// implementation the arena is validated against (and used to rebuild a name
    /// for the rare GPU-reported index).
    #[allow(dead_code)]
    #[inline]
    pub fn build(&self, lists: &[Vec<Vec<u8>>], idx: u64, out: &mut Vec<u8>) {
        out.clear();
        // decode mixed-radix index -> a pick per used slot (stack array: no heap
        // allocation in the hot loop; patterns use far fewer than 16 slots)
        let mut picks = [0usize; 16];
        let n = self.lens.len();
        let mut rem = idx;
        for i in 0..n {
            picks[i] = (rem % self.lens[i]) as usize;
            rem /= self.lens[i];
        }
        for part in &self.parts {
            match part {
                Part::Lit(b) => out.extend_from_slice(b),
                Part::Slot(pos) => out.extend_from_slice(&lists[self.used[*pos]][picks[*pos]]),
            }
        }
    }
}

/// Holds the slot bindings and can compile patterns against them.
pub struct Compiler {
    /// slot letter (uppercase-normalised) -> global list index
    pub slot_index: Vec<(u8, usize)>,
    pub lists: Vec<Vec<Vec<u8>>>,
}

impl Compiler {
    pub fn new() -> Self {
        Compiler { slot_index: Vec::new(), lists: Vec::new() }
    }

    /// Bind (or fetch) the global list index for a slot letter.
    pub fn slot(&mut self, c: u8) -> usize {
        let c = c.to_ascii_lowercase();
        if let Some(&(_, i)) = self.slot_index.iter().find(|(k, _)| *k == c) {
            return i;
        }
        let i = self.lists.len();
        self.lists.push(Vec::new());
        self.slot_index.push((c, i));
        i
    }

    /// Compile a pattern string. Returns an error message on a dangling `%`.
    pub fn compile(&self, pat: &str) -> Result<Compiled, String> {
        let bytes = pat.as_bytes();
        let mut parts = Vec::new();
        let mut used: Vec<usize> = Vec::new(); // used-position -> global list idx
        let mut lit: Vec<u8> = Vec::new();
        let mut i = 0;
        while i < bytes.len() {
            let b = bytes[i];
            if b == b'%' {
                if i + 1 >= bytes.len() {
                    return Err(format!("dangling % in pattern {pat:?}"));
                }
                let n = bytes[i + 1];
                if n == b'%' {
                    lit.push(b'%');
                    i += 2;
                    continue;
                }
                if !n.is_ascii_alphabetic() {
                    return Err(format!("bad slot %{} in pattern {pat:?}", n as char));
                }
                let g = self
                    .slot_index
                    .iter()
                    .find(|(k, _)| *k == n.to_ascii_lowercase())
                    .map(|(_, i)| *i)
                    .ok_or_else(|| format!("slot %{} has no --list", n as char))?;
                let pos = match used.iter().position(|&u| u == g) {
                    Some(p) => p,
                    None => {
                        used.push(g);
                        used.len() - 1
                    }
                };
                if !lit.is_empty() {
                    parts.push(Part::Lit(std::mem::take(&mut lit)));
                }
                parts.push(Part::Slot(pos));
                i += 2;
            } else {
                lit.push(b.to_ascii_lowercase());
                i += 1;
            }
        }
        if !lit.is_empty() {
            parts.push(Part::Lit(lit));
        }
        if used.len() > MAX_SLOTS {
            return Err(format!(
                "pattern {pat:?} uses {} slots; at most {MAX_SLOTS} are supported",
                used.len()
            ));
        }
        let lens: Vec<u64> = used.iter().map(|&g| self.lists[g].len() as u64).collect();
        let arena = Arena::build(&self.lists, &used, &parts);
        Ok(Compiled { parts, used, lens, arena })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn comp() -> Compiler {
        let mut c = Compiler::new();
        let d = c.slot(b'd');
        c.lists[d] = vec![b"a".to_vec(), b"b".to_vec()];
        let n = c.slot(b'n');
        c.lists[n] = vec![b"x".to_vec()];
        c
    }

    #[test]
    fn builds_in_order() {
        let c = comp();
        let p = c.compile("%d/%n_%d").unwrap();
        assert_eq!(p.total(), 2);
        let mut buf = Vec::new();
        p.build(&c.lists, 0, &mut buf);
        assert_eq!(buf, b"a/x_a");
        p.build(&c.lists, 1, &mut buf);
        assert_eq!(buf, b"b/x_b");
    }

    /// The arena is a second implementation of the same maths from a different
    /// layout, so it is checked against the reference (`build` + `hash_bytes`)
    /// across the *whole* space - every part boundary, block boundary and slot
    /// combination. This is the contract the crack loop relies on.
    #[test]
    fn arena_agrees_with_reference_over_the_whole_space() {
        let c = comp();
        let p = c.compile("%d/%n_%d").unwrap();
        let mut buf = Vec::new();
        let mut picks = [0usize; 16];
        let mut sbuf = vec![0u8; p.arena.max_len() + 8];
        for idx in 0..p.total() {
            p.build(&c.lists, idx, &mut buf);
            p.decode(idx, &mut picks);
            let n = p.arena.fill(&picks, &mut sbuf);
            assert_eq!(
                crate::murmur::hash_padded(&sbuf, n),
                crate::murmur::hash_bytes(&buf),
                "arena hash differs from the reference at idx {idx}"
            );
            let mut arena_buf = Vec::new();
            p.arena.emit_into(&picks, &mut arena_buf);
            assert_eq!(arena_buf, buf, "arena emit differs at idx {idx}");
        }
    }

    /// More slots than the fixed decode array can hold has to be a clean error:
    /// it used to be an index-out-of-bounds panic.
    #[test]
    fn too_many_slots_is_an_error_not_a_panic() {
        let mut c = Compiler::new();
        let mut pat = String::new();
        for ch in b'a'..=b'q' {
            c.slot(ch);
            pat.push('%');
            pat.push(ch as char);
        }
        assert_eq!(c.lists.len(), 17);
        let err = match c.compile(&pat) {
            Ok(_) => panic!("17-slot pattern compiled, but the limit is {MAX_SLOTS}"),
            Err(e) => e,
        };
        assert!(err.contains("17 slots"), "unexpected error: {err}");
    }
}
