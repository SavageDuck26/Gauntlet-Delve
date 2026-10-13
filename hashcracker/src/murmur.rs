//! MurmurHash64A - the exact variant Bitsquid/Stingray (and thus Gauntlet) uses
//! for resource + bundle names.
//!
//! Confirmed parameters:
//!   * seed  = 0
//!   * input = lowercase ASCII bytes of the resource path
//!   * output = little-endian u64
//!
//! This matches `murmur_hash64()` in the Python toolchain bit-for-bit.

pub const M: u64 = 0xc6a4_a793_5bd1_e995;
pub const R: u32 = 47;

/// Hash an already-lowercased byte slice (seed 0).
#[inline]
pub fn hash_bytes(data: &[u8]) -> u64 {
    let len = data.len() as u64;
    let mut h: u64 = len.wrapping_mul(M); // seed 0

    let nblocks = data.len() / 8;
    for i in 0..nblocks {
        let mut k = u64::from_le_bytes(data[i * 8..i * 8 + 8].try_into().unwrap());
        k = k.wrapping_mul(M);
        k ^= k >> R;
        k = k.wrapping_mul(M);
        h ^= k;
        h = h.wrapping_mul(M);
    }

    let tail = &data[nblocks * 8..];
    if !tail.is_empty() {
        let mut t: u64 = 0;
        for (i, &b) in tail.iter().enumerate() {
            t |= (b as u64) << (8 * i);
        }
        h ^= t;
        h = h.wrapping_mul(M);
    }

    h ^= h >> R;
    h = h.wrapping_mul(M);
    h ^= h >> R;
    h
}

/// Hash the first `len` bytes of `buf`, which must have at least `len + 8` bytes
/// of storage. That slack lets the tail be read as one masked 8-byte load
/// instead of a byte-at-a-time loop.
///
/// Bit-for-bit equal to `hash_bytes(&buf[..len])`; `padded_matches_plain`
/// checks that for every length and every starting offset.
#[inline]
pub fn hash_padded(buf: &[u8], len: usize) -> u64 {
    debug_assert!(buf.len() >= len + 8, "tail read needs 8 bytes of slack");
    let mut h: u64 = (len as u64).wrapping_mul(M); // seed 0

    let nblocks = len / 8;
    for i in 0..nblocks {
        // SAFETY: i*8 + 8 <= nblocks*8 <= len <= buf.len() - 8.
        let mut k = unsafe { (buf.as_ptr().add(i * 8) as *const u64).read_unaligned() };
        k = k.wrapping_mul(M);
        k ^= k >> R;
        k = k.wrapping_mul(M);
        h ^= k;
        h = h.wrapping_mul(M);
    }

    let tail = len & 7;
    if tail != 0 {
        // SAFETY: the load starts at nblocks*8 <= len and the slack guarantees
        // eight readable bytes there; everything past `len` is masked off.
        let raw = unsafe { (buf.as_ptr().add(nblocks * 8) as *const u64).read_unaligned() };
        h ^= raw & ((1u64 << (tail * 8)) - 1);
        h = h.wrapping_mul(M);
    }

    h ^= h >> R;
    h = h.wrapping_mul(M);
    h ^= h >> R;
    h
}

/// Convenience: lowercase a `&str` (ASCII) and hash it.
#[allow(dead_code)]
#[inline]
pub fn hash_str(s: &str) -> u64 {
    let mut buf = Vec::with_capacity(s.len());
    for b in s.bytes() {
        buf.push(b.to_ascii_lowercase());
    }
    hash_bytes(&buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_python_reference() {
        // Values produced by the Python `murmur_hash64()` (list_game_bundles.py).
        assert_eq!(hash_str("resource_packages/elias"), 0xb22560b172a4cff8);
        assert_eq!(hash_str("resource_packages/boot"), 0x9e13b2414b41b842);
        assert_eq!(hash_str("modules/d01_crypt/resources"), 0x0164ad48615ba9ed);
        assert_eq!(hash_str("core/rendering/renderer"), 0x1a9c33dcd0301dfd);
        assert_eq!(hash_str("resource_packages/heroes/elf_base"), 0x2c8fb6cb55aba416);
        // case-insensitive
        assert_eq!(hash_str("RESOURCE_PACKAGES/ELIAS"), hash_str("resource_packages/elias"));
    }

    /// `hash_padded` must agree with `hash_bytes` for every length, including
    /// the ones whose tail straddles the end of the buffer.
    #[test]
    fn padded_matches_plain() {
        let data: Vec<u8> = (0..=200u32).map(|i| (i * 37 % 251) as u8).collect();
        for len in 0..=128usize {
            for off in 0..8usize {
                // 8 bytes of slack after the candidate, so the tail read is legal
                let buf = &data[off..off + len + 8];
                assert_eq!(
                    hash_padded(buf, len),
                    hash_bytes(&data[off..off + len]),
                    "len {len} off {off}"
                );
            }
        }
    }
}
