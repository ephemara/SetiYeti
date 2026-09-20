"""dsss_prove.py - SetiYeti proof: sub-noise signals FFT can't see, FAM can.
Builds two injections at SNR ~ -12dB into 2-bit-quantized noise (same backend as M31):
  A) weak narrow BPSK (Rb=2kHz @ f0=400kHz) - the "missed carrier" case
  B) DSSS (63-chip m-seq @ 100kchips/s, data 1kHz @ f0=600kHz) - spread 100kHz wide
Runs the REAL pipeline on each: direct FFT peak-hunt (driver.py method) vs
c/fam_scan carrier-squared line. Verdict: INVISIBLE vs DETECTED.
Usage: python dsss_prove.py --root .
"""
import argparse, subprocess, os, sys
import numpy as np

FS = 2929687.5
N = 1033216  # match ch32 slice length (~0.353 s)
NOISE_SIGMA = 2.07

def quantize(x):
    q = np.empty_like(x)
    q[x < -1.667] = -3.3359
    m = (x >= -1.667) & (x < 0); q[m] = -1.0
    m = (x >= 0) & (x < 1.667); q[m] = 1.0
    q[x >= 1.667] = 3.3359
    return q.astype(np.float32)

def span(v, n):
    v = np.asarray(v, dtype=np.float32)
    if len(v) >= n: return v[:n]
    r = np.empty(n, dtype=np.float32)
    r[:len(v)] = v; r[len(v):] = v[0]
    return r

def direct_peak_ratio(x, nfft=4096):
    nrows = len(x)//nfft
    W = np.hamming(nfft).astype(np.float32)
    spec = np.abs(np.fft.rfft((x[:nrows*nfft].reshape(nrows, nfft)*W), axis=1))**2
    avg = spec.mean(axis=0); med = np.median(avg)
    k = int(np.argmax(avg[1:-1]))+1
    return avg[k]/med, k

def fam_line_ratio(fam_exe, f32path, target_hz, tol_hz=2000.0):
    r = subprocess.run([fam_exe, f32path, str(FS), '32768', '8'],
                       capture_output=True, text=True)
    best = (0.0, 0.0)
    for line in r.stdout.splitlines():
        if 'alpha=' not in line: continue
        try:
            hz = float(line.split('alpha=')[1].split('Hz')[0].strip())
            ratio = float(line.split('ratio=')[1].split('x')[0].strip())
        except ValueError:
            continue
        if abs(hz-target_hz) <= tol_hz and ratio > best[0]:
            best = (ratio, hz)
    return best

def mseq63(nchips, seed=0x3F):
    sr = seed & 0x3F
    out = np.empty(nchips, dtype=np.float32)
    for i in range(nchips):
        bit = ((sr >> 5) ^ (sr & 1)) & 1  # x^6+x+1 primitive
        out[i] = 1.0 if (sr & 1) else -1.0
        sr = ((sr >> 1) | (bit << 5)) & 0x3F
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--snr-db', type=float, default=-12.0)
    a = ap.parse_args()
    fam = os.path.join(a.root, 'c', 'fam_scan.exe' if os.name == 'nt' else 'fam_scan')
    dat = os.path.join(a.root, 'data')
    rng = np.random.default_rng(7)
    t = np.arange(N)/FS
    # signal amplitude for target SNR vs noise power Pn≈4.28
    Pn = NOISE_SIGMA**2
    A = float(np.sqrt(2*Pn*10**(a.snr_db/10.0)))
    print(f'[cfg] N={N} fs={FS:.1f} SNR={a.snr_db}dB A={A:.4f} Pn={Pn:.2f}')

    # --- Test A: weak narrow BPSK ---
    Rb, f0 = 2000.0, 400000.0
    sps = int(round(FS/Rb))
    nbits = N//sps
    bits = np.where(rng.integers(0, 2, nbits), 1.0, -1.0).astype(np.float32)
    sym = span(np.repeat(bits, sps), N)
    sA = (A*sym*np.cos(2*np.pi*f0*t)).astype(np.float32)
    xA = quantize(rng.normal(0, NOISE_SIGMA, N).astype(np.float32) + sA)
    pA = os.path.join(dat, 'proveA_bpsk.f32'); xA.tofile(pA)
    dr, _ = direct_peak_ratio(xA)
    fr, fh = fam_line_ratio(fam, pA, 2*f0)
    print(f'[A BPSK Rb={Rb/1e3:.0f}k f0={f0/1e3:.0f}k CALIB] direct_peak={dr:.2f}x | '
          f'fam_2f0={fr:.2f}x@{fh:.0f}Hz (pos_agree={abs(fh-2*f0)<2000})')

    # --- Test B: DSSS, 63-chip code, 500 kchips/s (spread 1 MHz wide) ---
    # Spreading crushes per-bin FFT power but the carrier-squared tone only
    # depends on amplitude, not bandwidth: FAM keeps full sensitivity.
    Rc, f1 = 500000.0, 600000.0
    spc = int(round(FS/Rc))  # ~29 samples/chip
    nchips = N//spc
    code = span(np.repeat(mseq63(nchips), spc), N)
    Rb2, spb = 1000.0, int(round(FS/1000.0))
    data = span(np.repeat(np.where(rng.integers(0, 2, N//spb), 1.0, -1.0), spb), N)
    sB = (A*data*code*np.cos(2*np.pi*f1*t)).astype(np.float32)
    xB = quantize(rng.normal(0, NOISE_SIGMA, N).astype(np.float32) + sB)
    pB = os.path.join(dat, 'proveB_dsss.f32'); xB.tofile(pB)
    drB, _ = direct_peak_ratio(xB)
    frB, fhB = fam_line_ratio(fam, pB, 2*f1)
    print(f'[B DSSS Rc={Rc/1e3:.0f}k f0={f1/1e3:.0f}k] direct_maxbin={drB:.2f}x '
          f'({"no actionable LINE" if drB < 5.0 else "line"}) | fam_2f0={frB:.2f}x@{fhB:.0f}Hz '
          f'({"DETECTED" if frB > 3.0 else "miss"})')

    # --- Assisted despread (GPS-style acquisition, known 63-chip code) ---
    # correlate baseband-mixed I against code phase sweep; peak = sub-noise recovery
    NB = 200000
    mix = (xB*np.cos(2*np.pi*f1*t)).astype(np.float32)
    w = int(round(FS/Rc))*63  # one full code epoch in samples
    crep = np.repeat(mseq63(63), int(round(FS/Rc)))[:w]
    ne = NB//w
    seg = mix[:ne*w].reshape(ne, w)
    # non-coherent accumulation: mean |corr| per epoch, per code phase
    def acquire(segm):
        bestv = 0.0
        for shift in range(w):
            c = np.roll(crep, shift)
            v = float(np.abs(segm@c).mean())
            if v > bestv: bestv = v
        return bestv
    best = acquire(seg)
    # noise-only baseline same procedure
    xn = quantize(rng.normal(0, NOISE_SIGMA, N).astype(np.float32))
    mixn = (xn*np.cos(2*np.pi*f1*t)).astype(np.float32)
    segn = mixn[:ne*w].reshape(ne, w)
    bestn = acquire(segn)
    print(f'[B despread] code-phase peak sig={best:.3e} vs noise={bestn:.3e} '
          f'gain={best/max(bestn,1e-9):.2f}x ({"RECOVERED" if best > 2*bestn else "miss"})')

if __name__ == '__main__':
    main()
