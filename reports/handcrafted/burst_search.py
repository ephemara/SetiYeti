"""burst_search.py — single-pulse + periodicity search on the power series.

* band-averaged power time series, high-passed
* FFT periodicity (rotation band 1 Hz - 2 kHz)
* dedispersion over DM 0..1500, boxcar matched filter
"""
import numpy as np, sys
sys.path.insert(0,'reports/handcrafted')
from handraw import Raw

def chan_freq(r,ch): return r.chan_freq(ch)

def analyze(npz, rawpath, tag, dm_max=1500.0):
    d=np.load(npz, allow_pickle=True)
    T=d['T']; meta=d['meta'][0]
    r=Raw(rawpath)
    dt=meta['dt']; fs=1.0/dt
    print('='*70); print(tag, "T",T.shape, "dt=%.4f ms"%(dt*1e3), "dur=%.2f s"%(T.shape[0]*dt))
    # band-averaged, pol-summed
    s=T.sum(axis=(1,2)).astype(np.float64)
    # high-pass: subtract running median (window ~ 1 s)
    w=int(1.0/dt)
    from numpy.lib.stride_tricks import sliding_window_view
    if w < len(s):
        sw=sliding_window_view(s,w)
        med=np.median(sw,axis=1)
        base=np.concatenate([np.full(w//2,med[0]),med,np.full(len(s)-len(med)-w//2,med[-1])])
        hp=s-base
    else:
        hp=s-s.mean()
    z=hp/np.std(hp)
    print("  band-power: mean=%.1f std=%.1f  max z=%.2f at sample %d (t=%.3f s)"%(s.mean(),s.std(),z.max(),np.argmax(z),np.argmax(z)*dt))
    print("  top 5 power outliers:")
    for i in np.argsort(z)[::-1][:5]:
        print(f"    t={i*dt:7.3f}s  z={z[i]:+7.2f}  raw={s[i]:.1f}")
    # periodicity: FFT of hp (mean removed)
    x=hp-hp.mean()
    X=np.abs(np.fft.rfft(x*np.hanning(len(x))))**2
    fr=np.fft.rfftfreq(len(x),d=dt)
    # exclude < 1 Hz
    lo=np.searchsorted(fr,1.0)
    pk=np.argmax(X[lo:])+lo
    med=np.median(X[lo:])
    print("  periodicity: peak at %.4f Hz  ratio=%.1f  (median-based)"%(fr[pk],X[pk]/med))
    # top 5 periodicity peaks
    order=np.argsort(X[lo:])[::-1][:5]+lo
    for i in order:
        print(f"    f={fr[i]:9.3f} Hz  period={1/fr[i]:8.4f}s  ratio={X[i]/med:7.1f}")
    # dedispersion
    freqs=np.array([r.chan_freq(ch) for ch in range(r.nchan)])  # MHz
    fref=freqs.max()
    tt=np.arange(len(s))*dt
    # per-channel power series (pol-summed)
    Sc=T.sum(axis=2).astype(np.float64)   # (ntime, nchan)
    best=[]
    for dm in np.linspace(0,dm_max,61):
        shifts=(4.148808e3*dm*(1.0/freqs**2 - 1.0/fref**2))*1e-3  # ms -> s
        idx=np.round(shifts/dt).astype(int)
        # dedisperse by shifting each channel backwards in time
        acc=np.zeros(len(s))
        for c in range(r.nchan):
            sh=idx[c]
            if sh==0: acc+=Sc[:,c]
            elif sh<len(s): acc[sh:]+=Sc[:-sh,c]
        acc-=acc.mean()
        sd=np.std(acc)
        if sd>0:
            zz=acc/sd
            best.append((zz.max(), dm, np.argmax(zz)*dt))
    best.sort(reverse=True)
    print("  dedispersion top 8 (max z, DM, t):")
    for zz,dm,t in best[:8]:
        print(f"    DM={dm:7.1f}  z={zz:6.2f}  t={t:7.3f}s")
    return z,fr,X

if __name__=='__main__':
    analyze(sys.argv[1], sys.argv[2], sys.argv[3])
