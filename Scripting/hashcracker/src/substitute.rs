//! Substitute engine - build candidates out of the names we already have.
//!
//! Instead of guessing with dictionaries, every candidate is a *substitution* of
//! something present: a resolved name with one (or two) of its components
//! swapped for a value observed in the *same context* (`package_path` + `type`),
//! or the hybrid of two present names (one's directory, the other's leaf).
//!
//! A package is a small self-consistent naming world, so every value substituted
//! in is one the game really uses there.  Unlike `sweeps/pack_sweep.sh` this
//! covers *every* package (not the 20 biggest) and adds the hybrid and two-field
//! moves.
//!
//! Large-data rule: this walks the whole catalogue and generates millions of
//! candidates, so it lives in Rust (rayon) rather than Python.
//!
//!     hashcracker substitute [--catalogue FILE] [--overlay FILE] [--targets FILE]
//!                            [--packages N] [--no-hybrids] [--no-two-field]
//!                            [--matches FILE] [--quiet]

use anyhow::{Context, Result};
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use crate::{murmur, Args, Matches, TargetSet};

const DEF_CAT: &str = "../GauntletGameDigging/bundle_manifest/04_bundle_resources.csv";
const DEF_OVERLAY: &str = "../GauntletGameDigging/resource_name_overlay.json";

#[derive(Default)]
struct Ctx {
    present: Vec<String>,
    dirs: Vec<String>,
    leaves: Vec<String>,
    toks: Vec<String>,
    last: Vec<String>,
    sufs: Vec<String>,
    nums: Vec<String>,
}

fn is_num(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

/// Read `hash<TAB>name` style overlay (`resource_name_overlay.json`).
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
        let k = k.trim_start_matches('"');
        let v = v.trim_end_matches('"');
        if let Ok(h) = u64::from_str_radix(k, 16) {
            out.insert(h, v.to_string());
        }
    }
    out
}

/// Build per-context value sets from the catalogue, plus the unresolved hashes.
fn load(cat: &str, overlay: HashMap<u64, String>) -> Result<(Vec<Ctx>, Vec<u64>)> {
    let text = std::fs::read_to_string(cat).with_context(|| format!("reading {cat}"))?;
    let mut ctxs: HashMap<(String, String), Ctx> = HashMap::new();
    let mut targets = Vec::new();
    for (i, line) in text.lines().enumerate() {
        if i == 0 || line.is_empty() {
            continue;                       // header
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
        let c = ctxs.entry(key).or_default();
        c.present.push(owned.to_string());
        let (dir, leaf) = match owned.rfind('/') {
            Some(i) => (&owned[..=i], &owned[i + 1..]),
            None => ("", owned),
        };
        if !c.dirs.contains(&dir.to_string()) && !dir.is_empty() {
            c.dirs.push(dir.to_string());
        }
        if !c.leaves.contains(&leaf.to_string()) {
            c.leaves.push(leaf.to_string());
        }
        for t in leaf.split('_') {
            if t.len() < 2 {
                continue;
            }
            let bucket = if is_num(t) { &mut c.nums } else { &mut c.toks };
            if !bucket.iter().any(|x| x == t) {
                bucket.push(t.to_string());
            }
        }
        if let Some(l) = leaf.split('_').last() {
            if !c.last.iter().any(|x| x == l) {
                c.last.push(l.to_string());
            }
            if leaf.contains('_') {
                let s = format!("_{l}");
                if !c.sufs.iter().any(|x| *x == s) {
                    c.sufs.push(s);
                }
            }
        }
    }
    Ok((ctxs.into_values().collect(), targets))
}

fn split_name(name: &str) -> (&str, &str) {
    match name.rfind('/') {
        Some(i) => (&name[..=i], &name[i + 1..]),
        None => ("", name),
    }
}

/// One- and two-field substitutions of `name` from its own context's values.
fn emit(name: &str, c: &Ctx, two_field: bool, check: &mut impl FnMut(String)) {
    let (dir, leaf) = split_name(name);
    let parts: Vec<&str> = leaf.split('_').collect();
    for i in 0..parts.len() {
        for v in c.toks.iter().chain(c.last.iter()) {
            let mut p = parts.clone();
            p[i] = v;
            check(format!("{dir}{}", p.join("_")));
        }
        if is_num(parts[i]) {
            for v in &c.nums {
                let mut p = parts.clone();
                p[i] = v;
                check(format!("{dir}{}", p.join("_")));
            }
        }
    }
    for v in c.toks.iter().chain(c.last.iter()).chain(c.nums.iter()) {
        check(format!("{dir}{leaf}_{v}"));
        check(format!("{dir}{v}_{leaf}"));
    }
    if two_field {
        let top: Vec<&String> = c.toks.iter().take(40).collect();
        for i in 0..parts.len() {
            for j in (i + 1)..parts.len() {
                for a in &top {
                    for b in top.iter().take(20) {
                        let mut p = parts.clone();
                        p[i] = a;
                        p[j] = b;
                        check(format!("{dir}{}", p.join("_")));
                    }
                }
            }
        }
    }
}

/// One name's directory + another name's leaf, inside the same context.
fn hybrids(c: &Ctx, check: &mut impl FnMut(String)) {
    for d in &c.dirs {
        for l in &c.leaves {
            check(format!("{d}{l}"));
            if let Some((head, _)) = l.rsplit_once('_') {
                for s in &c.sufs {
                    check(format!("{d}{head}{s}"));
                }
            }
        }
    }
}

pub fn run(argv: &[String]) -> Result<()> {
    let args = Args::parse(argv)?;
    let cat = args.one("catalogue").unwrap_or_else(|| DEF_CAT.to_string());
    let ov_path = args.one("overlay").unwrap_or_else(|| DEF_OVERLAY.to_string());
    let matches_path = args.one_or("matches", "matches.tsv");
    let hybrid = !args.has("no-hybrids");
    let two_field = !args.has("no-two-field");
    let max_ctx: usize = args.one_or("packages", "0").parse().unwrap_or(0);

    let (mut ctxs, targets) = load(&cat, read_overlay(&ov_path))?;
    ctxs.sort_by_key(|c| std::cmp::Reverse(c.present.len()));
    if max_ctx > 0 {
        ctxs.truncate(max_ctx);
    }
    let target_list: Vec<u64> = match args.one("targets") {
        Some(f) => crate::read_targets(&f)?.into_iter().collect(),
        None => targets,
    };
    println!("contexts     : {}", ctxs.len());
    println!("targets      : {}", target_list.len());
    let tset = TargetSet::new(target_list.iter().copied());
    let matches = Mutex::new(Matches::open(&matches_path)?);
    let hits = AtomicU64::new(0);
    let cands = AtomicU64::new(0);
    let per_ctx: Mutex<Vec<(usize, usize)>> = Mutex::new(vec![(0, 0); ctxs.len()]);
    let t0 = std::time::Instant::now();

    ctxs.par_iter().enumerate().for_each_init(
        || HashSet::<u64>::with_capacity(1 << 16),
        |seen, (idx, c)| {
            let mut n = 0usize;
            let mut check = |name: String| {
                n += 1;
                let h = murmur::hash_bytes(name.as_bytes());
                if !seen.insert(h) {
                    return;
                }
                cands.fetch_add(1, Ordering::Relaxed);
                if tset.contains(h) {
                    let mut m = matches.lock().unwrap();
                    if m.add(h, &name).unwrap_or(false) {
                        println!("  MATCH {h:016x}  {name}");
                        hits.fetch_add(1, Ordering::Relaxed);
                    }
                }
            };
            for p in &c.present {
                emit(p, c, two_field, &mut check);
            }
            if hybrid {
                hybrids(c, &mut check);
            }
            per_ctx.lock().unwrap()[idx] = (c.present.len(), n);
        },
    );

    let secs = t0.elapsed().as_secs_f64();
    let total = cands.load(Ordering::Relaxed);
    println!("\nper context (present x candidates):");
    for (i, (p, n)) in per_ctx.lock().unwrap().iter().enumerate().take(12) {
        println!("  ctx {i:<4} present {p:>5}  candidates {n:>10}");
    }
    println!(
        "\ndone in {secs:.1}s\ncandidates   : {total}\nnew matches  : {}\nmatches file : {matches_path}",
        hits.load(Ordering::Relaxed)
    );
    Ok(())
}
