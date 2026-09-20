"""verify_veto.py — the smt2/veto_disposition.smt2 theorems prove the SPEC; this
proves the SPEC matches the SHIPPED CODE (else the proofs are vacuous).

1. MODEL TIE: transcription of score_slice's E/net/disp tail (using the REAL
   structure_score for S — no duplication of the engineeredness logic),
   differentially fuzzed against rfi_veto.score_slice on 3000 random rows.
   Any disp mismatch = transcription drift = FAIL.
2. PROPERTY TIE: the three safety properties re-checked against the REAL code:
   hard-recurring+unstructured => BLOCK; CANDIDATE => persist&(eng|multi);
   engineered+recurring never hard-BLOCKs.
Usage: python z3/verify_veto.py [--root .] [--n 3000]
"""
import argparse, os, random, sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import rfi_veto as V


def model_disp(E, S, persist, multi, n_seen):
    """Transcription of score_slice tail (end of the EARTH/structure/cat blocks)."""
    engineered = S >= 0.25
    hard = (n_seen >= 3 and not engineered)
    net = E - S
    if hard or net >= 0.50:
        return 'BLOCK'
    if net < 0.15 and persist and (engineered or multi):
        return 'CANDIDATE'
    return 'WATCH'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--n', type=int, default=3000)
    a = ap.parse_args()
    rng = random.Random(777)
    cf = V.make_chan_freq(1407.71484375, -187.5, 64)
    bad = p1 = p2 = p3 = 0
    nP1 = nP2 = nP3 = 0
    for i in range(a.n):
        ch = rng.randint(0, 63)
        al = rng.choice([179.0, 358.0, 900000.0, rng.uniform(1, 5e6)])
        n_seen = rng.choice([0, 1, 2, 3, 5, 12])
        persist = rng.random() < 0.5
        multi = rng.random() < 0.5
        flags = {k: ('1' if rng.random() < 0.3 else '0')
                 for k in ('comb', 'frame', 'nongauss', 'pol')}
        vm = '0.75/CANDIDATE-structure' if rng.random() < 0.3 else '0.00/noise-like'
        row = {'block': '0', 'chan': str(ch), 'pol': '0', 'spec_ratio': '2.0',
               'spec_bin': '1', 'fam_best': '5.0', 'fam_hz': str(al),
               'fam_tag': 'Y4', 'vm_sign': vm, 'vm_diff': '0.00/noise-like',
               'verdict': 'FAM-HIT'}
        row.update(flags)
        S, _ = V.structure_score(row)
        E = 0.4  # fixed probe offset; disp tail depends on E only via net
        # rebuild a ctx that yields plantable evidence + catalog
        ck = f'T:{V.alpha_bucket(al)}:x'
        cat = {'features': {}}
        if n_seen:
            cat['features'][ck] = {'sig': 'x', 'alpha': al, 'n_seen': 0,
                                   'structured': False}
            # score_slice reads prev n_seen from class_key, not ck; emulate:
        ctx = {'chan_freq': cf,
               'evidence': {('0', str(ch)): {'persist': '1' if persist else '0',
                                             'multichan': '1' if multi else '0'}},
               'catalog': {'features': {f'T:{V.alpha_bucket(al)}:{V.alloc(cf(ch))[1]}':
                                        {'sig': 'x', 'alpha': al, 'n_seen': n_seen,
                                         'structured': S >= 0.25}}},
               'target': 'T', 'on_idx': [(ch, al)], 'off_idx': [(ch, al)]}
        E_real, S_real, net, disp, _, _ = V.score_slice(row, ctx)
        fam = model_disp(E_real, S_real, persist, multi, n_seen)
        mine = {'BLOCK:earth-likely': 'BLOCK'}.get(disp, disp)
        if mine != fam:
            bad += 1
            if bad <= 3:
                print(f'  MISMATCH E={E_real:.2f} S={S_real:.2f} p={persist} m={multi} '
                      f'n={n_seen}: code={disp} model={fam}')
        # property ties on real verdicts
        eng = S_real >= 0.25
        if n_seen >= 3 and not eng:
            nP1 += 1
            if not disp.startswith('BLOCK'):
                p1 += 1
        if disp == 'CANDIDATE':
            nP2 += 1
            if not (persist and (eng or multi)):
                p2 += 1
        if eng and n_seen >= 3:
            nP3 += 1
            if disp.startswith('BLOCK') and 'HARD' in str(disp):
                p3 += 1
    print(f'[tie] model-vs-code disp on {a.n} fuzz rows: {a.n - bad}/{a.n} agree')
    print(f"[{'PASS' if p1 == 0 else 'FAIL'}] P1 recurring+unstructured=>BLOCK "
          f'({nP1} cases, {p1} viol)')
    print(f"[{'PASS' if p2 == 0 else 'FAIL'}] P2 CANDIDATE=>persist&(eng|multi) "
          f'({nP2} cases, {p2} viol)')
    print(f"[{'PASS' if p3 == 0 else 'FAIL'}] P3 engineered+recurring never hard-blocks "
          f'({nP3} cases, {p3} viol)')
    ok = bad == 0 and p1 == 0 and p2 == 0 and p3 == 0
    print('VERIFY_VETO: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
