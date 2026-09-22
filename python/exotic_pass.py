"""exotic_pass.py - XENO bizarre-physics hunters: signals cold plasma forbids.

WHY THIS EXISTS: every mainstream pipeline assumes the interstellar medium is
cold plasma and every transmitter obeys it. Anything that does NOT is either
an instrument artifact (most of the time) or genuinely new physics / engineering
beyond the current paradigm. These five tests hunt exactly that class, with
thresholds calibrated to sit above instrumental slop:

  NEGDM     negative dispersion: low frequencies arrive FIRST. Cold plasma
            delays low frequencies (dt ~ DM/f^2, always positive). A
            significant NEGATIVE delay is superluminal group velocity,
            a matched-filter echo ... or a transmitter pre-compensating
            for the ISM (which is itself an engineered marker). Flag only
            |DM| > 50 (cables/filters live below DM ~ 0.1) with r^2 >= 0.8.
  CLOCK     period stability across halves: same-bin in both halves at high
            sigma. A hum is also stable - stability is reported, never
            interpreted; the veto + context decide. The killer app is
            stability ACROSS observations (monument repeat).
  LADDER    cepstral comb (independent numpy re-implementation of the C
            xeno_scan marker; two codes, one physics).
  PRIMES    pulse intervals that are prime multiples of a base (2,3,5,7,11...
            is not a magnetar glitch rhythm; 2,4,8,16 is machinery).
  PRECURSOR energy BEFORE the main pulse (non-causal echo / reflection
            geometry worth escalating, never auto-explaining).

  python exotic_pass.py --prove
  python exotic_pass.py --f32 ch.f32 --fs 2929687.5 --f0-mhz 1407.7 --json
"""
import argparse
import json
import sys

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FS_DEFAULT = 2929687.5
K_DM = 4.15e-3        # s * DM * (GHz^-2), cold-plasma constant
DM_R2 = 0.80
DM_SPAN_FR = 4.0
DM_EXOTIC = 50.0      # |DM| above this is no cable, no filter
LADDER_FLAG = 20.0    # shared calibration with c/xeno_scan.c
PRIMES_SET = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
              53, 59, 61, 67, 71, 73, 79, 83, 89, 97)


def _stft_env(x, seg=4096, hop=2048, nsb=8):
    nfr = (len(x) - seg) // hop + 1
    if nfr < 8:
        return None
    nfr = min(nfr, 512)
    E = np.empty((nfr, nsb))
    for t in range(nfr):
        P = np.abs(np.fft.rfft(x[t * hop:t * hop + seg].astype(np.float64))) ** 2
        bins = np.linspace(2, len(P) - 1, nsb + 1).astype(int)
        for b in range(nsb):
            E[t, b] = P[bins[b]:bins[b + 1]].mean()
    fcent = [(bins[b] + bins[b + 1]) / 2 * (FS_DEFAULT / seg) for b in range(nsb)]
    return E, fcent


def negdm(x, fs=FS_DEFAULT, f0_mhz=1407.7, bw_mhz=2.9296875):
    """Arrival-order fit -> equivalent DM. Negative = forbidden."""
    r = _stft_env(x)
    if r is None:
        return {'flag': 0, 'reason': 'too short'}
    E, _ = r
    nfr, nsb = E.shape
    f_edges = np.linspace(f0_mhz - bw_mhz / 2, f0_mhz + bw_mhz / 2, nsb + 1)
    fc = (f_edges[:-1] + f_edges[1:]) / 2.0  # MHz
    tt = np.array([float(np.argmax(E[:, b])) for b in range(nsb)])
    A = np.vstack([fc, np.ones(nsb)]).T
    sol, res, _, _ = np.linalg.lstsq(A, tt, rcond=None)
    slope_fr_mhz, _ = sol
    pred = A @ sol
    ss = float(((tt - tt.mean()) ** 2).sum())
    r2 = float(1 - ((tt - pred) ** 2).sum() / ss) if ss > 0 else 0.0
    span = float(tt.max() - tt.min())
    # slope: frames/MHz -> s/GHz
    dt_row = 2048 / fs
    slope_s_GHz = slope_fr_mhz * dt_row * 1000.0
    f0_ghz = f0_mhz / 1000.0
    dm = slope_s_GHz / (K_DM * -2.0 * f0_ghz ** -3)
    flag = 0
    kind = 'quiet'
    if r2 >= DM_R2 and span >= DM_SPAN_FR:
        if dm <= -DM_EXOTIC:
            flag, kind = 1, 'EXOTIC-NEGDM'
        elif dm >= DM_EXOTIC:
            flag, kind = 0, 'normal-dispersion'
        else:
            kind = 'small-delay'
    return {'flag': flag, 'kind': kind, 'dm_eq': float(dm), 'r2': r2,
            'span_fr': span}


def _env_peak(env, fmin=1.0, fmax=2000.0, env_fs=6000.0):
    e = np.asarray(env, dtype=np.float64)
    e = (e - e.mean()) * np.hanning(len(e))
    nfft = int(2 ** np.ceil(np.log2(max(len(e) * 4, 16))))
    P = np.abs(np.fft.rfft(e, n=nfft)) ** 2
    df = env_fs / nfft
    i0 = max(2, int(np.ceil(fmin / df)))
    i1 = min(len(P) - 1, int(np.floor(fmax / df)))
    if i1 <= i0:
        return 0.0, 0.0, df
    seg = P[i0:i1 + 1]
    med = float(np.median(seg))
    k = int(np.argmax(seg))
    sig = float(seg[k] / max(med, 1e-30))
    return (i0 + k) * df, sig, df


def clock(x, fs=FS_DEFAULT):
    """Same-bin period in both halves at high sigma = clock-grade stable."""
    dec = max(1, int(round(fs / 6000.0)))
    n = (len(x) // dec) * dec
    env = (x[:n].astype(np.float64) ** 2).reshape(-1, dec).mean(axis=1)
    h = len(env) // 2
    f1, s1, df = _env_peak(env[:h])
    f2, s2, _ = _env_peak(env[h:])
    stable = (s1 > 10.0 and s2 > 10.0 and abs(f1 - f2) <= df / 2
              and f1 > 0)
    qbound = f1 / max(df, 1e-30) if stable else 0.0
    return {'flag': 1 if stable else 0,
            'kind': 'CLOCK-STABLE' if stable else 'quiet',
            'f1_hz': float(f1), 'f2_hz': float(f2),
            'sig1': float(s1), 'sig2': float(s2),
            'q_lower_bound': float(qbound)}


def ladder(x, seg=4096):
    # Same estimator as c/xeno_scan.c (mean spectrum over segments, log,
    # quefrency FFT) written independently: a single-slice spectrum has
    # 2-DOF chi-squared ripple that buries the floor (measured ratio 18 on
    # a ladder that scores 113 averaged). Two codes, one physics.
    n = (min(len(x), 524288) // seg) * seg
    if n < seg * 4:
        return {'flag': 0, 'kind': 'too short', 'ratio': 0.0, 'q': 0}
    A = np.abs(np.fft.rfft(x[:n].astype(np.float64).reshape(-1, seg),
                           axis=1)) ** 2
    avg = A.mean(axis=0)[:2048]
    med = float(np.median(avg[2:]))
    L = np.log(avg / max(med, 1e-30) + 1e-30)
    # Whiten in QUEFRENCY (same estimator as c/xeno_scan.c, independent
    # code): shelves are smooth in q and divide out under a wide (+-60)
    # running median; comb lines are narrow and survive at any spacing.
    # denom is floored at the global median - cepstral nulls near zero
    # would otherwise manufacture ratios of 1000+ (measured, fixed).
    # Whitening in frequency instead blinds wide combs (measured, reverted).
    C = np.abs(np.fft.rfft(L)) ** 2
    band = C[10:701]
    m2 = float(np.median(band))
    try:
        from scipy.ndimage import median_filter
        bg = median_filter(band, size=121, mode='nearest')
    except Exception:
        bg = np.array([np.median(band[max(0, i - 60):i + 61])
                       for i in range(len(band))])
    denom = np.maximum(bg, max(m2, 1e-30))
    part = band / denom
    q = int(np.argmax(part)) + 10
    return {'flag': 1 if float(part.max()) >= LADDER_FLAG else 0,
            'kind': 'LADDER' if float(part.max()) >= LADDER_FLAG else 'quiet',
            'ratio': float(part.max()), 'q': q}


def _pulses(env, sigma=6.0, min_sep=3):
    med = float(np.median(env))
    mad = float(np.median(np.abs(env - med))) or 1e-12
    z = (env - med) / (1.4826 * mad)
    idx = np.where(z > sigma)[0]
    if len(idx) == 0:
        return []
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= min_sep:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    return [float(np.mean(g)) for g in groups]


def primes(x, fs=None):
    blk = 256
    n = (len(x) // blk) * blk
    env = np.abs(x[:n].astype(np.float64)).reshape(-1, blk).mean(axis=1)
    c = _pulses(env)
    if len(c) < 4:
        return {'flag': 0, 'kind': 'quiet', 'n_pulses': len(c),
                'score': 0.0, 'base': 0.0, 'intervals': []}
    iv = np.diff(np.array(c))
    if float(iv.min()) <= 0 or len(iv) < 3:
        return {'flag': 0, 'kind': 'quiet', 'n_pulses': len(c),
                'score': 0.0, 'base': 0.0, 'intervals': [float(v) for v in iv]}
    # The fundamental is NOT the minimum: [2,3,5,7,11]xP has min 2P, and
    # ratios to 2P are half-integers. Search base = min/k (k = 1..12) and
    # take the best prime-lock fraction - this finds the GCD honestly.
    best_score, best_base = 0.0, float(iv.min())
    for k in range(1, 13):
        base = float(iv.min()) / k
        locked = 0
        for v in iv:
            r = v / base
            n = int(round(r))
            if abs(r - n) / max(n, 1) < 0.03 and n in PRIMES_SET:
                locked += 1
        s = locked / len(iv)
        if s > best_score:
            best_score, best_base = s, base
    # PRIME-GUARD (hum-locked numerology confounder, filed 2026-09-21):
    # pulse pickers trace hum cycles, so intervals come out as multiples of
    # the hum period and base=min/k manufactures a prime lock (measured:
    # 31.5-bin intervals x 87us = 2.75ms ~= half the 179 Hz period, 9/9 lock
    # on pure hum). If the winning base frequency sits within 4% of a small
    # integer multiple of 89.5 Hz, the lock is hum numerology, not code:
    # reported, never escalated.
    hum_lock = False
    # base is in envelope blocks (256 samples); convert to Hz with fs.
    # Without a sample rate the guard cannot evaluate and is skipped.
    if best_score >= 0.8 and best_base > 0 and fs:
        base_freq = fs / (best_base * blk)
        for mult in range(1, 9):
            if abs(base_freq - mult * 89.5) / (mult * 89.5) < 0.04:
                hum_lock = True
                break
    if hum_lock:
        return {'flag': 0, 'kind': 'PRIME-HUM-LOCK', 'score': float(best_score),
                'n_pulses': len(c), 'intervals': [float(v) for v in iv],
                'base': float(best_base)}
    flag = 1 if best_score >= 0.8 else 0
    return {'flag': flag,
            'kind': 'PRIME-TRAIN' if flag else 'quiet',
            'score': float(best_score), 'n_pulses': len(c),
            'intervals': [float(v) for v in iv], 'base': float(best_base)}


def precursor(x):
    blk = 256
    n = (len(x) // blk) * blk
    env = np.abs(x[:n].astype(np.float64)).reshape(-1, blk).mean(axis=1)
    med = float(np.median(env))
    mad = float(np.median(np.abs(env - med))) or 1e-12
    z = (env - med) / (1.4826 * mad)
    pk = int(np.argmax(z))
    if float(z[pk]) < 10.0:
        return {'flag': 0, 'kind': 'quiet', 'peak_sigma': float(z[pk])}
    # Peak-hold, not median: a median over the pre-window dilutes a narrow
    # echo with clean sky (measured 0.20 vs a 0.30 gate). Noise max-hold over
    # ~10 blocks sits at ~0.04 of a 12-sigma main pulse: 7x margin holds.
    lo, hi = max(0, pk - 12), max(0, pk - 2)
    pre = float(env[lo:hi].max()) if hi > lo else med
    ratio = (pre - med) / max(float(env[pk]) - med, 1e-30)
    flag = 1 if ratio > 0.3 else 0
    return {'flag': flag,
            'kind': 'PRECURSOR' if flag else 'quiet',
            'echo_ratio': float(ratio), 'peak_sigma': float(z[pk])}


def analyze(x, fs=FS_DEFAULT, f0_mhz=1407.7):
    out = {'negdm': negdm(x, fs, f0_mhz),
           'clock': clock(x, fs),
           'ladder': ladder(x),
           'primes': primes(x, fs),
           'precursor': precursor(x)}
    out['exotic_score'] = sum(1 for k in out if out[k].get('flag'))
    return out


def prove():
    rng = np.random.default_rng(31337)
    N = 524288
    fs = FS_DEFAULT
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    noise = rng.normal(0, 14, N).astype(np.float32)
    a = analyze(noise)
    check('CTRL noise exotic-quiet', a['exotic_score'] == 0,
          f"score={a['exotic_score']}")

    # descending chirp (high-first) = normal plasma order, huge +DM
    t = np.arange(N) / fs
    ph = 2 * np.pi * (1400000.0 * t - 1300000.0 * t * t / (2 * N / fs))
    dn = (noise + 25 * np.sin(ph)).astype(np.float32)
    ad = analyze(dn)
    check('down-chirp normal dispersion', ad['negdm']['kind'] == 'normal-dispersion',
          f"DM={ad['negdm']['dm_eq']:.0f} r2={ad['negdm']['r2']:.2f}")

    # ascending chirp (low-first) = EXOTIC negative DM
    ph2 = 2 * np.pi * (100000.0 * t + 1300000.0 * t * t / (2 * N / fs))
    up = (noise + 25 * np.sin(ph2)).astype(np.float32)
    au = analyze(up)
    check('up-chirp EXOTIC negDM', au['negdm']['flag'] == 1,
          f"DM={au['negdm']['dm_eq']:.0f} r2={au['negdm']['r2']:.2f}")

    # stable tone = clock-grade; drifted tone = not
    st = (noise + 2.0 * 14 * np.sin(2 * np.pi * 179.0 * t)).astype(np.float32)
    ac = analyze(st)
    check('stable 179 Hz CLOCK', ac['clock']['flag'] == 1,
          f"Q>{ac['clock']['q_lower_bound']:.0f}")
    ph3 = 2 * np.pi * (179.0 * t + 3.0 * t * t / (N / fs))
    dr = (noise + 2.0 * 14 * np.sin(ph3)).astype(np.float32)
    ad2 = analyze(dr)
    check('drifted tone not clock', ad2['clock']['flag'] == 0,
          f"f1={ad2['clock']['f1_hz']:.2f} f2={ad2['clock']['f2_hz']:.2f}")

    # tone ladder = comb
    lad = noise.copy()
    for k in range(1, 6):
        lad = lad + 6.0 * np.sin(2 * np.pi * 100000.0 * k * t)
    al = analyze(lad.astype(np.float32))
    check('5-tone ladder fires', al['ladder']['flag'] == 1,
          f"ratio={al['ladder']['ratio']:.1f}")

    # prime-interval pulse train vs machinery rhythm
    def train(intervals, P=58594, amp=8.0):
        v = rng.normal(0, 14, N)
        pos = 20000
        for m in intervals:
            pos += int(m * P)
            if pos + 400 >= N:
                break
            w = np.exp(-0.5 * (np.arange(-200, 200) / 60.0) ** 2)
            v[pos - 200:pos + 200] += amp * 14 * w
        return v.astype(np.float32)
    ap = analyze(train([2, 3, 5, 7, 11], P=15000))
    check('prime train 2-3-5-7-11 fires', ap['primes']['flag'] == 1,
          f"score={ap['primes']['score']:.2f}")
    # hum-locked numerology must NOT escalate: base 8192 samples @2.93 MHz
    # = 2.80 ms ~= half the 179 Hz period -> manufactured prime lock.
    ah = analyze(train([2, 3, 5, 7, 11], P=8192))
    check('hum-period train held (PRIME-HUM-LOCK)',
          ah['primes']['flag'] == 0 and ah['primes']['kind'] == 'PRIME-HUM-LOCK',
          f"kind={ah['primes']['kind']} score={ah['primes']['score']:.2f}")
    am = analyze(train([2, 4, 8, 16]))
    check('machinery 2-4-8-16 quiet', am['primes']['flag'] == 0,
          f"score={am['primes']['score']:.2f}")

    # precursor echo vs lone pulse
    def shot(pre=False):
        v = rng.normal(0, 14, N)
        pk = N // 2
        w = np.exp(-0.5 * (np.arange(-200, 200) / 60.0) ** 2)
        v[pk - 200:pk + 200] += 12 * 14 * w
        if pre:
            v[pk - 1200 - 200:pk - 1200 + 200] += 6 * 14 * w
        return v.astype(np.float32)
    ae = analyze(shot(pre=True))
    check('precursor echo fires', ae['precursor']['flag'] == 1,
          f"echo={ae['precursor']['echo_ratio']:.2f}")
    an = analyze(shot(pre=False))
    check('lone pulse no precursor', an['precursor']['flag'] == 0,
          f"echo={an['precursor']['echo_ratio']:.2f}")

    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', default='')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--fs', type=float, default=FS_DEFAULT)
    ap.add_argument('--f0-mhz', type=float, default=1407.7)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    x = np.fromfile(a.f32, dtype=np.float32)
    r = analyze(x, a.fs, a.f0_mhz)
    if a.json:
        print(json.dumps(r))
        return
    for k in ('negdm', 'clock', 'ladder', 'primes', 'precursor'):
        v = r[k]
        det = {k2: (round(v2, 3) if isinstance(v2, float) else v2)
               for k2, v2 in v.items() if k2 not in ('intervals',)}
        print(f"[{k}] {v['kind']} {det}")
    print(f"[exotic] score={r['exotic_score']}/5")


if __name__ == '__main__':
    main()
