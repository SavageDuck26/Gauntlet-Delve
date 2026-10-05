//! hashcracker — multithreaded MurmurHash64A brute-forcer for Gauntlet
//! resource/bundle names.
//!
//! Subcommands:
//!   crack --targets F --list X=F ... --pattern P ...   brute-force names
//!   mine  --dict F --corpus F ...                      prune a word list to
//!                                                      tokens that really occur
//!
//! See README.md for usage.

mod murmur;
mod pattern;

use anyhow::{anyhow, Context, Result};
use pattern::Compiler;
use rayon::prelude::*;
use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("crack") => crack(&args[2..]),
        Some("mutate") => mutate(&args[2..]),
        Some("mine") => mine(&args[2..]),
        Some("-h") | Some("--help") | None => {
            print_help();
            Ok(())
        }
        Some(other) => Err(anyhow!("unknown subcommand {other:?} (try --help)")),
    }
}

fn print_help() {
    println!(
        "hashcracker — MurmurHash64A name brute-forcer

USAGE
  hashcracker crack  --targets <file> --list <X=file>... --pattern <pat>... [opts]
  hashcracker mutate --names <file> --targets <file> [--suffixes F] [--tokens F]
  hashcracker mine   --dict <file> --corpus <file>... [opts]

MUTATE OPTIONS (derive candidates from known names by swapping/editing tokens)
  --names <file>      known names to mutate (one per line)
  --targets <file>    target hashes
  --exclude <file>    hashes to skip
  --suffixes <file>   suffixes to swap in (e.g. data/suffixes.txt)
  --tokens <file>     token vocabulary for replacements (e.g. data/names.txt)
  --matches <file>    output TSV (default matches.tsv)

CRACK OPTIONS
  --targets <file>    file of target hashes (hex, one per line; # comments ok)
  --exclude <file>    hashes to skip (e.g. already-solved), same format
  --list <X=file>     word list for slot letter X (repeatable), e.g. n=names.txt
  --pattern <pat>     template with %X slots (repeatable); %% = literal %
  --threads <n>       worker threads (default: all cores)
  --matches <file>    append matches as TSV here, live + de-duplicated across
                      runs (default: matches.tsv); format: <hash-hex><TAB><name>
  --limit <n>         stop each pattern after n candidates (testing)
"
    );
}

/// Parse `--flag value` style args into a flat list.
struct Args {
    flags: Vec<(String, String)>,
}

impl Args {
    fn parse(a: &[String]) -> Result<Args> {
        let mut flags = Vec::new();
        let mut i = 0;
        while i < a.len() {
            let k = &a[i];
            if let Some(name) = k.strip_prefix("--") {
                let v = a.get(i + 1).ok_or_else(|| anyhow!("--{name} needs a value"))?;
                flags.push((name.to_string(), v.clone()));
                i += 2;
            } else {
                i += 1;
            }
        }
        Ok(Args { flags })
    }
    fn all(&self, key: &str) -> Vec<String> {
        self.flags.iter().filter(|(k, _)| k == key).map(|(_, v)| v.clone()).collect()
    }
    fn one(&self, key: &str) -> Option<String> {
        self.flags.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone())
    }
    fn one_or(&self, key: &str, d: &str) -> String {
        self.one(key).unwrap_or_else(|| d.to_string())
    }
}

/// Read a file of lines into lowercased, non-empty byte vectors.
fn read_lines(path: &str) -> Result<Vec<Vec<u8>>> {
    let text = fs::read_to_string(path).with_context(|| format!("reading {path}"))?;
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        out.push(line.bytes().map(|b| b.to_ascii_lowercase()).collect());
    }
    Ok(out)
}

/// Read target hashes (first whitespace/comma token per line, parsed as hex).
fn read_targets(path: &str) -> Result<HashSet<u64>> {
    let text = fs::read_to_string(path).with_context(|| format!("reading {path}"))?;
    let mut set = HashSet::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let tok = line.split([' ', '\t', ',']).next().unwrap_or("").trim_start_matches("0x");
        if let Ok(h) = u64::from_str_radix(tok, 16) {
            set.insert(h);
        }
    }
    Ok(set)
}

/// Open-addressed u64 set with a cheap multiply-hash (no SipHash) — used for
/// the per-candidate membership test in the hot loop.
struct TargetSet {
    mask: usize,
    slots: Vec<u64>,
    used: Vec<bool>,
}

impl TargetSet {
    #[inline]
    fn slot(h: u64, mask: usize) -> usize {
        (h.wrapping_mul(0x9E37_79B9_7F4A_7C15) >> 40) as usize & mask
    }
    fn new(hashes: impl IntoIterator<Item = u64>) -> Self {
        let v: Vec<u64> = hashes.into_iter().collect();
        let mut cap = 16;
        while cap < v.len() * 2 {
            cap <<= 1;
        }
        let mut s = TargetSet { mask: cap - 1, slots: vec![0; cap], used: vec![false; cap] };
        for h in v {
            let mut i = Self::slot(h, s.mask);
            loop {
                if !s.used[i] {
                    s.used[i] = true;
                    s.slots[i] = h;
                    break;
                }
                if s.slots[i] == h {
                    break;
                }
                i = (i + 1) & s.mask;
            }
        }
        s
    }
    #[inline]
    fn contains(&self, h: u64) -> bool {
        let mut i = Self::slot(h, self.mask);
        loop {
            if !self.used[i] {
                return false;
            }
            if self.slots[i] == h {
                return true;
            }
            i = (i + 1) & self.mask;
        }
    }
}

/// Append-only, de-duplicated match writer. Loads hashes already on disk so
/// repeated runs never write the same name twice; each new hit is flushed
/// immediately (matches are rare, so the I/O cost is negligible).
struct Matches {
    seen: HashSet<u64>,
    file: std::fs::File,
}

impl Matches {
    fn open(path: &str) -> Result<Self> {
        let mut seen = HashSet::new();
        if let Ok(text) = fs::read_to_string(path) {
            for line in text.lines() {
                let tok = line.split('\t').next().unwrap_or("").trim();
                if let Ok(h) = u64::from_str_radix(tok, 16) {
                    seen.insert(h);
                }
            }
        }
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .with_context(|| format!("opening {path}"))?;
        Ok(Matches { seen, file })
    }
    /// Returns true if this hash was newly written.
    fn add(&mut self, h: u64, name: &str) -> std::io::Result<bool> {
        if !self.seen.insert(h) {
            return Ok(false);
        }
        writeln!(self.file, "{h:016x}\t{name}")?;
        self.file.flush()?;
        Ok(true)
    }
    fn len(&self) -> usize {
        self.seen.len()
    }
}

fn crack(argv: &[String]) -> Result<()> {
    let args = Args::parse(argv)?;
    let targets_path = args.one("targets").ok_or_else(|| anyhow!("--targets required"))?;
    let patterns = args.all("pattern");
    if patterns.is_empty() {
        return Err(anyhow!("at least one --pattern required"));
    }
    let threads: usize = args.one_or("threads", "0").parse().unwrap_or(0);
    let limit: u64 = args.one_or("limit", "0").parse().unwrap_or(0);

    let mut targets = read_targets(&targets_path)?;
    if let Some(ex) = args.one("exclude") {
        let drop = read_targets(&ex)?;
        let before = targets.len();
        targets.retain(|h| !drop.contains(h));
        println!("excluded     : {} already-solved", before - targets.len());
    }
    println!("targets      : {} hashes", targets.len());

    // build compiler + load word lists (must exist before compiling patterns)
    let mut comp = Compiler::new();
    for spec in args.all("list") {
        let (slot, file) = spec
            .split_once('=')
            .ok_or_else(|| anyhow!("--list must be X=FILE, got {spec:?}"))?;
        let c = slot.bytes().next().ok_or_else(|| anyhow!("empty slot in {spec:?}"))?;
        let idx = comp.slot(c);
        let words = read_lines(file)?;
        println!("list %{}       : {} words  ({file})", c as char, words.len());
        comp.lists[idx] = words;
    }

    let mut compiled = Vec::new();
    for p in &patterns {
        compiled.push(comp.compile(p).map_err(|e| anyhow!(e))?);
    }

    let pool = rayon::ThreadPoolBuilder::new().num_threads(threads).build()?;

    let matches_path = args.one_or("matches", "matches.tsv");
    let matches = Mutex::new(Matches::open(&matches_path)?);
    let new_hits = AtomicU64::new(0);
    let tset = TargetSet::new(targets.iter().copied());
    println!(
        "matches file : {matches_path} ({} names already)",
        matches.lock().unwrap().len()
    );

    // record a hit: stream to file immediately, de-duplicated across runs
    let record = |h: u64, buf: &[u8]| {
        let name = String::from_utf8_lossy(buf);
        if matches.lock().unwrap().add(h, &name).unwrap_or(false) {
            println!("  MATCH {h:016x}  {name}");
            new_hits.fetch_add(1, Ordering::Relaxed);
        }
    };

    let mut grand: u64 = 0;
    for (pi, pat) in compiled.iter().enumerate() {
        let mut total = pat.total();
        if limit > 0 {
            total = total.min(limit);
        }
        grand = grand.saturating_add(total);
        let nslots = pat.slots();
        let t0 = std::time::Instant::now();
        pool.install(|| {
            // Split the flat index space into one contiguous chunk per thread.
            // Each thread decodes its start index ONCE (a few divisions) and
            // then walks its range with a division-free odometer.
            let nt = rayon::current_num_threads() as u64;
            let chunk = total.div_ceil(nt.max(1));
            (0..nt).into_par_iter().for_each(|t| {
                let start = t * chunk;
                let end = ((t + 1) * chunk).min(total);
                let mut buf = Vec::with_capacity(192);
                let mut picks = [0usize; 16];
                if nslots == 0 {
                    if t == 0 {
                        pat.emit(&comp.lists, &[], &mut buf);
                        let h = murmur::hash_bytes(&buf);
                        if tset.contains(h) {
                            record(h, &buf);
                        }
                    }
                    return;
                }
                if start >= end {
                    return;
                }
                pat.decode(start, &mut picks);
                for _ in start..end {
                    pat.emit(&comp.lists, &picks[..nslots], &mut buf);
                    let h = murmur::hash_bytes(&buf);
                    if tset.contains(h) {
                        record(h, &buf);
                    }
                    if !pat.bump(&mut picks) {
                        break;
                    }
                }
            });
        });
        let secs = t0.elapsed().as_secs_f64();
        let rate = if secs > 0.0 { total as f64 / secs / 1e6 } else { 0.0 };
        println!("pattern {pi:<4} : {:>34}  {total:>15} cands  ({rate:.1}M/s)", patterns[pi]);
    }

    println!("\ntotal cands  : {grand}");
    println!("new matches  : {} (this run)", new_hits.load(Ordering::Relaxed));
    println!(
        "matches file : {matches_path} ({} unique names total)",
        matches.lock().unwrap().len()
    );
    Ok(())
}

/// Mutation cracker: derive candidates from *known* names by swapping suffixes,
/// replacing/permuting `_`-separated tokens and substituting numbers. The
/// pattern engine can't express these (they are edits *within* a leaf), and the
/// candidate space is small (names x tokens) so it runs in seconds.
fn mutate(argv: &[String]) -> Result<()> {
    let args = Args::parse(argv)?;
    let names_path = args.one("names").ok_or_else(|| anyhow!("--names required"))?;
    let targets_path = args.one("targets").ok_or_else(|| anyhow!("--targets required"))?;
    let threads: usize = args.one_or("threads", "0").parse().unwrap_or(0);

    let s = |f: &str| -> Result<Vec<String>> {
        Ok(read_lines(f)?.into_iter().map(|b| String::from_utf8_lossy(&b).into_owned()).collect())
    };
    let names = s(&names_path)?;
    let suffixes = match args.one("suffixes") { Some(f) => s(&f)?, None => Vec::new() };
    let tokens = match args.one("tokens") { Some(f) => s(&f)?, None => Vec::new() };
    let mut numbers: Vec<String> = (0..100).map(|i| format!("{i:02}")).collect();
    numbers.extend((0..100).map(|i| i.to_string()));

    let mut targets = read_targets(&targets_path)?;
    if let Some(ex) = args.one("exclude") {
        let drop = read_targets(&ex)?;
        targets.retain(|h| !drop.contains(h));
    }
    let tset = TargetSet::new(targets.iter().copied());

    let matches_path = args.one_or("matches", "matches.tsv");
    let matches = Mutex::new(Matches::open(&matches_path)?);
    let new_hits = AtomicU64::new(0);
    let pool = rayon::ThreadPoolBuilder::new().num_threads(threads).build()?;

    println!("names        : {}", names.len());
    println!("tokens       : {}", tokens.len());
    println!("suffixes     : {}", suffixes.len());
    println!("targets      : {}", targets.len());

    let record = |h: u64, name: &str| {
        if matches.lock().unwrap().add(h, name).unwrap_or(false) {
            println!("  MATCH {h:016x}  {name}");
            new_hits.fetch_add(1, Ordering::Relaxed);
        }
    };

    let t0 = std::time::Instant::now();
    pool.install(|| {
        names.par_iter().for_each(|name| {
            let (dir, leaf) = match name.rsplit_once('/') {
                Some((d, l)) => (format!("{d}/"), l.to_string()),
                None => (String::new(), name.clone()),
            };
            let emit = |cand: &str| {
                let h = murmur::hash_str(cand);
                if tset.contains(h) {
                    record(h, cand);
                }
            };
            // 1. suffix swap / strip
            if !suffixes.is_empty() {
                let mut base = leaf.clone();
                for sfx in &suffixes {
                    if sfx.len() > 1 && base.ends_with(sfx.as_str()) {
                        base.truncate(base.len() - sfx.len());
                        break;
                    }
                }
                for sfx in &suffixes {
                    emit(&format!("{dir}{base}{sfx}"));
                }
            }
            // 2. token edits
            let parts: Vec<&str> = leaf.split('_').collect();
            if parts.len() > 1 {
                for i in 0..parts.len() - 1 {
                    let mut v = parts.clone();
                    v.swap(i, i + 1);
                    emit(&format!("{dir}{}", v.join("_")));
                }
                for i in 0..parts.len() {
                    // 2a. replace a token with any token from the vocabulary
                    for t in &tokens {
                        let mut v = parts.clone();
                        v[i] = t;
                        emit(&format!("{dir}{}", v.join("_")));
                    }
                    // 2b. numeric substitution (any token containing a digit)
                    if parts[i].chars().any(|c| c.is_ascii_digit()) {
                        for num in &numbers {
                            let mut v = parts.clone();
                            v[i] = num;
                            emit(&format!("{dir}{}", v.join("_")));
                        }
                    }
                }
            }
        });
    });
    let secs = t0.elapsed().as_secs_f64();
    println!(
        "\ndone in {secs:.1}s\nnew matches  : {}\nmatches file : {matches_path} ({} total)",
        new_hits.load(Ordering::Relaxed),
        matches.lock().unwrap().len()
    );
    Ok(())
}

/// Report which dictionary words actually occur in the given corpora.
fn mine(argv: &[String]) -> Result<()> {
    use aho_corasick::AhoCorasickBuilder;
    let args = Args::parse(argv)?;
    let dict_path = args.one("dict").ok_or_else(|| anyhow!("--dict required"))?;
    let corpora = args.all("corpus");
    if corpora.is_empty() {
        return Err(anyhow!("at least one --corpus required"));
    }
    let dict = read_lines(&dict_path)?;
    let ac = AhoCorasickBuilder::new()
        .ascii_case_insensitive(true)
        .build(dict.iter().map(|w| w.as_slice()))
        .context("building aho-corasick automaton")?;

    let mut seen = vec![false; dict.len()];
    for c in &corpora {
        let bytes = fs::read(c).with_context(|| format!("reading {c}"))?;
        for m in ac.find_iter(&bytes) {
            seen[m.pattern().as_usize()] = true;
        }
    }
    let kept = seen.iter().filter(|s| **s).count();
    println!("dict             : {} words ({dict_path})", dict.len());
    println!("present in corpus: {kept}");
    for (w, s) in dict.iter().zip(&seen) {
        if *s {
            println!("  {}", String::from_utf8_lossy(w));
        }
    }
    Ok(())
}

