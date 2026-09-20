"""jerk_scan.py - SetiYeti non-linear drift / jerk tracker (Viterbi track-before-detect).
Catches curved, parabolic, frequency-agile trajectories turboSETI's straight-line
matched filter misses. Method: STFT waterfall -> per-row robust z-scores ->
Viterbi DP over frequency states with +-k bins/row agility (accel/jerk-inclusive
by construction) -> traceback best path -> quad fit for (v, a) in Hz/s, Hz/s^2.
Usage:
  prove:  python jerk_scan.py --prove --root .
  real:   python jerk_scan.py --f32 data/full_ch32.f32 [--thresh T]
"""
import argparse, os, sys, time
import numpy as np

FS = 2929687.5

def stft_power(x, nfft, hop):
    # rectangular window: maximum coherent gain for faint tones (detection-first)
    nrows = (len(x)-nfft)//hop + 1
    P = np.empty((nrows, nfft//2+1), dtype=np.float32)
    for r in range(nrows):
        F = np.fft.rfft(x[r*hop:r*hop+nfft].astype(np.float32))
        P[r] = (F.real*F.real+F.imag*F.imag).astype(np.float32)
    return P

def robust_z(P, cap=6.0):
    med = np.median(P, axis=1, keepdims=True)
    mad = np.median(np.abs(P-med), axis=1, keepdims=True) + 1e-12
    Z = ((P-med)/(1.4826*mad)).astype(np.float32)
    # winsorize: single-bin RFI/noise spikes must not outvote a persistent track
    return np.clip(Z, -3.0, cap)

def viterbi(Z, k=2):
    R, B = Z.shape
    prev = Z[0].astype(np.float64)
    SH = np.empty((R, B), dtype=np.int8)
    SH[0] = 0
    NEG = -1e18
    S = np.arange(-k, k+1)
    for r in range(1, R):
        Pv = np.empty((len(S), B), dtype=np.float64)
        Pv[:] = NEG
        for i, s in enumerate(S):
            if s < 0: Pv[i, :s if s else B] = prev[-s:] if s else prev
            elif s > 0: Pv[i, s:] = prev[:-s]
            else: Pv[i] = prev
        ai = Pv.argmax(axis=0)
        SH[r] = (ai-k).astype(np.int8)
        prev = Z[r].astype(np.float64) + Pv[ai, np.arange(B)]
    f = np.empty(R, dtype=np.int32)
    f[-1] = int(prev.argmax())
    score = float(prev[f[-1]])/R
    for r in range(R-1, 0, -1):
        f[r-1] = f[r]-int(SH[r, f[r]])
        if f[r-1] < 0: f[r-1] = 0
        elif f[r-1] >= B: f[r-1] = B-1
    return f, score

def fit_motion(fbins, nfft, hop, fs):
    t = np.arange(len(fbins))*(hop/fs)
    fh = fbins.astype(np.float64)*(fs/nfft)
    p2 = np.polyfit(t, fh, 2)  # a2 t^2 + a1 t + a0
    p1 = np.polyfit(t, fh, 1)
    r2 = float(np.mean((np.polyval(p2, t)-fh)**2))
    r1 = float(np.mean((np.polyval(p1, t)-fh)**2))
    return {'jerk_hz_s2': 2*p2[0], 'drift_hz_s': p2[1], 'f0_hz': p2[2],
            'quad_res': r2, 'lin_res': r1,
            'curve_gain_db': 10*np.log10(max(r1,1e-9)/max(r2,1e-9))}

def sidereal_check(mo, freq_mhz=1407.7):
    """M5 Doppler-anomaly screen: is the fitted drift consistent with an
    Earth-bound transmitter? Max rotational Doppler rate ~ w^2*R*f/c:
    (7.27e-5)^2 * 6.4e6 * f / 3e8 ~= 0.16 Hz/s at L-band; bound 0.35 Hz/s
    scaled by frequency leaves margin for orbital + telescope motion.
    A transmitter OFF Earth (third-party link endpoints, orbiters) can sit
    far outside this. Screening only - attribution stays with the veto."""
    bound = 0.35 * (freq_mhz / 1407.7)
    v = mo['drift_hz_s']
    if abs(v) <= bound:
        return 'OK'
    return f'ANOMALOUS(|v|={v:+.1f}>bound {bound:.2f})'


def scan(x, nfft=32768, hop=16384, k=2, fs=FS, thresh=0.0, tag='',
         freq_mhz=1407.7):
    t0 = time.time()
    P = stft_power(x, nfft, hop)
    Z = robust_z(P)
    rowmax = float(Z.max())
    f, score = viterbi(Z, k)
    mo = fit_motion(f, nfft, hop, fs)
    dt = time.time()-t0
    sid = sidereal_check(mo, freq_mhz)
    verdict = 'CANDIDATE-track' if (thresh and score >= thresh) else ('clean' if thresh else 'scored')
    print(f'[{tag}] rows={Z.shape[0]} bins={Z.shape[1]} rowmax_z={rowmax:.2f} '
          f'track_score={score:.3f} v={mo["drift_hz_s"]:+.1f}Hz/s a={mo["jerk_hz_s2"]:+.2f}Hz/s^2 '
          f'curve_gain={mo["curve_gain_db"]:.1f}dB sidereal={sid} t={dt:.1f}s -> {verdict}', flush=True)
    return {'score': score, 'motion': mo, 'rowmax': rowmax, 'path': f,
            'sidereal': sid}

def synth_chirp(N, fs, f0, v, a, A, rng):
    t = np.arange(N)/fs
    ph = 2*np.pi*(f0*t + 0.5*v*t*t + (1.0/6.0)*a*t**3)
    return (A*np.cos(ph)).astype(np.float32)

def quantize(x):
    q = np.empty_like(x)
    q[x < -1.667] = -3.3359
    m = (x >= -1.667) & (x < 0); q[m] = -1.0
    m = (x >= 0) & (x < 1.667); q[m] = 1.0
    q[x >= 1.667] = 3.3359
    return q.astype(np.float32)

def prove(fs=FS, save_thresh=None):
    rng = np.random.default_rng(11)
    N = 16*1024*1024  # ~5.7 s
    nfft, hop = 32768, 16384
    A = 0.05  # per-row sub-noise; tune once from output
    print(f'[prove] N={N} A={A} (~{20*np.log10(A/np.sqrt(2)/2.07):.0f}dB total)')
    xn = quantize(rng.normal(0, 2.07, N).astype(np.float32))
    n = scan(xn, nfft, hop, fs=fs, tag='noise-only')
    # extra noise realizations: threshold must clear the max, not one draw
    nmax = n['score']
    for s in range(2):
        xn2 = quantize(rng.normal(0, 2.07, N).astype(np.float32))
        r2 = scan(xn2, nfft, hop, fs=fs, tag=f'noise-cal{s}')
        nmax = max(nmax, r2['score'])
    xl = quantize(rng.normal(0, 2.07, N).astype(np.float32)
                  + synth_chirp(N, fs, 500e3, 40.0, 0.0, A, rng))
    L = scan(xl, nfft, hop, fs=fs, tag='linear 40Hz/s')
    xp = quantize(rng.normal(0, 2.07, N).astype(np.float32)
                  + synth_chirp(N, fs, 700e3, 10.0, 18.0, A, rng))
    P = scan(xp, nfft, hop, fs=fs, tag='parabolic a=18')
    th = nmax*1.25
    print(f'[prove] noise_max={nmax:.3f} thresh={th:.3f} | '
          f'linear={L["score"]:.3f} (v_fit={L["motion"]["drift_hz_s"]:+.1f}) | '
          f'parab={P["score"]:.3f} (a_fit={P["motion"]["jerk_hz_s2"]:+.1f})')
    ok = L['score'] > th and P['score'] > th and abs(L['motion']['drift_hz_s']-40) < 15 \
        and abs(P['motion']['jerk_hz_s2']-18) < 12
    print('[prove] ' + ('PASS: sub-row-noise drift+parabola recovered, params agree'
                        if ok else 'TUNE: adjust A/thresh'))
    if save_thresh:
        try:
            with open(save_thresh, 'w') as f:
                f.write(f'{th:.4f}\n')
            print(f'[prove] threshold {th:.4f} saved -> {save_thresh}')
        except OSError as e:
            print(f'[prove] WARNING: could not save threshold ({e})')
    return th

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', default='')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--nfft', type=int, default=32768)
    ap.add_argument('--hop', type=int, default=16384)
    ap.add_argument('--k', type=int, default=2)
    ap.add_argument('--thresh', type=float, default=0.0)
    ap.add_argument('--load-thresh', default='',
                    help='file holding a prove threshold (written by --save-thresh); '
                         'beats the default 0.0 only when --thresh is unset')
    ap.add_argument('--save-thresh', default='',
                    help='prove mode: persist the calibrated threshold here')
    ap.add_argument('--fs', type=float, default=None,
                    help='sample rate Hz (default: 2929687.5)')
    ap.add_argument('--freq-mhz', type=float, default=1407.7,
                    help='channel sky frequency for the sidereal-drift screen')
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    fs = a.fs if a.fs else FS
    thresh = a.thresh
    if not thresh and a.load_thresh:
        try:
            thresh = float(open(a.load_thresh).read().strip().split()[0])
            print(f'[thresh] loaded {thresh:.4f} from {a.load_thresh}')
        except (OSError, ValueError) as e:
            print(f'[thresh] WARNING: {e}; running unscored')
    if a.prove:
        prove(fs=fs, save_thresh=a.save_thresh or None)
    else:
        x = np.fromfile(a.f32, dtype=np.float32)
        print(f'[in] n={len(x)} ({len(x)/fs:.2f}s)', flush=True)
        scan(x, a.nfft, a.hop, a.k, fs, thresh, tag=os.path.basename(a.f32),
             freq_mhz=a.freq_mhz)

if __name__ == '__main__':
    main()
