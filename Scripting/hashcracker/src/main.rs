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
use std::collections::{HashMap, HashSet};
use std::fs;
use std::sync::Mutex;

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("crack") => crack(&args[2..]),
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
  hashcracker crack --targets <file> --list <X=file>... --pattern <pat>... [opts]
  hashcracker mine  --dict <file> --corpus <file>... [opts]

CRACK OPTIONS
  --targets <file>    file of target hashes (hex, one per line; # comments ok)
  --exclude <file>    hashes to skip (e.g. already-solved), same format
  --list <X=file>     word list for slot letter X (repeatable), e.g. n=names.txt
  --pattern <pat>     template with %X slots (repeatable); %% = literal %
  --threads <n>       worker threads (default: all cores)
  --out <file>        write matches as JSON {{hash: name}}
  --tsv <file>        write matches as TSV (hash<TAB>name)
  --show <n>          print up to n matches (default 40)
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

fn json_escape(s: &str, out: &mut String) {
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            _ => out.push(c),
        }
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
    let show: usize = args.one_or("show", "40").parse().unwrap_or(40);
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

    let hits: Mutex<Vec<(u64, String)>> = Mutex::new(Vec::new());
    let mut grand: u64 = 0;
    for (pi, pat) in compiled.iter().enumerate() {
        let mut total = pat.total();
        if limit > 0 {
            total = total.min(limit);
        }
        grand = grand.saturating_add(total);
        let t0 = std::time::Instant::now();
        pool.install(|| {
            (0..total).into_par_iter().for_each_init(
                || Vec::with_capacity(192),
                |buf, idx| {
                    pat.build(&comp.lists, idx, buf);
                    let h = murmur::hash_bytes(buf);
                    if targets.contains(&h) {
                        hits.lock().unwrap().push((h, String::from_utf8_lossy(buf).into_owned()));
                    }
                },
            );
        });
        let secs = t0.elapsed().as_secs_f64();
        let rate = if secs > 0.0 { total as f64 / secs / 1e6 } else { 0.0 };
        println!("pattern {pi:<4} : {:>34}  {total:>15} cands  ({rate:.1}M/s)", patterns[pi]);
    }

    let mut map: HashMap<u64, String> = HashMap::new();
    for (h, n) in hits.into_inner().unwrap() {
        map.entry(h).or_insert(n);
    }
    println!("\ntotal cands  : {grand}");
    println!("MATCHED      : {} / {}", map.len(), targets.len());

    let mut sorted: Vec<(u64, String)> = map.into_iter().collect();
    sorted.sort_by_key(|(h, _)| *h);
    for (h, n) in sorted.iter().take(show) {
        println!("  {h:016x}  {n}");
    }

    if let Some(out) = args.one("out") {
        let mut s = String::from("{\n");
        for (i, (h, n)) in sorted.iter().enumerate() {
            s.push_str(&format!("  \"{h:016x}\": \""));
            json_escape(n, &mut s);
            s.push('"');
            if i + 1 < sorted.len() {
                s.push(',');
            }
            s.push('\n');
        }
        s.push_str("}\n");
        fs::write(&out, s).with_context(|| format!("writing {out}"))?;
        println!("wrote JSON   : {out}");
    }
    if let Some(tsv) = args.one("tsv") {
        let mut s = String::new();
        for (h, n) in &sorted {
            s.push_str(&format!("{h:016x}\t{n}\n"));
        }
        fs::write(&tsv, s).with_context(|| format!("writing {tsv}"))?;
        println!("wrote TSV    : {tsv}");
    }
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

