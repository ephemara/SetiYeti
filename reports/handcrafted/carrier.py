"""carrier.py — full characterization of the 1426.9 MHz narrowband carrier."""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handraw import Raw

def chan_spec(r, b, ch, p, nperseg=None):
    a = r.chan_block(b, ch)[:, p].astype(np.float64)
    if nperseg is None or nperseg >= len(a):
        x = a - a.mean(); w = np.hanning(len(x))
        return np.abs(np.fft.rfft(x*w))**2/(w**2).sum(), r.fs/len(x)
    # Welch
    n = len(a)//nperseg
    acc = None
    w = np.hanning(nperseg)
    for i in range(n):
        x = a[i*nperseg:(i+1)*nperseg]; x = x-x.mean()
        P = np.abs(np.fft.rfft(x*w))**2/(w**2).sum()
        acc = P if acc is None else acc+P
    return acc/n, r.fs/nperseg

def characterize(path, tag, ch=25, f_lo=1426.80e6, f_hi=1427.00e6):
    r = Raw(path)
    fc = r.chan_freq(ch)
    print('='*76); print(f"{tag}: {os.path.basename(path)}  ch{ch} centre {fc:.5f} MHz")
    # average spectrum over blocks, all pols
    nf = r.ntime//2+1
    avg = np.zeros((r.npol, nf))
    amps = np.zeros((r.nblocks, r.npol))
    freqs = np.zeros((r.nblocks, r.npol))
    for b in range(r.nblocks):
        for p in range(r.npol):
            P, df = chan_spec(r, b, ch, p)
            if b == 0: faxis = fc + np.arange(len(P))*df/1e6
            avg[p] += P
            m = (faxis >= f_lo/1e6) & (faxis <= f_hi/1e6)
            i = np.argmax(P[m]) + np.argmax(m)
            amps[b,p] = P[i]; freqs[b,p] = faxis[i]
    avg /= r.nblocks
    # peak / local median for each pol
    print("  averaged spectrum, peak in search window:")
    for p in range(r.npol):
        m = (faxis >= f_lo/1e6) & (faxis <= f_hi/1e6)
        i = np.argmax(avg[p][m]) + np.argmax(m)
        med = np.median(avg[p])
        print(f"    pol{p}: peak {faxis[i]:.5f} MHz  ratio-to-median {avg[p][i]/med:9.1f}  "
              f"amp {avg[p][i]:.4g}")
    # width: -3dB points around peak of pol0
    m = (faxis >= f_lo/1e6) & (faxis <= f_hi/1e6)
    i = np.argmax(avg[0][m]) + np.argmax(m)
    half = avg[0][i]/2
    # count bins above half in a window
    j = i
    while avg[0][j] > half and j > 0: j -= 1
    k = i
    while avg[0][k] > half and k < len(avg[0])-1: k += 1
    print(f"  pol0 FWHM ~ {(k-j)*df:.2f} Hz over {k-j} bins")
    print("  pol0 spectrum near peak:")
    for q in range(i-5, i+6):
        print(f"    {faxis[q]:.6f} MHz  {avg[0][q]:.5g}")
    # drift within scan (pol0, pol1)
    for p in range(min(2, r.npol)):
        d = np.polyfit(np.arange(r.nblocks), freqs[:,p], 1)
        print(f"  pol{p} peak freq across 128 blocks: first {freqs[0,p]:.6f} last {freqs[-1,p]:.6f} "
              f"slope {d[0]*1e3:+.2f} Hz/block  std {freqs[:,p].std():.2f} Hz")
    # amplitude vs time
    print("  pol0 amplitude (first 12 blocks):", " ".join(f"{v:.3g}" for v in amps[:12,0]))
    print("  pol0 amplitude (last 12 blocks): ", " ".join(f"{v:.3g}" for v in amps[-12:,0]))
    return r, faxis, avg, amps, freqs

if __name__=='__main__':
    characterize(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else '')
