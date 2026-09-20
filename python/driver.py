"""driver.py - SetiYeti quick-look for 2-bit GUPPI M31 file.
Builds c/seti_slice, slices one coarse channel to .f32, renders waterfall + spectrum.
Usage:
  python driver.py --raw data/blc2_...raw --chan 32 --blocks 4
"""
import argparse, subprocess, os, sys
import numpy as np

LVL = np.array([-3.3359,-1.0,1.0,3.3359], dtype=np.float32)

def build_c(root):
    cdir = os.path.join(root,'c')
    src = os.path.join(cdir,'seti_slice.c')
    exe = os.path.join(cdir,'seti_slice.exe' if os.name=='nt' else 'seti_slice')
    if not os.path.exists(exe) or os.path.getmtime(src) > os.path.getmtime(exe):
        print(f'[build] gcc {src} -> {exe}')
        r = subprocess.run(['gcc','-O3','-o',exe,src,'-lm'], capture_output=True, text=True)
        if r.returncode!=0:
            print(r.stdout); print(r.stderr); sys.exit(1)
    return exe

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True)
    ap.add_argument('--chan', type=int, default=32)
    ap.add_argument('--pol', type=int, default=0)
    ap.add_argument('--blocks', type=int, default=2)
    ap.add_argument('--nfft', type=int, default=4096)
    ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if '__file__' in globals() else '.')
    a = ap.parse_args()
    root = a.root if os.path.isdir(a.root) else os.getcwd()
    # when run asDriver inside T:/Projects/SetiYeti, root fix:
    if not os.path.join(root,'c'): root=os.getcwd()
    exe = build_c(root if os.path.exists(os.path.join(root,'c','seti_slice.c')) else os.getcwd())
    out = os.path.join(os.path.dirname(a.raw) if os.path.dirname(a.raw) else '.', f'ch{a.chan}_p{a.pol}_{a.blocks}blk.f32')
    cmd=[exe,a.raw,str(a.chan),out,str(a.blocks),'--pol',str(a.pol)]
    print('[run]',' '.join(cmd))
    r=subprocess.run(cmd,text=True,capture_output=True)
    print(r.stdout); 
    if r.stderr: print(r.stderr, file=sys.stderr)
    if r.returncode!=0: sys.exit(r.returncode)
    x=np.fromfile(out,dtype=np.float32)
    print(f'[slice] n={len(x)} mean={x.mean():.4f} rms={x.std():.4f}')
    # waterfall: NFFT spectrum per row
    N=a.nfft
    nrows=len(x)//N
    print(f'[fft] rows={nrows} NFFT={N}')
    W=np.hamming(N).astype(np.float32)
    spec=np.abs(np.fft.rfft((x[:nrows*N].reshape(nrows,N)*W),axis=1))**2
    # average spectrum + peak hunt
    avg=spec.mean(axis=0)
    k=int(np.argmax(avg[1:-1]))+1
    print(f'[spectrum] peak_bin={k} peak_val={avg[k]:.3e} med={np.median(avg):.3e} ratio={avg[k]/np.median(avg):.2f}x')
    # top-5 bins
    idx=np.argpartition(avg, -5)[-5:]
    print('[top5 bins]',sorted([(int(i),float(avg[i]/np.median(avg))) for i in idx],key=lambda t:-t[1]))
    # save waterfall png
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        lg=np.log10(spec+1e-9)
        # downsample rows to <=256 for png
        step=max(1,nrows//256)
        img=lg[::step]
        plt.figure(figsize=(12,5))
        plt.imshow(img,aspect='auto',origin='lower',interpolation='nearest')
        plt.xlabel(f'freq bin (NFFT={N}, chan_bw~2.93MHz / {N} = {2.9296875*1e6/N:.1f} Hz/bin)')
        plt.ylabel('time row')
        plt.title(f"M31 ch{a.chan} p{a.pol} waterfall (log power)")
        plt.colorbar(label='log10 power')
        png=out+'.waterfall.png'
        plt.tight_layout(); plt.savefig(png,dpi=110)
        print(f'[png] {png}')
        # average spectrum png
        plt.figure(figsize=(12,3))
        plt.semilogy(avg)
        plt.xlabel('freq bin'); plt.ylabel('mean power'); plt.title('mean spectrum')
        png2=out+'.spectrum.png'
        plt.tight_layout(); plt.savefig(png2,dpi=110)
        print(f'[png] {png2}')
    except Exception as e:
        print(f'[png skipped] {e}')
    # lag autocorr quick (numpy, first 100k)
    y=x[:100000]-x[:100000].mean()
    e=(y*y).sum()
    for L in [1,7,64,256,1024,4096]:
        print(f'py-Rxx lag {L:<6d} norm={(y[:len(y)-L]*y[L:]).sum()/e:.5f}')

if __name__=='__main__':
    main()
