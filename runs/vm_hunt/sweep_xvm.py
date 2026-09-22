#!/usr/bin/env python
"""sweep_xvm.py - per-block alien-code sweep: 0017 ch44+ch56, all 128 blocks.
Hunts a single executing block hiding in the blaze. Records per block:
fam top-1, xvm sign/diff (ops, loops, acf_z, ham, crc, score, verdict).
"""
import os, re, subprocess, csv
import numpy as np
from concurrent.futures import ThreadPoolExecutor

R = 'E:/SetiYeti'
SL = os.path.join(R, 'c', 'seti_slice.exe')
FAM = os.path.join(R, 'c', 'fam_scan.exe')
XVM = os.path.join(R, 'c', 'xvm_sandbox.exe')
W = os.path.join(R, 'data', 'mvp_tmp')
os.makedirs(W, exist_ok=True)
RAW = os.path.join(R, 'data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw')
RX = re.compile(r'xvm_stk_ops=(\d+) xvm_stk_loops=(\d+).*?xvm_acf_lag=(\d+) xvm_acf_z=([-\d.]+) xvm_ham=([\d.]+) xvm_crc=(\d+) xvm_score=([\d.]+) (\S+)')
RF = re.compile(r'^(Y2|Y4) peak\s+\d+\s+bin=\d+\s+alpha=\s*([\d.]+) Hz\s+ratio=\s*([\d.]+)x')

def one(job):
    ch, b = job
    f32 = os.path.join(W, f'swp_{ch}_{b}.f32')
    try:
        r = subprocess.run([SL, RAW, str(ch), f32, '1', '--pol', '0', '--start', str(b)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(f32):
            return (ch, b, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'XFAIL')
        x = np.fromfile(f32, dtype=np.float32)
        r = subprocess.run([FAM, f32, '2929687.5', '32768', '2', '-'],
                           capture_output=True, text=True, timeout=120)
        fb = 0.0
        for ln in r.stdout.splitlines():
            m = RF.match(ln)
            if m and float(m.group(3)) > fb:
                fb = float(m.group(3))
        N = min(len(x), 200000)
        seg = x[:N]
        s = np.sign(seg); s[s == 0] = 1
        best = (0, 0, 0.0, 0.0, 0, 0.0, 'noise-like')
        for bits in ((seg > 0).astype(np.uint8),
                     (np.concatenate([[1], s[1:] * s[:-1]]) < 0).astype(np.uint8)):
            p = os.path.join(W, f'swp_{ch}_{b}.bin')
            np.packbits(bits, bitorder='big').tofile(p)
            r = subprocess.run([XVM, p], capture_output=True, text=True, timeout=120)
            try: os.remove(p)
            except OSError: pass
            m = RX.search(r.stdout.replace('\n', ' '))
            if not m:
                continue
            ops, loops, z = int(m.group(1)), int(m.group(2)), abs(float(m.group(4)))
            score = (loops, z, ops)
            if score > (best[1], best[2], best[0]):
                best = (ops, loops, z, float(m.group(5)), int(m.group(6)), float(m.group(7)), m.group(8))
        return (ch, b, round(fb, 1)) + tuple(best)
    finally:
        try: os.remove(f32)
        except OSError: pass

jobs = [(c, b) for c in (44, 56) for b in range(128)]
print(f'[sweep] {len(jobs)} blocks...', flush=True)
out = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, r in enumerate(ex.map(one, jobs)):
        out.append(r)
        if (i + 1) % 64 == 0:
            print(f'  {i+1}/{len(jobs)}', flush=True)
with open(os.path.join(R, 'runs', 'vm_hunt', 'sweep.csv'), 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['chan', 'block', 'fam', 'ops', 'loops', 'acf_z', 'ham', 'crc', 'score', 'verdict'])
    w.writerows(out)
print('[sweep] DONE -> runs/vm_hunt/sweep.csv')
