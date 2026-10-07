//! Substitute engine - candidates built out of the names we already have.
//!
//! Every candidate is a *substitution* of something present, drawn from the
//! values its own context (`package_path` + `type`) actually uses: a package is
//! a small self-consistent naming world, so nothing here is a dictionary guess.
//!
//! The engine is expressed as **patterns with slots**, so the GPU path
//! (`gpu::Gpu::eval_pattern`) does the generation *and* the hashing, with the
//! same CPU/rayon fallback the `crack` mode uses:
//!
//!     %0_%1_%2 ...   positional substitution: any token position may take any
//!                    value seen in that position in this context, so
//!                    `wep_elf_special_bomb_trail` yields
//!                    `wep_elf_special_<x>_trail` (middle position included)
//!     %a%s           stem + map suffix   (`caverock_rock_01_diff`)
//!     %a_%n          stem + number       (`caverock_rock_01_02`)
//!     %d ...         the directory is a slot too, so the hybrid move (one
//!                    name's directory + another's leaf) falls out of it
//!
//! Large-data rule: this walks the whole catalogue and generates billions of
//! candidates, so it lives in Rust rather than Python.
//!
//!     hashcracker substitute [--catalogue FILE] [--overlay FILE] [--targets FILE]
//!                            [--packages N] [--depth N] [--top N] [--cpu]
//!                            [--matches FILE]

use anyhow::{Context, Result};
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use crate::gpu::Gpu;
use crate::pattern::Compiler;
use crate::{murmur, Args, Matches};

const DEF_CAT: &str = "../GauntletGameDigging/bundle_manifest/04_bundle_resources.csv";
const DEF_OVERLAY: &str = "../GauntletGameDigging/resource_name_overlay.json";

/// Per-context value sets, already in the shape the slots want.
#[derive(Default)]
struct Ctx {
    pack: String,
    typ: String,
    dirs: Vec<Vec<u8>>,    // "a/b/" - with the trailing slash
    first: Vec<Vec<u8>>,   // first token of a leaf
    mid: Vec<Vec<u8>>,     // tokens (bounded pool for the deep patterns)
    last: Vec<Vec<u8>>,    // last token of a leaf
    leaves: Vec<Vec<u8>>,  // whole leaves
    stems: Vec<Vec<u8>>,   // leaf minus its last token ("x_diff" -> "x")
    sufs: Vec<Vec<u8>>,    // "_diff" style suffixes
    nums: Vec<Vec<u8>>,    // numeric tokens
    present: usize,
}

fn is_num(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

fn push_unique(v: &mut Vec<Vec<u8>>, s: &str) {
    if s.is_empty() {
        return;
    }
    let b = s.as_bytes();
    if !v.iter().any(|x| x == b) {
        v.push(b.to_vec());
    }
}

/// Read `resource_name_overlay.json` (a `"hash": "name"` map) without a JSON dep.
fn read_overlay(path: &str) -> HashMap<u64, String> {
    let mut out = HashMap::new();
    let Ok(text) = std::fs::read_to_string(path) else {
        return out;
    };
    for line in text.lines() {
        let line = line.trim().trim_end_matches(',');
        if !line.starts_with('"') {
            continue;
        }
        let Some((k, v)) = line.split_once("\": \"") else {
            continue;
        };
        if let Ok(h) = u64::from_str_radix(k.trim_start_matches('"'), 16) {
            out.insert(h, v.trim_end_matches('"').to_string());
        }
    }
    out
}

/// Walk the catalogue: build the per-context value sets and collect the
/// unresolved hashes.
fn load(cat: &str, overlay: &HashMap<u64, String>) -> Result<(Vec<Ctx>, Vec<u64>)> {
    let text = std::fs::read_to_string(cat).with_context(|| format!("reading {cat}"))?;
    let mut map: HashMap<(String, String), Ctx> = HashMap::new();
    let mut targets = Vec::new();
    for (i, line) in text.lines().enumerate() {
        if i == 0 || line.is_empty() {
            continue;
        }
        let f: Vec<&str> = line.split(',').collect();
        if f.len() < 7 {
            continue;
        }
        let (pack, typ, hash, name) = (f[1], f[3], f[5], f[6]);
        let Ok(h) = u64::from_str_radix(hash, 16) else {
            continue;
        };
        let owned = overlay.get(&h).map(String::as_str).unwrap_or(name);
        if owned.is_empty() {
            targets.push(h);
            continue;
        }
        let key = (pack.to_string(), typ.to_string());
        let c = map.entry(key.clone()).or_insert_with(|| Ctx {
            pack: key.0.clone(),
            typ: key.1.clone(),
            ..Default::default()
        });
        c.present += 1;
        let (dir, leaf) = match owned.rfind('/') {
            Some(i) => (&owned[..=i], &owned[i + 1..]),
            None => ("", owned),
        };
        push_unique(&mut c.dirs, dir);
        push_unique(&mut c.leaves, leaf);
        let toks: Vec<&str> = leaf.split('_').collect();
        if let Some(t) = toks.first() {
            push_unique(&mut c.first, t);
        }
        if let Some(t) = toks.last() {
            push_unique(&mut c.last, t);
            if toks.len() > 1 {
                push_unique(&mut c.stems, &leaf[..leaf.len() - t.len() - 1]);
                push_unique(&mut c.sufs, &format!("_{t}"));
            }
        }
        for t in &toks {
            if t.len() < 2 {
                continue;
            }
            if is_num(t) {
                push_unique(&mut c.nums, t);
            } else {
                push_unique(&mut c.mid, t);
            }
        }
    }
    Ok((map.into_values().collect(), targets))
}

/// Number neighbours: every observed number also gets +/-1..3, keeping its width
/// (`_03` -> `_02`, `_04`, `_00`), plus the unpadded spelling.
fn expand_nums(nums: &[Vec<u8>]) -> Vec<Vec<u8>> {
    let mut out: Vec<Vec<u8>> = nums.to_vec();
    for n in nums {
        let s = String::from_utf8_lossy(n).into_owned();
        let Ok(v) = s.parse::<i64>() else { continue };
        for d in [-3i64, -2, -1, 1, 2, 3] {
            let x = v + d;
            if x < 0 {
                continue;
            }
            let padded = format!("{x:0width$}", width = s.len());
            push_unique(&mut out, &padded);
            if s.len() > 1 {
                push_unique(&mut out, &x.to_string());
            }
        }
    }
    out
}

/// Plural siblings of a token pool - quilt/effect groups are plural in the
/// shipped names (`juggernaut` -> `juggernauts`, `statue` -> `statues`).
fn plurally(vals: &[Vec<u8>]) -> Vec<Vec<u8>> {
    let mut out: Vec<Vec<u8>> = vals.to_vec();
    for v in vals {
        let s = String::from_utf8_lossy(v).into_owned();
        if let Some(stem) = s.strip_suffix('y') {
            push_unique(&mut out, &format!("{stem}ies"));
        }
        if s.ends_with('s') || s.ends_with('x') || s.ends_with("ch") || s.ends_with("sh") {
            push_unique(&mut out, &format!("{s}es"));
        }
        push_unique(&mut out, &format!("{s}s"));
    }
    out
}

/// Bind this context's values to slot letters and return its patterns.
///
/// Slot letters: `d` directory, `l` whole leaf, `a` stem, `s` suffix,
/// `n` number, `0` first token, `1` middle token (bounded pool), `2` last token.
fn plan(c: &Ctx, comp: &mut Compiler, depth: usize, top: usize) -> Vec<String> {
    let mid: Vec<Vec<u8>> = plurally(&c.mid.iter().take(top).cloned().collect::<Vec<_>>());
    let nums = expand_nums(&c.nums);
    for (ch, vals) in [(b'd', &c.dirs), (b'l', &c.leaves), (b'a', &c.stems),
                       (b's', &c.sufs), (b'n', &c.nums), (b'0', &c.first),
                       (b'2', &c.last)] {
        let i = comp.slot(ch);
        comp.lists[i] = vals.clone();
    }
    for ch in [b'1', b'3', b'4', b'5'] {
        let i = comp.slot(ch);
        comp.lists[i] = mid.clone();
    }
    let i = comp.slot(b'n');
    comp.lists[i] = nums;

    let mut pats: Vec<String> = vec![
        "%d%l".into(),        // one name's directory + another's whole leaf (hybrid)
        "%l".into(),
        "%d%0_%2".into(),     // directory + first + last     (positional swap)
        "%0_%2".into(),
        "%d%a%s".into(),      // directory + stem + map suffix
        "%a%s".into(),
        "%d%a_%n".into(),     // directory + stem + number
        "%a_%n".into(),
    ];
    if depth >= 3 {
        pats.push("%d%0_%1_%2".into());   // three positions at once
        pats.push("%0_%1_%2".into());
        pats.push("%d%a_%1_%2".into());   // stem + middle + last
        pats.push("%0_%3_%2".into());     // middle-first order too
    }
    if depth >= 4 {
        pats.push("%d%0_%3_%1_%2".into());   // four tokens
        pats.push("%0_%3_%1_%2".into());
        pats.push("%d%0_%1_%3_%2".into());
    }
    if depth >= 5 {
        pats.push("%d%0_%3_%4_%1_%2".into()); // five tokens
        pats.push("%0_%3_%4_%1_%2".into());
    }
    pats
}

/// CPU fallback: walk the pattern's index space with the odometer emitter.
fn run_cpu(pat: &crate::pattern::Compiled, lists: &[Vec<Vec<u8>>],
           targets: &HashSet<u64>) -> Vec<(u64, Vec<u8>)> {
    let total = pat.total();
    if total == 0 {
        return Vec::new();
    }
    let nslots = pat.slots();
    let nt = rayon::current_num_threads() as u64;
    let chunk = total.div_ceil(nt.max(1));
    (0..nt)
        .into_par_iter()
        .map(|t| {
            let start = t * chunk;
            let end = ((t + 1) * chunk).min(total);
            let mut out = Vec::new();
            let mut buf = Vec::with_capacity(192);
            let mut picks = [0usize; 16];
            if start >= end {
                return out;
            }
            if nslots == 0 {
                pat.emit(lists, &[], &mut buf);
                let h = murmur::hash_bytes(&buf);
                if targets.contains(&h) {
                    out.push((h, buf.clone()));
                }
                return out;
            }
            pat.decode(start, &mut picks);
            for _ in start..end {
                pat.emit(lists, &picks[..nslots], &mut buf);
                let h = murmur::hash_bytes(&buf);
                if targets.contains(&h) {
                    out.push((h, buf.clone()));
                }
                if !pat.bump(&mut picks) {
                    break;
                }
            }
            out
        })
        .flatten()
        .collect()
}

/// Union the value sets of every context of the same type.
///
/// Per-package contexts keep the candidates maximally plausible but make each
/// pattern tiny, and the GPU pays a fixed cost per dispatch - 1,665 contexts x
/// 11 patterns of a few hundred thousand candidates each runs at ~33 M/s, while
/// the same engine at type granularity runs at ~800 M/s with much wider pools.
/// `--by-package` selects the precise (slow) variant.
fn merge_by_type(ctxs: Vec<Ctx>) -> Vec<Ctx> {
    let mut map: HashMap<String, Ctx> = HashMap::new();
    for c in ctxs {
        let e = map.entry(c.typ.clone()).or_insert_with(|| Ctx {
            pack: "*".to_string(),
            typ: c.typ.clone(),
            ..Default::default()
        });
        e.present += c.present;
        for (dst, src) in [(&mut e.dirs, &c.dirs), (&mut e.first, &c.first),
                           (&mut e.mid, &c.mid), (&mut e.last, &c.last),
                           (&mut e.leaves, &c.leaves), (&mut e.stems, &c.stems),
                           (&mut e.sufs, &c.sufs), (&mut e.nums, &c.nums)] {
            for v in src {
                if !dst.iter().any(|x| x == v) {
                    dst.push(v.clone());
                }
            }
        }
    }
    map.into_values().collect()
}

/// Cross-type substitution: borrow the value pools of the *other* types.
///
/// A texture is named after the unit or material that owns it
/// (`characters/x/x_diff`), and those stems live in the `unit` / `material`
/// contexts - so the per-type sweep can never reach them.  This pass binds the
/// catalogue-wide pools (every directory, stem, suffix and number) and crosses
/// them, bounded by `--top` so the space stays runnable.
/// Read extra vocabulary files (one value per line) into byte vectors.
fn read_vocab(paths: &[String]) -> Vec<Vec<u8>> {
    let mut out: Vec<Vec<u8>> = Vec::new();
    for path in paths {
        let Ok(text) = std::fs::read_to_string(path) else { continue };
        for line in text.lines() {
            let v = line.trim().to_ascii_lowercase();
            if v.is_empty() || v.starts_with('#') || v.len() > 64 {
                continue;
            }
            push_unique(&mut out, &v);
        }
    }
    out
}

fn cross_ctx(ctxs: &[Ctx], top: usize, extra: &[Vec<u8>], sufs_extra: &[Vec<u8>]) -> Ctx {
    let mut g = Ctx { pack: "*".to_string(), typ: "any".to_string(), ..Default::default() };
    let mut dirs = Vec::new();
    let mut stems = Vec::new();
    let mut sufs = Vec::new();
    let mut nums = Vec::new();
    for c in ctxs {
        for (dst, src) in [(&mut dirs, &c.dirs), (&mut stems, &c.stems),
                           (&mut sufs, &c.sufs), (&mut nums, &c.nums)] {
            for v in src {
                if !dst.iter().any(|x| x == v) {
                    dst.push(v.clone());
                }
            }
        }
    }
    g.present = ctxs.iter().map(|c| c.present).sum();
    let mut all = stems;
    for v in extra {
        if !all.iter().any(|x| x == v) {
            all.push(v.clone());
        }
    }
    if all.is_empty() {
        all = extra.to_vec();
    }
    g.dirs = dirs;
    g.stems = all;
    let mut s = sufs;
    for v in sufs_extra {
        if !s.iter().any(|x| x == v) {
            s.push(v.clone());
        }
    }
    g.sufs = s.into_iter().take(128).collect();
    g.nums = nums.into_iter().take(256).collect();
    let _ = top;
    g
}

fn cross_patterns(c: &Ctx, comp: &mut Compiler) -> Vec<String> {
    for (ch, vals) in [(b'D', &c.dirs), (b'A', &c.stems), (b'S', &c.sufs),
                       (b'N', &c.nums)] {
        let i = comp.slot(ch);
        comp.lists[i] = vals.clone();
    }
    vec!["%D%A".into(), "%D%A%S".into(), "%D%A_%N".into()]
}

fn record(matches: &Mutex<Matches>, hits: &AtomicU64, ctx: &str, h: u64, name: &[u8]) {
    let shown = String::from_utf8_lossy(name).into_owned();
    if matches.lock().unwrap().add(h, &shown).unwrap_or(false) {
        println!("  MATCH {h:016x}  {shown}   [{ctx}]");
        hits.fetch_add(1, Ordering::Relaxed);
    }
}

pub fn run(argv: &[String]) -> Result<()> {
    let args = Args::parse(argv)?;
    let cat = args.one("catalogue").unwrap_or_else(|| DEF_CAT.to_string());
    let ov_path = args.one("overlay").unwrap_or_else(|| DEF_OVERLAY.to_string());
    let matches_path = args.one_or("matches", "matches.tsv");
    let depth: usize = args.one_or("depth", "3").parse().unwrap_or(2);
    let top: usize = args.one_or("top", "24").parse().unwrap_or(24);
    let max_ctx: usize = args.one_or("packages", "0").parse().unwrap_or(0);
    let suf_path = args.one("suffixes").unwrap_or_else(|| "data/suffixes.txt".to_string());

    let overlay = read_overlay(&ov_path);
    let (ctxs, targets) = load(&cat, &overlay)?;
    let mut ctxs = if args.has("by-package") {
        let mut v = ctxs;
        v.sort_by_key(|c| std::cmp::Reverse(c.present));
        v
    } else {
        merge_by_type(ctxs)
    };
    ctxs.sort_by_key(|c| std::cmp::Reverse(c.present));
    if max_ctx > 0 {
        ctxs.truncate(max_ctx);
    }
    let tset: HashSet<u64> = match args.one("targets") {
        Some(f) => crate::read_targets(&f)?.into_iter().collect(),
        None => targets.into_iter().collect(),
    };

    let gpu = if args.has("cpu") { None } else { Gpu::new().ok() };
    println!("contexts     : {}", ctxs.len());
    println!("targets      : {}", tset.len());
    println!("depth        : {depth}   (middle pool {top})");
    match &gpu {
        Some(g) => println!("gpu           : {}", g.info()),
        None => println!("gpu           : unavailable - CPU path for everything"),
    }

    let matches = Mutex::new(Matches::open(&matches_path)?);
    let hits = AtomicU64::new(0);
    let cands = AtomicU64::new(0);
    let used_gpu = AtomicU64::new(0);
    let per: Mutex<Vec<(String, u64)>> = Mutex::new(Vec::new());
    let t0 = std::time::Instant::now();

    for c in &ctxs {
        let mut ctx_cands: u64 = 0;
        let mut comp = Compiler::new();
        for p in plan(c, &mut comp, depth, top) {
            let Ok(pat) = comp.compile(&p) else { continue };
            let total = pat.total();
            if total == 0 {
                continue;
            }
            cands.fetch_add(total, Ordering::Relaxed);
            ctx_cands += total;
            let mut done = false;
            if let Some(g) = &gpu {
                let label = format!("{}/{}", c.pack, c.typ);
                let mut cb = |h: u64, name: &[u8]| record(&matches, &hits, &label, h, name);
                match g.eval_pattern(&pat, &comp.lists, &tset, 0, &mut cb) {
                    Ok(_) => {
                        done = true;
                        used_gpu.fetch_add(total, Ordering::Relaxed);
                    }
                    Err(e) => eprintln!("  gpu: {e} - CPU fallback for {p:?}"),
                }
            }
            if !done {
                let label = format!("{}/{}", c.pack, c.typ);
                for (h, name) in run_cpu(&pat, &comp.lists, &tset) {
                    record(&matches, &hits, &label, h, &name);
                }
            }
        }
        per.lock().unwrap().push((format!("{}/{}", c.pack, c.typ), ctx_cands));
    }

    if args.has("cross") {
        let extra = read_vocab(&args.all("vocab"));
        let sufs_extra = read_vocab(&[suf_path]);
        let g = cross_ctx(&ctxs, top, &extra, &sufs_extra);
        let mut comp = Compiler::new();
        for p in cross_patterns(&g, &mut comp) {
            let Ok(pat) = comp.compile(&p) else { continue };
            let total = pat.total();
            if total == 0 {
                continue;
            }
            println!("cross {p:<12} {total:>15} cands");
            cands.fetch_add(total, Ordering::Relaxed);
            let mut done = false;
            if let Some(gpu) = &gpu {
                let label = "cross-type".to_string();
                let mut cb = |h: u64, name: &[u8]| record(&matches, &hits, &label, h, name);
                match gpu.eval_pattern(&pat, &comp.lists, &tset, 0, &mut cb) {
                    Ok(_) => {
                        done = true;
                        used_gpu.fetch_add(total, Ordering::Relaxed);
                    }
                    Err(e) => eprintln!("  gpu: {e} - CPU fallback for {p:?}"),
                }
            }
            if !done {
                for (h, name) in run_cpu(&pat, &comp.lists, &tset) {
                    record(&matches, &hits, "cross-type", h, &name);
                }
            }
        }
    }

    let mut rows = per.into_inner().unwrap();
    rows.sort_by_key(|r| std::cmp::Reverse(r.1));
    println!("\ncontexts by candidates:");
    for (k, n) in rows.iter().take(12) {
        println!("  {k:<40} {n:>14}");
    }

    let secs = t0.elapsed().as_secs_f64();
    let total = cands.load(Ordering::Relaxed);
    let on_gpu = used_gpu.load(Ordering::Relaxed);
    println!(
        "\ndone in {secs:.1}s\ncandidates   : {total}  (gpu {on_gpu}, cpu {})",
        total - on_gpu
    );
    if secs > 0.0 {
        println!("rate         : {:.0} M/s", total as f64 / secs / 1e6);
    }
    println!(
        "new matches  : {}\nmatches file : {matches_path}",
        hits.load(Ordering::Relaxed)
    );
    Ok(())
}
