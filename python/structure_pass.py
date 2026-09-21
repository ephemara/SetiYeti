"""structure_pass.py - M1 STRUCTURE producer: comb + nongauss flags for the veto.

WHY THIS EXISTS: rfi_veto.py scores STRUCTURE (baud comb, frame period,
non-Gaussian tail, polarisation coherence) - but no pipeline stage ever
produced those columns, so S scored 0.00 on all ~2,700 Kepler flags and the
bystander-model inversion never engaged. This stage computes two of the four
(frame comes from frame_hunt --json; pol comes from build_evidence multichan):

  comb       harmonic-comb test on the slice's Y2/Y4 spectra (Gardner-style):
             >= 3 distinct peaks on harmonics m*f0 (m = 1..8, +-1 bin) with
             mean member ratio >= 6.0. THE COMB RULE - shared verbatim with
             c/comb_scan.c (fast path). Single tones (the ch0 standing line)
             can never satisfy members >= 3.
  nongauss   excess kurtosis > 1.0 OR 4-sigma tail > 3x Gaussian expectation.
             Coded traffic is mildly non-Gaussian; impulsive RFI is wildly so
             the other way - either way it is STRUCTURE input, and the veto
             decides attribution, not this tool.

Backend: c/comb_scan[.exe] when the binary exists (one pass, RESULT line),
else a numpy fallback running fam_scan's proven spectra + the same rule.
Output: struct CSV = input rows + comb,comb_f0,comb_score,frame,nongauss
columns (veto flag() picks them up; absent = 0, so old CSVs still score).

Usage:
  python structure_pass.py --scan scan_on_p0.csv --raw data/x.raw
      --out struct_on_p0.csv [--frames frame_results.json]
      [--min-fam 4.0 --topk 600]
  python structure_pass.py --selftest
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC  # noqa: E402

FAM_BIN_HZ = 89.4           # SEG=32768 grid (matches fam_scan resolution)
COMB_MIN_MEMBERS = 3
COMB_MIN_SCORE = 6.0
KURT_THRESH = 1.0
TAIL_THRESH = 3.0
TAIL_GAUSS_4SIGMA = 6.33e-5


def run(exe, *args, timeout=300):
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except OSError as e:
        return 127, '', f'spawn failed: {e}'


def comb_backend(root):
    ext = '.exe' if os.name == 'nt' else ''
    p = os.path.join(root, 'c', 'comb_scan' + ext)
    return p if os.path.exists(p) else None


def comb_via_c(exe, f32, fs):
    rc, out, _ = run(exe, f32, f'{fs:.1f}')
    m = re.search(r'^RESULT comb=(\d+) comb_score=([\d.]+) f0_hz=([\d.]+) '
                  r'members=(\d+) nongauss=(\d+) kurt=([-\d.]+) tailx=([\d.]+)'
                  r'(?: nlines10=(\d+) thicket=(\d+))?',
                  out, re.M)
    if not m:
        return None
    return {'comb': int(m.group(1)), 'comb_score': float(m.group(2)),
            'comb_f0': float(m.group(3)), 'members': int(m.group(4)),
            'nongauss': int(m.group(5)), 'kurt': float(m.group(6)),
            'tailx': float(m.group(7)),
            'lines10': int(m.group(8)) if m.group(8) is not None else -1,
            'thicket': int(m.group(9)) if m.group(9) is not None else 0}


def fam_peaks(fam_exe, f32, fs, topk=15):
    rc, out, _ = run(fam_exe, f32, f'{fs:.1f}', '32768', str(topk))
    peaks = []
    for line in out.splitlines():
        m = re.match(r'^(Y2|Y4) peak\s+\d+\s+bin=\d+\s+alpha=\s*([\d.]+) Hz'
                     r'\s+ratio=\s*([\d.]+)x', line)
        if m:
            peaks.append((m.group(1), float(m.group(2)), float(m.group(3))))
    return peaks


def comb_rule_on_bins(peak_bins, B):
    """THE COMB RULE on {bin: ratio}. Returns (members, score, f0bin)."""
    best = (0, 0.0, 0)
    for b0 in range(2, 129):
        tot, n = 0.0, 0
        for m in range(1, 9):
            tgt = m * b0
            if tgt > B:
                break
            hit = None
            for b, r in peak_bins.items():
                if tgt - 1 <= b <= tgt + 1:
                    hit = (b, r)
                    break
            if hit is not None:
                tot += hit[1]
                n += 1
        s = tot / n if n else 0.0
        if n >= COMB_MIN_MEMBERS and (n > best[0] or
                                      (n == best[0] and s > best[1])):
            best = (n, s, b0)
    n, s, b0 = best
    if n >= COMB_MIN_MEMBERS and s >= COMB_MIN_SCORE:
        return n, s, b0
    return 0, s, 0


def comb_via_numpy(fam_exe, f32, fs):
    peaks = fam_peaks(fam_exe, f32, fs)
    bins = {}
    for _, a, r in peaks:
        b = int(round(a / (fs / 32768.0)))
        if b not in bins or r > bins[b]:
            bins[b] = r
    n, s, b0 = comb_rule_on_bins(bins, 32768 // 2)
    f0 = b0 * fs / 32768.0 if n else 0.0
    return {'comb': 1 if n else 0, 'comb_score': s, 'comb_f0': f0,
            'members': n, 'lines10': -1, 'thicket': 0}


def nongauss_stats(x):
    x = np.asarray(x, dtype=np.float64)
    m = x.mean()
    sd = x.std()
    if sd <= 0:
        return 0.0, 0.0
    z = (x - m) / sd
    kurt = float((z ** 4).mean() - 3.0)
    tailx = float((np.abs(z) > 4).mean() / TAIL_GAUSS_4SIGMA)
    return kurt, tailx


def analyze_slice(root, raw, block, chan, pol, fs, work, tag, timeout=300):
    """Extract one block and score it. Returns dict with comb/nongauss."""
    ext = '.exe' if os.name == 'nt' else ''
    sl = os.path.join(root, 'c', 'seti_slice' + ext)
    fam = os.path.join(root, 'c', 'fam_scan' + ext)
    f32 = os.path.join(work, f'struct_{tag}_b{block}_ch{chan}.f32')
    try:
        rc, _, _ = run(sl, raw, str(chan), f32, '1', '--pol', str(pol),
                       '--start', str(block), timeout=timeout)
        if rc != 0 or not os.path.exists(f32) \
                or os.path.getsize(f32) < 1000000:
            return None
        comb_exe = comb_backend(root)
        if comb_exe:
            res = comb_via_c(comb_exe, f32, fs)
            if res is not None:
                return res
        # numpy fallback: fam_scan peaks + same comb rule, numpy tail stats
        res = comb_via_numpy(fam, f32, fs)
        x = np.fromfile(f32, dtype=np.float32)
        kurt, tailx = nongauss_stats(x)
        res['nongauss'] = 1 if (kurt > KURT_THRESH
                               or tailx > TAIL_THRESH) else 0
        res['kurt'] = kurt
        res['tailx'] = tailx
        return res
    finally:
        try:
            os.remove(f32)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', required=False, default='')
    ap.add_argument('--raw', required=False, default='')
    ap.add_argument('--out', default='struct.csv')
    ap.add_argument('--frames', default='',
                    help='frame_results.json; channels with detections get frame=1')
    ap.add_argument('--min-fam', type=float, default=4.0)
    ap.add_argument('--topk', type=int, default=600)
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--timeout', type=float, default=300.0)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if not a.scan or not a.raw:
        sys.exit('need --scan and --raw')

    scanp = os.path.join(a.root, a.scan)
    rawp = os.path.join(a.root, a.raw)
    outp = os.path.join(a.root, a.out)
    rows = list(csv.DictReader(open(scanp)))
    fs = SC.fs_from_header(rawp) or SC.DEFAULT_FS

    frame_chans = set()
    if a.frames and os.path.exists(os.path.join(a.root, a.frames)):
        fd = json.load(open(os.path.join(a.root, a.frames)))
        for c in fd.get('channels', []):
            if c.get('frame_detected'):
                frame_chans.add(str(c.get('chan')))

    cands = [r for r in rows if str(r.get('verdict', '')).startswith(
        ('FAM-HIT', 'SPECTRAL-LINE'))]
    try:
        cands.sort(key=lambda r: -float(r.get('fam_best') or 0))
    except (ValueError, TypeError):
        pass
    cands = [r for r in cands
             if float(r.get('fam_best') or 0) >= a.min_fam][:a.topk]

    work = os.path.join(a.root, 'data', 'mvp_tmp')
    os.makedirs(work, exist_ok=True)
    tag = os.path.basename(scanp).replace('.csv', '')
    scored = {}
    for r in cands:
        key = (str(r['block']), str(r['chan']))
        res = analyze_slice(a.root, rawp, r['block'], r['chan'],
                            r.get('pol', '0'), fs, work, tag, a.timeout)
        scored[key] = res or {'comb': 0, 'comb_score': 0.0, 'comb_f0': 0.0,
                              'members': 0, 'nongauss': 0, 'kurt': 0.0,
                              'tailx': 0.0, 'lines10': -1, 'thicket': 0}
    n_comb = sum(1 for v in scored.values() if v['comb'])
    n_ng = sum(1 for v in scored.values() if v['nongauss'])

    fields = list(rows[0].keys()) if rows else []
    for extra in ('comb', 'comb_f0', 'comb_score', 'frame', 'nongauss',
                  'lines10', 'thicket'):
        if extra not in fields:
            fields.append(extra)
    with open(outp, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r = dict(r)
            key = (str(r.get('block')), str(r.get('chan')))
            s = scored.get(key, {})
            r['comb'] = s.get('comb', 0)
            r['comb_f0'] = f"{s.get('comb_f0', 0.0):.0f}"
            r['comb_score'] = f"{s.get('comb_score', 0.0):.2f}"
            r['lines10'] = s.get('lines10', -1)
            r['thicket'] = s.get('thicket', 0)
            r['frame'] = 1 if str(r.get('chan')) in frame_chans else 0
            r['nongauss'] = s.get('nongauss', 0)
            w.writerow(r)
    SC.write_manifest(outp, {'tool': 'structure_pass.py', 'scan': a.scan,
                             'raw': a.raw, 'min_fam': a.min_fam,
                             'topk': a.topk, 'analyzed': len(scored),
                             'comb_hits': n_comb, 'nongauss_hits': n_ng,
                             'frame_chans': sorted(frame_chans)})
    backend = 'comb_scan(C)' if comb_backend(a.root) else 'numpy fallback'
    print(f'[structure] {len(scored)} slices via {backend}: '
          f'comb={n_comb} nongauss={n_ng} frame_chans={len(frame_chans)} '
          f'-> {a.out}')


def selftest():
    """Pure-rule tests (no binaries, no data): the comb rule + tail stats."""
    ok = True

    def check(name, cond):
        global_ok = cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        return cond

    # 1. exact harmonic family (the Kepler 358 case: bins 4/16/32 @89.4Hz)
    n, s, b0 = comb_rule_on_bins({4: 30.0, 16: 25.0, 32: 20.0, 900: 40.0},
                                 16384)
    ok &= check('harmonic family fires (members>=3)', n >= 3 and b0 == 4)
    # 2. single tone + unrelated giant: no comb
    n, s, b0 = comb_rule_on_bins({56: 120.0, 900: 40.0}, 16384)
    ok &= check('single tone does not fire', n == 0)
    # 3. two harmonics only: below member threshold
    n, s, b0 = comb_rule_on_bins({4: 30.0, 8: 25.0}, 16384)
    ok &= check('two harmonics insufficient', n == 0)
    # 4. weak harmonics below score floor
    n, s, b0 = comb_rule_on_bins({4: 3.1, 8: 3.0, 12: 3.2}, 16384)
    ok &= check('weak harmonics below score floor', n == 0)
    # 5. tail stats: gaussian quiet, impulses loud
    rng = np.random.default_rng(7)
    k, t = nongauss_stats(rng.normal(0, 14, 200000).astype(np.float64))
    ok &= check(f'gaussian quiet (kurt={k:.2f} tailx={t:.2f})',
                abs(k) < KURT_THRESH and t < TAIL_THRESH)
    x = rng.normal(0, 14, 200000)
    x[rng.choice(200000, 40, replace=False)] = 20 * 14.0
    k, t = nongauss_stats(x)
    loud = k > KURT_THRESH or t > TAIL_THRESH
    ok &= check(f'impulses loud (kurt={k:.2f} tailx={t:.2f})', loud)
    print('[selftest] ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return bool(ok)


if __name__ == '__main__':
    main()
