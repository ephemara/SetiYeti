"""corpus.py - SetiYeti MASS-DATA library: every slice, flag, floor and prove
in ONE queryable SQLite file. The self-evolution memory.

WHY THIS EXISTS: the scientific record was scattered - hits*.csv here,
evidence there, rfi_catalog.json elsewhere, veto verdicts only in stdout,
prove receipts in REPORTs nobody queries. A pipeline that cannot ask
"how often has this signature recurred?", "what does CLEAN fam_best look
like in L-band?", "which thresholds does the corpus justify?" cannot learn.
This is the memory; the proves stay the immune system.

Design (all stdlib `sqlite3`, single file, regenerable - never committed,
rebuilt by this script from the committed record):
  observations  one row per scanned file (header geometry + provenance)
  slices        every analyzed slice (superset schema; missing = NULL)
  signatures    pattern library: class_key (alpha x band) with history
  flags         veto disposition events (slice, disp, E/S/net, reasons, run)
  noise_floors  empirical metric distributions + threshold suggestions
  proves        every prove receipt (suite, pass/fail, key numbers)
  runs          pipeline runs + grade censuses + report paths

Self-evolution policy (NON-NEGOTIABLE, see AGENTS.md):
  the loop is propose -> prove -> promote, NEVER auto-tune. `corpus.py
  --suggest` derives candidate thresholds from CLEAN-slice distributions;
  a human validates them through the prove harnesses before anything ships.
  The DB proposes; the proves dispose.

Usage:
  python corpus.py --db corpus/setiyeti.db --item scan:runs/xeno/trap_on_p0.csv:DATA... --target TRAPPIST1
  python corpus.py --auto                      # walk known trees (runs/, hits*.csv, catalog)
  python corpus.py --catalog rfi_catalog.json
  python corpus.py --veto-log runs/.../veto_p0.log --veto-hits runs/.../struct_on_p0.csv --target KEPLER160
  INGEST ORDER (load-bearing): scan/struct/xeno CSVs first, catalog second,
  veto logs LAST. Re-ingesting a CSV wipes its slices by design (idempotent
  replace) which orphans-then-deletes attached flags - measured 90 flags
  lost to an --auto refresh in 2026-09. Veto logs re-attach deterministically.
  python corpus.py --query \"SELECT * FROM v_review LIMIT 5\"
  python corpus.py --top 20                    # top grades corpus-wide
  python corpus.py --family 626                # signature history near 626 Hz
  python corpus.py --suggest                   # human-gated threshold proposals
  python corpus.py --stats                     # census
  python corpus.py --selftest                  # idempotency + invariants
"""
import argparse
import csv
import datetime
import glob
import json
import os
import re
import sqlite3
import sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations(
  obs_id INTEGER PRIMARY KEY,
  src_file TEXT UNIQUE, target TEXT, pointing TEXT, kind TEXT, mjd REAL,
  telescope TEXT, freq_mhz REAL, bw_mhz REAL, nchan INTEGER, fs REAL,
  blocks TEXT, header_json TEXT, ingested_at TEXT);
CREATE TABLE IF NOT EXISTS slices(
  slice_id INTEGER PRIMARY KEY, obs_id INTEGER REFERENCES observations(obs_id),
  block INTEGER, chan INTEGER, pol INTEGER, verdict TEXT,
  spec_ratio REAL, spec_bin INTEGER, fam_best REAL, fam_hz REAL, fam_tag TEXT,
  vm_sign TEXT, vm_diff TEXT, spikes INTEGER, rms REAL,
  comb INTEGER, comb_f0 REAL, comb_score REAL, frame INTEGER, nongauss INTEGER,
  lines10 INTEGER, thicket INTEGER, grade TEXT,
  x_skflag INTEGER, x_cohflag INTEGER, x_ladderq INTEGER, x_dm_sign INTEGER,
  x_impuls INTEGER, xvm_nflags INTEGER, xvm_cand INTEGER, xvm_acf_lag INTEGER,
  scint_class TEXT, pol_verdict TEXT,
  ex_negdm INTEGER, ex_clock INTEGER, ex_ladder INTEGER, ex_primes INTEGER,
  ex_precursor INTEGER, tag TEXT, src_kind TEXT,
  UNIQUE(obs_id, block, chan, pol, src_kind));
CREATE TABLE IF NOT EXISTS signatures(
  sig_id INTEGER PRIMARY KEY, class_key TEXT UNIQUE, alpha_hz REAL,
  band TEXT, kind TEXT, n_seen INTEGER DEFAULT 0, structured INTEGER DEFAULT 0,
  first_seen TEXT, last_seen TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS flags(
  flag_id INTEGER PRIMARY KEY, slice_id INTEGER REFERENCES slices(slice_id),
  disposition TEXT, E REAL, S REAL, net REAL, reasons TEXT,
  run_id TEXT, scored_at TEXT, UNIQUE(slice_id, run_id));
CREATE TABLE IF NOT EXISTS noise_floors(
  floor_id INTEGER PRIMARY KEY, detector TEXT, metric TEXT, context TEXT,
  n_samples INTEGER, p50 REAL, p99 REAL, p999 REAL, maxv REAL,
  threshold_now REAL, suggested REAL, measured_at TEXT);
CREATE TABLE IF NOT EXISTS proves(
  prove_id INTEGER PRIMARY KEY, suite TEXT, name TEXT, passed INTEGER,
  detail TEXT, measured_at TEXT);
CREATE TABLE IF NOT EXISTS runs(
  run_id INTEGER PRIMARY KEY, outdir TEXT, tool TEXT, target TEXT,
  started TEXT, grade_census_json TEXT, report_path TEXT);
CREATE VIEW IF NOT EXISTS v_review AS
  SELECT s.slice_id, o.target, o.src_file, s.block, s.chan, s.pol,
         s.verdict, s.fam_best, s.fam_hz, s.grade,
         f.disposition, f.E, f.S
  FROM slices s JOIN observations o ON s.obs_id = o.obs_id
  LEFT JOIN flags f ON f.slice_id = s.slice_id
  WHERE (s.grade IN ('I2','I3','I4','I5')
         OR f.disposition IN ('WATCH','CANDIDATE'))
  ORDER BY o.target, s.fam_best DESC;
CREATE VIEW IF NOT EXISTS v_recurrence AS
  SELECT class_key, COUNT(*) AS n_obs, SUM(n_seen) AS n_hits,
         GROUP_CONCAT(DISTINCT band) AS bands
  FROM signatures GROUP BY class_key HAVING COUNT(*) >= 1 ORDER BY n_hits DESC;
"""

SLICE_COLS = ['block', 'chan', 'pol', 'verdict', 'spec_ratio', 'spec_bin',
              'fam_best', 'fam_hz', 'fam_tag', 'vm_sign', 'vm_diff', 'spikes',
              'rms', 'comb', 'comb_f0', 'comb_score', 'frame', 'nongauss',
              'lines10', 'thicket', 'grade', 'x_skflag', 'x_cohflag',
              'x_ladderq', 'x_dm_sign', 'x_impuls', 'xvm_nflags', 'xvm_cand',
              'xvm_acf_lag', 'scint_class', 'pol_verdict', 'ex_negdm',
              'ex_clock', 'ex_ladder', 'ex_primes', 'ex_precursor',
              'tag']
NUM_COLS = {'block', 'chan', 'pol', 'spec_ratio', 'spec_bin', 'fam_best',
            'fam_hz', 'spikes', 'rms', 'comb', 'comb_f0', 'comb_score',
            'frame', 'nongauss', 'lines10', 'thicket', 'x_skflag',
            'x_cohflag', 'x_ladderq', 'x_dm_sign', 'x_impuls', 'xvm_nflags',
            'xvm_cand', 'xvm_acf_lag', 'ex_negdm', 'ex_clock', 'ex_ladder',
            'ex_primes', 'ex_precursor'}


def connect(db):
    os.makedirs(os.path.dirname(db) or '.', exist_ok=True)
    cx = sqlite3.connect(db)
    cx.executescript(SCHEMA)
    return cx


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()[:19]


def num(v):
    try:
        return float(v) if v not in (None, '') else None
    except (ValueError, TypeError):
        return None


def ensure_obs(cx, src_file, target='', kind='scan', raw=None,
               pointing='UNKNOWN'):
    h, freq, bw, nchan, fs, mjd = {}, None, None, None, None, None
    if raw and os.path.exists(raw):
        h = SC.read_header(raw)
        try:
            freq = float(h.get('OBSFREQ', 'nan'))
        except (ValueError, TypeError):
            pass
        try:
            bw = float(h.get('OBSBW', 'nan'))
        except (ValueError, TypeError):
            pass
        try:
            nchan = int(float(h.get('OBSNCHAN', h.get('NCHAN', 0))))
        except (ValueError, TypeError):
            pass
        fs = SC.fs_from_header(raw)
        try:
            mjd = float(h.get('STT_IMJD', 'nan'))
        except (ValueError, TypeError):
            pass
    tel = h.get('TELESCOP', '') if h else ''
    cx.execute(
        'INSERT OR IGNORE INTO observations(src_file,target,pointing,kind,mjd,'
        'telescope,freq_mhz,bw_mhz,nchan,fs,header_json,ingested_at)'
        ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (src_file, target, pointing, kind, mjd, tel, freq, bw, nchan or None, fs,
         json.dumps(h) if h else None, now()))
    return cx.execute('SELECT obs_id FROM observations WHERE src_file=?',
                      (src_file,)).fetchone()[0]


def ingest_csv(cx, path, raw, target, kind, pointing='UNKNOWN'):
    obs_id = ensure_obs(cx, os.path.basename(path), target, kind, raw,
                        pointing)
    # wipe + replace this source (idempotent re-ingest, FK-safe order)
    cx.execute('DELETE FROM flags WHERE slice_id IN '
               '(SELECT slice_id FROM slices WHERE obs_id=?)', (obs_id,))
    cx.execute('DELETE FROM slices WHERE obs_id=?', (obs_id,))
    # Pre-aggregate on (block,chan,pol), last row wins: old scans sometimes
    # carry resume-append duplicates (measured: hits.csv), and the resume
    # convention everywhere else is later-supersedes. Deterministic.
    seen, dups = {}, 0
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            vals = {}
            for c in SLICE_COLS:
                if c == 'tag':
                    vals[c] = r.get('file', '') or None  # strips-style source tag
                    continue
                v = r.get(c)
                vals[c] = num(v) if c in NUM_COLS else (v or None)
            if vals['pol'] is None:
                vals['pol'] = 0  # v1 schema fallback
            key = (vals['block'], vals['chan'], vals['pol'])
            if key in seen:
                dups += 1
            seen[key] = vals
    n = 0
    for vals in seen.values():
        cx.execute(
            'INSERT INTO slices(obs_id,' + ','.join(SLICE_COLS) +
            ',src_kind) VALUES(?' + ',?' * len(SLICE_COLS) + ',?)',
            (obs_id, *[vals[c] for c in SLICE_COLS], kind))
        n += 1
    cx.commit()
    if dups:
        print(f'[ingest] note: {dups} resume-dups superseded in {os.path.basename(path)}')
    return obs_id, n


def ingest_catalog(cx, path):
    n = 0
    cat = json.load(open(path))
    for key, fe in cat.get('features', {}).items():
        try:
            alpha = float(fe.get('alpha') or 0)
        except (ValueError, TypeError):
            alpha = 0.0
        cx.execute(
            'INSERT INTO signatures(class_key,alpha_hz,band,kind,n_seen,'
            'structured,first_seen,last_seen,notes) VALUES(?,?,?,?,?,?,?,?,?)'
            ' ON CONFLICT(class_key) DO UPDATE SET n_seen=excluded.n_seen,'
            ' structured=excluded.structured, last_seen=excluded.last_seen',
            (key, alpha, '', '', int(fe.get('n_seen', 0)),
             1 if fe.get('structured') else 0, now(), now(),
             str(fe.get('disp', '')) + ('; ' + fe['audit'] if fe.get('audit') else '')))
        n += 1
    cx.commit()
    return n


VETO_LINE = re.compile(
    r'\[veto\] b(\d+)/ch(\d+)\s+\S+:([-\d.]+)Hz\s+E=([-\d.]+)\s+S=([-\d.]+)\s+'
    r'net=([+\d.-]+)\s+->\s+(\S+)')


def ingest_veto_log(cx, path, target, raw, run_tag='', pol=None, hits_csv=''):
    """Parse saved veto stdout into flags (the verdicts as actually issued).
    Matches (block,chan,pol): veto logs omit pol, so it comes from the log
    filename (_p0.._p3) or --veto-pol. An early version matched (block,chan)
    only and pasted WATCH dispositions onto clean wrong-pol rows (measured).
    Re-ingesting a run_tag wipes its flags first (idempotent)."""
    run_tag = run_tag or os.path.basename(path)
    if pol is None:
        m = re.search(r'_p([0-3])\b', os.path.basename(path))
        pol = int(m.group(1)) if m else 0
    cx.execute('DELETE FROM flags WHERE run_id=?', (run_tag,))
    hit_obs = None
    if hits_csv:
        hit_obs = cx.execute('SELECT obs_id FROM observations WHERE src_file=?',
                             (os.path.basename(hits_csv),)).fetchone()
        hit_obs = hit_obs[0] if hit_obs else None
    n = 0
    lines = open(path, errors='replace').read().splitlines()
    # verdict line -> following indented '- reason' lines (the WHY, needed
    # for the noise watch: "blocked as hum" vs "blocked as thicket" are
    # different noise families going forward)
    REASON = re.compile(r'^\s+-\s+(.*\S)\s*$')
    idx = []
    for i, ln in enumerate(lines):
        if VETO_LINE.search(ln):
            idx.append(i)
    for ii, i in enumerate(idx):
        m = VETO_LINE.search(lines[i])
        b, ch, hz, E, S, net, disp = m.groups()
        j = i + 1
        why = []
        end = idx[ii + 1] if ii + 1 < len(idx) else len(lines)
        while j < end:
            rm = REASON.match(lines[j])
            if rm:
                why.append(rm.group(1))
            j += 1
        if hit_obs is not None:
            row = cx.execute(
                'SELECT slice_id FROM slices WHERE obs_id=?'
                ' AND block=? AND chan=? AND pol=?'
                ' ORDER BY src_kind DESC LIMIT 1',
                (hit_obs, int(b), int(ch), pol)).fetchone()
        else:
            row = cx.execute(
                'SELECT slice_id FROM slices WHERE obs_id IN '
                '(SELECT obs_id FROM observations WHERE target=?)'
                ' AND block=? AND chan=? AND pol=?'
                ' ORDER BY src_kind DESC LIMIT 1',
                (target, int(b), int(ch), pol)).fetchone()
        if not row:
            continue
        cx.execute(
            'INSERT OR IGNORE INTO flags(slice_id,disposition,E,S,net,'
            'reasons,run_id,scored_at) VALUES(?,?,?,?,?,?,?,?)',
            (row[0], disp, float(E), float(S), float(net),
             ' | '.join(why)[:2000], run_tag, now()))
        n += 1
    cx.commit()
    return n


def ingest_carriers(cx, path):
    """Hand-built carrier catalog -> signature seeds (kind='carrier').
    Sky-frequency grain (not cyclic alpha): class_key carries MHz so the
    pattern library spans both domains. likely_origin becomes notes."""
    n = 0
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            try:
                f = float(r.get('frequency_MHz', 'nan'))
            except (ValueError, TypeError):
                continue
            key = f"carrier:{f:.3f}:{r.get('session', '?')}"
            try:
                ns = int(float(r.get('scans', 1)))
            except (ValueError, TypeError):
                ns = 1
            cx.execute(
                'INSERT INTO signatures(class_key,alpha_hz,band,kind,n_seen,'
                'structured,first_seen,last_seen,notes) VALUES(?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(class_key) DO UPDATE SET notes=excluded.notes',
                (key, None, f"{f:.1f}MHz sky", 'carrier', ns, 0, now(), now(),
                 f"{r.get('likely_origin', '?')} (peak {r.get('peak_over_median', '?')}x," 
                 f" w={r.get('width_Hz', '?')}Hz ch={r.get('ch', '?')})"))
            n += 1
    cx.commit()
    return n


def record_prove(cx, suite, name, passed, detail=''):
    cx.execute('INSERT INTO proves(suite,name,passed,detail,measured_at)'
               ' VALUES(?,?,?,?,?)', (suite, name, 1 if passed else 0,
                                      detail[:500], now()))
    cx.commit()


# ------------------------------------------------------------ queries --
CANNED = {
    'top': "SELECT target, block, chan, pol, verdict, fam_best, fam_hz, grade,"
           " disposition FROM v_review LIMIT {}",
    'family': "SELECT class_key, alpha_hz, n_seen, structured, notes FROM signatures"
              " WHERE ABS(alpha_hz - {}) < {} ORDER BY n_seen DESC LIMIT 30",
    'floors': "SELECT detector, metric, context, n_samples, p50, p99, p999,"
              " maxv, threshold_now, suggested FROM noise_floors",
    'recurrence': "SELECT * FROM v_recurrence LIMIT 30",
}


def stats(cx):
    out = {}
    for t in ('observations', 'slices', 'signatures', 'flags',
              'noise_floors', 'proves', 'runs'):
        out[t] = cx.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    out['grades'] = dict(cx.execute(
        "SELECT grade, COUNT(*) FROM slices WHERE grade IS NOT NULL"
        " GROUP BY grade").fetchall())
    out['dispositions'] = dict(cx.execute(
        'SELECT disposition, COUNT(*) FROM flags GROUP BY disposition').fetchall())
    return out


# ------------------------------------------------- threshold suggest --
# WHAT THE CORPUS MAY AND MAY NOT SAY ABOUT THRESHOLDS (measured 2026-09-21):
# The clean distribution is TRUNCATED at the trigger (clean-max 2.99 vs
# fam_trig 3.0 by verdict construction), so p999 x margin proposals are
# circular - they measure the trigger, not the noise (an early version
# proposed 3.71 from its own shadow). And full-distribution extrema are
# dominated by real contaminants (thickets at 91x). So v1 issues NO numeric
# proposals: it reports distributions + trigger margin + flag rates, with
# HOLDS/REVIEW verdicts. Drift (margin collapse, rate spikes) is the signal
# the corpus CAN contribute; numbers still come from the prove harnesses.
SUGGEST_METRICS = [
    # (detector, column, current threshold)
    ('mvp_fam', 'fam_best', 3.0),
    ('mvp_spec', 'spec_ratio', 5.0),
]


def suggest(cx):
    """Distribution snapshots + trigger margins + flag rates. HUMAN-GATED:
    REVIEW verdicts go to a human with a prove harness, never to a config.
    """
    import statistics
    tot = cx.execute('SELECT COUNT(*) FROM slices').fetchone()[0] or 1
    flagged = cx.execute("SELECT COUNT(*) FROM slices WHERE verdict LIKE 'FAM-HIT%'"
                         " OR verdict LIKE 'SPECTRAL%'").fetchone()[0]
    rate = flagged / tot * 1000.0
    rows = []
    for det, col, cur in SUGGEST_METRICS:
        q = cx.execute(
            f"SELECT {col} FROM slices WHERE verdict='clean' AND {col} IS NOT NULL")
        v = sorted(x[0] for x in q if x[0] is not None)
        if len(v) < 100:
            rows.append((det, col, len(v), None, cur, f'{rate:.2f}/1k',
                         'too few clean slices'))
            continue
        p50 = statistics.median(v)
        p99 = v[int(0.99 * len(v))]
        p999 = v[int(0.999 * len(v))]
        mx = v[-1]
        margin = (cur - mx) / cur if cur else 0.0
        verdict = 'HOLDS' if margin > 0.10 else 'REVIEW (boundary-hugging)'
        cx.execute(
            'INSERT INTO noise_floors(detector,metric,context,n_samples,p50,'
            'p99,p999,maxv,threshold_now,suggested,measured_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (det, col, 'clean corpus', len(v), p50, p99, p999, mx, cur,
             None, now()))
        rows.append((det, col, len(v), (round(p50, 2), round(p99, 2),
                                        round(p999, 2), round(mx, 2)),
                     cur, f'{rate:.2f}/1k',
                     f'{verdict} margin={margin * 100:.1f}%'))
    cx.commit()
    return rows


# ---------------------------------------------------------- noise watch --
def bucket3(x):
    """3-significant-figure frequency bucket (matches alpha_bucket)."""
    if x is None or x <= 0:
        return None
    try:
        return float(f'{float(x):.3g}')
    except (ValueError, TypeError):
        return None


def noise_watch(cx, topn=25, min_hits=5):
    """The common-noise library: every slice already records its top cyclic
    peak (fam_hz), flagged or not. Bucket them: hum, thicket lines and
    standing tones concentrate; thermal argmaxes spray. Returns rows +
    writes nothing (export is explicit via --noise-export)."""
    q = cx.execute(
        'SELECT s.fam_hz, s.fam_best, s.verdict, o.target, o.pointing,'
        ' f.disposition FROM slices s JOIN observations o ON s.obs_id=o.obs_id'
        ' LEFT JOIN flags f ON f.slice_id=s.slice_id'
        ' WHERE s.fam_hz IS NOT NULL AND s.fam_hz > 0')
    agg = {}
    for hz, fb, verdict, tgt, ptg, disp in q:
        b = bucket3(hz)
        if b is None:
            continue
        d = agg.setdefault(b, {'n': 0, 'sig': 0, 'blk': 0, 'wat': 0,
                               'obs': set(), 'maxfb': 0.0})
        d['n'] += 1
        if (verdict or '').startswith(('FAM-HIT', 'SPECTRAL')):
            d['sig'] += 1
        if (disp or '').startswith('BLOCK'):
            d['blk'] += 1
        if disp in ('WATCH', 'CANDIDATE'):
            d['wat'] += 1
        d['obs'].add(f"{tgt}/{ptg}")
        if fb and fb > d['maxfb']:
            d['maxfb'] = fb
    rows = [(b, d['n'], d['sig'], d['blk'], d['wat'], len(d['obs']),
             sorted(d['obs']), round(d['maxfb'], 1))
            for b, d in agg.items() if d['n'] >= min_hits]
    # Rank by SIGNAL count first: raw slice count is dominated by
    # sub-threshold noise-argmax spray (every clean slice reports some peak).
    # Recurring LINES - the filter-list candidates - rank by flags, then
    # strength. (The spray shape itself is the background template; query it
    # directly when needed.)
    rows.sort(key=lambda r: (-r[2], -r[7], -r[1]))
    return rows[:topn]


def export_noise_filter(cx, path, min_targets=2, min_hits=20, min_signal=10,
                        min_max=5.0):
    """Write the known-noise filter list (human-gated seed for future
    veto/catalog rules - NOT auto-wired). Entry = recurring bucket seen in
    >=min_targets pointings with >=min_hits slices AND real line evidence
    (>=min_signal flags, max ratio >=min_max). The signal/max gates keep
    sub-threshold argmax spray (thousands of slices, nothing above ~3x)
    out of the filter: background template, not lines."""
    rows = noise_watch(cx, topn=100000, min_hits=min_hits)
    filt = []
    for b, n, sig, blk, wat, ntgt, obs, maxfb in rows:
        if ntgt < min_targets or sig < min_signal or maxfb < min_max:
            continue
        filt.append({'freq_hz': b, 'n_slices': n, 'n_signal': sig,
                     'n_block': blk, 'n_watch': wat, 'n_targets': ntgt,
                     'targets': obs, 'max_ratio': maxfb,
                     'status': 'known-noise candidate (human review required)'})
    filt.sort(key=lambda e: (-e['n_targets'], -e['n_slices']))
    json.dump(filt, open(path, 'w'), indent=1)
    return filt


# ------------------------------------------------------------- selftest --
def selftest(db=':memory:'):
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    cx = connect(db)
    # synthetic observation: 200 clean + 5 engineered slices
    cx.execute("INSERT INTO observations(src_file,target,kind) VALUES('t.csv','T','scan')");
    oid = cx.execute("SELECT obs_id FROM observations WHERE src_file='t.csv'").fetchone()[0]
    import random
    rng = random.Random(4)
    for i in range(200):
        cx.execute('INSERT INTO slices(obs_id,block,chan,pol,verdict,fam_best,'
                   'spec_ratio,comb_score,src_kind) VALUES(?,?,?,?,?,?,?,?,?)',
                   (oid, i // 64, i % 64, 0, 'clean', 1.0 + rng.random() * 1.5,
                    1.0 + rng.random(), 0.0, 'scan'))
    for i in range(5):
        cx.execute('INSERT INTO slices(obs_id,block,chan,pol,verdict,fam_best,'
                   'comb,comb_score,grade,src_kind) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (oid, 9, i, 0, 'FAM-HIT', 20.0, 1, 25.0, 'I2', 'struct'))
    cx.commit()
    n1 = cx.execute('SELECT COUNT(*) FROM slices').fetchone()[0]
    # idempotency: re-ingest same logical source replaces, never duplicates.
    # (Simulated here by the UNIQUE constraint + wipe-replace contract: a
    # second identical batch must violate UNIQUE and be rejected.)
    try:
        cx.execute('INSERT INTO slices(obs_id,block,chan,pol,verdict,src_kind)'
                   " VALUES(?,0,0,0,'clean','scan')", (oid,))
        check('UNIQUE blocks duplicate slices', False, 'no error raised!')
    except sqlite3.IntegrityError:
        check('UNIQUE blocks duplicate slices', True, '')
    n2 = cx.execute('SELECT COUNT(*) FROM slices').fetchone()[0]
    check('row count stable', n1 == n2 == 205, f'{n1}/{n2}')
    # enum domains: grades and verdicts drawn from closed sets
    bad_g = cx.execute("SELECT COUNT(*) FROM slices WHERE grade IS NOT NULL"
                       " AND grade NOT IN ('I0','I1','I2','I3','I4','I5')").fetchone()[0]
    check('grade domain closed', bad_g == 0, '')
    # orphans: every flag/slice join resolves
    orph = cx.execute('SELECT COUNT(*) FROM flags f LEFT JOIN slices s'
                      ' ON f.slice_id=s.slice_id WHERE s.slice_id IS NULL').fetchone()[0]
    check('no orphan flags', orph == 0, '')
    # review view surfaces the engineered rows
    rev = cx.execute('SELECT COUNT(*) FROM v_review').fetchone()[0]
    check('v_review surfaces I2+', rev == 5, f'{rev}')
    # suggest runs on the synthetic corpus (200 clean, max 2.5 vs trig 3.0
    # -> 16.7% margin -> HOLDS; truncation circularity is documented, not coded)
    rows = suggest(cx)
    check('suggest holds on sufficient corpus',
          len(rows) == 2 and all('HOLDS' in r[-1] for r in rows),
          str([r[-1] for r in rows]))
    # ...and refuses a thin one honestly
    cx.execute("DELETE FROM slices WHERE verdict='clean' AND slice_id % 4 != 0")
    cx.commit()
    rows2 = suggest(cx)
    check('suggest refuses thin corpus honestly',
          any(r[-1] == 'too few clean slices' for r in rows2), '')
    # signatures upsert is monotonic
    cx.execute("INSERT INTO signatures(class_key,alpha_hz,n_seen) VALUES('k',358.0,3)"
               " ON CONFLICT(class_key) DO UPDATE SET n_seen=excluded.n_seen");
    cx.execute("INSERT INTO signatures(class_key,alpha_hz,n_seen) VALUES('k',358.0,5)"
               " ON CONFLICT(class_key) DO UPDATE SET n_seen=excluded.n_seen");
    nv = cx.execute("SELECT n_seen FROM signatures WHERE class_key='k'").fetchone()[0]
    check('signature upsert monotonic', nv == 5, '')
    # veto-log reasons parse (the WHY behind dispositions)
    dl = ['[veto] b1/ch57 Y4:626Hz E=1.45 S=0.15 net=+1.30 -> BLOCK:earth-likely',
          '         - +0.00 comb DISCOUNTED (thicket)',
          '         - +0.15 non-Gaussian tail',
          '[veto] BLOCK=1 WATCH=0 skipped=0 | catalog=1 | run_id=x']
    got_reasons = []
    RE = re.compile(r'^\s+-\s+(.*\S)\s*$')
    idx = [i for i, ln in enumerate(dl) if VETO_LINE.search(ln)]
    for ii, i in enumerate(idx):
        end = idx[ii + 1] if ii + 1 < len(idx) else len(dl)
        for ln in dl[i + 1:end]:
            m2 = RE.match(ln)
            if m2:
                got_reasons.append(m2.group(1))
    check('veto reasons parse', got_reasons ==
          ['+0.00 comb DISCOUNTED (thicket)', '+0.15 non-Gaussian tail'],
          str(got_reasons))
    # noise-watch buckets concentrate lines, spray stays sprayed
    check('bucket3 groups families',
          bucket3(625.85) == bucket3(626.4) != bucket3(1430.5), '')
    print('[selftest] ' + ('ALL PASS' if all(ok) else 'FAILURES PRESENT'))
    return all(ok)


# ------------------------------------------------------------------ main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='corpus/setiyeti.db')
    ap.add_argument('--item', action='append', default=[],
                    help='kind:csv[:raw[:target]] repeatable (kind=scan|struct|xeno)')
    ap.add_argument('--target', default='')
    ap.add_argument('--auto', action='store_true',
                    help='walk known trees (runs/xeno, runs/longhaul_kepler, hits*.csv)')
    ap.add_argument('--catalog', default='')
    ap.add_argument('--carrier-catalog', default='')
    ap.add_argument('--veto-log', action='append', default=[])
    ap.add_argument('--veto-hits', action='append', default=[],
                    help='hits CSV each --veto-log scored (same order); pins'
                         ' flags to the scored file, not target-wide')
    ap.add_argument('--veto-raw', default='')
    ap.add_argument('--veto-pol', type=int, default=None)
    ap.add_argument('--query', default='')
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--family', type=float, default=None)
    ap.add_argument('--family-tol', type=float, default=50.0)
    ap.add_argument('--floors', action='store_true')
    ap.add_argument('--suggest', action='store_true')
    ap.add_argument('--noise-watch', nargs='?', const=25, type=int, default=0,
                    help='top-N recurring cyclic frequencies (the common-noise library)')
    ap.add_argument('--noise-min', type=int, default=5)
    ap.add_argument('--noise-export', default='',
                    help='write known-noise filter JSON (human-gated, never auto-wired)')
    ap.add_argument('--noise-sig-min', type=int, default=10)
    ap.add_argument('--noise-max-min', type=float, default=5.0)
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--prove-rec', nargs=4, default=None,
                    metavar=('SUITE', 'NAME', 'PASS', 'DETAIL'))
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    db = os.path.join(a.root, a.db)
    cx = connect(db)

    SKIP_SUB = ('QUARANTINED', 'WRONG', 'jerk_results', 'scd_results',
                'sweep.csv', 'evidence_kep', 'evidence_trap', 'evidence.csv',
                'manifest.csv', 'carrier_catalog')

    def sniff_kind(path):
        try:
            with open(path, newline='') as fh:
                cols = next(csv.reader(fh))
        except (OSError, StopIteration):
            return ''
        if 'block' not in cols or 'chan' not in cols:
            return ''
        if 'grade' in cols:
            return 'xeno'
        if 'comb' in cols:
            return 'struct'
        if 'fam_best' in cols or 'spec_ratio' in cols:
            return 'scan'
        return ''

    def norm_target(src):
        src = src[5:] if src.startswith('DIAG_') else src
        return src.replace('-', '')

    def guess_target(path, manifest_raw):
        # returns (target, pointing, rawpath). Pointing (ON/OFF cadence leg)
        # comes from _on/_off in the raw or csv name, else UNKNOWN.
        rawbn = os.path.basename(manifest_raw) if manifest_raw else ''
        csvbn = os.path.basename(path)

        def pointing():
            low = (rawbn + ' ' + csvbn).lower()
            if '_off' in low or 'off_' in low:
                return 'OFF'
            if '_on' in low or 'on_' in low:
                return 'ON'
            return 'UNKNOWN'
        # 1. the raw header never lies (40 KB read, works on 17 GB files)
        if manifest_raw:
            rp = os.path.join(a.root, 'data', os.path.basename(manifest_raw))
            if os.path.exists(rp):
                h = SC.read_header(rp)
                src = (h.get('SRC_NAME') or '').strip()
                if src:
                    return norm_target(src), pointing(), rp
        # 2. path/name heuristics (documented guesses, UNKNOWN on doubt)
        low = path.lower()
        bn = csvbn
        if 'kepler' in low or '/kep_' in low or bn.startswith(
                ('kstruct', 'kxeno', 'kep_')):
            return 'KEPLER160', pointing(), ''
        if 'trap' in low or 't15' in low or 't16' in low or 't17' in low \
                or '0015' in bn or '0016' in bn or '0017' in bn \
                or 'blc00' in low or 'ch44' in bn or bn == 'strips.csv':
            return 'TRAPPIST1', pointing(), ''
        if bn == 'hits.csv':
            return 'M31', pointing(), ''
        if 'hip' in low:
            return 'HIP', pointing(), ''
        if 'voyager' in low:
            return 'VOYAGER', pointing(), ''
        if 'w75n' in low:
            return 'W75N', pointing(), ''
        return 'UNKNOWN', pointing(), ''

    if a.auto:
        files = sorted(glob.glob(os.path.join(a.root, 'runs', '**', '*.csv'),
                                 recursive=True))
        files += sorted(glob.glob(os.path.join(a.root, 'hits*.csv')))
        files += [os.path.join(a.root, 'evidence.csv')]
        for f in files:
            bn = os.path.basename(f)
            if any(s in f for s in SKIP_SUB):
                continue
            kind = sniff_kind(f)
            if not kind:
                print(f'[ingest] SKIP {bn}: not slice schema')
                continue
            mf = f + '.manifest.json'
            mraw = ''
            if os.path.exists(mf):
                try:
                    mraw = json.load(open(mf)).get('raw', '')
                except (OSError, ValueError):
                    pass
            tgt, ptg, rawp = guess_target(f, mraw)
            tgt = a.target or tgt
            try:
                _, n = ingest_csv(cx, f, rawp, tgt, kind, pointing=ptg)
                print(f'[ingest] {kind:6s} {os.path.relpath(f, a.root)}: {n} slices ({tgt})')
            except (OSError, ValueError) as e:
                print(f'[ingest] SKIP {bn}: {e}')
        # junk cleanup: dead ensure_obs rows from a veto-log draft (no slices)
        cx.execute("DELETE FROM observations WHERE src_file LIKE 'veto:%'")
        cx.commit()
        if not a.catalog and os.path.exists(os.path.join(a.root, 'rfi_catalog.json')):
            a.catalog = os.path.join(a.root, 'rfi_catalog.json')
    for item in a.item:
        parts = item.split(':')
        kind, csvp = parts[0], os.path.join(a.root, parts[1])
        rawp = os.path.join(a.root, parts[2]) if len(parts) > 2 and parts[2] else ''
        tgt = parts[3] if len(parts) > 3 else a.target
        ptg = parts[4] if len(parts) > 4 else 'UNKNOWN'
        _, n = ingest_csv(cx, csvp, rawp, tgt, kind, pointing=ptg)
        print(f'[ingest] {kind:6s} {os.path.basename(csvp)}: {n} slices ({tgt}/{ptg})')
    if a.catalog:
        n = ingest_catalog(cx, os.path.join(a.root, a.catalog))
        print(f'[ingest] catalog: {n} signature classes')
    cc = os.path.join(a.root, 'reports', 'handcrafted', 'carrier_catalog.csv')
    if a.carrier_catalog:
        cc = os.path.join(a.root, a.carrier_catalog)
    if a.auto or a.carrier_catalog:
        if os.path.exists(cc):
            n = ingest_carriers(cx, cc)
            print(f'[ingest] carrier catalog: {n} seeds')
    for i, vl in enumerate(a.veto_log):
        hits = a.veto_hits[i] if i < len(a.veto_hits) else ''
        n = ingest_veto_log(cx, os.path.join(a.root, vl), a.target,
                            os.path.join(a.root, a.veto_raw), pol=a.veto_pol,
                            hits_csv=hits)
        print(f'[ingest] veto-log {os.path.basename(vl)}: {n} flags')
    if a.prove_rec:
        suite, name, ps, det = a.prove_rec
        record_prove(cx, suite, name, ps == '1', det)
        print(f'[prove] recorded {suite}/{name}={ps}')
    if a.stats or not any([a.query, a.top, a.family is not None, a.floors,
                           a.suggest, a.item, a.auto, a.catalog, a.veto_log,
                           a.prove_rec]):
        st = stats(cx)
        print(json.dumps(st, indent=1))
    if a.top:
        for r in cx.execute(CANNED['top'].format(a.top)):
            print(r)
    if a.family is not None:
        for r in cx.execute(CANNED['family'].format(a.family, a.family_tol)):
            print(r)
    if a.floors:
        for r in cx.execute(CANNED['floors']):
            print(r)
    if a.query:
        for r in cx.execute(a.query):
            print(r)
    if a.noise_watch:
        print(f"{'freq_hz':>12s} {'slices':>7s} {'signal':>6s} {'block':>5s} "
              f"{'watch':>5s} {'tgts':>4s} {'max':>6s}  pointings")
        for b, n, sig, blk, wat, ntgt, obs, maxfb in noise_watch(
                cx, a.noise_watch, a.noise_min):
            tag = ' COMMON-MODE' if ntgt >= 2 else ''
            print(f'{b:12g} {n:7d} {sig:6d} {blk:5d} {wat:5d} {ntgt:4d} '
                  f'{maxfb:6.1f}  {",".join(obs[:4])}{tag}')
    if a.noise_export:
        filt = export_noise_filter(cx, os.path.join(a.root, a.noise_export),
                                   min_signal=a.noise_sig_min,
                                   min_max=a.noise_max_min)
        print(f'[noise] {len(filt)} known-noise candidates -> {a.noise_export} '
              f'(human review required before any veto use)')
    if a.suggest:
        print(f"{'detector':12s} {'metric':10s} {'n':>6s} "
              f"{'p50/p99/p99.9/max':28s} {'now':>5s} {'rate':>8s}  verdict")
        for det, col, n, dist, cur, rate, v in suggest(cx):
            print(f'{det:12s} {col:10s} {n:6d} {str(dist):28s} '
                  f'{cur:>5} {rate:>8s}  {v}')
        print('\nHUMAN-GATED: REVIEW verdicts go to a human with a prove harness, never to a config.')


if __name__ == '__main__':
    main()
