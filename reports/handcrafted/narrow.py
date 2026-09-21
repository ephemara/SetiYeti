"""narrow.py — narrowband carrier search + ON/OFF bandpass comparison.

Excludes the DC/1-f region (< 1 kHz) and the Nyquist edge. Uses a
robust local-median threshold so red noise can't fake a line.
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handraw import Raw

def block_spectra(r, b=0):
    a = r.block(b)
    n = r.ntime
    win = np.hanning(n).astype(np.float32)
    wnorm = (win**2).sum()
    P = np.empty((r.nchan, r.npol, n//2+1), dtype=np.float32)
    for ch in range(r.nchan):
        for p in range(r.npol):
            x = a[:, ch, p].astype(np.float64); x -= x.mean()
            P[ch,p] = (np.abs(np.fft.rfft(x*win))**2)/wnorm
    return P

def local_med(P, k=257):
    kern=np.ones(k)/k
    return np.exp(np.convolve(np.log(P+1e-30), kern, mode='same'))

def search(P, r, fmin_khz=1.0, fmax_frac=0.98, topn=12):
    n=P.shape[-1]
    df=r.fs/n
    lo=max(2,int(fmin_khz*1e3/df)); hi=int(fmax_frac*n/2)
    hits=[]
    for ch in range(r.nchan):
        for p in range(r.npol):
            Pc=P[ch,p]
            med=local_med(Pc)
            ratio=Pc/med
            sub=ratio[lo:hi]
            i=np.argmax(sub)+lo
            hits.append((ratio[i], ch, p, i, df))
    hits.sort(reverse=True)
    return hits

if __name__=='__main__':
    path=sys.argv[1]; b=int(sys.argv[2]) if len(sys.argv)>2 else 0
    r=Raw(path); P=block_spectra(r,b)
    print(f"{os.path.basename(path)} blk{b}  df={r.fs/r.ntime:.3f} Hz  search 1kHz..Nyq")
    hits=search(P,r)
    print("top 20 narrowband peaks (single-bin, DC excluded):")
    for ratio,ch,p,i,df in hits[:20]:
        # signed offset from channel centre
        foff=(i if i< r.ntime//2 else i-r.ntime)*(df)
        print(f"  ch{ch:2d} pol{p}  {r.chan_freq(ch):9.4f} MHz  peak/med={ratio:6.2f}  bin {i}  off={foff/1e3:+8.3f} kHz")
    # per-channel total power (bandpass)
    bp=P.mean(axis=(1,2))
    print("\nbandpass (mean power per coarse channel, normalised):")
    bp=bp/bp.mean()
    for ch in range(0,r.nchan,1):
        bar='#'*int(60*max(0,(bp[ch]-0.7))/0.6)
        print(f"  ch{ch:2d} {r.chan_freq(ch):9.4f} MHz  {bp[ch]:.4f} {bar}")
