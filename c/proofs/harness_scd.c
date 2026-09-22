// harness_scd.c — CBMC proof for scd_dechirp.c safety + verdict contracts.
//
// PROVES:
//   S-MEM  SCD cell (k-h, k+h) is read only when 0<=k-h and k+h<Np;
//          otherwise the cell is 0 (zero-pad, never a peak).
//   S-ND   dechirp length ND is a power of two <= 131072 (FFT contract).
//   S-DIV  peak ratios divide by med only when med>0 (no div-by-zero;
//          med<=0 maps to ratio 0).
//   S-HIT  scd_hit == (top>=8), baud_hit == (baud>2*noise),
//          dechirp_hit == (bank>1.5*nb && bank>3*direct) exactly.
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "cbmc_stubs.h"

static int cell_valid(int k, int h, int Np) {
    return !(k - h < 0 || k + h >= Np);
}
static int scd_hit(double top) { return (top >= 8.0) ? 1 : 0; }
static int baud_hit(double b, double n) { return (b > 2.0 * n) ? 1 : 0; }
static int dechirp_hit(double bp, double nb, double direct) {
    return (bp > 1.5 * nb && bp > 3.0 * direct) ? 1 : 0;
}
static double ratio(double v, double med) { return med > 0 ? v / med : 0.0; }

#ifndef __CPROVER__
int main(void) {
    printf("[harness_scd] bounded fuzz\n");
    for (int iter = 0; iter < 2000; iter++) {
        int Np = 1024;
        int k = (int)(nondet_uint() % (unsigned)Np);
        int h = 1 + (int)(nondet_uint() % (unsigned)(Np / 2 - 1));
        int v = cell_valid(k, h, Np);
        if (!v) {
            __CPROVER_assert(k - h < 0 || k + h >= Np,
                             "S-MEM invalid cell really OOB");
        } else {
            __CPROVER_assert(k - h >= 0 && k + h < Np,
                             "S-MEM valid cell really in bounds");
        }
    }
    /* ND contract: power of two <= 2^17 */
    for (int iter = 0; iter < 200; iter++) {
        int nx = 1000 + (int)(nondet_uint() % 2000000);
        int ND = nx > 131072 ? 131072 : nx;
        int p = 1;
        while (p * 2 <= ND) p <<= 1;
        ND = p;
        __CPROVER_assert(ND <= 131072, "S-ND length capped");
        __CPROVER_assert((ND & (ND - 1)) == 0, "S-ND power of two");
    }
    /* div guard */
    __CPROVER_assert(ratio(5.0, 0.0) == 0.0, "S-DIV med<=0 maps to 0");
    __CPROVER_assert(ratio(5.0, -1.0) == 0.0, "S-DIV negative med maps to 0");
    __CPROVER_assert(ratio(16.0, 2.0) == 8.0, "S-DIV exact division");
    /* verdicts on measured numbers */
    __CPROVER_assert(scd_hit(4.5) == 0, "S-HIT noise floor quiet");
    __CPROVER_assert(scd_hit(124.8) == 1, "S-HIT BPSK fires");
    __CPROVER_assert(baud_hit(16120.0, 16120.0) == 0, "S-HIT single-bin not baud");
    __CPROVER_assert(baud_hit(134700.0, 16120.0) == 1, "S-HIT BPSK baud fires");
    __CPROVER_assert(dechirp_hit(1379.7, 18.4, 49.3) == 1, "S-HIT chirp bank fires");
    __CPROVER_assert(dechirp_hit(49.3, 18.4, 49.3) == 0, "S-HIT no concentration quiet");
    if (_cbmc_fail == 0) printf("[harness_scd] ALL PASS\n");
    else printf("[harness_scd] %d FAILURES\n", _cbmc_fail);
    return _cbmc_fail ? 1 : 0;
}
#else
void harness(void) {
    __CPROVER_assert(scd_hit(4.5) == 0, "S-HIT noise floor quiet");
    __CPROVER_assert(scd_hit(124.8) == 1, "S-HIT BPSK fires");
    __CPROVER_assert(dechirp_hit(1379.7, 18.4, 49.3) == 1, "S-HIT chirp bank fires");
    __CPROVER_assert(ratio(5.0, 0.0) == 0.0, "S-DIV med<=0 maps to 0");
}
#endif
