"""hires.py — hand-crafted high-resolution spectral search.

Each coarse channel is a critically-sampled real voltage stream at
fs=CHAN_BW. One full-block FFT gives ~5.6 Hz resolution. We look for
narrowband peaks relative to the local median (robust to red noise).
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handraw import Raw

def spectra(r, b=0, pols=(0,1,2,3)):
    """Return dict (ch,pol)->(freqs_mhz, power) using one full-block FFT."""
    a = r.block(b)
    out = {}
    n = r.ntime
    win = np.hanning(n).astype(np.float32)
    wnorm = (win**2).sum()
    for ch in range(r.nchan):
        for p in pols:
            x = a[:, ch, p].astype(np.float64)
            x = x - x.mean()
            X = np.fft.rfft(x * win)
            P = (np.abs(X)**2) / wnorm
            out[(ch,p)] = P
    return out

def peak_report(P, r, ch, p, nsigma=8.0):
    """Find peaks vs local median, return list."""
    n = len(P)
    # local median via coarse smoothing of log
    k = 257
    kern = np.ones(k)/k
    med = np.exp(np.convolve(np.log(P+1e-12), kern, mode='same'))
    ratio = P/med
    # ignore DC region
    lo = 4; hi = n-4
    idx = np.argsort(ratio[lo:hi])[::-1][:6] + lo
    res=[]
    for i in idx:
        res.append((ratio[i], i))
    return res, ratio

if __name__ == '__main__':
    path = sys.argv[1]
    b = int(sys.argv[2]) if len(sys.argv)>2 else 0
    r = Raw(path)
    print(f"{os.path.basename(path)}  block {b}  ntime={r.ntime}  df={r.fs/r.ntime:.3f} Hz")
    S = spectra(r, b)
    hits=[]
    for (ch,p),P in S.items():
        res, ratio = peak_report(P, r, ch, p)
        top = res[0][0]
        hits.append((top, ch, p, res))
    hits.sort(reverse=True)
    print("top 25 channel/pol by max peak/median:")
    for top,ch,p,res in hits[:25]:
        f0=r.chan_freq(ch)
        locs = ", ".join(f"{ratio:.1f}@{i}" for ratio,i in res[:3])
        print(f"  ch{ch:2d} pol{p} {f0:9.4f} MHz  max={top:6.1f}x  peaks: {locs}")
