"""verify_xeno.py - the smt2/xeno_rules.smt2 theorems prove the SPEC; this
proves the SPEC matches the SHIPPED CODE (else the proofs are vacuous).

1. LADDER TIE: independent transcription of xeno_pass.grade_slice,
   differentially fuzzed against the real function on 5000 random flag
   dicts. Any grade mismatch = transcription drift = FAIL.
2. PROPERTY TIE: X1/X2/X3/X5 re-checked against REAL grade outputs:
   I5 => persist&xvm&eng&sky; eng&sky&exo => grade>=I4;
   unflagged => I0; not-eng => I0|I1.
Usage: python z3/verify_xeno.py [--root .] [--n 5000]
"""
import argparse
import os
import random
import sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import xeno_pass as X


def model_grade(f):
    """Independent transcription of the ladder (re-derived from the doc)."""
    eng = f['eng_v'] or f['x2']
    sky = f['scint'] or f['pol_sky'] or (f['persist'] and f['on_only'])
    exo = f['negdm'] or f['primes'] or f['precursor']
    strong = exo or f['doppler'] or f['xvm_cand']
    if not f['flagged']:
        return 'I0'
    if not eng:
        return 'I1'
    if not sky:
        return 'I2'
    if not strong:
        return 'I3'
    if not (f['xvm_cand'] and f['persist']):
        return 'I4'
    return 'I5'


def to_code_flags(f):
    S = 0.5 if f['eng_v'] else 0.0
    return {'flagged': int(f['flagged']), 'S': S,
            'xcount': 2 if f['x2'] else 0,
            'scint': int(f['scint']), 'pol_sky': int(f['pol_sky']),
            'persist': int(f['persist']), 'on_only': int(f['on_only']),
            'negdm': int(f['negdm']), 'primes': int(f['primes']),
            'precursor': int(f['precursor']),
            'doppler_anom': int(f['doppler']),
            'xvm_cand': int(f['xvm_cand'])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--n', type=int, default=5000)
    a = ap.parse_args()
    rng = random.Random(20260920)
    keys = ('flagged', 'eng_v', 'x2', 'scint', 'pol_sky', 'persist',
            'on_only', 'negdm', 'primes', 'precursor', 'doppler', 'xvm_cand')
    bad = 0
    v1 = v2 = v3 = v5 = 0
    n1 = n2 = n3 = n5 = 0
    order = {'I0': 0, 'I1': 1, 'I2': 2, 'I3': 3, 'I4': 4, 'I5': 5}
    for _ in range(a.n):
        f = {k: rng.random() < 0.35 for k in keys}
        mine = model_grade(f)
        real = X.grade_slice(to_code_flags(f))
        if mine != real:
            bad += 1
            if bad <= 3:
                print(f'  MISMATCH {f}: code={real} model={mine}')
        eng = f['eng_v'] or f['x2']
        sky = f['scint'] or f['pol_sky'] or (f['persist'] and f['on_only'])
        exo = f['negdm'] or f['primes'] or f['precursor']
        if real == 'I5':
            n1 += 1
            if not (f['persist'] and f['xvm_cand'] and eng and sky):
                v1 += 1
        if f['flagged'] and eng and sky and exo:
            n2 += 1
            if order[real] < 4:
                v2 += 1
        if not f['flagged']:
            n3 += 1
            if real != 'I0':
                v3 += 1
        if not eng:
            n5 += 1
            if real not in ('I0', 'I1'):
                v5 += 1
    print(f'[tie] model-vs-code grade on {a.n} fuzz rows: {a.n - bad}/{a.n} agree')
    print(f"[{'PASS' if v1 == 0 else 'FAIL'}] X1 I5=>persist&xvm&eng&sky "
          f'({n1} cases, {v1} viol)')
    print(f"[{'PASS' if v2 == 0 else 'FAIL'}] X2 eng&sky&exo=>grade>=I4 "
          f'({n2} cases, {v2} viol)')
    print(f"[{'PASS' if v3 == 0 else 'FAIL'}] X3 unflagged=>I0 "
          f'({n3} cases, {v3} viol)')
    print(f"[{'PASS' if v5 == 0 else 'FAIL'}] X5 not-eng=>I0|I1 "
          f'({n5} cases, {v5} viol)')
    ok = bad == 0 and v1 == 0 and v2 == 0 and v3 == 0 and v5 == 0
    print('VERIFY_XENO: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
