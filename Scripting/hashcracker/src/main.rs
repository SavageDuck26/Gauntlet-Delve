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
  --candidates <file> extra plain candidate strings to test (one per line)
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
    if patterns.is_empty() && args.one("candidates").is_none() {
        return Err(anyhow!("need at least one --pattern or --candidates"));
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

    // Optional: a plain list of candidate strings to test (no pattern needed).
    if let Some(cf) = args.one("candidates") {
        let cands = read_lines(&cf)?;
        println!("candidates   : {} strings  ({cf})", cands.len());
        let t0 = std::time::Instant::now();
        pool.install(|| {
            cands.par_iter().for_each(|c| {
                let h = murmur::hash_bytes(c);
                if tset.contains(h) {
                    record(h, c);
                }
            });
        });
        println!("candidates   : done in {:.1}s", t0.elapsed().as_secs_f64());
    }

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

/// Write `toks` joined by `_` into `buf`, optionally swapping two positions
/// and/or replacing one position with `repl`.
#[inline]
fn join(
    buf: &mut Vec<u8>,
    toks: &[Vec<u8>],
    swap: Option<(usize, usize)>,
    repl: Option<(usize, &[u8])>,
) {
    for (j, t) in toks.iter().enumerate() {
        if j > 0 {
            buf.push(b'_');
        }
        let mut s: &[u8] = t;
        if let Some((a, b)) = swap {
            if j == a {
                s = &toks[b];
            } else if j == b {
                s = &toks[a];
            }
        }
        if let Some((i, r)) = repl {
            if j == i {
                s = r;
            }
        }
        buf.extend_from_slice(s);
    }
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

    let suffixes: Vec<Vec<u8>> = match args.one("suffixes") { Some(f) => read_lines(&f)?, None => Vec::new() };
    let tokens: Vec<Vec<u8>> = match args.one("tokens") { Some(f) => read_lines(&f)?, None => Vec::new() };
    let mut numbers: Vec<Vec<u8>> = Vec::with_capacity(200);
    for i in 0..100 {
        numbers.push(format!("{i:02}").into_bytes());
    }
    for i in 0..100 {
        numbers.push(i.to_string().into_bytes());
    }

    // precompute (dir-with-slash, leaf tokens) per known name — all byte-based
    // so the hot loop never allocates a String.
    let mut ents: Vec<(Vec<u8>, Vec<Vec<u8>>)> = Vec::new();
    for line in read_lines(&names_path)? {
        let (dir, leaf) = match line.iter().rposition(|&b| b == b'/') {
            Some(i) => (line[..=i].to_vec(), line[i + 1..].to_vec()),
            None => (Vec::new(), line.clone()),
        };
        let toks: Vec<Vec<u8>> = leaf.split(|&b| b == b'_').map(|s| s.to_vec()).collect();
        ents.push((dir, toks));
    }

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

    println!("names        : {}", ents.len());
    println!("tokens       : {}", tokens.len());
    println!("suffixes     : {}", suffixes.len());
    println!("targets      : {}", targets.len());

    let record = |h: u64, name: &[u8]| {
        let nm = String::from_utf8_lossy(name).into_owned();
        if matches.lock().unwrap().add(h, &nm).unwrap_or(false) {
            println!("  MATCH {h:016x}  {nm}");
            new_hits.fetch_add(1, Ordering::Relaxed);
        }
    };

    let t0 = std::time::Instant::now();
    pool.install(|| {
        ents.par_iter().for_each_init(
            || Vec::with_capacity(256),
            |buf, (dir, toks)| {
                // stem = leaf with one known suffix stripped
                let mut stem: Vec<Vec<u8>> = toks.clone();
                if let Some(last) = stem.last_mut() {
                    for sfx in &suffixes {
                        if sfx.len() > 1 && last.ends_with(sfx) {
                            last.truncate(last.len() - sfx.len());
                            break;
                        }
                    }
                }
                let check = |c: &[u8]| {
                    let h = murmur::hash_bytes(c);
                    if tset.contains(h) {
                        record(h, c);
                    }
                };
                // 1. suffix swap (material parent -> its map variants, etc.)
                for sfx in &suffixes {
                    buf.clear();
                    buf.extend_from_slice(dir);
                    join(buf, &stem, None, None);
                    buf.extend_from_slice(sfx);
                    check(buf);
                }
                // 2. append / prepend a token (+ optional suffix)
                for t in &tokens {
                    buf.clear();
                    buf.extend_from_slice(dir);
                    join(buf, &stem, None, None);
                    buf.push(b'_');
                    buf.extend_from_slice(t);
                    check(buf);
                    buf.clear();
                    buf.extend_from_slice(dir);
                    buf.extend_from_slice(t);
                    buf.push(b'_');
                    join(buf, &stem, None, None);
                    check(buf);
                    for sfx in &suffixes {
                        buf.clear();
                        buf.extend_from_slice(dir);
                        join(buf, &stem, None, None);
                        buf.push(b'_');
                        buf.extend_from_slice(t);
                        buf.extend_from_slice(sfx);
                        check(buf);
                    }
                }
                // 3. token edits
                if stem.len() > 1 {
                    for i in 0..stem.len() - 1 {
                        buf.clear();
                        buf.extend_from_slice(dir);
                        join(buf, &stem, Some((i, i + 1)), None);
                        check(buf);
                    }
                    for i in 0..stem.len() {
                        for t in &tokens {
                            buf.clear();
                            buf.extend_from_slice(dir);
                            join(buf, &stem, None, Some((i, t)));
                            check(buf);
                        }
                        if stem[i].iter().any(|c| c.is_ascii_digit()) {
                            for n in &numbers {
                                buf.clear();
                                buf.extend_from_slice(dir);
                                join(buf, &stem, None, Some((i, n)));
                                check(buf);
                            }
                        }
                    }
                }
            },
        );
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

