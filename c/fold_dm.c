// fold_dm.c - SetiYeti periodicity + single-pulse detector in C (C99, -lm only)
//
// WHY THIS EXISTS (Objective 1, blind spots #1-2): the pipeline was deaf to
// rotation-powered pulsars (no folding) and to FRB-like shots (no DM sweep).
// This ports python/pulsar_fold.py + python/transient_dm.py with IDENTICAL
// thresholds so the Python prove floors transfer:
//
//   FOLD: power envelope -> decimate to ~6 kHz -> Hann -> FFT periodogram ->
//     running-median whiten (red-noise robust) -> harmonic sum
//     H(f0)=sum_h P(h*f0)/sqrt(h), h=1..8 -> MAD sigma -> 16-sigma gate.
//     (8-draw noise max ~10.8; weakest inject 3400+.)
//   DM: 16-sample filterbank (naive DFT-16, 9 bands) -> per-band median
//     normalise -> cold-plasma dedispersion over 32 DM trials (0..1000) ->
//     boxcar matched filter over widths [1..128] -> MAD sigma -> 14-sigma
//     gate. (Noise max ~10.8 over DM x width trials; weakest inject 168.)
//     Single-coarse-channel proxy: catches bright narrow shots; full-band
//     coherent dedispersion stays the follow-up lever.
//
// Output contract (single machine-readable line):
//   RESULT fold_det=%d fold_f=%.2f fold_sig=%.1f dm_det=%d dm=%.0f dm_sig=%.1f dm_w=%d verdict=%s
//
// Usage: fold_dm <in.f32> [fs_Hz=2929687.5] [mode=both|fold|dm] [--f0-mhz 1400]
//        fold_dm --selftest   (noise quiet; pulsar + shot fire)
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

#define FOLD_FMIN 1.0
#define FOLD_FMAX 2000.0
#define FOLD_HARMS 8
#define FOLD_SIGMA 16.0
#define DM_THRESH 14.0
#define DM_TRIALS 32
#define DM_MAX 1000.0
#define DM_MSUB 16
#define K_DM 4.15e-3

static uint64_t rng_s = 0xF01D511EULL;
static double rnorm(void) {
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u1 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16 + 1e-300;
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u2 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16;
    return sqrt(-2.0 * log(u1)) * cos(2 * M_PI * u2);
}

static int next_pow2(int n) {
    int p = 1;
    while (p < n) p <<= 1;
    return p;
}

/* ---------------- FOLD ---------------- */
typedef struct { int det; double f, sig; } fold_t;

static int fold_detect(const float *x, int nx, double fs, fold_t *o) {
    int dec = (int)(fs / 6000.0 + 0.5);
    if (dec < 1) dec = 1;
    int ne = nx / dec;
    if (ne < 64 * 2) return 0;
    if (ne > 65536) ne = 65536; /* cap work: first ~10 s carry any rotation */
    double *env = (double *)malloc((size_t)ne * sizeof(double));
    if (!env) return 0;
    for (int i = 0; i < ne; i++) {
        double s = 0;
        for (int j = 0; j < dec; j++) {
            double v = x[(long)i * dec + j];
            s += v * v;
        }
        env[i] = s / dec;
    }
    double m = 0;
    for (int i = 0; i < ne; i++) m += env[i];
    m /= ne;
    for (int i = 0; i < ne; i++) {
        double h = 0.5 * (1.0 - cos(2 * M_PI * i / (ne - 1)));
        env[i] = (env[i] - m) * h;
    }
    int nfft = next_pow2(ne * 4);
    if (nfft > 131072) nfft = 131072;
    if (nfft < 16) nfft = 16;
    double *re = (double *)calloc((size_t)nfft, sizeof(double));
    double *im = (double *)calloc((size_t)nfft, sizeof(double));
    double *pwr = (double *)malloc((size_t)nfft * sizeof(double));
    if (!re || !im || !pwr) { free(env); free(re); free(im); free(pwr); return 0; }
    for (int i = 0; i < ne; i++) re[i] = env[i];
    sy_fft_mag2(re, im, nfft, pwr);
    int nh = nfft / 2 + 1;
    /* whiten by running median (width 201, edge-clamped) */
    double *Q = (double *)malloc((size_t)nh * sizeof(double));
    double *win = (double *)malloc(201 * sizeof(double));
    if (!Q || !win) { free(env); free(re); free(im); free(pwr); free(Q); free(win); return 0; }
    for (int i = 0; i < nh; i++) {
        for (int j = 0; j < 201; j++) {
            int k = i - 100 + j;
            if (k < 0) k = 0;
            if (k >= nh) k = nh - 1;
            win[j] = pwr[k];
        }
        double cont = sy_median(win, 201);
        if (cont <= 0) cont = 1e-30;
        Q[i] = pwr[i] / cont;
    }
    double env_fs = fs / dec;
    double df = env_fs / nfft;
    int i0 = (int)ceil(FOLD_FMIN / df);
    if (i0 < 2) i0 = 2;
    int i1 = (int)floor(FOLD_FMAX / df);
    if (i1 >= nh - FOLD_HARMS - 1) i1 = nh - FOLD_HARMS - 2;
    if (i1 <= i0) { free(env); free(re); free(im); free(pwr); free(Q); free(win); return 0; }
    int nf = i1 - i0 + 1;
    double *H = (double *)malloc((size_t)nf * sizeof(double));
    if (!H) { free(env); free(re); free(im); free(pwr); free(Q); free(win); return 0; }
    for (int i = 0; i < nf; i++) {
        double f = (i0 + i) * df;
        double s = 0;
        for (int h = 1; h <= FOLD_HARMS; h++) {
            int idx = (int)(f * h / df + 0.5);
            if (idx < 0) idx = 0;
            if (idx >= nh) idx = nh - 1;
            s += Q[idx] / sqrt((double)h);
        }
        H[i] = s;
    }
    double med = sy_median(H, nf);
    double *ad = (double *)malloc((size_t)nf * sizeof(double));
    for (int i = 0; i < nf; i++) ad[i] = fabs(H[i] - med);
    double mad = sy_median(ad, nf);
    free(ad);
    if (!(mad > 0)) mad = 1e-12;
    double best_sig = -1e30, best_f = 0;
    for (int i = 0; i < nf; i++) {
        double sig = (H[i] - med) / (1.4826 * mad);
        if (sig > best_sig) { best_sig = sig; best_f = (i0 + i) * df; }
    }
    o->sig = best_sig;
    o->f = best_f;
    o->det = (best_sig >= FOLD_SIGMA) ? 1 : 0;
    free(env); free(re); free(im); free(pwr); free(Q); free(win); free(H);
    return 1;
}

/* ---------------- DM ---------------- */
typedef struct { int det; double dm, sig; int width, t; } dm_t;

static const int WIDTHS[] = {1, 2, 4, 8, 16, 32, 64, 128};
#define NW (sizeof(WIDTHS)/sizeof(WIDTHS[0]))

static int dm_detect(const float *x, int nx, double fs, double f0_mhz, dm_t *o) {
    const int msub = DM_MSUB;
    int nt = nx / msub;
    if (nt < 256) return 0;
    if (nt > 131072) nt = 131072; /* cap work on long slices */
    const int nb = msub / 2 + 1;  /* 9 */
    double *P = (double *)malloc((size_t)nt * nb * sizeof(double));
    if (!P) return 0;
    /* DFT-16 filterbank power */
    for (int t = 0; t < nt; t++) {
        const float *s = x + (long)t * msub;
        for (int k = 0; k < nb; k++) {
            double re = 0, im = 0;
            for (int n = 0; n < msub; n++) {
                double a = 2 * M_PI * k * n / msub;
                re += s[n] * cos(a);
                im -= s[n] * sin(a);
            }
            P[(size_t)t * nb + k] = re * re + im * im;
        }
    }
    /* per-band median normalise + demean */
    double *col = (double *)malloc((size_t)nt * sizeof(double));
    if (!col) { free(P); return 0; }
    for (int b = 0; b < nb; b++) {
        for (int t = 0; t < nt; t++) col[t] = P[(size_t)t * nb + b];
        double med = sy_median(col, nt);
        if (med <= 0) med = 1e-30;
        double mu = 0;
        for (int t = 0; t < nt; t++) { P[(size_t)t * nb + b] /= med; mu += P[(size_t)t * nb + b]; }
        mu /= nt;
        for (int t = 0; t < nt; t++) P[(size_t)t * nb + b] -= mu;
    }
    /* sub-band centre freqs (GHz) across the 2.93 MHz coarse channel */
    double bw = 2.93;
    double fc[16];
    double ftop = 0;
    for (int b = 0; b < nb; b++) {
        double f = (f0_mhz - bw / 2) + bw * (b + 0.5) / nb;
        fc[b] = f / 1000.0;
        if (fc[b] > ftop) ftop = fc[b];
    }
    double dt = msub / fs;
    double *ts = (double *)malloc((size_t)nt * sizeof(double));
    double *flt = (double *)malloc((size_t)nt * sizeof(double));
    double *tmp = (double *)malloc((size_t)nt * sizeof(double));
    double *dv = (double *)malloc((size_t)nt * sizeof(double));
    if (!ts || !flt || !tmp || !dv) {
        free(P); free(col); free(ts); free(flt); free(tmp); free(dv);
        return 0;
    }
    double best_sig = 0;
    double best_dm = 0;
    int best_w = 1, best_t = 0;
    for (int di = 0; di < DM_TRIALS; di++) {
        double dm = DM_MAX * di / (DM_TRIALS - 1);
        int sh[16];
        for (int b = 0; b < nb; b++)
            sh[b] = (int)(K_DM * dm * (1.0 / (fc[b] * fc[b]) - 1.0 / (ftop * ftop)) / dt);
        for (int t = 0; t < nt; t++) {
            double s = 0;
            for (int b = 0; b < nb; b++) {
                int src = t + sh[b];
                /* roll semantics (python np.roll): wrap, so edge shots keep
                 * their energy instead of falling off the array end. */
                src %= nt;
                if (src < 0) src += nt;
                s += P[(size_t)src * nb + b];
            }
            ts[t] = s;
        }
        for (size_t wi = 0; wi < NW; wi++) {
            int w = WIDTHS[wi];
            if (w >= nt) continue;
            double inv = 1.0 / sqrt((double)w);
            /* centered boxcar with zero outside (python
             * np.convolve(ts, ones(w)/sqrt(w), mode='same') semantics):
             * edges see fewer samples but the same 1/sqrt(w), so they
             * are suppressed, never enhanced. A causal 1/sqrt(t+1)
             * normalisation inflates the first w samples and forged
             * 14.4-sigma edge peaks on pure noise (measured). */
            int half = (w - 1) / 2;
            for (int t = 0; t < nt; t++) {
                double s = 0;
                int lo = t - half;
                for (int j = 0; j < w; j++) {
                    int idx = lo + j;
                    if (idx >= 0 && idx < nt) s += ts[idx];
                }
                flt[t] = s * inv;
            }
            for (int t = 0; t < nt; t++) tmp[t] = flt[t];
            double med = sy_median(tmp, nt);
            for (int t = 0; t < nt; t++) dv[t] = fabs(flt[t] - med);
            double mad = sy_median(dv, nt);
            if (!(mad > 0)) mad = 1e-12;
            for (int t = 0; t < nt; t++) {
                double s = (flt[t] - med) / (1.4826 * mad);
                if (s > best_sig) {
                    best_sig = s; best_dm = dm; best_w = w; best_t = t;
                }
            }
        }
    }
    o->sig = best_sig; o->dm = best_dm; o->width = best_w; o->t = best_t;
    o->det = (best_sig >= DM_THRESH) ? 1 : 0;
    free(P); free(col); free(ts); free(flt); free(tmp); free(dv);
    return 1;
}

static int selftest(void) {
    const int N = 2 * 524288;
    const double fs = 2929687.5;
    float *x = (float *)malloc((size_t)N * sizeof(float));
    double *dn = (double *)malloc((size_t)N * sizeof(double));
    if (!x || !dn) { printf("[selftest] OOM\n"); return 1; }
    int ok = 1, i;
#define FCHECK(nm, cd, dt) do { \
        printf("[selftest] %-34s %s  %s\n", nm, (cd) ? "PASS" : "FAIL", dt); \
        ok = ok && !!(cd); } while (0)
    /* rebuild rnorm stream deterministically per case via reseed */
    rng_s = 0x123456789abcdefULL;
    for (i = 0; i < N; i++) { double v = 14.0 * rnorm(); dn[i] = v; x[i] = (float)v; }
    {
        fold_t f = {0, 0, 0};
        dm_t d = {0, 0, 0, 0, 0};
        fold_detect(x, N, fs, &f);
        dm_detect(x, N, fs, 1400.0, &d);
        char dd[160];
        snprintf(dd, sizeof(dd), "fold_sig=%.1f dm_sig=%.1f", f.sig, d.sig);
        FCHECK("noise: fold quiet", !f.det, dd);
        FCHECK("noise: dm quiet", !d.det, dd);
    }
    /* pulsar-like train at 29.7 Hz, duty 0.03, 6-sigma pulses */
    rng_s = 0xabcdef123456789ULL;
    for (i = 0; i < N; i++) dn[i] = 14.0 * rnorm();
    for (i = 0; i < N; i++) {
        double t = i / fs;
        double ph = fmod(t * 29.7, 1.0);
        double dd2 = (ph - 0.5) / 0.03;
        double pulse = exp(-0.5 * dd2 * dd2);
        x[i] = (float)(dn[i] + 6.0 * pulse * 14.0);
    }
    {
        fold_t f = {0, 0, 0};
        fold_detect(x, N, fs, &f);
        char dd[160];
        snprintf(dd, sizeof(dd), "f=%.2f sig=%.1f", f.f, f.sig);
        FCHECK("pulsar 29.7 Hz: fold fires",
               f.det && fabs(f.f - 29.7) / 29.7 < 0.05, dd);
    }
    /* bright narrow shot, width 8, 12 sigma */
    rng_s = 0x7777777777777777ULL;
    for (i = 0; i < N; i++) x[i] = (float)(14.0 * rnorm());
    for (i = 0; i < 8; i++) x[300000 + i] += (float)(12.0 * 14.0);
    {
        dm_t d = {0, 0, 0, 0, 0};
        dm_detect(x, N, fs, 1400.0, &d);
        char dd[160];
        snprintf(dd, sizeof(dd), "sig=%.1f w=%d dm=%.0f", d.sig, d.width, d.dm);
        FCHECK("narrow shot: dm fires", d.det, dd);
    }
    free(x); free(dn);
    printf("[selftest] %s\n", ok ? "ALL PASS" : "FAILURES PRESENT");
    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc > 1 && (!strcmp(argv[1], "--selftest") || !strcmp(argv[1], "--prove")))
        return selftest();
    if (argc < 2) {
        fprintf(stderr, "usage: %s <in.f32> [fs] [mode=both|fold|dm] [--f0-mhz X]\n",
                argv[0]);
        return 2;
    }
    double fs = argc > 2 ? atof(argv[2]) : 2929687.5;
    const char *mode = argc > 3 ? argv[3] : "both";
    double f0 = 1400.0;
    for (int i = 4; i < argc; i++)
        if (!strcmp(argv[i], "--f0-mhz") && i + 1 < argc) f0 = atof(argv[++i]);
    int nx = 0;
    float *x = sy_load_f32(argv[1], &nx);
    if (!x) { perror("load"); return 1; }
    fold_t f = {0, 0, 0};
    dm_t d = {0, 0, 0, 1, 0};
    if (!strcmp(mode, "both") || !strcmp(mode, "fold")) fold_detect(x, nx, fs, &f);
    if (!strcmp(mode, "both") || !strcmp(mode, "dm")) dm_detect(x, nx, fs, f0, &d);
    const char *verd = (f.det || d.det) ? "PERIODIC/SHOT" : "no period/shot";
    printf("fold_det=%d fold_f=%.2fHz fold_sig=%.1f dm_det=%d dm=%.0f dm_sig=%.1f dm_w=%d\n",
           f.det, f.f, f.sig, d.det, d.dm, d.sig, d.width);
    printf("RESULT fold_det=%d fold_f=%.2f fold_sig=%.1f dm_det=%d dm=%.0f "
           "dm_sig=%.1f dm_w=%d verdict=%s\n",
           f.det, f.f, f.sig, d.det, d.dm, d.sig, d.width, verd);
    free(x);
    return 0;
}
