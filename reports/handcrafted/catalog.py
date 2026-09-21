"""catalog.py — find every significant narrowband carrier in the averaged spectra."""
import numpy as np, sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handraw import Raw

def local_med(P,k=401):
    kern=np.ones(k)/k
    return np.exp(np.convolve(np.log(P+1e-30),kern,mode='same'))

def find_peaks(P, r, thresh=4.0):
    n=P.shape[-1]; df=r.fs/r.ntime
    lo=int(2000/df); hi=int(0.98*n/2)
    out=[]
    for ch in range(r.nchan):
        for p in range(r.npol):
            Pc=P[ch,p]; med=local_med(Pc); ratio=Pc/med
            for i in range(lo+1,hi-1):
                if ratio[i]>thresh and ratio[i]>=ratio[i-1] and ratio[i]>=ratio[i+1]:
                    # centroid over +-3
                    sl=slice(max(0,i-3),i+4)
                    w=Pc[sl]-np.median(Pc[sl])
                    w=np.clip(w,0,None)
                    if w.sum()<=0: continue
                    bins=np.arange(max(0,i-3),i+4)
                    cen=(w*bins).sum()/w.sum()
                    out.append((r.chan_freq(ch) + cen*df/1e6,
                                ratio[i], ch, p, cen))
    return out

if __name__=='__main__':
    files=sorted(glob.glob('reports/handcrafted/tmp/avg_*.npy'))
    allp=[]
    for f in files:
        raw=os.path.basename(f)[4:-4]
        P=np.load(f)
        r=Raw('data/'+raw)
        peaks=find_peaks(P,r)
        # dedupe: keep strongest per (ch,pol)
        best={}
        for freq,ratio,ch,p,cen in peaks:
            k=(ch,p)
            if k not in best or ratio>best[k][1]: best[k]=(freq,ratio,ch,p)
        peaks=sorted(best.values(),key=lambda x:-x[1])
        print('='*76); print(raw, "  (%d peaks>6x)"%len(peaks))
        for freq,ratio,ch,p in peaks[:12]:
            print(f"    {freq:11.5f} MHz  pol{p} ch{ch:2d}  ratio={ratio:7.2f}")
            allp.append((freq,ratio,raw,ch,p))
    # cross-file frequency clustering
    print('\n'+'='*76)
    print("CROSS-FILE frequency clusters (within 2 kHz):")
    allp.sort()
    used=[False]*len(allp)
    for i in range(len(allp)):
        if used[i]: continue
        grp=[allp[i]]; used[i]=True
        for j in range(i+1,len(allp)):
            if used[j]: continue
            if abs(allp[j][0]-allp[i][0])<2e-3:
                grp.append(allp[j]); used[j]=True
        if len(grp)>=1:
            fs="; ".join(f"{g[2][:18]} pol{g[4]} {g[1]:.1f}x" for g in grp)
            print(f"  {allp[i][0]:11.5f} MHz : {fs}")
