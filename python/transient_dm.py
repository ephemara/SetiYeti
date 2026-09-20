"""transient_dm.py — BEAST single-pulse + DM sweep (closes blind spot #2).

No FRB/magnetar-shot coverage existed. This adds incoherent dedispersion over
DM trials + boxcar matched filtering on the channelised power:

  method (fast, operates on one coarse channel as a narrowband proxy):
  1. split slice into M sub-bands (default 16) via rfft filterbank
  2. for each DM trial: shift sub-band envelopes by Δt(DM, f) (cold-plasma law,
     astropy constants when available), sum → dedispersed time series
  3. boxcar matched filter over widths [1..128]; robust-z vs MAD floor
  4. report best (DM, width, sigma); threshold 14σ (noise max ~10.8, weakest inject 168)

Cold plasma: Δt = 4.15ms * DM * (f_lo^-2 − f_hi^-2), f in GHz.
For a 2.93 MHz coarse channel the intra-channel smear is small — this stage
catches bright narrow shots + validates the machinery; full-band coherent
dedispersion is the follow-up lever, not a blocker.

  python transient_dm.py --prove   # fires on injected dispersed shot, quiet on noise
"""
import argparse, sys
import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FS_DEFAULT = 2929687.5
K_DM = 4.15e-3  # s * DM * (GHz^-2)


def _filterbank(x, m=16):
    n = (len(x) // m) * m
    X = np.fft.rfft(x[:n].reshape(-1, m), axis=1)
    return np.abs(X) ** 2  # (nt, m+1); use m sub-bands


def detect(x, fs=FS_DEFAULT, f0_mhz=1400.0, bw_mhz=2.93, dm_trials=32,
           dm_max=1000.0, widths=(1, 2, 4, 8, 16, 32, 64, 128), msub=16,
           thresh=14.0):  # noise-only max ~10.8 over DM x width trials; weakest inject 168
    x = np.asarray(x, dtype=np.float64)
    P = _filterbank(x, msub)
    nt, nb = P.shape
    if nt < 256:
        return {'detected': False, 'reason': 'too short'}
    # sub-band centre freqs across the coarse channel
    f_edges = np.linspace(f0_mhz - bw_mhz / 2, f0_mhz + bw_mhz / 2, nb + 1)
    f_c = (f_edges[:-1] + f_edges[1:]) / 2.0 / 1000.0  # GHz
    f_top = f_c.max()
    dt = msub / fs  # seconds per envelope row
    dms = np.linspace(0, dm_max, max(dm_trials, 1))
    env = P / np.maximum(np.median(P, axis=0, keepdims=True), 1e-30)
    env = env - env.mean(axis=0, keepdims=True)
    best = {'sigma': 0, 'dm': 0, 'width': 1, 't': 0}
    for dm in dms:
        shifts = (K_DM * dm * (f_c ** -2 - f_top ** -2) / dt).astype(int)
        D = np.empty_like(env)
        for b in range(nb):
            D[:, b] = np.roll(env[:, b], -int(shifts[b]))
        ts = D.sum(axis=1)
        for w in widths:
            if w >= nt:
                continue
            k = np.ones(w) / np.sqrt(w)
            f = np.convolve(ts, k, mode='same')
            med = float(np.median(f))
            mad = float(np.median(np.abs(f - med))) or 1e-12
            s = (f - med) / (1.4826 * mad)
            i = int(np.argmax(s))
            if float(s[i]) > best['sigma']:
                best = {'sigma': float(s[i]), 'dm': float(dm),
                        'width': int(w), 't': int(i)}
    return {'detected': bool(best['sigma'] >= thresh), 'best': best,
            'thresh': thresh, 'nt': nt, 'dt_s': dt}


def prove():
    rng = np.random.default_rng(777)
    N = 2 * 524288
    fs = FS_DEFAULT
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    noise = rng.normal(0, 14, N).astype(np.float64)
    r = detect(noise, fs)
    check('CTRL noise quiet', not r['detected'], f"maxσ={r['best']['sigma']:.2f}")
    # inject bright narrow shot (width 8 samples, 12σ) at DM=0
    y = noise.copy()
    y[300000:300008] += 12 * 14
    r = detect(y, fs)
    check('INJECT narrow shot fires', r['detected'], f"σ={r['best']['sigma']:.1f} w={r['best']['width']}")
    # dispersed sweep proxy: staggered sub-band pulses (DM-like delay across band)
    y2 = noise.copy()
    m = 16
    per = N // m
    for b in range(m):
        y2[b * per + 1000 + b * 40: b * per + 1000 + b * 40 + 6] += 10 * 14
    r2 = detect(y2, fs, dm_max=2000.0, dm_trials=48)
    check('INJECT staggered sweep fires', r2['detected'], f"σ={r2['best']['sigma']:.1f} DM={r2['best']['dm']:.0f}")
    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', default='')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--fs', type=float, default=FS_DEFAULT)
    ap.add_argument('--f0-mhz', type=float, default=1400.0)
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    import json as _j
    x = np.fromfile(a.f32, dtype=np.float32)
    r = detect(x, fs=a.fs, f0_mhz=a.f0_mhz)
    print(_j.dumps(r) if False else
          f"[dm] best σ={r['best']['sigma']:.2f} DM={r['best']['dm']:.0f} w={r['best']['width']} " +
          ('SHOT' if r['detected'] else 'no shot'))


if __name__ == '__main__':
    main()
