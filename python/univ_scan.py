"""univ_scan.py - SetiYeti universal scan: any file in, battery out.

WHY THIS EXISTS: univ_ingest.py delivers ONE canonical stream per format;
this runs the detection battery on it and writes a verdict. Voltage and
complex inputs get the FULL battery (every C tool + python detector, via a
canonical .f32 handoff - zero detector changes). Detected-power inputs
(filterbank, spectra) honestly get the SPECTRAL subset: nothing that needs
phase is attempted, and the grade is capped accordingly.

  python univ_scan.py --in signal.wav --outdir runs/univ_wav
  python univ_scan.py --in blc.fil --outdir runs/univ_fil
  python univ_scan.py --in capture.cfile --fs 2000000 --outdir runs/univ_iq
  python univ_scan.py --in capture.cu8 --fs 2000000 --outdir runs/univ_rtl

Single-file rule: no cadence, no persistence evidence - grades cap at I2
(ENGINEERED without sky context). Anything higher needs xeno_pass.py with
a pair and evidence. The report says so explicitly.
"""
import argparse
import csv
import json
import os
import subprocess
import sys

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import univ_ingest as UI
import scint_pol as SCINT
import exotic_pass as EXOTIC
import xeno_pass as XPASS
import seti_common as SC

CAP_DEFAULT = 4_000_000


def run(exe, *args, timeout=600):
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except OSError as e:
        return 127, '', f'spawn failed: {e}'


def direct_peak(x, fs=None):
    n = min(len(x), 262144)
    P = np.abs(np.fft.rfft(x[:n].astype(np.float64))) ** 2
    P[:2] = 0
    med = float(np.median(P)) or 1e-30
    k = int(np.argmax(P))
    f = k * (fs / n) if fs else 0.0
    return float(P[k] / med), float(f)


def battery_full(root, f32, fs, work):
    """Every tool that needs voltage. Returns dict of marker results."""
    ext = '.exe' if os.name == 'nt' else ''
    fam = os.path.join(root, 'c', 'fam_scan' + ext)
    cmb = os.path.join(root, 'c', 'comb_scan' + ext)
    xen = os.path.join(root, 'c', 'xeno_scan' + ext)
    xvm = os.path.join(root, 'c', 'xvm_sandbox' + ext)
    out = {}
    x = np.fromfile(f32, dtype=np.float32)
    sr, sf = direct_peak(x, fs)
    out['spec_ratio'] = round(sr, 2)
    out['spec_freq'] = round(sf, 1)
    out['spec_flag'] = int(sr >= 5.0)
    if os.path.exists(fam):
        rc, so, _ = run(fam, f32, f'{fs:.1f}', '32768', '6', '-')
        peaks = []
        import re
        for line in so.splitlines():
            m = re.search(r'alpha=\s*([\d.]+) Hz\s+ratio=\s*([\d.]+)x', line)
            if m:
                peaks.append((float(m.group(1)), float(m.group(2))))
        peaks.sort(key=lambda t: -t[1])
        out['fam_best'] = round(peaks[0][1], 2) if peaks else 0.0
        out['fam_hz'] = round(peaks[0][0], 1) if peaks else 0.0
        out['fam_flag'] = int(out['fam_best'] >= 3.0)
    if os.path.exists(cmb):
        rc, so, _ = run(cmb, f32, f'{fs:.1f}')
        import re
        m = re.search(r'RESULT comb=(\d+) comb_score=([\d.]+) f0_hz=([\d.]+) '
                      r'members=(\d+) nongauss=(\d+).*?nlines10=(\d+) thicket=(\d+)',
                      so, re.S)
        if m:
            out['comb'] = int(m.group(1))
            out['comb_score'] = float(m.group(2))
            out['nongauss'] = int(m.group(5))
            out['lines10'] = int(m.group(6))
            out['thicket'] = int(m.group(7))
    if os.path.exists(xen):
        rc, so, _ = run(xen, f32, f'{fs:.1f}')
        r = XPASS.parse_xeno_result(so)
        if r:
            out.update({f'x_{k}': v for k, v in r.items()})
    if os.path.exists(xvm):
        N = min(len(x), 200000)
        seg = x[:N]
        s = np.sign(seg)
        s[s == 0] = 1
        best = None
        s2 = np.sign(seg)
        s2[s2 == 0] = 1
        for name, bits in (('sign', (seg > 0).astype(np.uint8)),
                           ('diff', (s2[1:] * s2[:-1] < 0).astype(np.uint8))):
            p = os.path.join(work, f'univ_{name}.bin')
            try:
                np.packbits(bits.astype(np.uint8),
                            bitorder='big').tofile(p)
                rc, so, _ = run(xvm, p)
                if 'entropy_gate=BLOCK' in so:
                    continue
                r = XPASS.parse_xvm_result(so)
                if r and (best is None or
                          r['xvm_nflags'] > best['xvm_nflags']):
                    best = r
            finally:
                try:
                    os.remove(p)
                except OSError:
                    pass
        if best:
            out.update(best)
    try:
        E, _ = SCINT.stft_bands(x)
        if E is not None:
            s = SCINT.scint_classify(E)
            out['scint_class'] = s['class']
    except Exception:
        pass
    try:
        ex = EXOTIC.analyze(x, fs or 2929687.5)
        for k in ('negdm', 'clock', 'ladder', 'primes', 'precursor'):
            out[f'ex_{k}'] = ex[k]['flag']
        out['exotic_score'] = ex['exotic_score']
    except Exception:
        pass
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import pulsar_fold as FOLD
        fr = FOLD.detect(x, fs=fs or 2929687.5)
        out['fold_flag'] = int(fr['detected'])
        out['fold_f'] = round(fr.get('best', {}).get('freq_hz', 0.0), 2)
    except Exception:
        pass
    return out


def battery_power(meta, arr):
    """Spectral subset for detected-power inputs. No phase, no pretending."""
    out = {'subset': 'spectral-only (phase discarded at record time)'}
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim == 3:
        a = a[:, 0, :]
    env = a.mean(axis=1) if a.ndim == 2 else a.ravel()
    env = np.ascontiguousarray(env, dtype=np.float32)
    sr, _ = direct_peak(env)
    out['spec_ratio'] = round(sr, 2)
    out['spec_flag'] = int(sr >= 5.0)
    try:
        E = a if a.ndim == 2 else env.reshape(-1, 1)
        s = SCINT.scint_classify(E if E.shape[1] >= 2 else
                                 np.stack([E.ravel()] * 2, axis=1))
        out['scint_class'] = s['class']
    except Exception:
        pass
    # pulse-train/echo/ladder hunters need long envelopes; a 128-spectra
    # filterbank window is 128 points - attempting them manufactures
    # divide-by-zero warnings on empty blocks (measured), not science.
    if len(env) >= 1024:
        try:
            pf = EXOTIC.primes(env)
            pc = EXOTIC.precursor(env)
            out['ex_primes'] = pf['flag']
            out['ex_precursor'] = pc['flag']
            ld = EXOTIC.ladder(env)
            out['ex_ladder'] = ld['flag']
        except Exception:
            pass
    else:
        out['pulse_hunters'] = 'skipped: envelope too short for trains'
    try:
        import pulsar_fold as FOLD
        fr = FOLD.detect((env - env.mean()).astype(np.float32))
        out['fold_flag'] = int(fr['detected'])
    except Exception:
        pass
    return out


def grade_single(res, kind):
    """Single-file grade via the shipped ladder, sky/persist forced 0
    (no cadence exists) -> honest cap at I2."""
    xcount = sum(int(res.get(k, 0)) for k in
                 ('x_skflag', 'x_cohflag', 'x_ladderq', 'ex_ladder',
                  'ex_clock')) + (1 if res.get('x_dm_sign', 0) else 0) \
        + (1 if res.get('xvm_nflags', 0) >= 1 else 0)
    S = 0.0
    if res.get('comb'):
        S += 0.0 if res.get('thicket') else 0.20
    if res.get('nongauss'):
        S += 0.15
    if res.get('xvm_cand'):
        S += 0.25
    S = min(S, 1.0)
    f = {'flagged': int(bool(res.get('spec_flag') or res.get('fam_flag')
                              or res.get('fold_flag'))),
         'S': S, 'xcount': xcount, 'scint': 0, 'pol_sky': 0, 'persist': 0,
         'on_only': 0, 'negdm': int(res.get('ex_negdm', 0)),
         'primes': int(res.get('ex_primes', 0)),
         'precursor': int(res.get('ex_precursor', 0)),
         'doppler_anom': 0, 'xvm_cand': int(res.get('xvm_cand', 0))}
    return XPASS.grade_slice(f), S, xcount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--outdir', default='runs/univ_0')
    ap.add_argument('--reader', default='')
    ap.add_argument('--fs', type=float, default=None)
    ap.add_argument('--iq-format', default='')
    ap.add_argument('--hint', default='')
    ap.add_argument('--t0', type=float, default=0.0)
    ap.add_argument('--dur', type=float, default=None)
    ap.add_argument('--cap', type=int, default=CAP_DEFAULT)
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    root = a.root
    outdir = os.path.join(root, a.outdir)
    os.makedirs(outdir, exist_ok=True)
    work = os.path.join(root, 'data', 'mvp_tmp')
    os.makedirs(work, exist_ok=True)

    src = a.inp if os.path.isabs(a.inp) else os.path.join(root, a.inp)
    meta, arr = UI.open_any(src, t0=a.t0, dur=a.dur, reader=a.reader,
                            fs=a.fs, iq_format=a.iq_format, hint=a.hint,
                            root=root)
    real = UI.canonical_real(meta, arr)
    if len(real) > a.cap:
        meta['caveats'].append(f'window capped to {a.cap} samples for the battery')
        real = real[:a.cap]
    f32 = os.path.join(outdir, 'signal.f32')
    real.tofile(f32)
    json.dump({k: str(v) for k, v in meta.items()},
              open(os.path.join(outdir, 'meta.json'), 'w'), indent=1)

    if meta['kind'] in ('voltage', 'complex'):
        fs = meta.get('fs') or a.fs
        if not fs:
            sys.exit('voltage input without sample rate: pass --fs')
        res = battery_full(root, f32, float(fs), work)
        mode = 'FULL battery (phase intact)'
    else:
        res = battery_power(meta, arr)
        mode = res.get('subset', 'spectral subset')
    grade, S, xcount = grade_single(res, meta['kind'])
    res['grade'] = grade
    res['S'] = round(S, 2)
    res['xcount'] = xcount
    json.dump(res, open(os.path.join(outdir, 'battery.json'), 'w'),
              indent=1, default=str)

    lines = [f'# Universal scan — {meta["src"]}', '',
             f'reader={meta["reader"]} ({meta["detect_why"]})  kind={meta["kind"]}',
             f'mode: {mode}', '']
    for k in ('fs', 'f_center_mhz', 'bw_mhz', 'tsamp', 'nchans', 'duration_s'):
        if meta.get(k) is not None:
            lines.append(f'- {k}={meta[k]}')
    for c in meta.get('caveats', []):
        lines.append(f'- caveat: {c}')
    lines += ['', '## Battery', '']
    for k, v in res.items():
        lines.append(f'- {k}={v}')
    lines += ['',
              f'## Verdict: {grade} (single-file cap: I2 maximum without '
              'cadence/persistence evidence)',
              '']
    if grade == 'I2':
        lines.append('ENGINEERED without sky context: characterise (dechirp, '
                     'fold, longer stare), then bring a second pointing.')
    elif grade == 'I1':
        lines.append('NOTABLE but unstructured: no coding, no comb, no '
                     'exotic marker pair. Astrophysical or mundane until '
                     'proven otherwise.')
    else:
        lines.append('CLEAN on this window at these floors.')
    open(os.path.join(outdir, 'REPORT.md'), 'w').write('\n'.join(lines))
    SC.write_manifest(os.path.join(outdir, 'REPORT.md'),
                      {'tool': 'univ_scan.py', 'src': meta['src'],
                       'reader': meta['reader'], 'kind': meta['kind'],
                       'grade': grade})
    print(f"[univ] {meta['reader']}/{meta['kind']}: grade={grade} -> {a.outdir}")


if __name__ == '__main__':
    main()
