"""multiblock.py — incoherently average high-res spectra over many blocks,
then ON vs OFF. A coherent carrier stays at one bin and grows relative to
the noise; noise peaks wander and wash out.
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handraw import Raw

def avg_spectra(r, blocks, pols=(0,1,2,3), progress=True):
    n=r.ntime; nf=n//2+1
    win=np.hanning(n).astype(np.float32); wnorm=(win**2).sum()
    P=np.zeros((r.nchan,len(pols),nf),dtype=np.float64)
    tp=np.zeros((r.nchan,len(pols)),dtype=np.float64)
    for bi,b in enumerate(blocks):
        a=r.block(b)
        for ci,ch in enumerate(range(r.nchan)):
            for pi,p in enumerate(pols):
                x=a[:,ch,p].astype(np.float64); x-=x.mean()
                P[ci,pi]+= (np.abs(np.fft.rfft(x*win))**2)/wnorm
                tp[ci,pi]+= (x*x).mean()
        if progress and bi%8==0: print(f"    blk {b}...",flush=True)
    return P/len(blocks), tp/len(blocks)

def local_med(P,k=257):
    kern=np.ones(k)/k
    return np.exp(np.convolve(np.log(P+1e-30),kern,mode='same'))

def top_peaks(P,r,pols,fmin_khz=2.0,fmax_frac=0.98,topn=25):
    n=P.shape[-1]; df=r.fs/n
    lo=max(2,int(fmin_khz*1e3/df)); hi=int(fmax_frac*n/2)
    hits=[]
    for ci in range(r.nchan):
        for pi in range(len(pols)):
            med=local_med(P[ci,pi]); ratio=P[ci,pi]/med
            sub=ratio[lo:hi]; i=np.argmax(sub)+lo
            hits.append((ratio[i],r.chan_freq(ci),pols[pi],i))
    hits.sort(reverse=True); return hits

def report(path, blocks, tag, pols=(0,1,2,3)):
    r=Raw(path); print(f"\n### {tag}: {os.path.basename(path)}  nblk={len(blocks)}")
    P,tp=avg_spectra(r,blocks,pols)
    for pi,p in enumerate(pols):
        print(f"  pol{p} mean total power = {tp[:,pi].mean():.4f}")
    hits=top_peaks(P,r,pols)
    print("  top 15 narrowband peaks after averaging (DC>2kHz excluded):")
    for ratio,f,p,i in hits[:15]:
        print(f"    {f:9.4f} MHz pol{p}  peak/med={ratio:7.2f}  bin {i}")
    return r,P,tp,hits

if __name__=='__main__':
    f=sys.argv[1]; nb=int(sys.argv[2]) if len(sys.argv)>2 else 16
    tag=sys.argv[3] if len(sys.argv)>3 else f
    r,P,tp,hits=report(f,list(range(nb)),tag)
    import os as _os
    _d=_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),'tmp'); _os.makedirs(_d,exist_ok=True)
    np.save(_os.path.join(_d,'avg_'+_os.path.basename(f)+'.npy'),P)
