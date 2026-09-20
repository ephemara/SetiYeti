"""bitslice.py - SetiYeti bit-slice loudest bins -> vm_sandbox.
Demodulates .f32 voltage stream to candidate bitstreams (no carrier knowledge):
  sign bits: 1 if x>0 (BPSK phase)
  diff bits: 1 if sign flips vs prev sample (transition-coded, robust to inversion)
Optional integrate-and-dump at --alpha baud (sps=round(fs/alpha)) before slicing.
Then runs c/vm_sandbox on each .bin (SUBLEQ locality + Golay G24 syndrome).
Usage:
  python bitslice.py --f32 data/ch32_p0_2blk.f32 [--alpha 1234.0] [--fs 2929687.5]
"""
import argparse, subprocess, os, sys
import numpy as np

def build_vm(root):
    src = os.path.join(root,'c','vm_sandbox.c')
    exe = os.path.join(root,'c','vm_sandbox.exe' if os.name=='nt' else 'vm_sandbox')
    if not os.path.exists(exe) or os.path.getmtime(src) > os.path.getmtime(exe):
        print(f'[build] gcc {src} -> {exe}')
        r = subprocess.run(['gcc','-O3','-o',exe,src,'-lm'], capture_output=True, text=True)
        if r.returncode!=0: print(r.stdout); print(r.stderr); sys.exit(1)
    return exe

def pack_bits(bits):
    # MSB-first == numpy packbits bitorder='big' (vectorized, ~50x).
    return np.packbits(np.asarray(bits, dtype=np.uint8), bitorder='big')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32', required=True)
    ap.add_argument('--fs', type=float, default=2929687.5)
    ap.add_argument('--alpha', type=float, default=0.0, help='baud Hz from fam_scan; 0=raw slice')
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    root = a.root
    x = np.fromfile(a.f32, dtype=np.float32)
    print(f'[in] n={len(x)} mean={x.mean():.4f} rms={x.std():.4f}')
    y = x
    tag = 'raw'
    if a.alpha and a.alpha > 0:
        sps = max(1, int(round(a.fs / a.alpha)))
        # integrate-and-dump over sps samples (coherent gain if alpha=true baud)
        m = (len(y)//sps)*sps
        y = y[:m].reshape(-1, sps).mean(axis=1).astype(np.float32)
        tag = f'baud{a.alpha:.1f}_sps{sps}'
        print(f'[dump] sps={sps} integrated n={len(y)}')
    # sign + diff bitstreams (cap 200k bits to match vm_sandbox window)
    N = min(len(y), 200000)
    seg = y[:N]
    sign = (seg > 0).astype(np.uint8)
    s = np.sign(seg); s[s==0]=1
    diff = (np.concatenate([[1], s[1:]*s[:-1]]) < 0).astype(np.uint8)
    base = a.f32 + f'.{tag}'
    for name, bits in [('sign',sign),('diff',diff)]:
        p = base + f'.{name}.bin'
        pack_bits(bits).tofile(p)
        ones = float(bits.mean())
        # run-length: entropy proxy
        print(f'[bits] {name}: {p} nbits={len(bits)} ones={ones:.4f}')
    exe = build_vm(root if os.path.exists(os.path.join(root,'c','vm_sandbox.c')) else os.getcwd())
    for name in ['sign','diff']:
        p = base + f'.{name}.bin'
        print(f'--- vm_sandbox {name} ---')
        r = subprocess.run([exe, p], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.stderr: print(r.stderr.strip(), file=sys.stderr)

if __name__ == '__main__':
    main()
