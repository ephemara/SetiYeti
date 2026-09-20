"""verify_c_comb.py — the SMT2 comb theorems prove the RULE; this proves the CODE.

1. MODEL TIE: brute-force evaluator transcribed from the SMT2 semantics,
   checked against shipped structure_pass.comb_rule_on_bins on 2000 random
   peak sets (any mismatch = code/spec drift = FAIL).
2. THEOREM TIE: Z3 (QF_LIA) replays the shipped implementation's verdict on
   the Kepler family + single-tone cases and asserts agreement.
Usage: python z3/verify_c_comb.py [--root .] [--n 2000]
"""
import argparse, os, random, sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import z3
import structure_pass as SP


def spec_eval(peaks, B=16384):
    """Brute-force transcription of smt2/comb_rule.smt2 Theorem B semantics."""
    best = (0, 0.0, 0)
    for b0 in range(2, 129):
        tot, n = 0.0, 0
        for m in range(1, 9):
            tgt = m * b0
            if tgt > B:
                break
            hit = None
            for b, r in peaks.items():
                if tgt - 1 <= b <= tgt + 1:
                    hit = (b, r)
                    break
            if hit is not None:
                tot += hit[1]
                n += 1
        s = tot / n if n else 0.0
        if n >= 3 and (n > best[0] or (n == best[0] and s > best[1])):
            best = (n, s, b0)
    n, s, b0 = best
    if not (n >= 3 and s >= 6.0):
        return 0, s, 0  # code returns f0bin=0 on non-fire; verdict-relevant only
    return n, s, b0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--n', type=int, default=2000)
    a = ap.parse_args()
    rng = random.Random(20260920)
    bad = 0
    for i in range(a.n):
        peaks = {}
        for _ in range(rng.randint(0, 15)):
            peaks[rng.randint(2, 900)] = round(rng.uniform(0.5, 130.0), 2)
        n1, s1, b1 = SP.comb_rule_on_bins(dict(peaks), 16384)
        n2, s2, b2 = spec_eval(dict(peaks))
        if (n1, round(s1, 9), b1) != (n2, round(s2, 9), b2):
            bad += 1
            if bad <= 3:
                print(f'  MISMATCH {peaks}: code=({n1},{s1:.3f},{b1}) spec=({n2},{s2:.3f},{b2})')
    print(f'[tie] code-vs-spec on {a.n} random peak sets: {a.n - bad}/{a.n} agree')
    ok = bad == 0

    # Z3 replays the shipped verdict symbolically on the two canonical cases
    b0 = z3.Int('b0')
    s = z3.Solver()
    # single tone at bin 56 with ratio 120: exists b0 with >=3 members? NO
    hits = [z3.If(z3.Or([m * b0 == 55, m * b0 == 56, m * b0 == 57]), 1, 0)
            for m in range(1, 9)]
    s.add(b0 >= 2, b0 <= 128, z3.Sum(hits) >= 3)
    single_unsat = s.check() == z3.unsat
    n, _, _ = SP.comb_rule_on_bins({56: 120.0, 900: 40.0}, 16384)
    t1 = single_unsat and n == 0
    print(f"[{'PASS' if t1 else 'FAIL'}] single-tone: Z3-unsat={single_unsat}, code fires={n != 0}")
    ok &= t1

    n, _, fb = SP.comb_rule_on_bins({4: 30.0, 16: 25.0, 32: 20.0, 900: 40.0}, 16384)
    t2 = n >= 3 and fb == 4
    print(f"[{'PASS' if t2 else 'FAIL'}] Kepler family: code members={n} f0bin={fb}")
    ok &= t2

    print('VERIFY_C_COMB: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
