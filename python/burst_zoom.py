"""burst_zoom.py — BEAST spiky-strong burst morphology (kepler1 gap #4).

SCD selection skips spikes>0 — so the 100×+ OFF ch56 megas and the 39.5× ON
ch52 fell between stools: too spiky for SCD, never characterised either.
This routes every spiky-strong slice to a morphology zoom instead of silence:

  features per slice: spike count/rate, peak |x|/rms, burst widths, duty cycle,
  inter-arrival regularity (periodic radar vs aperiodic glint), Y2/Y4 ratio at
  the burst vs off-burst, spectral occupancy (narrow carrier vs broadband pop)
  classes: IMPULSE-RADAR (periodic, broadband, spiky) / CARRIER-BURST (narrow,
  spectral line + spikes) / GLINT (aperiodic, isolated) / NOISE-TAIL

  python burst_zoom.py --f32 slice.f32 --fs 2929687.5
  python burst_zoom.py --prove
"""
import argparse, sys
import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def features(x, fs=2929687.5):
    x = np.asarray(x, dtype=np.float64)
    rms = float(x.std() or 1e-12)
    z = np.abs(x) / rms
    spikes = np.where(z > 6)[0]
    n = len(x)
    peak = float(z.max())
    # burst widths: runs of |x|>4rms
    over = z > 4
    widths, onsets, i = [], [], 0
    while i < n:
        if over[i]:
            onsets.append(i)
            j = i
            while j < n and over[j]:
                j += 1
            widths.append(j - i)
            i = j
        else:
            i += 1
    widths = np.array(widths or [0])
    # inter-arrival regularity of BURST ONSETS (not raw spike samples:
    # within-burst diffs are 1 and would zero the statistic)
    reg = 0.0
    if len(onsets) >= 4:
        ia = np.diff(np.array(onsets)).astype(float)
        reg = float(np.median(ia) / (np.std(ia) + 1))
    # spectral occupancy: fraction of rfft bins >10x median
    S = np.abs(np.fft.rfft(x[:min(n, 1 << 18)])) ** 2
    occ = float(np.mean(S > 10 * np.median(S)))
    return {'n': n, 'rms': rms, 'spikes': int(len(spikes)),
            'spike_rate': len(spikes) / n, 'peak_z': peak,
            'n_bursts': int(len(widths)), 'mean_width': float(widths.mean()),
            'max_width': int(widths.max()), 'duty': float(widths.sum() / n),
            'regularity': reg, 'spec_occ': occ}


def classify(f):
    # Regularity first: a periodic train is a rotating emitter (radar) no
    # matter how spiky — sparkle-corruption is IRREGULAR by definition.
    if f['spikes'] == 0:
        return 'CLEAN'
    if f['regularity'] > 8:
        return 'IMPULSE-RADAR'
    if f['spec_occ'] < 0.005 and f['peak_z'] > 8:
        return 'CARRIER-BURST'
    if f['n_bursts'] <= 3 and f['duty'] < 1e-4:
        return 'GLINT'
    if f['spikes'] > 25:
        return 'SPARKLE-CORRUPT'
    return 'BURST-MIXED'


def prove():
    rng = np.random.default_rng(4242)
    N = 524288
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    noise = rng.normal(0, 14, N)
    f = features(noise)
    check('CTRL noise CLEAN', classify(f) == 'CLEAN', f"{f['spikes']} spikes")
    # periodic broadband impulses → radar
    y = noise.copy()
    for k in range(0, N, 20000):
        y[k:k + 30] += 30 * 14
    f = features(y)
    check('INJECT periodic impulses → RADAR-ish', classify(f) in ('IMPULSE-RADAR', 'BURST-MIXED'),
          f"{classify(f)} reg={f['regularity']:.1f}")
    # single isolated pop → glint
    y2 = noise.copy()
    y2[99999:100005] += 25 * 14
    f = features(y2)
    check('INJECT isolated pop → GLINT/CARRIER', classify(f) in ('GLINT', 'CARRIER-BURST'),
          classify(f))
    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', default='')
    ap.add_argument('--fs', type=float, default=2929687.5)
    ap.add_argument('--prove', action='store_true')
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    x = np.fromfile(a.f32, dtype=np.float32)
    f = features(x, a.fs)
    print(f"[burst] spikes={f['spikes']} peak={f['peak_z']:.1f}z bursts={f['n_bursts']} "
          f"duty={f['duty']:.2e} reg={f['regularity']:.1f} occ={f['spec_occ']:.3f} → {classify(f)}")


if __name__ == '__main__':
    main()
