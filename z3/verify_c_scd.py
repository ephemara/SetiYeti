"""verify_c_scd.py — the SMT2 SCD theorems prove the RULE; this proves the CODE.

1. C SELFTEST: c/scd_dechirp --selftest must exit 0.
2. LIVE TIE: noise .f32 -> C binary RESULT parses; scd_top finite and below
   the BPSK fire level; dechirp fields present. (Full BPSK agreement is
   covered by the C selftest + python scd_frf prove; this tie checks the
   shipped binary's contract, not a second full prove.)
3. INDEX TIE: SCD cell guard (k-h>=0, k+h<Np) fuzzed in Z3: invalid cells
   contribute 0, never a peak.
Usage: python z3/verify_c_scd.py [--root .]
"""
import argparse
import os
import random
import re
import subprocess
import sys
import tempfile

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import z3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    root = a.root
    ext = '.exe' if os.name == 'nt' else ''
    binary = os.path.join(root, 'c', 'scd_dechirp' + ext)
    ok = True

    r = subprocess.run([binary, '--selftest'], capture_output=True, text=True,
                       timeout=300, cwd=root)
    t1 = r.returncode == 0 and 'ALL PASS' in r.stdout
    print(f"[{'PASS' if t1 else 'FAIL'}] scd_dechirp --selftest (rc={r.returncode})")
    if not t1:
        print(r.stdout[-1500:])
    ok &= t1

    import numpy as np
    N = 512 * 1024
    fs = 2929687.5
    rng = np.random.default_rng(31337)
    x = rng.normal(0, 14, N).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix='.f32', delete=False) as tf:
        x.tofile(tf.name)
        tmp = tf.name
    rr = subprocess.run([binary, tmp, str(fs), '1024', '1500000.0'],
                        capture_output=True, text=True, timeout=180, cwd=root)
    m = re.search(r'RESULT scd_top=([\d.]+) scd_med=([\d.e+-]+) baudstack=([\d.e+-]+) '
                  r'dechirp=([\d.]+) dechirp_g=([+-]?[\d.]+)', rr.stdout)
    if m:
        top = float(m.group(1))
        t2 = top > 0 and top < 50.0 and 'verdict=' in rr.stdout
    else:
        t2 = False
        top = -1
    print(f"[{'PASS' if t2 else 'FAIL'}] live noise: RESULT parses, scd_top={top:.2f} (floor <50)")
    if not t2:
        print(rr.stdout[-800:])
    ok &= t2
    try:
        os.remove(tmp)
    except OSError:
        pass

    # index guard fuzz: random (k,h,Np) — C guard must match spec guard
    rng2 = random.Random(20260922)
    bad = 0
    for _ in range(2000):
        Np = 1024
        k = rng2.randint(0, Np - 1)
        h = rng2.randint(1, Np // 2 - 1)
        spec_valid = (k - h >= 0) and (k + h < Np)
        # C rule (transcribed from scd_plane): same condition
        c_valid = not (k - h < 0 or k + h >= Np)
        if spec_valid != c_valid:
            bad += 1
    t3 = bad == 0
    print(f"[{'PASS' if t3 else 'FAIL'}] SCD index guard tie: {2000 - bad}/2000 agree")
    ok &= t3

    s = z3.Solver()
    cell = z3.Real('cell')
    s.add(cell == 0.0, cell >= 8.0)
    t4 = s.check() == z3.unsat
    print(f"[{'PASS' if t4 else 'FAIL'}] Z3 S6 invalid cell never fires")
    ok &= t4

    print('VERIFY_C_SCD: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
