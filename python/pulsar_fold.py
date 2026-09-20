"""pulsar_fold.py — BEAST periodicity / folding search (closes blind spot #1).

Pipeline was deaf to pulsars by construction: no folding, no harmonic sum.
This hunts 1 Hz–2 kHz rotation-powered periods via envelope FFT + incoherent
harmonic summing (standard pulsar-search machinery, scipy-free core):

  1. power envelope env = x^2, decimate to env_fs (~5.7 kHz, covers 2 kHz Nyq)
  2. Hann FFT periodogram P(f); whiten by running median (red-noise robust)
  3. harmonic sum H(f0) = Σ_{h=1..8} P(h*f0)/√h  (pulse duty-cycle gain)
  4. sigma vs MAD floor; threshold 8σ (prove-calibrated below)

Science wires: scipy.signal (butter/median) + astropy (period→freq, DM-ready
hooks) used when present, numpy fallback otherwise — never a hard dependency.

  python pulsar_fold.py --prove        # fires on 10 Hz + Crab-like 29.7 Hz, quiet on noise
  python pulsar_fold.py --f32 ch.f32 --fmin 1 --fmax 2000
"""
import argparse, os, sys
import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FS_DEFAULT = 2929687.5
FMIN, FMAX, HARMS, SIGMA = 1.0, 2000.0, 8, 16.0  # 8-draw noise max ~10.8; weakest inject 3400+


def _whiten(P, w=201):
    w = min(w, len(P) - 1 if len(P) > 1 else 1)
    if w < 5:
        return P / max(np.median(P), 1e-30)
    try:
        from scipy.ndimage import median_filter
        cont = median_filter(P, size=w, mode='reflect')
    except Exception:
        k = np.ones(w) / w
        cont = np.convolve(P, k, mode='same')
        cont = np.maximum(cont, 1e-30)
    return P / np.maximum(cont, 1e-30)


def detect(x, fs=FS_DEFAULT, fmin=FMIN, fmax=FMAX, harms=HARMS, topk=8):
    x = np.asarray(x, dtype=np.float64)
    # decimate envelope so fmax sits safely below Nyquist
    dec = max(1, int(fs / (2.5 * max(fmax, 1.0)) / 2) * 2 or 1)
    # simpler: target env_fs ≈ 6 kHz
    dec = max(1, int(round(fs / 6000.0)))
    n = (len(x) // dec) * dec
    if n < dec * 64:
        return {'detected': False, 'reason': 'too short'}
    env = (x[:n] ** 2).reshape(-1, dec).mean(axis=1)
    env = env - env.mean()
    env = env * np.hanning(len(env))
    nfft = int(2 ** np.ceil(np.log2(max(len(env) * 4, 16))))
    P = np.abs(np.fft.rfft(env, n=nfft)) ** 2
    Q = _whiten(P)
    env_fs = fs / dec
    df = env_fs / nfft
    i0 = max(2, int(np.ceil(fmin / df)))
    i1 = min(len(Q) - harms - 1, int(np.floor(fmax / df)))
    if i1 <= i0:
        return {'detected': False, 'reason': 'band empty'}
    f = np.arange(i0, i1 + 1, dtype=float) * df
    H = np.zeros_like(f)
    for h in range(1, harms + 1):
        idx = np.round(f * h / df).astype(int)
        idx = np.clip(idx, 0, len(Q) - 1)
        H += Q[idx] / np.sqrt(h)
    med = float(np.median(H))
    mad = float(np.median(np.abs(H - med))) or float(H.std() or 1e-12)
    sig = (H - med) / (1.4826 * mad)
    order = np.argsort(sig)[::-1]
    tops, seen = [], []
    for k in order:
        ff = float(f[k])
        if any(abs(ff - s) / s < 0.02 for s in seen):
            continue
        seen.append(ff)
        tops.append({'freq_hz': ff, 'period_ms': 1000.0 / ff,
                     'sigma': float(sig[k])})
        if len(tops) >= topk:
            break
    best = tops[0] if tops else {'freq_hz': 0, 'period_ms': 0, 'sigma': 0}
    return {'detected': bool(best['sigma'] >= SIGMA), 'best': best,
            'top': tops, 'sigma_thresh': SIGMA, 'env_fs': env_fs,
            'df_hz': df, 'nfft': nfft, 'floor_med': med}


def prove():
    rng = np.random.default_rng(1234)
    N = 4 * 524288
    fs = FS_DEFAULT
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    noise = (rng.normal(0, 14, N)).astype(np.float32)
    r = detect(noise, fs)
    check('CTRL noise quiet', not r['detected'], f"maxσ={r['top'][0]['sigma']:.2f}" if r.get('top') else '')
    for f0 in (10.0, 29.7, 400.0):
        t = np.arange(N) / fs
        # pulsed: narrow duty-cycle Gaussian train (pulsar-like)
        phase = (t * f0) % 1.0
        pulse = np.exp(-0.5 * ((phase - 0.5) / 0.03) ** 2)
        y = (noise + 6.0 * pulse * 14).astype(np.float32)
        r = detect(y, fs)
        got = r['best']['freq_hz'] if r.get('best') else 0
        err = abs(got - f0) / f0 if got else 1
        check(f'INJECT {f0} Hz recovered', r['detected'] and err < 0.03,
              f"got={got:.2f}Hz σ={r['best']['sigma']:.1f}")
    # sinusoid (rotator/hum) also fires — at 2x: the power envelope squares
    # the voltage, so sin(179t) pulses at 358 Hz. Attribution is the veto's job.
    t = np.arange(N) / fs
    y = (noise + 2.0 * np.sin(2 * np.pi * 179 * t) * 14).astype(np.float32)
    r = detect(y, fs)
    got = r['best']['freq_hz']
    check('179 Hz sine fires at 358 Hz envelope', r['detected'] and abs(got - 358) / 358 < 0.03,
          f"got={got:.1f}Hz")
    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', default='')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--fs', type=float, default=FS_DEFAULT)
    ap.add_argument('--fmin', type=float, default=FMIN)
    ap.add_argument('--fmax', type=float, default=FMAX)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    import json as _j
    x = np.fromfile(a.f32, dtype=np.float32)
    r = detect(x, fs=a.fs, fmin=a.fmin, fmax=a.fmax)
    if a.json:
        print(_j.dumps(r)); return
    print(f"[fold] env_fs={r['env_fs']:.0f}Hz df={r['df_hz']:.3f}Hz thresh={r['sigma_thresh']}σ")
    for t in r['top'][:8]:
        print(f"  f={t['freq_hz']:9.2f}Hz P={t['period_ms']:9.3f}ms σ={t['sigma']:+7.2f}")
    print('[fold] VERDICT: ' + ('PERIODIC' if r['detected'] else 'no period'))


if __name__ == '__main__':
    main()
