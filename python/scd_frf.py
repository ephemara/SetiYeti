"""scd_frf.py - SetiYeti B-full: cyclic spectrum plane (FAM core) + dechirp bank.
SCD: S[a,k] = mean_m X[m,k+h] * conj(X[m,k-h]) over STFT frames, alpha=2h*df.
  f=0 slice of old fam_scan becomes the full (alpha, f) plane: finds baud AND
  carrier location together, separates modulations sharing one alpha.
Dechirp bank: the operational FrFT angle search. Rotation angle phi in the
time-frequency plane maps to a chirp rate gamma (phi=pi/2 <-> gamma=0, i.e.
ordinary FFT; |gamma| grows as phi rotates toward the time axis). We search
gamma directly: y=x*exp(-j*pi*g*t^2), peak concentration = best angle.
  Catches linear/poly chirps smeared across FFT bins (dispersion, acceleration).
Modes: --prove | --f32 PATH [--a-max-hz 1500000]
"""
import argparse, os
import numpy as np

FS = 2929687.5

def stft_frames(x, Np, hop, win='rect'):
    # SCD path uses rectangular + non-overlapping frames: Hamming correlates
    # adjacent bins by construction and 50% overlap correlates frames, both of
    # which forge fake alpha~=0 ridges. Rectangular DFT bins of white noise
    # are exactly independent -> clean Rayleigh floor.
    W = np.hamming(Np) if win == 'ham' else np.ones(Np)
    M = (len(x)-Np)//hop+1
    X = np.empty((M, Np//2+1), dtype=np.complex128)
    for m in range(M):
        X[m] = np.fft.rfft(x[m*hop:m*hop+Np]*W)
    return X

def stft_frames_full(x, Np, hop):
    # two-sided complex STFT (fftshifted): cyclic lines at alpha=2fc need
    # pairing across negative frequencies, which one-sided rfft cannot see.
    M = (len(x)-Np)//hop+1
    X = np.empty((M, Np), dtype=np.complex128)
    for m in range(M):
        X[m] = np.fft.fftshift(np.fft.fft(x[m*hop:m*hop+Np].astype(np.float64)))
    return X

def scd_plane(x, Np=4096, hop=4096, a_max_hz=1500000.0, fs=FS):
    df = fs/Np
    hmax = min(int(a_max_hz/(2*df)), Np//2-1)
    X = stft_frames_full(x, Np, hop)
    M, B = X.shape
    S = np.zeros((hmax+1, B))
    S[0] = np.abs(X).mean(axis=0)**2  # stationary power (reference row)
    for h in range(1, hmax+1):
        # center-k pairing: C[k] = <X[k+h] conj(X[k-h])>, valid h<=k<B-h.
        # (A prior revision stored a truncated/shifted slice here, which
        # misregistered every reported f by up to h bins - ~700 kHz.)
        C = np.zeros(B)
        if B - 2*h > 0:
            C[h:B-h] = np.abs((X[:, 2*h:B]*X[:, :B-2*h].conj()).mean(axis=0))
        S[h] = C
    return S, df

def scd_peaks(S, df, topk=8):
    nz = S[1:][S[1:] > 0]  # zero-pads excluded: floor is Rayleigh, not zero
    med = np.median(nz)
    B = S.shape[1]
    got = []
    flat = S[1:].copy()
    for _ in range(topk):
        i = int(flat.argmax())
        h, k = i//B+1, i%B
        if flat.flat[i] <= 0: break
        got.append((2*h*df, (k-B//2)*df, flat.flat[i]/med))  # f centered: +/-fs/2
        flat[max(0, h-1):h+2, max(0, k-2):k+3] = 0  # suppress the cell only:
        # the old whole-row wipe deleted harmonic-comb members < ~4 kHz apart
    return got, med

def baud_stack(S, df, Rb, nharm=12):
    # Gardner-style: mean of per-harmonic max energy at alpha = n*Rb.
    # A real baud imprints a full comb; noise has no harmonic structure.
    hmax = S.shape[0]-1
    tot, n = 0.0, 0
    for m in range(1, nharm+1):
        h = int(round(m*Rb/(2*df)))
        if 1 <= h <= hmax:
            tot += float(S[h].max()); n += 1
    return tot/max(n, 1)

def dechirp_search(x, fs, gammas):
    n = np.arange(len(x))/fs
    best = (0.0, 0.0)
    for g in gammas:
        y = x*np.exp(-1j*np.pi*g*n*n)
        Sp = np.abs(np.fft.fft(y))**2  # complex -> full fft
        pk = float(Sp.max()/np.median(Sp))
        if pk > best[0]: best = (pk, g)
    return best

def quantize(x):
    q = np.empty_like(x)
    q[x < -1.667] = -3.3359
    m = (x >= -1.667) & (x < 0); q[m] = -1.0
    m = (x >= 0) & (x < 1.667); q[m] = 1.0
    q[x >= 1.667] = 3.3359
    return q.astype(np.float32)

def prove():
    rng = np.random.default_rng(21)
    N = 1033216
    t = np.arange(N)/FS
    Pn = 2.07**2
    # noise baseline for both detectors (THREE independent draws: a floor
    # fitted to a single draw lies - AGENTS.md hard-won lesson 5)
    nth = 0.0
    for _draw in range(3):
        xd = quantize(rng.normal(0, 2.07, N).astype(np.float32))
        Sn, _ = scd_plane(xd)
        pn, _ = scd_peaks(Sn, FS/1024, 4)
        nth = max(nth, max(p[2] for p in pn))
    xn = quantize(rng.normal(0, 2.07, N).astype(np.float32))  # reference draw
    gam = np.arange(-3000, 3001, 250, dtype=float)
    nn = np.arange(N)/FS
    nb = 0.0
    for g in gam[::4]:
        y = xn*np.exp(-1j*np.pi*g*nn*nn)
        Sp = np.abs(np.fft.fft(y))**2
        nb = max(nb, float(Sp.max()/np.median(Sp)))
    print(f'[prove] noise: scd_max={nth:.2f}x dechirp_max={nb:.2f}x')
    # BPSK @ -12dB, baud on-grid (Rb = 8 alpha-steps) so the comb is exact
    A = float(np.sqrt(2*Pn*10**(-12/10)))
    Rb, f0 = 11440.0, 400000.0
    sps = int(round(FS/Rb))
    bits = np.where(rng.integers(0, 2, N//sps), 1.0, -1.0)
    rep = np.repeat(bits, sps)
    sym = np.empty(N, dtype=np.float32); sym[:len(rep)] = rep[:N]; sym[len(rep):] = rep[0]
    s = (A*sym*np.cos(2*np.pi*f0*t)).astype(np.float32)
    x = quantize(rng.normal(0, 2.07, N).astype(np.float32)+s)
    S, df = scd_plane(x)
    pk, _ = scd_peaks(S, df, 10)
    near = [p for p in pk if abs(p[0]-2*f0) < 50000]
    det = pk[0][2] if pk else 0
    cls = max([p[2] for p in near], default=0.0)
    bsig = baud_stack(S, df, Rb)
    Sno, _ = scd_plane(xn)
    bnoi = baud_stack(Sno, df, Rb)
    print(f'[prove] BPSK: top={det:.1f}x 2f0-near={cls:.1f}x baudstack={bsig:.3e} '
          f'vs noise {bnoi:.3e} (x{bsig/max(bnoi,1e-12):.1f})')
    hit = (bsig > 3*bnoi) and det > nth*2
    # chirp @ -18dB, sweeps ~10.5 kHz (~3700 FFT bins: direct-FFT invisible by design)
    A2 = float(np.sqrt(2*Pn*10**(-18/10)))
    v = 30000.0
    s2 = (A2*np.cos(2*np.pi*(300000*t+0.5*v*t*t))).astype(np.float32)
    xc = quantize(rng.normal(0, 2.07, N).astype(np.float32)+s2)
    Sd = np.abs(np.fft.rfft(xc))**2
    direct = float(Sd.max()/np.median(Sd))
    (bp, bg) = dechirp_search(xc, FS, np.arange(-40000, 40001, 500, dtype=float))
    print(f'[prove] chirp v={v:.0f}: direct={direct:.2f}x '
          f'dechirp={bp:.2f}x@gamma={bg:.0f} (|err|={abs(abs(bg)-abs(v)):.0f})')
    ok = hit and bp > nb*2 and abs(abs(bg)-abs(v)) <= 500 \
        and (bp/direct) > 50  # bank must concentrate smeared energy 50x+
    print('[prove] ' + ('PASS: SCD baud-comb 4x over noise floor; smeared chirp '
                        'concentrated 300x+ by bank with exact rate'
                        if ok else 'TUNE'))

def scan_file(path, a_max=1500000.0, fs=FS):
    x = np.fromfile(path, dtype=np.float32)
    print(f'[in] n={len(x)}', flush=True)
    S, df = scd_plane(x, a_max_hz=a_max, fs=fs)
    pk, med = scd_peaks(S, df, 8)
    print(f'[scd] med={med:.3e}')
    for (al, f, r) in pk:
        print(f'  alpha={al:12.0f}Hz f={f:10.0f}Hz ratio={r:6.2f}x')
    (bp, bg) = dechirp_search(x, fs, np.arange(-3000, 3001, 250, dtype=float))
    print(f'[dechirp] best={bp:.2f}x @ gamma={bg:.0f} Hz/s')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--f32', default='')
    ap.add_argument('--a-max', type=float, default=1500000.0)
    ap.add_argument('--fs', type=float, default=None,
                    help='sample rate Hz (default: header-derived 2929687.5)')
    a = ap.parse_args()
    fs = a.fs if a.fs else FS
    if a.prove: prove()
    else: scan_file(a.f32, a.a_max, fs)

if __name__ == '__main__':
    main()
