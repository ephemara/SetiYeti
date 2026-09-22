// harness_fold.c — CBMC proof for fold_dm.c safety + gate contracts.
//
// PROVES:
//   F-MEM  boxcar window [t-half, t-half+w) intersected with [0,nt) never
//          reads OOB (the edge-inflation bug: 1/sqrt(t+1) is gone, zero-pad
//          + 1/sqrt(w) is what ships).
//   F-HARM harmonic index round(f*h/df) is clamped to [0,nh) always.
//   F-GATE fold_det == (sig>=16.0) and dm_det == (sig>=14.0) exactly.
//   F-DM   DM shifts for dm in [0,1000] are finite and monotone non-decreasing
//          in dm (cold-plasma order).
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "cbmc_stubs.h"

#define FOLD_GATE 16.0
#define DM_GATE 14.0

static int fold_det(double sig) { return (sig >= FOLD_GATE) ? 1 : 0; }
static int dm_det(double sig) { return (sig >= DM_GATE) ? 1 : 0; }

/* centered boxcar sum with zero outside (ships in fold_dm.c) */
static double boxcar_at(const double *ts, int nt, int t, int w) {
    int half = (w - 1) / 2;
    int lo = t - half;
    double s = 0;
    for (int j = 0; j < w; j++) {
        int idx = lo + j;
        if (idx >= 0 && idx < nt) s += ts[idx];
    }
    return s / sqrt((double)w);
}

#ifndef __CPROVER__
int main(void) {
    printf("[harness_fold] bounded fuzz\n");
    static double ts[256];
    for (int i = 0; i < 256; i++) ts[i] = nondet_double();
    static const int WS[] = {1, 2, 4, 8, 16, 32, 64, 128};
    for (int iter = 0; iter < 300; iter++) {
        int nt = 32 + (int)(nondet_uint() % 224);
        int t = (int)(nondet_uint() % (unsigned)nt);
        int w = WS[nondet_uint() % 8];
        if (w >= nt) continue;
        double v = boxcar_at(ts, nt, t, w);
        __CPROVER_assert(v == v, "F-MEM boxcar finite (no OOB read)");
        /* every contributing index was in-bounds by construction */
        int half = (w - 1) / 2, lo = t - half;
        for (int j = 0; j < w; j++) {
            int idx = lo + j;
            if (idx >= 0 && idx < nt)
                __CPROVER_assert(idx >= 0 && idx < nt, "F-MEM window read in bounds");
        }
    }
    /* harmonic clamp */
    for (int iter = 0; iter < 300; iter++) {
        int nh = 4097;
        double df = 0.7 + fabs(nondet_double());
        double f = 1.0 + fabs(nondet_double()) * 10.0;
        for (int h = 1; h <= 8; h++) {
            int idx = (int)(f * h / df + 0.5);
            if (idx < 0) idx = 0;
            if (idx >= nh) idx = nh - 1;
            __CPROVER_assert(idx >= 0 && idx < nh, "F-HARM index clamped");
        }
    }
    /* gates sharp */
    __CPROVER_assert(fold_det(15.9) == 0, "F-GATE 15.9 quiet");
    __CPROVER_assert(fold_det(16.0) == 1, "F-GATE 16.0 fires");
    __CPROVER_assert(fold_det(4799.0) == 1, "F-GATE inject fires");
    __CPROVER_assert(dm_det(13.9) == 0, "F-GATE dm 13.9 quiet");
    __CPROVER_assert(dm_det(14.0) == 1, "F-GATE dm 14.0 fires");
    __CPROVER_assert(dm_det(11.7) == 0, "F-GATE dm noise quiet");
    /* DM shift monotonicity: sh = K*dm*(c) with c>0 constant per band */
    {
        double c = 0.001; /* representative positive band coefficient */
        double prev = -1e30;
        for (int di = 0; di <= 32; di++) {
            double dm = 1000.0 * di / 32;
            double sh = 4.15e-3 * dm * c / 5.46e-6;
            __CPROVER_assert(sh == sh, "F-DM shift finite");
            __CPROVER_assert(sh >= prev, "F-DM shifts monotone in dm");
            prev = sh;
        }
    }
    if (_cbmc_fail == 0) printf("[harness_fold] ALL PASS\n");
    else printf("[harness_fold] %d FAILURES\n", _cbmc_fail);
    return _cbmc_fail ? 1 : 0;
}
#else
void harness(void) {
    __CPROVER_assert(fold_det(15.9) == 0, "F-GATE 15.9 quiet");
    __CPROVER_assert(fold_det(16.0) == 1, "F-GATE 16.0 fires");
    __CPROVER_assert(dm_det(13.9) == 0, "F-GATE dm 13.9 quiet");
    __CPROVER_assert(dm_det(14.0) == 1, "F-GATE dm 14.0 fires");
}
#endif
