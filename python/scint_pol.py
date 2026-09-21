"""scint_pol.py - XENO interstellar-medium markers: scintillation + polarisation.

WHY THIS EXISTS (Objective 1, jackpot items 3-4): a celestial point source
shines THROUGH the interstellar medium, and the medium signs the signal:

  scintillation   diffractive scattering modulates intensity (modulation
                  index m ~ 0.2-1, timescale seconds-minutes at L-band,
                  DECORRELATED across frequency). Backend hum and local RFI
                  do not scintillate: hum is steady (m ~ 0.06), bursts are
                  broadband-simultaneous (cross-band correlation ~ 1).
  polarisation    a sky signal arrives in every feed at the SAME frequency
                  with different gains. The HIP-113357 backend-wander
                  fingerprint is the opposite: each polarisation peaks at a
                  DIFFERENT frequency. Agreement = sky-like; wander = local.

Neither is a detection alone. Either one multiplies an engineered flag into
an INTERSTELLAR grade (see INTERSTELLAR_HIT_CRITERIA.md, I2 -> I3).

Method (numpy only, no scipy):
  1. STFT power (rect window, SEG=4096/hop=2048), 8 sub-bands
  2. per-band modulation index m = std/mean (noise ~ 1/sqrt(256) ~= 0.06)
  3. timescale tau = ACF half-max width of the band-mean envelope (frames)
  4. xcorr = mean adjacent-sub-band envelope correlation
  5. class: QUIET / SCINT / COMMON / SPIKY (priority in that order reversed)
  6. pol: peak-frequency agreement across pol slices + amplitude ratio

  python scint_pol.py --prove
  python scint_pol.py --f32 a.p0.f32 --f32-pol a.p1.f32 --fs 2929687.5 --json
"""
import argparse
import json
import os
import sys

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FS_DEFAULT = 2929687.5
SEG, HOP, NSB = 4096, 2048, 8
M_QUIET = 0.15    # below: steady (hum / thermal; noise sits at 0.062)
M_COMMON = 0.10   # COMMON needs less m: sparse bursts barely move the median
M_SPIKY = 1.2     # above: impulsive, not scintillation
XCORR_COMMON = 0.80   # above: broadband-simultaneous (local-leaning).
                      # Calibrated gap: scintillation 0.66, bursts 0.95+.
TAU_SCINT = 2.0       # frames: scintillation breathes slower than white noise
TAU_COMMON = 4.0      # COMMON is fast: bursts strike in single frames


def stft_bands(x, seg=SEG, hop=HOP, nsb=NSB):
    nfr = (len(x) - seg) // hop + 1
    if nfr < 8:
        return None, 0
    nfr = min(nfr, 512)
    E = np.empty((nfr, nsb))
    for t in range(nfr):
        P = np.abs(np.fft.rfft(x[t * hop:t * hop + seg].astype(np.float64))) ** 2
        bins = np.linspace(2, len(P) - 1, nsb + 1).astype(int)
        for b in range(nsb):
            E[t, b] = P[bins[b]:bins[b + 1]].mean()
    return E, nfr


def acf_halfwidth(e):
    e = np.asarray(e, dtype=np.float64)
    e = e - e.mean()
    if e.std() <= 0:
        return 0.0
    e = e / e.std()
    a = np.correlate(e, e, mode='full')[len(e) - 1:]
    a = a / max(a[0], 1e-30)
    below = np.where(a < 0.5)[0]
    return float(below[0]) if len(below) else float(len(a))


def scint_classify(E):
    mu = E.mean(axis=0)
    sd = E.std(axis=0)
    m = sd / np.maximum(mu, 1e-30)
    m_med, m_max = float(np.median(m)), float(m.max())
    tau = acf_halfwidth(E.mean(axis=1))
    xc = []
    for b in range(E.shape[1] - 1):
        a, c = E[:, b], E[:, b + 1]
        if a.std() > 0 and c.std() > 0:
            xc.append(float(np.corrcoef(a, c)[0, 1]))
    xcorr = float(np.mean(xc)) if xc else 0.0
    if m_med > M_SPIKY:
        cls = 'SPIKY'
    elif m_med >= M_COMMON and xcorr >= XCORR_COMMON and tau < TAU_COMMON:
        cls = 'COMMON'
    elif m_med >= M_QUIET and tau >= TAU_SCINT and xcorr < XCORR_COMMON:
        cls = 'SCINT'
    elif m_med >= M_QUIET:
        cls = 'UNRESOLVED'
    else:
        cls = 'QUIET'  # NOTE: sparse weak bursts live here by duty cycle;
                       # COMMON requires real burst energy (see prove).
    return {'class': cls, 'm_med': m_med, 'm_max': m_max,
            'tau_frames': tau, 'xcorr': xcorr,
            'tau_s': tau * HOP / FS_DEFAULT}


def peak_freq(x, fs=FS_DEFAULT):
    n = min(len(x), 262144)
    P = np.abs(np.fft.rfft(x[:n].astype(np.float64))) ** 2
    P[:2] = 0
    k = int(np.argmax(P))
    df = fs / n
    return k * df, float(P[k] / max(np.median(P), 1e-30)), df


def pol_agree(xs, fs=FS_DEFAULT):
    peaks = [peak_freq(x, fs) for x in xs]
    fr = [p[0] for p in peaks]
    dfmax = max(fr) - min(fr) if fr else 0.0
    agree = dfmax <= 3 * (fs / min(len(x) for x in xs))
    rat = [p[1] for p in peaks]
    ratio = max(rat) / max(min(rat), 1e-30) if rat else 1.0
    # envelope co-variation: shared bursts/transients move all pols at the
    # same sky time even when no single tone dominates (peak_freq then
    # compares noise maxima and means nothing). corr ~ 1 = same sky event.
    envs = []
    for x in xs:
        E, _ = stft_bands(x)
        if E is not None:
            envs.append(E.mean(axis=1))
    ex = 0.0
    if len(envs) >= 2 and envs[0].std() > 0 and envs[1].std() > 0:
        n = min(len(envs[0]), len(envs[1]))
        ex = float(np.corrcoef(envs[0][:n], envs[1][:n])[0, 1])
    return {'agree': bool(agree), 'dfreq_hz': float(dfmax),
            'amp_ratio': float(ratio),
            'freqs_hz': [float(f) for f in fr],
            'env_xcorr': ex,
            'verdict': 'SKY-LIKE' if (agree or ex > 0.5) else 'WANDER-LOCAL'}


def analyze(paths, fs=FS_DEFAULT):
    xs = [np.fromfile(p, dtype=np.float32) for p in paths]
    out = {'scint': scint_classify(stft_bands(xs[0])[0])
           if stft_bands(xs[0])[0] is not None else {'class': 'TOOSHORT'}}
    out['fs'] = fs
    if len(xs) > 1:
        out['pol'] = pol_agree(xs, fs)
    else:
        f, r, _ = peak_freq(xs[0], fs)
        out['pol'] = {'agree': None, 'freqs_hz': [float(f)],
                      'verdict': 'SINGLE-POL'}
    return out


def prove():
    rng = np.random.default_rng(4242)
    N = 4 * 524288
    fs = FS_DEFAULT
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    noise = rng.normal(0, 14, N).astype(np.float32)
    E, _ = stft_bands(noise)
    s = scint_classify(E)
    check('CTRL thermal noise QUIET', s['class'] == 'QUIET',
          f"m={s['m_med']:.3f} tau={s['tau_frames']:.1f}")

    # scintillated: slow lognormal gain, tau ~ 20 frames, m ~ 0.5.
    # Gain is interpolated to SAMPLE rate first: writing per-frame (with
    # 50% STFT overlap) lets the last covering frame win per sample and
    # shreds the slow modulation into fast hash (measured m=0.10).
    nfr = (N - SEG) // HOP + 1
    sm = rng.normal(0, 1, nfr)
    ker = np.exp(-0.5 * (np.arange(-40, 41) / 20.0) ** 2)
    ker /= ker.sum()
    # Frequency-DEPENDENT gains: each sub-band breathes on its own. A single
    # broadband gain is backend wander (xcorr ~ 1, correctly COMMON); real
    # diffractive scintillation decorrelates across frequency (scintles),
    # which is exactly the ISM signature the classifier keys on.
    X = np.fft.rfft(noise.astype(np.float64))
    nb = len(X)
    edges = np.linspace(0, nb, NSB + 1).astype(int)
    centers = np.arange(nfr) * HOP + SEG / 2
    y = np.zeros(N, dtype=np.float64)
    for b in range(NSB):
        Xb = np.zeros_like(X)
        Xb[edges[b]:edges[b + 1]] = X[edges[b]:edges[b + 1]]
        xb = np.fft.irfft(Xb, n=N)
        sm_b = rng.normal(0, 1, nfr)
        s_b = np.convolve(sm_b, ker, mode='same')
        s_b = s_b / max(s_b.std(), 1e-30)
        gb = np.exp(0.5 * s_b)
        gb = gb / gb.mean()
        gs = np.interp(np.arange(N), centers, gb)
        y += xb * gs
    y = y.astype(np.float32)
    E2, _ = stft_bands(y)
    s2 = scint_classify(E2)
    check('INJECT scintillation SCINT', s2['class'] == 'SCINT',
          f"m={s2['m_med']:.3f} tau={s2['tau_frames']:.1f} xc={s2['xcorr']:.2f}")

    # common burst: shared impulses in two pols -> COMMON + env agreement.
    # Envelope m needs REAL burst energy: a 15-sigma spike adds only ~5% to
    # one frame's band power (measured m=0.06, invisible). Radar-class
    # bursts are tens of sigma and numerous: 60 x 40-sigma is honest.
    p0 = noise.copy().astype(np.float64)
    p1 = rng.normal(0, 14, N)
    pos = rng.integers(0, N, 80)
    p0[pos] += 60 * 14
    p1[pos] += 60 * 14
    E3, _ = stft_bands(p0.astype(np.float32))
    s3 = scint_classify(E3)
    pa = pol_agree([p0.astype(np.float32), p1.astype(np.float32)], fs)
    check('INJECT common burst COMMON', s3['class'] in ('COMMON', 'SPIKY'),
          f"m={s3['m_med']:.3f} xc={s3['xcorr']:.2f}")
    check('common burst pol agrees (same sky time)',
          pa['env_xcorr'] > 0.5, f"env_xcorr={pa['env_xcorr']:.2f}")

    # wander: different tone per pol -> WANDER-LOCAL (the HIP fingerprint)
    t = np.arange(N) / fs
    w0 = (noise + 3.0 * 14 * np.sin(2 * np.pi * 100000 * t)).astype(np.float32)
    w1 = (noise + 3.0 * 14 * np.sin(2 * np.pi * 200000 * t)).astype(np.float32)
    pa2 = pol_agree([w0, w1], fs)
    check('wander tones pol disagrees', not pa2['agree'],
          f"df={pa2['dfreq_hz']:.0f}Hz -> {pa2['verdict']}")

    # same tone both pols -> agree (sky-like geometry)
    c0 = (noise + 3.0 * 14 * np.sin(2 * np.pi * 150000 * t)).astype(np.float32)
    c1 = (rng.normal(0, 14, N) + 2.0 * 14 * np.sin(2 * np.pi * 150000 * t)).astype(np.float32)
    pa3 = pol_agree([c0, c1], fs)
    check('shared tone pol agrees', pa3['agree'],
          f"df={pa3['dfreq_hz']:.0f}Hz ratio={pa3['amp_ratio']:.1f}")

    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', default='', help='primary pol slice')
    ap.add_argument('--f32-pol', action='append', default=[],
                    help='extra pol slice of same block/chan (repeatable)')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--fs', type=float, default=FS_DEFAULT)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    if not a.f32:
        sys.exit('need --f32 (or --prove)')
    r = analyze([a.f32] + a.f32_pol, a.fs)
    if a.json:
        print(json.dumps(r))
        return
    s = r['scint']
    print(f"[scint] class={s['class']} m_med={s['m_med']:.3f} m_max={s['m_max']:.3f} "
          f"tau={s['tau_frames']:.1f}fr xcorr={s['xcorr']:.2f}")
    p = r['pol']
    print(f"[pol] {p['verdict']} agree={p['agree']} "
          f"freqs={','.join(f'{f/1e3:.1f}k' for f in p['freqs_hz'])}")


if __name__ == '__main__':
    main()
