"""powerseries.py — per-channel total-power time series at fine time resolution.

For a pulse/periodicity search: downsample each coarse channel to ~0.25 ms
(4 kHz) by summing squared voltage, keeping every polarization separately.
"""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from handraw import Raw

def build(path, win=732, out=None, maxblocks=None):
    r=Raw(path)
    nw = r.ntime//win
    nb = r.nblocks if maxblocks is None else min(maxblocks, r.nblocks)
    T=np.zeros((nb, nw, r.nchan, r.npol),dtype=np.float32)
    for b in range(nb):
        a=r.block(b)
        a=a[:nw*win].reshape(nw,win,r.nchan,r.npol)
        T[b]=(a*a).sum(axis=1)
        if b%16==0: print(f"  blk {b}",flush=True)
    T=T.reshape(nb*nw, r.nchan, r.npol)
    meta=dict(fs=r.fs, win=win, tbin=r.tbin, dt=win*r.tbin, nchan=r.nchan,
              npol=r.npol, freq=r.freq, bw=r.bw, nb=nb)
    if out: np.savez_compressed(out, T=T, meta=np.array([meta],dtype=object))
    return r,T,meta

if __name__=='__main__':
    path=sys.argv[1]; out=sys.argv[2] if len(sys.argv)>2 else None
    mb=int(sys.argv[3]) if len(sys.argv)>3 else None
    r,T,meta=build(path,out=out,maxblocks=mb)
    print("T shape",T.shape,"dt=%.4f ms"%(meta['dt']*1e3),"duration %.2f s"%(T.shape[0]*meta['dt']))
