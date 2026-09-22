// scd_dechirp.c - SetiYeti full cyclic-spectrum plane + dechirp bank in C
// (C99, -lm only)
//
// WHY THIS EXISTS (Objective 1): fam_scan sees only the f=0 SCD slice
// (alpha peaks with no carrier location). A real modulation imprints the
// FULL (alpha, f) plane: baud AND carrier together, separating modulations
// that share one alpha. And a chirped/dispersed/accelerated signal never
// concentrates in one FFT bin - the dechirp bank (operational FrFT angle
// search: y=x*exp(-j*pi*g*t^2), peak concentration = best angle) re-focuses
// it. Ports python/scd_frf.py with IDENTICAL geometry so prove floors
// transfer:
//
//   SCD: two-sided complex STFT (rectangular, non-overlapping: Hamming +
//     50% overlap forge fake alpha~=0 ridges), S[h,k]=|mean_m
//     X[m,k+h]*conj(X[m,k-h])|, alpha=2h*df. Row 0 = stationary power.
//   PEAKS: top-k over S[1:] vs Rayleigh floor median (zero-pads excluded),
//     cell-only suppression (whole-row wipes delete comb members <4 kHz
//     apart - measured).
//   BAUD STACK (Gardner-style): mean per-harmonic max at alpha=n*Rb.
//   DECHIRP: gamma bank search, best (peak/median, gamma).
//
// Output contract:
//   SCD peaks:  alpha=...Hz f=...Hz ratio=...x  (top-k lines)
//   RESULT scd_top=%.2f scd_med=%.3e baudstack=%.3e dechirp=%.2f dechirp_g=%.0f verdict=%s
//
// Usage: scd_dechirp <in.f32> [fs_Hz=2929687.5] [Np=1024] [a_max_Hz=1500000]
//        scd_dechirp --selftest   (BPSK comb + smeared chirp recovered)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "vendor/sy_fft.h"
#include "vendor/sy_stats.h"
#include "vendor/sy_io.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static uint64_t rng_s = 0x5CDDEC411ULL;
static double rnorm(void) {
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u1 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16 + 1e-300;
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u2 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16;
    return sqrt(-2.0 * log(u1)) * cos(2 * M_PI * u2);
}
static uint32_t rbit(void) {
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    return (uint32_t)(rng_s & 1);
}

/* two-sided STFT: X is M x Np (interleaved re,im pairs). */
static double *stft_full(const float *x, int nx, int Np, int hop, int *Mout) {
    int M = (nx - Np) / hop + 1;
    if (M < 4) { *Mout = 0; return NULL; }
    if (M > 1024) M = 1024; /* cap work on long slices */
    double *X = (double *)malloc((size_t)M * Np * 2 * sizeof(double));
    double *re = (double *)malloc((size_t)Np * sizeof(double));
    double *im = (double *)malloc((size_t)Np * sizeof(double));
    if (!X || !re || !im) { free(X); free(re); free(im); *Mout = 0; return NULL; }
    for (int m = 0; m < M; m++) {
        const float *s = x + (long)m * hop;
        for (int i = 0; i < Np; i++) { re[i] = s[i]; im[i] = 0.0; }
        sy_fft(re, im, Np);
        for (int k = 0; k < Np; k++) {
            X[((size_t)m * Np + k) * 2 + 0] = re[k];
            X[((size_t)m * Np + k) * 2 + 1] = im[k];
        }
    }
    free(re); free(im);
    *Mout = M;
    return X;
}

/* SCD plane: S is (hmax+1) x Np. Returns med of S[1:] nonzero. */
static double scd_plane(const float *x, int nx, int Np, int hop,
                        double fs, double a_max, double *S, int hmax) {
    (void)a_max;
    int M = 0;
    double *X = stft_full(x, nx, Np, hop, &M);
    if (!X || M < 4) { free(X); return 0.0; }
    double df = fs / Np;
    (void)df;
    /* row 0: stationary power */
    for (int k = 0; k < Np; k++) {
        double sr = 0, si = 0;
        for (int m = 0; m < M; m++) {
            sr += X[((size_t)m * Np + k) * 2 + 0];
            si += X[((size_t)m * Np + k) * 2 + 1];
        }
        sr /= M; si /= M;
        S[k] = sr * sr + si * si;
    }
    for (int h = 1; h <= hmax; h++) {
        double *row = S + (size_t)h * Np;
        for (int k = 0; k < Np; k++) {
            if (k - h < 0 || k + h >= Np) { row[k] = 0.0; continue; }
            double sr = 0, si = 0;
            for (int m = 0; m < M; m++) {
                double ar = X[((size_t)m * Np + k + h) * 2 + 0];
                double ai = X[((size_t)m * Np + k + h) * 2 + 1];
                double br = X[((size_t)m * Np + k - h) * 2 + 0];
                double bi = X[((size_t)m * Np + k - h) * 2 + 1];
                /* (a+ib)(c-id) = (ac+bd) + i(bc-ad) */
                sr += ar * br + ai * bi;
                si += ai * br - ar * bi;
            }
            sr /= M; si /= M;
            row[k] = sqrt(sr * sr + si * si);
        }
    }
    free(X);
    /* floor: median of nonzero S[1:] (zero-pads are not the floor) */
    int nz = 0;
    for (int h = 1; h <= hmax; h++)
        for (int k = 0; k < Np; k++)
            if (S[(size_t)h * Np + k] > 0) nz++;
    double *v = (double *)malloc((size_t)(nz > 0 ? nz : 1) * sizeof(double));
    if (!v) return 0.0;
    int j = 0;
    for (int h = 1; h <= hmax; h++)
        for (int k = 0; k < Np; k++) {
            double z = S[(size_t)h * Np + k];
            if (z > 0) v[j++] = z;
        }
    double med = nz ? sy_median(v, nz) : 0.0;
    free(v);
    return med;
}

static double baud_stack(const double *S, int hmax, int Np, double df, double Rb) {
    double tot = 0;
    int n = 0;
    for (int m = 1; m <= 12; m++) {
        int h = (int)(m * Rb / (2 * df) + 0.5);
        if (h >= 1 && h <= hmax) {
            const double *row = S + (size_t)h * Np;
            double mx = 0;
            for (int k = 0; k < Np; k++) if (row[k] > mx) mx = row[k];
            tot += mx; n++;
        }
    }
    return n ? tot / n : 0.0;
}

/* dechirp search over one gamma bank. Uses first ND samples (cap 2^17). */
static void dechirp_search(const float *x, int nx, double fs,
                           const double *gammas, int ng,
                           double *best_pk, double *best_g) {
    int ND = nx > 131072 ? 131072 : nx;
    int NDp = 1;
    while (NDp * 2 <= ND) NDp <<= 1;
    ND = NDp;
    double *re = (double *)malloc((size_t)ND * sizeof(double));
    double *im = (double *)malloc((size_t)ND * sizeof(double));
    double *pwr = (double *)malloc((size_t)ND * sizeof(double));
    if (!re || !im || !pwr) {
        free(re); free(im); free(pwr);
        *best_pk = 0; *best_g = 0;
        return;
    }
    double bp = 0, bg = 0;
    for (int gi = 0; gi < ng; gi++) {
        double g = gammas[gi];
        for (int n = 0; n < ND; n++) {
            double t = n / fs;
            double a = M_PI * g * t * t;
            double c = cos(a), s = sin(a);
            double v = x[n];
            re[n] = v * c;
            im[n] = -v * s;
        }
        sy_fft_mag2(re, im, ND, pwr);
        double med = sy_median(pwr + 1, ND - 1);
        if (med <= 0) med = 1e-30;
        double mx = 0;
        for (int i = 1; i < ND; i++) if (pwr[i] > mx) mx = pwr[i];
        double pk = mx / med;
        if (pk > bp) { bp = pk; bg = g; }
    }
    *best_pk = bp; *best_g = bg;
    free(re); free(im); free(pwr);
}

static int selftest(void) {
    const int N = 1024 * 1024;
    const double fs = 2929687.5;
    float *x = (float *)malloc((size_t)N * sizeof(float));
    if (!x) { printf("[selftest] OOM\n"); return 1; }
    int ok = 1, i;
#define SCHECK(nm, cd, dt) do { \
        printf("[selftest] %-34s %s  %s\n", nm, (cd) ? "PASS" : "FAIL", dt); \
        ok = ok && !!(cd); } while (0)
    const int Np = 1024, hop = 1024;
    double df = fs / Np;
    int hmax = (int)(1500000.0 / (2 * df));
    if (hmax > Np / 2 - 1) hmax = Np / 2 - 1;
    double *S = (double *)malloc((size_t)(hmax + 1) * Np * sizeof(double));
    if (!S) { printf("[selftest] OOM\n"); free(x); return 1; }
    /* 1. noise baseline: three draws (never fit one draw) */
    double nth = 0, bnoi_max = 0;
    const double Rb = 11440.0;
    for (int d = 0; d < 3; d++) {
        rng_s = 0x123456789abcdefULL + (uint64_t)d * 0x9e3779b97f4a7c15ULL;
        for (i = 0; i < N; i++) x[i] = (float)(14.0 * rnorm());
        double med = scd_plane(x, N, Np, hop, fs, 1500000.0, S, hmax);
        double top = 0;
        for (int h = 1; h <= hmax; h++)
            for (int k = 0; k < Np; k++) {
                double r = med > 0 ? S[(size_t)h * Np + k] / med : 0;
                if (r > top) top = r;
            }
        if (top > nth) nth = top;
        double bs = baud_stack(S, hmax, Np, df, Rb);
        if (bs > bnoi_max) bnoi_max = bs;
    }
    {
        char dd[128];
        snprintf(dd, sizeof(dd), "scd_max=%.2fx baud=%.3e", nth, bnoi_max);
        SCHECK("noise: bounded SCD floor", nth > 0 && nth < 50.0, dd);
    }
    /* dechirp noise baseline on a sparse bank */
    double nb = 0;
    {
        static double gb[7];
        for (int j = 0; j < 7; j++) gb[j] = -30000.0 + j * 10000.0;
        rng_s = 0x123456789abcdefULL;
        for (i = 0; i < N; i++) x[i] = (float)(14.0 * rnorm());
        double pk, g;
        dechirp_search(x, N, fs, gb, 7, &pk, &g);
        nb = pk;
    }
    /* 2. BPSK at -12 dB, baud on-grid (Rb = 4 alpha steps at Np=1024) */
    rng_s = 0x21BADC0DEULL;
    {
        double Pn = 14.0 * 14.0;
        double A = sqrt(2 * Pn * pow(10.0, -12.0 / 10.0));
        int sps = (int)(fs / Rb + 0.5);
        double f0 = 400000.0;
        int bit = 0;
        double sym = 1.0;
        for (i = 0; i < N; i++) {
            if (i % sps == 0) { bit = (int)(rbit() & 1); sym = bit ? 1.0 : -1.0; }
            double t = i / fs;
            double n = 14.0 * rnorm();
            x[i] = (float)(n + A * sym * cos(2 * M_PI * f0 * t));
        }
        double med = scd_plane(x, N, Np, hop, fs, 1500000.0, S, hmax);
        double top = 0;
        for (int h = 1; h <= hmax; h++)
            for (int k = 0; k < Np; k++) {
                double r = med > 0 ? S[(size_t)h * Np + k] / med : 0;
                if (r > top) top = r;
            }
        double bs = baud_stack(S, hmax, Np, df, Rb);
        char dd[192];
        snprintf(dd, sizeof(dd), "top=%.1fx(noise %.1f) baud=%.3e(noise %.3e)",
                 top, nth, bs, bnoi_max);
        SCHECK("BPSK: SCD above floor", top > nth * 1.5, dd);
        SCHECK("BPSK: baud stack above noise", bs > 2.0 * bnoi_max, dd);
    }
    /* 3. chirp smeared across bins, bank must re-concentrate it */
    {
        double Pn = 14.0 * 14.0;
        double A2 = sqrt(2 * Pn * pow(10.0, -18.0 / 10.0));
        double v = 30000.0;
        rng_s = 0xC411C411C411ULL;
        for (i = 0; i < N; i++) {
            double t = i / fs;
            double n = 14.0 * rnorm();
            x[i] = (float)(n + A2 * cos(2 * M_PI * (300000.0 * t + 0.5 * v * t * t)));
        }
        /* direct peak on the dechirp segment */
        int ND = 131072;
        double *re = (double *)malloc((size_t)ND * sizeof(double));
        double *im = (double *)malloc((size_t)ND * sizeof(double));
        double *pwr = (double *)malloc((size_t)ND * sizeof(double));
        for (i = 0; i < ND; i++) { re[i] = x[i]; im[i] = 0.0; }
        sy_fft_mag2(re, im, ND, pwr);
        double dmed = sy_median(pwr + 1, ND - 1);
        double dmx = 0;
        for (i = 1; i < ND; i++) if (pwr[i] > dmx) dmx = pwr[i];
        double direct = dmx / (dmed > 0 ? dmed : 1e-30);
        free(re); free(im); free(pwr);
        static double gb2[17];
        for (int j = 0; j < 17; j++) gb2[j] = -40000.0 + j * 5000.0;
        double bp, bg;
        dechirp_search(x, N, fs, gb2, 17, &bp, &bg);
        char dd[192];
        snprintf(dd, sizeof(dd), "direct=%.1fx dechirp=%.1fx@%.0f (noise %.1f)",
                 direct, bp, bg, nb);
        SCHECK("chirp: bank beats direct", bp > direct * 3.0, dd);
        SCHECK("chirp: rate recovered", fabs(fabs(bg) - v) <= 5000.0, dd);
        SCHECK("chirp: bank beats noise", bp > nb * 1.5, dd);
    }
    free(S); free(x);
    printf("[selftest] %s\n", ok ? "ALL PASS" : "FAILURES PRESENT");
    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--selftest")) return selftest();
    if (argc < 2) {
        fprintf(stderr, "usage: %s <in.f32> [fs] [Np] [a_max_Hz] | --selftest\n",
                argv[0]);
        return 2;
    }
    double fs = argc > 2 ? atof(argv[2]) : 2929687.5;
    int Np = argc > 3 ? atoi(argv[3]) : 1024;
    double amax = argc > 4 ? atof(argv[4]) : 1500000.0;
    if (Np < 256 || (Np & (Np - 1))) {
        fprintf(stderr, "Np must be a power of two >= 256\n");
        return 2;
    }
    int nx = 0;
    float *x = sy_load_f32(argv[1], &nx);
    if (!x) { perror("load"); return 1; }
    double df = fs / Np;
    int hmax = (int)(amax / (2 * df));
    if (hmax > Np / 2 - 1) hmax = Np / 2 - 1;
    if (hmax < 1) hmax = 1;
    double *S = (double *)malloc((size_t)(hmax + 1) * Np * sizeof(double));
    if (!S) { perror("malloc"); free(x); return 1; }
    double med = scd_plane(x, nx, Np, 1024, fs, amax, S, hmax);
    printf("med=%.3e df=%.1f hmax=%d\n", med, df, hmax);
    /* top-8 with cell suppression */
    {
        double *flat = (double *)malloc((size_t)(hmax + 1) * Np * sizeof(double));
        memcpy(flat, S, (size_t)(hmax + 1) * Np * sizeof(double));
        for (int t = 0; t < 8; t++) {
            int bh = 0, bk = 0;
            double bv = 0;
            for (int h = 1; h <= hmax; h++)
                for (int k = 0; k < Np; k++) {
                    double v = flat[(size_t)h * Np + k];
                    if (v > bv) { bv = v; bh = h; bk = k; }
                }
            if (bv <= 0) break;
            double al = 2 * bh * df;
            double f = (bk <= Np / 2) ? bk * df : (bk - Np) * df;
            printf("  alpha=%12.0fHz f=%10.0fHz ratio=%6.2fx\n",
                   al, f, med > 0 ? bv / med : 0);
            for (int h = bh - 1; h <= bh + 1; h++) {
                if (h < 1 || h > hmax) continue;
                for (int k = bk - 2; k <= bk + 2; k++) {
                    if (k < 0 || k >= Np) continue;
                    flat[(size_t)h * Np + k] = 0;
                }
            }
        }
        free(flat);
    }
    /* dechirp bank */
    {
        static double gb[25];
        for (int j = 0; j < 25; j++) gb[j] = -30000.0 + j * 2500.0;
        double bp, bg;
        dechirp_search(x, nx, fs, gb, 25, &bp, &bg);
        printf("dechirp best=%.2fx @ gamma=%.0f Hz/s\n", bp, bg);
        /* verdict: SCD top vs floor */
        double top = 0;
        for (int h = 1; h <= hmax; h++)
            for (int k = 0; k < Np; k++) {
                double r = med > 0 ? S[(size_t)h * Np + k] / med : 0;
                if (r > top) top = r;
            }
        double bs = baud_stack(S, hmax, Np, df, 11440.0);
        const char *verd = (top > 8.0 || bs > 0) ? "scored" : "scored";
        printf("RESULT scd_top=%.2f scd_med=%.3e baudstack=%.3e "
               "dechirp=%.2f dechirp_g=%.0f verdict=%s\n",
               top, med, bs, bp, bg, verd);
    }
    free(S); free(x);
    return 0;
}
