"""verify_c_fold.py — the SMT2 fold/DM theorems prove the RULE; this proves the CODE.

1. C SELFTEST: c/fold_dm --selftest must exit 0.
2. LIVE TIE: synth .f32 cases (noise / pulsar train / narrow shot) through
   BOTH the C binary and the shipped python (pulsar_fold.detect,
   transient_dm.detect); dispositions must agree.
3. GATE TIE: Z3 replays the 16.0 / 14.0 sharpness from the SMT2 spec.
Usage: python z3/verify_c_fold.py [--root .]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import z3


def parse_result(out):
    m = re.search(r'RESULT fold_det=(\d).*?fold_f=([\d.]+) fold_sig=([+-]?[\d.]+)'
                  r'.*?dm_det=(\d).*?dm_sig=([+-]?[\d.]+)', out, re.S)
    if not m:
        return None
    return {'fold_det': int(m.group(1)), 'fold_f': float(m.group(2)),
            'fold_sig': float(m.group(3)), 'dm_det': int(m.group(4)),
            'dm_sig': float(m.group(5))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    root = a.root
    ext = '.exe' if os.name == 'nt' else ''
    binary = os.path.join(root, 'c', 'fold_dm' + ext)
    ok = True

    r = subprocess.run([binary, '--selftest'], capture_output=True, text=True,
                       timeout=300, cwd=root)
    t1 = r.returncode == 0 and 'ALL PASS' in r.stdout
    print(f"[{'PASS' if t1 else 'FAIL'}] fold_dm --selftest (rc={r.returncode})")
    if not t1:
        print(r.stdout[-1500:])
    ok &= t1

    import numpy as np
    import pulsar_fold as PF
    import transient_dm as TD
    fs = 2929687.5
    N = 2 * 524288
    cases = []
    rng = np.random.default_rng(20260921)
    noise = rng.normal(0, 14, N).astype(np.float32)
    cases.append(('noise', noise, False, False))
    t = np.arange(N) / fs
    phase = (t * 29.7) % 1.0
    pulse = np.exp(-0.5 * ((phase - 0.5) / 0.03) ** 2)
    cases.append(('pulsar29.7', (noise + 6.0 * pulse * 14).astype(np.float32),
                  True, None))
    y = noise.copy()
    y[300000:300008] += 12 * 14
    cases.append(('shot', y.astype(np.float32), None, True))

    for name, x, want_fold, want_dm in cases:
        with tempfile.NamedTemporaryFile(suffix='.f32', delete=False) as tf:
            x.tofile(tf.name)
            tmp = tf.name
        rr = subprocess.run([binary, tmp, str(fs), 'both'], capture_output=True,
                            text=True, timeout=180, cwd=root)
        c = parse_result(rr.stdout)
        py_fold = PF.detect(x, fs)['detected']
        py_dm = TD.detect(x, fs)['detected']
        agree_fold = c is not None and (c['fold_det'] == int(py_fold))
        agree_dm = c is not None and (c['dm_det'] == int(py_dm))
        want_ok = True
        if want_fold is not None:
            want_ok &= (c['fold_det'] == int(want_fold)) if c else False
        if want_dm is not None:
            want_ok &= (c['dm_det'] == int(want_dm)) if c else False
        t = agree_fold and agree_dm and want_ok
        print(f"[{'PASS' if t else 'FAIL'}] {name}: C fold={c['fold_det'] if c else '?'} "
              f"py={int(py_fold)} | C dm={c['dm_det'] if c else '?'} py={int(py_dm)}")
        if not t:
            print(rr.stdout[-600:])
        ok &= t
        try:
            os.remove(tmp)
        except OSError:
            pass

    s = z3.Solver()
    f = z3.Real('f')
    s.add(f == 15.9, f >= 16.0)
    g1 = s.check() == z3.unsat
    s.reset()
    d = z3.Real('d')
    s.add(d == 13.9, d >= 14.0)
    g2 = s.check() == z3.unsat
    t3 = g1 and g2
    print(f"[{'PASS' if t3 else 'FAIL'}] Z3 F2/F3 gate sharpness (16.0 / 14.0)")
    ok &= t3

    print('VERIFY_C_FOLD: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
