import numpy as np, sys
sys.path.insert(0,'reports/handcrafted')
from handraw import Raw

def analyze(npz, rawpath, tag, dm_max=1500.0):
    d=np.load(npz, allow_pickle=True); T=d['T']; meta=d['meta'][0]
    r=Raw(rawpath); dt=meta['dt']; nw_per_blk = r.ntime//meta['win']
    print('='*70); print(tag,"T",T.shape,"dt=%.4f ms"%(dt*1e3))
    s=T.sum(axis=(1,2)).astype(np.float64)
    # per-block mean (block gain) and detrended series
    nb=len(s)//nw_per_blk
    blkmean=s[:nb*nw_per_blk].reshape(nb,nw_per_blk).mean(axis=1)
    print("  per-block mean power: min=%.3g max=%.3g ratio=%.2f  std/mean=%.3f"%(
        blkmean.min(),blkmean.max(),blkmean.max()/blkmean.min(),blkmean.std()/blkmean.mean()))
    print("  block mean power across 8 evenly spaced blocks:", [f"{v:.3g}" for v in blkmean[::max(1,nb//8)]])
    # detrend: subtract per-block mean
    s2=s[:nb*nw_per_blk].reshape(nb,nw_per_blk).copy()
    s2=(s2-blkmean[:,None]).ravel()
    # also smooth over 1ms
    z=s2/np.std(s2)
    print("  detrended band-power: max z=%.2f at t=%.3fs"%(z.max(),np.argmax(z)*dt))
    order=np.argsort(z)[::-1][:8]
    for i in order:
        print(f"    t={i*dt:7.3f}s z={z[i]:+6.2f}")
    # periodicity on detrended, high-passed
    x=s2-s2.mean()
    X=np.abs(np.fft.rfft(x*np.hanning(len(x))))**2
    fr=np.fft.rfftfreq(len(x),d=dt)
    lo=np.searchsorted(fr,1.0)
    med=np.median(X[lo:])
    order=np.argsort(X[lo:])[::-1][:8]+lo
    print("  periodicity (detrended) top peaks vs median:")
    for i in order:
        print(f"    f={fr[i]:9.4f} Hz  P={1/fr[i]:8.5f}s  ratio={X[i]/med:8.1f}  {'<-- BLOCK RATE' if abs(fr[i]-1/(meta['win']*meta['tbin']*1))<0.05 else ''}")
    # dedispersion on detrended per-channel series
    Sc=T.sum(axis=2).astype(np.float64)[:nb*nw_per_blk].reshape(nb,nw_per_blk,r.nchan)
    Sc=(Sc-blkmean[:,None,None]).reshape(nb*nw_per_blk,r.nchan)
    freqs=np.array([r.chan_freq(ch) for ch in range(r.nchan)]); fref=freqs.max()
    best=[]
    for dm in np.linspace(0,dm_max,81):
        shifts=(4.148808e3*dm*(1.0/freqs**2-1.0/fref**2))*1e-3
        idx=np.round(shifts/dt).astype(int)
        acc=np.zeros(len(s2))
        for c in range(r.nchan):
            sh=idx[c]
            if sh==0: acc+=Sc[:,c]
            elif 0<sh<len(s2): acc[sh:]+=Sc[:-sh,c]
        sd=np.std(acc)
        if sd>0:
            zz=acc/sd; best.append((zz.max(),dm,np.argmax(zz)*dt))
    best.sort(reverse=True)
    print("  dedispersion top 8:")
    for zz,dm,t in best[:8]: print(f"    DM={dm:7.1f} z={zz:6.2f} t={t:7.3f}s")
    return

if __name__=='__main__':
    analyze(sys.argv[1],sys.argv[2],sys.argv[3])
