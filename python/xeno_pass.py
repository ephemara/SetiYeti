"""xeno_pass.py - XENO orchestrator: every new marker, one grade per slice.

WHY THIS EXISTS: the pipeline grew five detectors that never met each other
(xeno_scan, xvm_sandbox, scint_pol, exotic_pass, plus the veto's STRUCTURE).
A human should not have to hold all of that in their head per slice. This
stage runs the full XENO battery over the top candidates of a scan CSV and
emits ONE interstellar grade per slice (I0-I5, see
INTERSTELLAR_HIT_CRITERIA.md):

  flagged? --no--> I0 CLEAN
  engineered? (veto S>=0.25 OR >=2 xeno markers) --no--> I1 NOTABLE
  sky marker? (scint SCINT, pol SKY-LIKE, persist+on_only) --no--> I2 ENGINEERED
  strong? (negDM, prime train, precursor, anomalous Doppler, xvm) --no--> I3 LEAN
  payload? (xvm-CANDIDATE AND persistent) --no--> I4 STRONG
  else I5 JACKPOT (full house: structure + sky + exotic + code + persistence)

Monotonic by construction: adding markers never lowers a grade. Exotic alone
never engineers (a chirp with no coding is I1 until proven otherwise).

Usage:
  python xeno_pass.py --scan scan_on_p0.csv --raw data/x.raw --out xeno_p0.csv
      [--off scan_off_p0.csv] [--evidence evidence.csv] [--jerk jerk_results.csv]
      [--topk 40] [--min-fam 4.0]
  --scan/--off are REPEATABLE: pass on_p0 + on_p1 (and off_p0 + off_p1)
  to pool polarizations. Candidates are taken across the pool by fam_best,
  so each (block,chan) is analysed at whichever pol has the higher-SNR
  slice (the mega-run blindspot: p1-only candidates graded never). The
  per-row pol flows into seti_slice, so no extra extraction is needed.
  python xeno_pass.py --selftest   # grade-ladder unit tests (no data/binaries)
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rfi_veto as VETO
import scint_pol as SCINT
import exotic_pass as EXOTIC
import seti_common as SC

GRADES = ('I0', 'I1', 'I2', 'I3', 'I4', 'I5')


def grade_slice(f):
    """Pure grade function. f: dict with keys flagged,S,xcount,scint,pol_sky,
    persist,on_only,negdm,primes,precursor,doppler_anom,xvm_cand (0/1 except
    S float). THE GRADE LADDER - mirrored in z3/smt2/xeno_rules.smt2 and
    z3/verify_xeno.py. Change all three together."""
    eng = (f.get('S', 0.0) >= 0.25) or (f.get('xcount', 0) >= 2)
    sky = f.get('scint', 0) or f.get('pol_sky', 0) or (
        f.get('persist', 0) and f.get('on_only', 0))
    exo = f.get('negdm', 0) or f.get('primes', 0) or f.get('precursor', 0)
    strong = exo or f.get('doppler_anom', 0) or f.get('xvm_cand', 0)
    if not f.get('flagged', 0):
        return 'I0'
    if not eng:
        return 'I1'
    if not sky:
        return 'I2'
    if not strong:
        return 'I3'
    if not (f.get('xvm_cand', 0) and f.get('persist', 0)):
        return 'I4'
    return 'I5'


def selftest():
    base = {'flagged': 1, 'S': 0.0, 'xcount': 0, 'scint': 0, 'pol_sky': 0,
            'persist': 0, 'on_only': 0, 'negdm': 0, 'primes': 0,
            'precursor': 0, 'doppler_anom': 0, 'xvm_cand': 0}
    cases = [
        ('clean -> I0', dict(base, flagged=0), 'I0'),
        ('bare flag -> I1', dict(base), 'I1'),
        ('exotic w/o eng stays I1', dict(base, negdm=1, primes=1), 'I1'),
        ('veto-eng alone -> I2', dict(base, S=0.5), 'I2'),
        ('xeno-pair alone -> I2', dict(base, xcount=2), 'I2'),
        ('single xeno marker not eng -> I1', dict(base, xcount=1), 'I1'),
        ('eng+scint -> I3', dict(base, S=0.5, scint=1), 'I3'),
        ('eng+persist+on_only -> I3', dict(base, S=0.5, persist=1, on_only=1), 'I3'),
        ('persist w/o on_only not sky -> I2', dict(base, S=0.5, persist=1), 'I2'),
        ('I3+negdm -> I4', dict(base, S=0.5, scint=1, negdm=1), 'I4'),
        ('I3+doppler -> I4', dict(base, S=0.5, scint=1, doppler_anom=1), 'I4'),
        ('I3+xvm w/o persist -> I4', dict(base, S=0.5, scint=1, xvm_cand=1), 'I4'),
        ('full house -> I5', dict(base, S=0.5, scint=1, negdm=1,
                                  xvm_cand=1, persist=1), 'I5'),
        ('common-mode bystander can reach I5',
         dict(base, S=0.5, pol_sky=1, primes=1, xvm_cand=1, persist=1,
              on_only=0), 'I5'),
    ]
    ok = True
    for name, f, want in cases:
        got = grade_slice(f)
        passed = got == want
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: got {got} want {want}")
    print('[selftest] ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return ok


def run(exe, *args, timeout=600):
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except OSError as e:
        return 127, '', f'spawn failed: {e}'


def parse_xeno_result(out):
    m = re.search(
        r'RESULT skdev=([\d.]+) skfrac=([\d.]+) skflag=(\d+) coh=([\d.]+) '
        r'cohflag=(\d+) ladder=([\d.]+) ladderq=(\d+) dm_sign=([+-]?\d+) '
        r'dm_r2=([\d.]+) impuls=(\d+) maxz=([\d.]+) kurt=([-\d.]+) tailx=([\d.]+)',
        out)
    if not m:
        return None
    g = m.groups()
    return {'skflag': int(g[2]), 'cohflag': int(g[4]), 'ladderq': int(g[6]),
            'dm_sign': int(g[7]), 'impuls': int(g[9]),
            'skdev': float(g[0]), 'ladder': float(g[5]),
            'dm_r2': float(g[8]), 'maxz': float(g[10])}


def parse_xvm_result(out):
    # New contract (BM + RASTER replaced HAM + CRC; polynomial-agnostic):
    m = re.search(
        r'xvm_sub=([\d.]+) xvm_stk_ops=(\d+) xvm_stk_loops=(\d+) xvm_stk_depth=(\d+) xvm_stk_w=(\d+) '
        r'xvm_ca=([\d.]+) xvm_acf_lag=(\d+) xvm_acf_z=([-\d.]+) xvm_bm_L=(\d+) xvm_bm_z=([-\d.]+) '
        r'xvm_raster_w=(\d+) xvm_raster_h=(\d+) xvm_raster_z=([-\d.]+) xvm_score=([\d.]+) (\S+)', out)
    if not m:
        # Legacy contract (pre-BM binaries): HAM/CRC floors, kept so old
        # logs still parse. New runs always emit the contract above.
        m = re.search(
            r'xvm_sub=([\d.]+) xvm_stk_ops=(\d+) xvm_stk_loops=(\d+) xvm_stk_depth=(\d+) '
            r'xvm_ca=([\d.]+) xvm_acf_lag=(\d+) xvm_acf_z=([-\d.]+) xvm_ham=([\d.]+) '
            r'xvm_crc=(\d+) xvm_score=([\d.]+) (\S+)', out)
        if not m:
            return None
        g = m.groups()
        sub = float(g[0]) >= 0.6
        stk = int(g[2]) >= 20 and int(g[1]) >= 5000
        ca = float(g[4]) >= 0.0015
        acf = abs(float(g[6])) >= 6.0
        ham = float(g[7]) >= 0.25
        crc = int(g[8]) >= 3
        score = float(g[9])
        return {'xvm_nflags': int(sub) + int(stk) + int(ca) + int(acf) + int(ham) + int(crc),
                'xvm_score': score,
                'xvm_cand': 1 if ('XENO-CANDIDATE' in g[10]) else 0,
                'xvm_acf_lag': int(g[5]), 'xvm_bm_z': 0.0}
    g = m.groups()
    sub = float(g[0]) >= 0.6
    stk = int(g[2]) >= 20 and int(g[1]) >= 5000
    ca = float(g[5]) >= 0.0015
    acf = abs(float(g[7])) >= 6.0
    bm = float(g[9]) >= 6.0
    raster = float(g[12]) >= 6.0
    score = float(g[13])
    return {'xvm_nflags': int(sub) + int(stk) + int(ca) + int(acf) + int(bm) + int(raster),
            'xvm_score': score,
            'xvm_cand': 1 if ('XENO-CANDIDATE' in g[14]) else 0,
            'xvm_acf_lag': int(g[6]), 'xvm_bm_z': float(g[9])}


def pack_bits(bits):
    return np.packbits(np.asarray(bits, dtype=np.uint8), bitorder='big')


def analyze_candidate(root, raw, block, chan, pol, fs, work, tag, pols_extra=()):
    ext = '.exe' if os.name == 'nt' else ''
    sl = os.path.join(root, 'c', 'seti_slice' + ext)
    xe = os.path.join(root, 'c', 'xeno_scan' + ext)
    xv = os.path.join(root, 'c', 'xvm_sandbox' + ext)
    out = {'xeno_ok': 0, 'xvm_ok': 0}
    f32 = os.path.join(work, f'xeno_{tag}_b{block}_ch{chan}_p{pol}.f32')
    try:
        rc, _, _ = run(sl, raw, str(chan), f32, '1', '--pol', str(pol),
                       '--start', str(block), timeout=300)
        if rc != 0 or not os.path.exists(f32) or os.path.getsize(f32) < 1000000:
            out['extract_fail'] = 1
            return out
        x = np.fromfile(f32, dtype=np.float32)
        # xeno_scan (C microscopic battery)
        if os.path.exists(xe):
            rc, so, _ = run(xe, f32, f'{fs:.1f}', timeout=300)
            r = parse_xeno_result(so)
            if r:
                out.update(r)
                out['xeno_ok'] = 1
        # xvm_sandbox on sign/diff bitstreams
        if os.path.exists(xv):
            N = min(len(x), 200000)
            seg = x[:N]
            best = None
            for name, bits in (('sign', (seg > 0).astype(np.uint8)),
                               ('diff', (((np.sign(seg) +
                                           (np.sign(seg) == 0)))[1:] *
                                         (np.sign(seg) +
                                          (np.sign(seg) == 0))[:-1] < 0).astype(np.uint8))):
                p = os.path.join(work, f'xvm_{tag}_b{block}_ch{chan}_{name}.bin')
                try:
                    pack_bits(bits).tofile(p)
                    rc, so, _ = run(xv, p, timeout=300)
                    if 'entropy_gate=BLOCK' in so:
                        continue
                    r = parse_xvm_result(so)
                    # Audit trail (lands in xeno.log via the runner): which
                    # machines fired is otherwise invisible downstream -
                    # xvm_nflags carries the count, never the cause.
                    last = so.strip().splitlines()[-1] if so.strip() else 'no-output'
                    print(f'[xvm] b{block} ch{chan} p{pol} {name}: {last}')
                    if r and (best is None or r['xvm_nflags'] > best['xvm_nflags']):
                        best = r
                finally:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            if best:
                out.update(best)
                out['xvm_ok'] = 1
        # scintillation (same-pol envelope class)
        try:
            E, _ = SCINT.stft_bands(x)
            if E is not None:
                s = SCINT.scint_classify(E)
                out['scint_class'] = s['class']
                out['scint_m'] = round(s['m_med'], 3)
        except Exception:
            pass
        # exotic battery (pure python, in-process)
        try:
            ex = EXOTIC.analyze(x, fs)
            out['ex_negdm'] = ex['negdm']['flag']
            out['ex_negdm_kind'] = ex['negdm']['kind']
            out['ex_clock'] = ex['clock']['flag']
            out['ex_ladder'] = ex['ladder']['flag']
            out['ex_primes'] = ex['primes']['flag']
            out['ex_precursor'] = ex['precursor']['flag']
            out['exotic_ok'] = 1
        except Exception:
            pass
        # cross-pol agreement when extra pols requested
        if pols_extra:
            others = []
            for p2 in pols_extra:
                f2 = os.path.join(work, f'xeno_{tag}_b{block}_ch{chan}_p{p2}.f32')
                rc, _, _ = run(sl, raw, str(chan), f2, '1', '--pol', str(p2),
                               '--start', str(block), timeout=300)
                if rc == 0 and os.path.exists(f2):
                    try:
                        others.append(np.fromfile(f2, dtype=np.float32))
                    finally:
                        try:
                            os.remove(f2)
                        except OSError:
                            pass
            if others:
                try:
                    pa = SCINT.pol_agree([x] + others, fs)
                    out['pol_verdict'] = pa['verdict']
                    out['pol_agree'] = 1 if pa['agree'] else 0
                except Exception:
                    pass
        return out
    finally:
        try:
            os.remove(f32)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', required=False, default=[], action='append',
                    help='scan CSV (repeatable: on_p0 + on_p1 pool pols)')
    ap.add_argument('--raw', required=False, default='')
    ap.add_argument('--out', default='xeno.csv')
    ap.add_argument('--off', default=[], action='append',
                    help='OFF scan CSV, cadence map (repeatable)')
    ap.add_argument('--evidence', default='', help='evidence.csv (persist/multichan)')
    ap.add_argument('--jerk', default='', help='jerk_results.csv (Doppler screen)')
    ap.add_argument('--target', default='')
    ap.add_argument('--topk', type=int, default=40)
    ap.add_argument('--min-fam', type=float, default=4.0)
    ap.add_argument('--xpol', action='store_true',
                    help='extract all 4 pols per candidate (pol verdict)')
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--timeout', type=float, default=300.0)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if not a.scan or not a.raw:
        sys.exit('need --scan and --raw')

    scanps = [os.path.join(a.root, s) for s in a.scan]
    rawp = os.path.join(a.root, a.raw)
    outp = os.path.join(a.root, a.out)
    rows = []
    for sp in scanps:
        rows.extend(list(csv.DictReader(open(sp))))
    if not rows:
        sys.exit('no rows in --scan files')
    fs = SC.fs_from_header(rawp) or SC.DEFAULT_FS

    ev = {}
    if a.evidence and os.path.exists(os.path.join(a.root, a.evidence)):
        for r in csv.DictReader(open(os.path.join(a.root, a.evidence))):
            ev[(r.get('target', ''), r['block'], r['chan'])] = r
            ev.setdefault((r['block'], r['chan']), r)

    off_idx = None
    for o in (a.off or []):
        op = os.path.join(a.root, o)
        if not os.path.exists(op):
            continue
        if off_idx is None:
            off_idx = []
        off_idx.extend([(int(r['chan']), float(r.get('fam_hz') or 0))
                        for r in csv.DictReader(open(op))
                        if str(r.get('verdict', '')).startswith(('FAM-HIT', 'SPECTRAL'))])
    on_idx = [(int(r['chan']), float(r.get('fam_hz') or 0)) for r in rows
              if str(r.get('verdict', '')).startswith(('FAM-HIT', 'SPECTRAL'))]

    jerk_anom = set()
    if a.jerk and os.path.exists(os.path.join(a.root, a.jerk)):
        for r in csv.DictReader(open(os.path.join(a.root, a.jerk))):
            if str(r.get('sidereal', '')).startswith('ANOMALOUS'):
                jerk_anom.add((str(r['chan']), str(r['pol'])))

    cands = [r for r in rows if str(r.get('verdict', '')).startswith(
        ('FAM-HIT', 'SPECTRAL'))]
    try:
        cands.sort(key=lambda r: -float(r.get('fam_best') or 0))
    except (ValueError, TypeError):
        pass
    cands = [r for r in cands
             if float(r.get('fam_best') or 0) >= a.min_fam][:a.topk]
    print(f'[xeno] {len(cands)} candidates (fam>={a.min_fam}, topk={a.topk})')

    work = os.path.join(a.root, 'data', 'mvp_tmp')
    os.makedirs(work, exist_ok=True)
    tag = os.path.basename(scanps[0]).replace('.csv', '')

    fields = list(rows[0].keys()) if rows else []
    for extra in ('x_skflag', 'x_cohflag', 'x_ladderq', 'x_dm_sign', 'x_impuls',
                  'xvm_nflags', 'xvm_cand', 'xvm_acf_lag', 'scint_class',
                  'pol_verdict', 'ex_negdm', 'ex_clock', 'ex_ladder',
                  'ex_primes', 'ex_precursor', 'grade'):
        if extra not in fields:
            fields.append(extra)

    from collections import Counter
    gc = Counter()
    with open(outp, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r = dict(r)
            is_cand = str(r.get('verdict', '')).startswith(('FAM-HIT', 'SPECTRAL'))
            key = (str(r.get('block')), str(r.get('chan')))
            # Per-POL match: with pooled scans each pol is graded on its OWN
            # evidence (a p1 winner's battery must not launder its twin's
            # row). Single-scan behaviour is unchanged (rows unique per
            # block,chan there). The pooling fix is upstream: topk is taken
            # across pols, so a p1-only candidate IS analysed (at its pol).
            pkey = (key[0], key[1], str(r.get('pol', '0')))
            match = [c for c in cands if str(c['block']) == pkey[0]
                     and str(c['chan']) == pkey[1]
                     and str(c.get('pol', '0')) == pkey[2]]
            if match:
                c = match[0]
                pols_extra = (tuple(p for p in ('1', '2', '3')
                                    if p != str(c.get('pol', '0'))) if a.xpol else ())
                res = analyze_candidate(a.root, rawp, c['block'], c['chan'],
                                        c.get('pol', '0'), fs, work, tag,
                                        pols_extra)
                S, _ = VETO.structure_score(c)
                e = ev.get((a.target, key[0], key[1]), ev.get(key, {}))
                persist = 1 if str(e.get('persist', '0')) == '1' else 0
                try:
                    ch, al = int(c['chan']), float(c.get('fam_hz') or 0)
                    on_only = 1 if (off_idx is not None and not
                                    VETO.in_index(off_idx, ch, al)) else 0
                except (ValueError, KeyError):
                    on_only = 0
                xcount = (res.get('skflag', 0) + res.get('cohflag', 0)
                          + (1 if res.get('ladderq', 0) else 0)
                          + (1 if res.get('dm_sign', 0) else 0)
                          + (1 if res.get('xvm_nflags', 0) >= 1 else 0)
                          + (1 if res.get('ex_ladder', 0) else 0)
                          + (1 if res.get('ex_clock', 0) else 0))
                f = {'flagged': 1, 'S': S, 'xcount': xcount,
                     'scint': 1 if res.get('scint_class') == 'SCINT' else 0,
                     'pol_sky': 1 if res.get('pol_verdict') == 'SKY-LIKE' else 0,
                     'persist': persist, 'on_only': on_only,
                     'negdm': res.get('ex_negdm', 0),
                     'primes': res.get('ex_primes', 0),
                     'precursor': res.get('ex_precursor', 0),
                     'doppler_anom': 1 if key + (str(c.get('pol', '0')),)
                     in jerk_anom else 0,
                     'xvm_cand': res.get('xvm_cand', 0)}
                g = grade_slice(f)
                r['x_skflag'] = res.get('skflag', '')
                r['x_cohflag'] = res.get('cohflag', '')
                r['x_ladderq'] = res.get('ladderq', '')
                r['x_dm_sign'] = res.get('dm_sign', '')
                r['x_impuls'] = res.get('impuls', '')
                r['xvm_nflags'] = res.get('xvm_nflags', '')
                r['xvm_cand'] = res.get('xvm_cand', '')
                r['xvm_acf_lag'] = res.get('xvm_acf_lag', '')
                r['scint_class'] = res.get('scint_class', '')
                r['pol_verdict'] = res.get('pol_verdict', '')
                r['ex_negdm'] = res.get('ex_negdm', '')
                r['ex_clock'] = res.get('ex_clock', '')
                r['ex_ladder'] = res.get('ex_ladder', '')
                r['ex_primes'] = res.get('ex_primes', '')
                r['ex_precursor'] = res.get('ex_precursor', '')
                r['grade'] = g
                gc[g] += 1
            else:
                v = str(r.get('verdict', 'clean'))
                # quarantined/errored rows hold no sky information at all:
                # I0 (nothing analysable), never I1 (which claims a flag).
                r['grade'] = 'I0' if (v == 'clean' or v.startswith(
                    ('QUARANTINE', 'ERROR'))) else 'I1'
                gc[r['grade']] += 1
            w.writerow(r)
    SC.write_manifest(outp, {'tool': 'xeno_pass.py', 'scan': a.scan,
                             'raw': a.raw, 'min_fam': a.min_fam,
                             'topk': a.topk, 'grades': dict(gc)})
    print(f"[xeno] grades: {' '.join(f'{k}={gc[k]}' for k in GRADES)} -> {a.out}")


if __name__ == '__main__':
    main()
