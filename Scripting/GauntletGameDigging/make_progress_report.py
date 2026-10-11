#!/usr/bin/env python3
"""
Overall progress report for the name-recovery work (FINDINGS.txt 41+).

`05_summary.txt` is written by `list_game_bundles.py` and describes the *catalogue*
- and its `Unresolved` line is counted against the static `hash_database.json`,
not against what we have actually recovered, so it does not move as names land.
This writes the missing view: one file that answers "how far are we, what did each
sweep find, and where do I look next".

    python3 make_progress_report.py            # -> bundle_manifest/08_progress.txt
    python3 make_progress_report.py --stdout   # print instead

Inputs, all read-only:
    04_bundle_resources.csv            the catalogue (20,000 rows)
    resource_name_overlay.json         names we have recovered
    ../hashcracker/matches.tsv         every hit ever recorded by any sweep
    ../hashcracker/work/*/status.log   the per-sweep histories
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import time

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / 'bundle_manifest'
HC = HERE.parent / 'hashcracker'
FINDINGS = HERE / 'docs' / 'FINDINGS.txt'
WIDTH = 98
PLUS = re.compile(r'\+(\d+)')


def catalogue():
    ov = json.loads((HERE / 'resource_name_overlay.json').read_text())
    rows = list(csv.DictReader((MANIFEST / '04_bundle_resources.csv').open(
        newline='', encoding='utf-8', errors='replace')))
    named_rows, named_hash, unres_hash = 0, set(), set()
    by_type = collections.defaultdict(lambda: [0, 0, set()])
    by_pkg = collections.Counter()
    for r in rows:
        h = r['name_hash'].lower()
        n = r.get('name') or ov.get(h)
        t = r['type'] or '?'
        if n:
            named_rows += 1
            named_hash.add(h)
            by_type[t][0] += 1
        else:
            unres_hash.add(h)
            by_type[t][1] += 1
            by_type[t][2].add(h)
            by_pkg[r['package_path']] += 1
    return ov, rows, named_rows, named_hash, unres_hash, by_type, by_pkg


def matches():
    p = HC / 'matches.tsv'
    if not p.exists():
        return []
    out = []
    for line in p.read_text(errors='replace').splitlines():
        if '\t' in line:
            h, _, name = line.partition('\t')
            out.append((h.strip().lower(), name.strip()))
    return out


def sweeps():
    """Per-sweep history from the status logs, with a tolerant parser."""
    out = []
    for log in sorted((HC / 'work').glob('*/status.log')):
        lines = [l.rstrip() for l in log.read_text(errors='replace').splitlines() if l.strip()]
        if not lines:
            continue
        rounds = sum(1 for l in lines if l.startswith('==='))
        hits = 0
        for l in lines:
            if 'total' in l or 'overlay:' in l or 'matches' in l:
                continue
            m = PLUS.search(l)
            if m:
                hits += int(m.group(1))
        last_round = next((l for l in reversed(lines) if l.startswith('===')), '')
        done = next((l for l in reversed(lines) if 'DONE' in l.upper()), '')
        fix = 'fixpoint' if any('fixpoint' in l.lower() for l in lines) else ''
        out.append({'name': log.parent.name, 'rounds': rounds, 'hits': hits,
                    'last': last_round, 'done': done, 'fix': fix,
                    'lines': lines[-1][:60]})
    out.sort(key=lambda s: -s['hits'])
    return out


def timeline(n=15):
    """Row counts of matches.tsv at each commit that changed it (real history)."""
    import subprocess
    repo = HERE.parent.parent                       # the gauntlet repo root
    rel = 'Scripting/hashcracker/matches.tsv'
    try:
        log = subprocess.run(['git', '-C', str(repo), 'log', f'-{n}',
                              '--format=%h|%ad|%s', '--date=short', '--', rel],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:                                                 # noqa: BLE001
        return []
    out = []
    for line in log.splitlines():
        if '|' not in line:
            continue
        h, date, subj = line.split('|', 2)
        try:
            blob = subprocess.run(['git', '-C', str(repo), 'show', f'{h}:{rel}'],
                                  capture_output=True, text=True, timeout=60).stdout
            rows = sum(1 for l in blob.splitlines() if '\t' in l)
        except Exception:                                             # noqa: BLE001
            rows = 0
        out.append((date, h, rows, subj))
    return out


def findings_sections():
    if not FINDINGS.exists():
        return []
    txt = FINDINGS.read_text(errors='replace')
    return re.findall(r'^\s*(\d+(?:\.[0-9]+)?)\.?\s+([A-Z"\u201c][^\n]{6,70})', txt, re.M)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stdout', action='store_true')
    args = ap.parse_args()

    ov, rows, named_rows, named_hash, unres_hash, by_type, by_pkg = catalogue()
    mt = matches()
    sw = sweeps()

    L = []
    def w(s=''):
        L.append(s)

    total = len(rows)
    pct = 100.0 * named_rows / total if total else 0.0
    w('GAUNTLET NAME-RECOVERY PROGRESS')
    w('=' * WIDTH)
    w(f'generated {time.strftime("%Y-%m-%d %H:%M")}   '
      f'(regenerate with: python3 make_progress_report.py)')
    w()
    w('1. HEADLINE')
    w('-' * WIDTH)
    w(f'  catalogue rows                {total:>9,}')
    w(f'  rows with a name              {named_rows:>9,}   ({pct:.2f}%)')
    w(f'  unique hashes in catalogue    {len(named_hash | unres_hash):>9,}')
    w(f'  unique hashes resolved        {len(named_hash):>9,}')
    w(f'  unique hashes UNRESOLVED      {len(unres_hash):>9,}')
    w(f'  names in the overlay          {len(ov):>9,}')
    w(f'  hits in matches.tsv (ever)    {len(mt):>9,}')
    w(f'  sweeps with a status log      {len(sw):>9,}')
    master = MANIFEST / '10_unresolved_master.tsv'
    if master.exists():
        with master.open(newline='', encoding='utf-8') as fh:
            rows_m = list(csv.DictReader(fh, delimiter='\t'))
        un = sum(1 for r in rows_m if r['status'] == 'UNREACHABLE')
        orphan = sum(1 for r in rows_m if r['status'] == 'UNREACHABLE'
                     and r['reason'] == 'nothing references it')
        w(f'  unreachable (no named ref)    {un:>9,}   of which orphans {orphan}')
    w()
    # 05_summary.txt's "Unresolved" line is counted against the static
    # hash_database.json, not against the overlay, so it barely moves as names land.
    # Read the number back rather than quoting it, or the note goes stale (it sat at
    # 3,444 long after the catalogue said 2,143).
    static_metric = 'n/a'
    summary_05 = MANIFEST / '05_summary.txt'
    if summary_05.exists():
        for line in summary_05.read_text(encoding='utf-8').splitlines():
            if line.startswith('Unresolved'):
                words = line.replace(':', ' ').split()
                if len(words) >= 2:
                    static_metric = words[1]
                break
    w(f'  note: 05_summary.txt reports "Unresolved {static_metric}" - that is counted against the')
    w('  static hash_database.json, not against this overlay, which is why it never moves')
    w('  as names land.  The numbers above are the live ones (tools/status.sh prints the')
    w('  same score).')
    w()

    w('2. COVERAGE BY TYPE   (rows named / rows unresolved / unique unresolved)')
    w('-' * WIDTH)
    open_types = {t: v for t, v in by_type.items() if v[2]}
    for t, (ok, no, hs) in sorted(open_types.items(), key=lambda kv: (-len(kv[1][2]), kv[0])):
        w(f'  {t:26s} {ok:>7,} / {no:>6,} / {len(hs):>6,}')
    closed = {t: v for t, v in by_type.items() if not v[2]}
    w(f'  ({len(closed)} further types are fully named: '
      f'{", ".join(sorted(closed))[:70]})')
    w()

    w('3. PACKAGES WITH THE MOST UNRESOLVED ROWS   (top 15)')
    w('-' * WIDTH)
    for p, n in by_pkg.most_common(15):
        w(f'  {n:>6,}  {p}')
    w()

    w('4. SWEEP HISTORY   (per-sweep status logs; +N summed over tier lines)')
    w('-' * WIDTH)
    w(f'  {"sweep":16s} {"rounds":>7s} {"hits +N":>9s}  last round / outcome')
    for s in sw:
        lr = s['last'][:44] if s['last'] else s['lines']
        tag = s['done'][:22] if s['done'] else (s['fix'] or '')
        w(f'  {s["name"]:16s} {s["rounds"]:>7,} {s["hits"]:>9,}  {lr:46s} {tag}')
    w()
    w(f'  total +N across these logs {sum(s["hits"] for s in sw):,}, which is a lower bound')
    w('  only: each log is overwritten per run, so older rounds of the same sweep are')
    w('  gone.  The authoritative total is the matches.tsv row count above, and the')
    w('  timeline below is the real history.')
    w()

    tl = timeline()
    if tl:
        w('5. RECOVERY TIMELINE   (matches.tsv as committed, newest first)')
        w('-' * WIDTH)
        w(f'  {"date":11s} {"commit":8s} {"rows":>7s}  change')
        prev = None
        for date, h, rows, subj in tl:
            delta = '' if prev is None else f'{prev - rows:+d}'
            w(f'  {date:11s} {h:8s} {rows:>7,}  {delta:>5s}  {subj[:52]}')
            prev = rows
        w()

    w('6. WHERE TO LOOK')
    w('-' * WIDTH)
    # The section range is read off the file, not quoted: the pointer below claimed
    # "1-60" for a whole section after 61 landed.  A real top-level heading is
    # "NN. TITLE" at column 0 - `findings_sections()` is deliberately loose and also
    # catches body prose ("  245 BILLION candidates across every ..."), so it cannot
    # answer this question.
    sections = findings_sections()
    top_section = 0
    if FINDINGS.exists():
        for m in re.finditer(r'^(\d+)\. [A-Z"\u201c]',
                             FINDINGS.read_text(errors='replace'), re.M):
            top_section = max(top_section, int(m.group(1)))
    for name, what in [
            ('bundle_manifest/00_file_tree.txt', 'every file in the install'),
            ('bundle_manifest/01_bundle_files.txt', 'the 75 bundle files'),
            ('bundle_manifest/02_bundle_database.txt', 'bundle -> package map'),
            ('bundle_manifest/03_bundle_resources.txt', 'all 20,000 rows'),
            ('bundle_manifest/04_bundle_resources.csv', 'the catalogue the sweeps key off'),
            ('bundle_manifest/05_summary.txt', 'catalogue stats (static-database metric)'),
            ('bundle_manifest/06_names_by_name.txt', 'recovered names, A-Z'),
            ('bundle_manifest/07_names_by_type.txt', 'recovered names grouped by type'),
            ('bundle_manifest/08_progress.txt', 'this file'),
            ('bundle_manifest/09_reachability.tsv', 'per unresolved hash: named refs, unresolved refs, sample referrer'),
            ('bundle_manifest/10_unresolved_master.tsv', 'THE MASTER LIST: every unresolved resource with status reachable / UNREACHABLE'),
            ('../hashcracker/matches.tsv', 'every hit ever, hash<TAB>name'),
            ('../hashcracker/work/*/status.log', 'per-sweep logs (current run only)'),
            ('../hashcracker/tools/status.sh', 'live score + what is running right now'),
            ('docs/FINDINGS.txt', f'the full narrative, sections 1-{top_section}'),
    ]:
        w(f'  {name:44s} {what}')
    w()

    w('7. WHERE THE WORK IS RECORDED   (FINDINGS.txt, most recent last)')
    w('-' * WIDTH)
    for num, title in sections[-14:]:
        w(f'  {num:>6s}  {title}')
    w()
    w('=' * WIDTH)

    text = '\n'.join(L) + '\n'
    if args.stdout:
        print(text, end='')
    else:
        (MANIFEST / '08_progress.txt').write_text(text)
        print(f'  wrote {MANIFEST / "08_progress.txt"}  ({len(L)} lines)')
        print(f'  {named_rows:,}/{total:,} rows named ({pct:.2f}%)   '
              f'unique unresolved {len(unres_hash):,}   overlay {len(ov):,}')


if __name__ == '__main__':
    main()
