/* sy_stats.h — SetiYeti vendored streaming stats (single header, C99).
 * Median via quickselect (O(n) average, no full sort), MAD, kurtosis/tail,
 * harmonic-comb rule shared with structure_pass.py. Deps: -lm only.
 * Deterministic.
 */
#ifndef SY_STATS_H
#define SY_STATS_H
#include <math.h>
#include <stdlib.h>
#include <string.h>

static inline void sy_swap_d(double *a, double *b) {
    double t = *a; *a = *b; *b = t;
}

/* Lomuto quickselect: k-th smallest of v[0..n-1] (reorders v). */
static inline double sy_quickselect(double *v, int n, int k) {
    int lo = 0, hi = n - 1;
    while (lo < hi) {
        double pivot = v[hi];
        int s = lo;
        for (int i = lo; i < hi; i++) {
            if (v[i] < pivot) { sy_swap_d(&v[i], &v[s]); s++; }
        }
        sy_swap_d(&v[s], &v[hi]);
        if (k == s) return v[s];
        else if (k < s) hi = s - 1;
        else lo = s + 1;
    }
    return v[lo];
}

static inline double sy_median(double *v, int n) {
    if (n <= 0) return 0.0;
    double *t = (double *)malloc((size_t)n * sizeof(double));
    if (!t) return 0.0;
    memcpy(t, v, (size_t)n * sizeof(double));
    double m;
    if (n & 1) {
        m = sy_quickselect(t, n, n / 2);
    } else {
        double a = sy_quickselect(t, n, n / 2 - 1);
        /* second select on reordered array is still valid for k>=prev */
        double b = sy_quickselect(t, n, n / 2);
        m = 0.5 * (a + b);
    }
    free(t);
    return m;
}

/* excess kurtosis + 4-sigma tail excess over first `st` samples (cap for speed) */
static inline void sy_nongauss(const float *x, int nx, double *kurt, double *tailx) {
    int st = nx > 524288 ? 524288 : nx;
    double m = 0.0;
    for (int i = 0; i < st; i++) m += x[i];
    m /= (double)st;
    double v = 0.0;
    for (int i = 0; i < st; i++) { double d = x[i] - m; v += d * d; }
    v /= (double)st;
    double sd = sqrt(v);
    if (!(sd > 0.0)) { *kurt = 0.0; *tailx = 0.0; return; }
    double k = 0.0;
    long tail = 0;
    for (int i = 0; i < st; i++) {
        double z = (x[i] - m) / sd;
        k += z * z * z * z;
        if (z > 4.0 || z < -4.0) tail++;
    }
    *kurt = k / st - 3.0;
    *tailx = ((double)tail / (double)st) / 6.33e-5;
}

/* THE COMB RULE on peak (bin,ratio) lists. Mirrors structure_pass.py exactly. */
typedef struct { int bin; double ratio; } sy_peak_t;
static inline int sy_comb_rule(const sy_peak_t *pk, int npk, int B,
                               double *score, int *f0bin) {
    int best_n = 0, best_b = 0;
    double best_s = 0.0;
    for (int b0 = 2; b0 <= 128; b0++) {
        double tot = 0.0;
        int n = 0;
        for (int m = 1; m <= 8; m++) {
            int tgt = m * b0;
            if (tgt > B) break;
            int lo = tgt - 1 < 2 ? 2 : tgt - 1;
            int hi = tgt + 1 > B ? B : tgt + 1;
            int hit = -1;
            for (int i = 0; i < npk; i++) {
                if (pk[i].bin >= lo && pk[i].bin <= hi) { hit = i; break; }
            }
            if (hit >= 0) { tot += pk[hit].ratio; n++; }
        }
        double s = n ? tot / n : 0.0;
        if (n >= 3 && (n > best_n || (n == best_n && s > best_s))) {
            best_n = n; best_s = s; best_b = b0;
        }
    }
    *score = best_s;
    *f0bin = best_b;
    return (best_n >= 3 && best_s >= 6.0) ? best_n : 0;
}
#endif
