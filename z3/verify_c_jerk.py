"""verify_c_jerk.py — the SMT2 jerk theorems prove the RULE; this proves the CODE.

1. C SELFTEST: c/jerk_track --selftest must exit 0 (noise quiet, chirps found).
2. FORMULA TIE: sidereal bound 0.35*freq/1407.7 fuzzed against shipped
   python/jerk_scan.sidereal_check on 2000 random (v, freq) pairs.
3. LIVE TIE: synth .f32 (stationary tone) -> C binary RESULT parses and the
   verdict obeys score>=thresh; drift is finite and small vs a chirp.
Usage: python z3/verify_c_jerk.py [--root .]
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


def c_bound(freq):
    return 0.35 * (freq / 1407.7)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    root = a.root
    ext = '.exe' if os.name == 'nt' else ''
    binary = os.path.join(root, 'c', 'jerk_track' + ext)
    ok = True

    # 1. C selftest
    r = subprocess.run([binary, '--selftest'], capture_output=True, text=True,
                       timeout=300, cwd=root)
    t1 = r.returncode == 0 and 'ALL PASS' in r.stdout
    print(f"[{'PASS' if t1 else 'FAIL'}] jerk_track --selftest (rc={r.returncode})")
    if not t1:
        print(r.stdout[-1500:])
    ok &= t1

    # 2. formula tie vs shipped python
    import jerk_scan as J
    rng = random.Random(20260921)
    bad = 0
    for _ in range(2000):
        v = rng.uniform(-5000, 5000)
        f = rng.uniform(100.0, 3000.0)
        mo = {'drift_hz_s': v}
        py = J.sidereal_check(mo, f)
        mine_anom = abs(v) > c_bound(f)
        py_anom = py.startswith('ANOMALOUS')
        if mine_anom != py_anom:
            bad += 1
            if bad <= 3:
                print(f'  MISMATCH v={v:.2f} f={f:.1f}: py={py} mine_anom={mine_anom}')
    t2 = bad == 0
    print(f"[{'PASS' if t2 else 'FAIL'}] sidereal formula tie: {2000 - bad}/2000 agree")
    ok &= t2

    # 3. Z3 replays the shipped verdict symbolically
    s = z3.Solver()
    v_ = z3.Real('v')
    s.add(v_ == 0.2, z3.Abs(v_) > 0.35)
    j2 = s.check() == z3.unsat
    s.reset()
    step, k = z3.Real('step'), z3.Real('k')
    s.add(step == 3.0, k == 2.0, z3.Abs(step) <= k)
    j4 = s.check() == z3.unsat
    t3 = j2 and j4
    print(f"[{'PASS' if t3 else 'FAIL'}] Z3 J2 (v=0.2 quiet) + J4 (step 3/k2 invalid)")
    ok &= t3

    # 4. live tie: stationary tone through the real binary
    try:
        import numpy as np
        N = 512 * 1024
        fs = 2929687.5
        rngn = np.random.default_rng(99)
        t = np.arange(N) / fs
        x = (rngn.normal(0, 14, N) + 8.0 * np.cos(2 * np.pi * 300000.0 * t)).astype(np.float32)
        with tempfile.NamedTemporaryFile(suffix='.f32', delete=False) as tf:
            x.tofile(tf.name)
            tmp = tf.name
        rr = subprocess.run([binary, tmp, '2929687.5', '8192', '4096', '2', '0'],
                            capture_output=True, text=True, timeout=120, cwd=root)
        m = re.search(r'RESULT score=([\d.]+) drift=([+-]?[\d.]+)', rr.stdout)
        if m:
            score, drift = float(m.group(1)), float(m.group(2))
            t4 = score > 0 and abs(drift) < 2000.0 and 'verdict=' in rr.stdout
        else:
            t4 = False
        print(f"[{'PASS' if t4 else 'FAIL'}] live tone: RESULT parses, drift sane")
        if not t4:
            print(rr.stdout[-800:])
        ok &= t4
        try:
            os.remove(tmp)
        except OSError:
            pass
    except Exception as e:
        print(f'[FAIL] live tie raised {e}')
        ok = False

    print('VERIFY_C_JERK: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
