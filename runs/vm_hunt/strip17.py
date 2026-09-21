#!/usr/bin/env python
"""strip17.py - ON-OFF-ON persistence strips for TRAPPIST triple.
For each file x hot-chan x block(stride) x pol0: extract 1 block, fam top-1,
rms, maxz. Answers: transient or continuous? in both ONs? in OFF?
"""
import os, re, subprocess, sys, csv
import numpy as np
from concurrent.futures import ThreadPoolExecutor

R = 'E:/SetiYeti'
SL = os.path.join(R, 'c', 'seti_slice.exe')
FAM = os.path.join(R, 'c', 'fam_scan.exe')
W = os.path.join(R, 'data', 'mvp_tmp')
os.makedirs(W, exist_ok=True)

FILES = {'0015ON': 'data/blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.raw',
         '0016OFF': 'data/blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw',
         '0017ON': 'data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw'}
CHANS = [4, 12, 24, 26, 28, 36, 44, 48, 56]
BLOCKS = list(range(0, 128, 4))

def one(job):
    tag, raw, ch, b = job
    f32 = os.path.join(W, f'strip_{tag}_{ch}_{b}.f32')
    try:
        r = subprocess.run([SL, os.path.join(R, raw), str(ch), f32, '1',
                            '--pol', '0', '--start', str(b)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(f32):
            return (tag, ch, b, -1, -1, -1, -1)
        x = np.fromfile(f32, dtype=np.float32)
        rms = float(x.std()); mz = float(np.abs((x - x.mean()) / x.std()).max())
        r = subprocess.run([FAM, f32, '2929687.5', '32768', '3', '-'],
                           capture_output=True, text=True, timeout=120)
        best, bhz = 0.0, 0.0
        for ln in r.stdout.splitlines():
            m = re.match(r'^(Y2|Y4) peak\s+\d+\s+bin=\d+\s+alpha=\s*([\d.]+) Hz\s+ratio=\s*([\d.]+)x', ln)
            if m and float(m.group(3)) > best:
                best, bhz = float(m.group(3)), float(m.group(2))
        return (tag, ch, b, round(best, 2), round(bhz, 1), round(rms, 2), round(mz, 1))
    finally:
        try: os.remove(f32)
        except OSError: pass

jobs = [(t, rw, c, b) for t, rw in FILES.items() for c in CHANS for b in BLOCKS]
print(f'[strip] {len(jobs)} extractions...', flush=True)
out = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, r in enumerate(ex.map(one, jobs)):
        out.append(r)
        if (i + 1) % 200 == 0:
            print(f'  {i+1}/{len(jobs)}', flush=True)
with open(os.path.join(R, 'runs', 'vm_hunt', 'strips.csv'), 'w', newline='') as fh:
    w = csv.writer(fh); w.writerow(['file', 'chan', 'block', 'fam_best', 'fam_hz', 'rms', 'maxz'])
    w.writerows(out)
print('[strip] DONE -> runs/vm_hunt/strips.csv')
