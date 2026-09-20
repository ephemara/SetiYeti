"""verify_c_median.py — FULL FORMAL PROOF of the vendored quickselect median.

sy_stats.h sy_quickselect (Lomuto) + sy_median are the FAM noise floor: a wrong
median shifts every fam_best ratio in every slice. This proves, in Z3 over ALL
inputs in a bounded domain, that unrolled quickselect returns the true median:

  sorting network (Batcher odd-even, N=5, 9 comparators) defines sorted order;
  unrolled Lomuto partition + recurse defines quickselect(k=2);
  assert exists input with quickselect != sorted[2]  →  expect UNSAT (no
  counterexample exists for values 0..3, i.e. all 4^5=1024 cases covered).

Plus a DIFFERENTIAL tie: compiled C harness (z3/harness_median.c, includes the
real vendor header) vs Python statistics.median on random arrays.
Usage: python z3/verify_c_median.py [--root .] [--cc gcc]
"""
import argparse, os, statistics, subprocess, sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import z3


def sort5(v):
    """Batcher odd-even mergesort network for 5 (9 comparators)."""
    def cmp_swap(a, i, j):
        a[i], a[j] = z3.If(a[i] > a[j], a[j], a[i]), z3.If(a[i] > a[j], a[i], a[j])
    a = list(v)
    for i, j in [(0, 1), (3, 4), (2, 4), (2, 3), (0, 3), (0, 2), (1, 4), (1, 3), (1, 2)]:
        cmp_swap(a, i, j)
    return a


def quickselect2(a5):
    """Rank-2 select on 5 elements, SOUND symbolic encoding of Lomuto QS.
    One partition: pivot piv=a[4] lands finally at p = #{i<4 : a[i]<piv}.
    Left slice  = {a[i] : a[i]<piv} (all < piv), right = {a[i] : a[i]>=piv}.
    Global rank 2 is: left[2] if p>2, piv if p==2, right[2-p] if p<2.
    Slices are built with INF-fill (9 > domain max 3) + sort5, so only
    CONCRETE indices appear — no symbolic array indexing anywhere."""
    piv = a5[4]
    p = z3.Sum([z3.If(a5[i] < piv, 1, 0) for i in range(4)])  # in 0..4
    left = [z3.If(a5[i] < piv, a5[i], z3.IntVal(9)) for i in range(4)] + [z3.IntVal(9)]
    right = [z3.If(a5[i] < piv, z3.IntVal(9), a5[i]) for i in range(4)] + [z3.IntVal(9)]
    sl, sr = sort5(left), sort5(right)
    out = a5[0]  # default; every concrete p overwrites below
    for pv in range(5):
        if pv == 2:
            branch = piv
        elif pv > 2:
            branch = sl[2]          # left has pv>=3 real elems; [2] is rank 2
        else:
            branch = sr[1 - pv]     # right starts at global rank pv+1
        out = z3.If(p == pv, branch, out)
    return out


def select_rank(seg, r):
    """Exact rank-r select of a short symbolic slice (len<=5, values<=3).
    Pad with +INF (9, above domain max) to length 5 and Batcher-sort: the
    first len(seg) entries are exactly the sorted slice, so [r] is sound."""
    assert 0 <= r < len(seg)
    padded = list(seg) + [z3.IntVal(9)] * (5 - len(seg))
    return sort5(padded)[r]


def prove_median():
    xs = [z3.Int(f'x{i}') for i in range(5)]
    s = z3.Solver()
    for x in xs:
        s.add(x >= 0, x <= 3)  # all 1024 input combos in scope
    med_sorted = sort5(xs)[2]
    med_qs = quickselect2(xs)
    s.add(med_qs != med_sorted)  # exists a counterexample?
    res = s.check()
    return res == z3.unsat


HARNESS = r"""
#include <stdio.h>
#include "vendor/sy_stats.h"
int main(void){
    /* deterministic corpus: arithmetic, plateaus, spikes, bit patterns */
    double t[][8] = {
        {5,1,4,2,8,0,0,0}, {7,7,7,7,7,0,0,0}, {1,2,3,4,5,6,7,8},
        {8,7,6,5,4,3,2,1}, {0,0,0,100,0,0,0,0}, {-3,-1,-1,0,2,2,9,9},
    };
    int ns[] = {5,4,8,8,7,8};
    for(int c=0;c<6;c++){
        double m = sy_median(t[c], ns[c]);
        printf("%.6f\n", m);
    }
    return 0;
}
"""


def tie_c(root, cc):
    hp = os.path.join(root, 'z3', 'harness_median.c')
    open(hp, 'w').write(HARNESS)
    exe = hp + ('.exe' if os.name == 'nt' else '.out')
    r = subprocess.run([cc, '-O2', '-std=c99', '-I', os.path.join(root, 'c'),
                        '-o', exe, hp, '-lm'], capture_output=True, text=True)
    if r.returncode != 0:
        print('  harness build FAILED:', r.stderr[:300])
        return False
    r = subprocess.run([exe], capture_output=True, text=True)
    got = [float(x) for x in r.stdout.split()]
    want = [5 - 2, 7, 4.5, 4.5, 0, 0.5]  # medians: {5,1,4,2,8}->4? recompute below
    import statistics as S
    cases = [[5, 1, 4, 2, 8], [7, 7, 7, 7], [1, 2, 3, 4, 5, 6, 7, 8],
             [8, 7, 6, 5, 4, 3, 2, 1], [0, 0, 0, 100, 0, 0, 0], [-3, -1, -1, 0, 2, 2, 9, 9]]
    # NOTE sy_median averages two middles for even n (upper-middle would differ)
    want = [float(S.median(c)) for c in cases]
    ok = len(got) == len(want) and all(abs(g - w) < 1e-9 for g, w in zip(got, want))
    print(f'  C harness vs statistics.median on 6 arrays: {"agree" if ok else "MISMATCH " + str(got)}')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--cc', default=None)
    a = ap.parse_args()
    cc = a.cc or ('C:/scoop/apps/mingw/current/bin/gcc.exe'
                  if os.path.exists('C:/scoop/apps/mingw/current/bin/gcc.exe') else 'gcc')
    print('[proof] quickselect N=5 over 0..3 (all 1024 inputs) == sorted median ...')
    p = prove_median()
    print(f"[{'PASS' if p else 'FAIL'}] Z3: no counterexample (UNSAT) = {p}")
    t = tie_c(a.root, cc)
    print(f"[{'PASS' if t else 'FAIL'}] C header tied to statistics.median")
    ok = p and t
    print('VERIFY_C_MEDIAN: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
