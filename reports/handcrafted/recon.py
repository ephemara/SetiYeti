import sys, numpy as np
sys.path.insert(0,'reports/handcrafted')
from handraw import Raw

def recon(path, b=0):
    r = Raw(path)
    print('#'*78)
    print(path)
    print(f"src={r.kv.get('SRC_NAME')}  centre={r.freq} MHz  bw={r.bw}  nblocks={r.nblocks}")
    print(f"ch0={r.chan_freq(0):.4f}  ch63={r.chan_freq(63):.4f} MHz")
    a = r.block(b)  # (ntime,nchan,npol)
    print("block shape", a.shape, "bytes", a.nbytes)
    # global stats
    print(f"  global min={a.min():.0f} max={a.max():.0f} mean={a.mean():.3f} std={a.std():.3f}")
    print(f"  distinct int values: {len(np.unique(a.astype(np.int16)))}")
    sat = np.mean(np.abs(a)>=127)
    print(f"  saturation |x|>=127: {sat*100:.4f}%")
    # per pol
    for p in range(r.npol):
        x=a[:,:,p]
        print(f"  pol{p}: mean={x.mean():8.3f} std={x.std():8.3f} min={x.min():.0f} max={x.max():.0f} "
              f"skew={np.mean(((x-x.mean())/x.std())**3):6.3f} kurt={np.mean(((x-x.mean())/x.std())**4):7.3f}")
    # per channel rms and mean
    rms = np.sqrt((a.astype(np.float64)**2).mean(axis=(0,2)))
    mn  = a.mean(axis=(0,2))
    print("  per-channel RMS (all pol combined):")
    for ch in range(r.nchan):
        bar = '#'*int(40*rms[ch]/rms.max())
        print(f"    ch{ch:2d} {r.chan_freq(ch):9.4f} MHz  rms={rms[ch]:7.3f} mean={mn[ch]:8.3f} {bar}")
    return r,a

for p in sys.argv[1:]:
    recon(p, 0)
