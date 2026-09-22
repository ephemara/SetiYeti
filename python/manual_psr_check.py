"""manual_psr_check.py - by-hand pulsar verification. No pipeline trust.

For each coarse-channel lane: square-law envelope -> FFT -> top peaks.
Then: which peak frequencies are COMMON across lanes (sky) vs lane-local
(electronics)? For the best common candidate: fold every lane, lag the
profiles against lane 0, fit lag vs nu^-2. DM >> 0 with small error =
astrophysical plasma. Zero lag = local hum. Numbers only.
Usage: python manual_psr_check.py --lanes data/mpsr_ch --chans 0,8,16,24,32,40,48,56 --f0-mhz 2587.5 --f1-mhz 2775.0
"""
import argparse, os
import numpy as np

FS = 2929687.5

def env_spectrum(x, fmin=1.0, fmax=100.0, top=10):
    env = (x * x).astype(np.float64)
    env -= env.mean()
    # downsample to 2 kHz envelope rate (plenty for <=100 Hz search)
    stride = int(FS / 2000)
    env = env[:len(env) // stride * stride].reshape(-1, stride).mean(axis=1)
    spec = np.abs(np.fft.rfft(env - env.mean())) ** 2
    fr = np.fft.rfftfreq(len(env), 1 / 2000.0)
    m = (fr >= fmin) & (fr <= fmax)
    idx = np.where(m)[0]
    order = idx[np.argsort(spec[idx])[::-1][:top]]
    med = np.median(spec[m])
    return [(float(fr[i]), float(spec[i] / med)) for i in order]

def fold(x, f_hz, nbins=32):
    t = np.arange(len(x)) / FS
    ph = ((t * f_hz) % 1.0 * nbins).astype(int)
    env = (x * x).astype(np.float64)
    prof = np.bincount(ph, weights=env, minlength=nbins)
    cnt = np.bincount(ph, minlength=nbins).astype(float) + 1e-9
    return prof / cnt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lanes', required=True)
    ap.add_argument('--chans', required=True)
    ap.add_argument('--f0-mhz', type=float, required=True)
    ap.add_argument('--f1-mhz', type=float, required=True)
    a = ap.parse_args()
    chans = [int(c) for c in a.chans.split(',')]
    lanes, freqs = [], []
    for c in chans:
        p = f'{a.lanes}{c}.f32'
        lanes.append(np.fromfile(p, dtype=np.float32))
        freqs.append(a.f0_mhz + (a.f1_mhz - a.f0_mhz) * c / 63.0)
    print(f'[man] {len(lanes)} lanes, N={len(lanes[0])} ({len(lanes[0])/FS:.2f}s each)')

    # 1. per-lane peaks + coincidence
    tops = [env_spectrum(x) for x in lanes]
    for c, t in zip(chans, tops):
        print(f"  ch{c:2d} ({freqs[chans.index(c)]:7.1f} MHz): " +
              ', '.join(f'{f:.2f}Hz@{s:.0f}s' for f, s in t[:5]))
    buckets = {}
    for t in tops:
        for f, s in t:
            key = round(f / 0.5) * 0.5
            buckets.setdefault(key, [0, 0.0])
            buckets[key][0] += 1
            buckets[key][1] = max(buckets[key][1], s)
    common = sorted(((k, v) for k, v in buckets.items() if v[0] >= 6),
                    key=lambda kv: -kv[1][1])
    print('[man] frequencies in >=6/8 lanes:',
          ', '.join(f'{k:.2f}Hz(n={v[0]},max={v[1]:.0f}s)' for k, v in common[:8])
          or 'NONE -- no common signal')
    if not common:
        print('[man] VERDICT: no broadband periodicity. File holds lane-local tones only.')
        return 0

    # 2. dispersion via SPECTRAL PHASE of the fundamental per lane.
    # Phase precision ~ 1/(2pi*SNR): at hundreds of sigma this resolves
    # milli-cycle lags. A DM above ~5 must tilt phase vs nu^-2 here.
    f0 = common[0][0]
    phases, snrs = [], []
    for x in lanes:
        env = (x * x).astype(np.float64)
        env -= env.mean()
        stride = int(FS / 2000)
        env = env[:len(env) // stride * stride].reshape(-1, stride).mean(axis=1)
        S = np.fft.rfft(env - env.mean())
        fr = np.fft.rfftfreq(len(env), 1 / 2000.0)
        i = int(np.argmin(abs(fr - f0)))
        phases.append(float(np.angle(S[i])))
        loc = np.median(np.abs(S[max(0, i - 50):i + 50]))
        snrs.append(float(abs(S[i]) / max(loc, 1e-12)))
    ph = np.unwrap(np.array(phases))  # radians
    x = np.array([(1 / (f / 1e3) ** 2) for f in freqs])
    A = np.vstack([x, np.ones_like(x)]).T
    slope, off = np.linalg.lstsq(A, ph, rcond=None)[0]
    pred = slope * x + off
    resid = float(np.std(ph - pred))
    dof = max(len(x) - 2, 1)
    se_slope = resid / max(float(np.sqrt(((x - x.mean()) ** 2).sum())), 1e-12)
    P_ms = 1000.0 / f0
    dm = slope / (2 * np.pi) * P_ms / 4.15
    dm_err = se_slope / (2 * np.pi) * P_ms / 4.15
    print(f'[man] candidate {f0:.2f} Hz per-lane phase (rad): ' +
          ' '.join(f'{v:+.3f}' for v in ph))
    print('[man] per-lane SNR: ' + ' '.join(f'{v:.0f}' for v in snrs))
    print(f'[man] nu^-2 phase slope={slope:+.4f}+/-{se_slope:.4f} rad/GHz^-2 '
          f'(t={slope / max(se_slope, 1e-12):+.2f}), residual={resid:.4f} rad '
          f'-> DM = {dm:+.1f}+/-{dm_err:.1f} pc/cm^3')
    # 3. amplitude stability across blocks (pulsar breathes, hum drones)
    segs = np.array_split(lanes[0], 8)
    amps = []
    for s in segs:
        p = fold(s, f0)
        amps.append(float(p.max() - p.min()))
    amps = np.array(amps)
    print(f'[man] ch{chans[0]} pulse amplitude per block: ' +
          ' '.join(f'{v:.3f}' for v in amps) +
          f' (CV={amps.std() / max(amps.mean(), 1e-12):.2f})')
    tstat = abs(slope) / max(se_slope, 1e-12)
    if tstat < 3:
        print(f'[man] VERDICT: slope consistent with zero (t={tstat:.2f}) -> '
              f'no measurable dispersion; DM = {dm:+.1f}+/-{dm_err:.1f}. '
              f'LOCAL electronics favored; astrophysical needs DM >> {dm_err:.0f}.')
    elif abs(dm) >= 5:
        print('[man] VERDICT: significant dispersed slope -> ASTROPHYSICAL. '
              'Follow up with full-band fold.')
    else:
        print('[man] VERDICT: ambiguous -- needs longer span / wider band.')
    return 0

if __name__ == '__main__':
    main()
