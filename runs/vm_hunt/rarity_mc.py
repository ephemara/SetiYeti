#!/usr/bin/env python
"""rarity_mc.py - empirical null for (STACK loops + ACF z) coincidence.
Surrogate test: phase-randomize the actual T17 b0/ch56 slice (spectrum,
incl. the 179 Hz wobble, preserved EXACTLY; any coded phase info destroyed).
If surrogates reproduce (1011 ops / 250 loops / ACF z=5.8), the spectrum explains
it and there is no code. Pure-noise arm as second control.
Usage: python rarity_mc.py [n_surr] [n_noise]
"""
import os, re, subprocess, sys
import numpy as np

R = 'E:/SetiYeti'
XVM = os.path.join(R, 'c', 'xvm_sandbox.exe')
SRC = os.path.join(R, 'data', 'mvp_tmp', 'r11.f32')
W = os.path.join(R, 'data', 'mvp_tmp')
NS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
NN = int(sys.argv[2]) if len(sys.argv) > 2 else 200

RX = re.compile(r'xvm_stk_ops=(\d+) xvm_stk_loops=(\d+).*?xvm_acf_z=([-\d.]+).*?xvm_score=([\d.]+) (\S+)')

def run_xvm(bits):
    p = os.path.join(W, 'mc.bin')
    np.packbits(bits, bitorder='big').tofile(p)
    r = subprocess.run([XVM, p], capture_output=True, text=True, timeout=120)
    os.remove(p)
    m = RX.search(r.stdout.replace('\n', ' '))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4)), m.group(5)

def surrogate(x, rng):
    X = np.fft.rfft(x)
    ph = rng.uniform(0, 2 * np.pi, len(X))
    ph[0] = 0
    if len(x) % 2 == 0:
        ph[-1] = 0
    return np.fft.irfft(np.abs(X) * np.exp(1j * ph), len(x)).astype(np.float32)

x0 = np.fromfile(SRC, dtype=np.float32)
N = min(len(x0), 200000)
rms = float(x0.std())
rng = np.random.default_rng(20260921)

def trial_sign(v):
    return (v[:N] > 0).astype(np.uint8)

print(f'[mc] slice n={len(x0)} rms={rms:.2f} Nbits={N} surr={NS} noise={NN}', flush=True)
for name, gen, cnt in (('surr', lambda: trial_sign(surrogate(x0, rng)), NS),
                       ('noise', lambda: (rng.normal(0, rms, N) > 0).astype(np.uint8), NN)):
    hit_loop = hit_acf = hit_joint = 0
    maxloops = maxz = 0
    for i in range(cnt):
        r = run_xvm(gen())
        if r is None:
            continue
        ops, loops, z, score, verdict = r
        maxloops = max(maxloops, loops)
        maxz = max(maxz, abs(z))
        L = (ops >= 1000 and loops >= 85)
        A = (abs(z) >= 5.8)
        hit_loop += L
        hit_acf += A
        hit_joint += (L and A)
        if (i + 1) % 50 == 0:
            print(f'  [{name}] {i+1}/{cnt} loop={hit_loop} acf={hit_acf} joint={hit_joint} maxloops={maxloops} max|z|={maxz:.1f}', flush=True)
    print(f'[RESULT {name}] n={cnt} P_loop~{hit_loop}/{cnt}={hit_loop/max(cnt,1):.3f} '
          f'P_acf~{hit_acf}/{cnt}={hit_acf/max(cnt,1):.4f} P_joint~{hit_joint}/{cnt}={hit_joint/max(cnt,1):.4f} '
          f'maxloops={maxloops} max|z|={maxz:.1f}', flush=True)
print('[mc] DONE')
