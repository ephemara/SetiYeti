"""run_cbmc.py — CBMC proof gate for the C backend (with gcc-fuzz fallback).

WHY TWO MODES: CBMC is not vendored (no binary on Windows MinGW, no network
install here). The harnesses in c/proofs/harness_*.c are written once and run
both ways:

  * cbmc present  -> real exhaustive proof (unwound, all asserts verified).
  * cbmc missing  -> gcc-compiled bounded fuzz with the SAME asserts
                    (memory guards + verdict contracts). Weaker than a proof
                    but byte-identical checks, and it fails loudly.

Usage: python z3/run_cbmc.py [--root .] [--unwind 8]
"""
import argparse
import os
import shutil
import subprocess
import sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HARNESSES = ['harness_jerk', 'harness_fold', 'harness_scd']


def run(cmd, cwd, timeout=300):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, 'TIMEOUT'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--unwind', type=int, default=8)
    a = ap.parse_args()
    root = a.root
    pdir = os.path.join(root, 'c', 'proofs')
    cbmc = shutil.which('cbmc')
    print(f'=== CBMC gate (cbmc={"found" if cbmc else "missing: gcc-fuzz fallback"}) ===')
    ok = True
    for h in HARNESSES:
        src = os.path.join(pdir, h + '.c')
        if cbmc:
            cmd = [cbmc, src, f'--unwind', str(a.unwind),
                   '-I', pdir, '--bounds-check', '--div-by-zero-check',
                   '--pointer-check']
            rc, out = run(cmd, root, timeout=600)
            passed = rc == 0 and 'VERIFICATION SUCCESSFUL' in out
            print(f"[{'PASS' if passed else 'FAIL'}] {h} (cbmc proof, rc={rc})")
            if not passed:
                print(out[-1500:])
            ok &= passed
        else:
            ext = '.exe' if os.name == 'nt' else ''
            exe = os.path.join(pdir, h + ext)
            c = ['gcc', '-O1', '-Wall', '-Wextra', '-std=c99', '-I', 'c',
                 '-o', exe, src, '-lm']
            rc, out = run(c, root, timeout=120)
            if rc != 0:
                print(f'[FAIL] {h} compile:\n{out[-1000:]}')
                ok = False
                continue
            rc, out = run([exe], root, timeout=300)
            passed = rc == 0 and 'ALL PASS' in out
            print(f"[{'PASS' if passed else 'FAIL'}] {h} (gcc fuzz, rc={rc})")
            print('   ' + '\n   '.join(out.strip().splitlines()[-4:]))
            ok &= passed
    print('CBMC GATE: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    if not cbmc:
        print('(note: gcc fuzz is a fallback — install CBMC for exhaustive proof; '
              'same asserts, stronger engine)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
