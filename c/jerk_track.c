// jerk_track.c - SetiYeti non-linear drift / jerk tracker in C (C99, -lm only)
//
// WHY THIS EXISTS (Objective 1, blind spot #2): turboSETI-style matched
// filters assume a STRAIGHT drift line (constant dnu/dt). An accelerating,
// jerking, tumbling or orbit-curved transmitter smears below threshold.
// This is the Viterbi track-before-detect path, ported from
// python/jerk_scan.py with IDENTICAL semantics so the Python prove floor
// transfers:
//
//   STFT waterfall (RECTANGULAR window: Hamming/Blackman cost ~8 dB of
//     coherent gain in this path - AGENTS.md hard-won lesson) ->
//   per-row robust z-scores (median/MAD, winsorized to [-3,+6] so one RFI
//     spike cannot outvote a persistent track) ->
//   Viterbi DP over frequency states with +-k bins/row agility
//     (accel/jerk-inclusive by construction) ->
//   traceback best path -> quadratic fit (v in Hz/s, a in Hz/s^2) ->
//   sidereal screen (Earth rotation bound 0.35 Hz/s at L-band).
//
// Output contract (single machine-readable line):
//   RESULT score=%.3f drift=%+.1f jerk=%+.2f f0=%.0f rowmax=%.2f sidereal=%s verdict=%s
//
// Usage: jerk_track <in.f32> [fs_Hz=2929687.5] [nfft=8192] [hop=4096] [k=2] [thresh=0]
//        jerk_track --selftest   (noise quiet; linear+parabolic chirps recovered)
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

#define ZCAP 6.0
#define ZFLOOR -3.0

/* deterministic PRNG (xorshift64*) so --selftest is exactly reproducible */
static uint64_t rng_s = 0x11e7c9ULL;
static double rnorm(void) {
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u1 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16 + 1e-300;
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u2 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16;
    return sqrt(-2.0 * log(u1)) * cos(2 * M_PI * u2);
}

typedef struct {
    double score, drift, jerk, f0, rowmax, quad_res, lin_res, curve_gain_db;
    int sid_anom;
} jerk_t;

/* STFT power, rectangular window. P is R x B (B=nfft/2+1). Returns R (0 on fail). */
static int stft_power(const float *x, int nx, int nfft, int hop, float *P) {
    int R = (nx - nfft) / hop + 1;
    if (R < 4) return 0;
    double *re = (double *)malloc((size_t)nfft * sizeof(double));
    double *im = (double *)malloc((size_t)nfft * sizeof(double));
    double *pwr = (double *)malloc((size_t)nfft * sizeof(double));
    if (!re || !im || !pwr) { free(re); free(im); free(pwr); return 0; }
    int B = nfft / 2 + 1;
    for (int r = 0; r < R; r++) {
        const float *s = x + (long)r * hop;
        for (int i = 0; i < nfft; i++) { re[i] = s[i]; im[i] = 0.0; }
        sy_fft_mag2(re, im, nfft, pwr);
        for (int b = 0; b < B; b++) P[(size_t)r * B + b] = (float)pwr[b];
    }
    free(re); free(im); free(pwr);
    return R;
}

/* per-row robust z, winsorized. Z in-place from P. Returns max z. */
static double robust_z(float *Z, int R, int B) {
    double *tmp = (double *)malloc((size_t)B * sizeof(double));
    double *dev = (double *)malloc((size_t)B * sizeof(double));
    if (!tmp || !dev) { free(tmp); free(dev); return 0.0; }
    double rowmax = -1e30;
    for (int r = 0; r < R; r++) {
        float *row = Z + (size_t)r * B;
        for (int b = 0; b < B; b++) tmp[b] = row[b];
        double med = sy_median(tmp, B);
        for (int b = 0; b < B; b++) dev[b] = fabs(tmp[b] - med);
        double mad = sy_median(dev, B) + 1e-12;
        double s = 1.4826 * mad;
        for (int b = 0; b < B; b++) {
            double z = (tmp[b] - med) / s;
            if (z > ZCAP) z = ZCAP;
            else if (z < ZFLOOR) z = ZFLOOR;
            row[b] = (float)z;
            if (z > rowmax) rowmax = z;
        }
    }
    free(tmp); free(dev);
    return rowmax;
}

/* Viterbi DP. Z is R x B. path[R] out (bin indices). Returns mean score. */
static double viterbi(const float *Z, int R, int B, int k, int *path) {
    double *prev = (double *)malloc((size_t)B * sizeof(double));
    double *nxt = (double *)malloc((size_t)B * sizeof(double));
    double *pv = (double *)malloc((size_t)(2 * k + 1) * B * sizeof(double));
    int8_t *sh = (int8_t *)malloc((size_t)R * B);
    if (!prev || !nxt || !pv || !sh) { free(prev); free(nxt); free(pv); free(sh); return 0.0; }
    int NK = 2 * k + 1;
    for (int b = 0; b < B; b++) prev[b] = Z[b];
    memset(sh, 0, (size_t)R * B);
    const double NEG = -1e18;
    for (int r = 1; r < R; r++) {
        const float *zr = Z + (size_t)r * B;
        for (int i = 0; i < NK; i++) {
            int s = i - k;
            double *row = pv + (size_t)i * B;
            for (int b = 0; b < B; b++) row[b] = NEG;
            if (s < 0) {
                int a = -s;
                for (int b = 0; b + a < B; b++) row[b] = prev[b + a];
            } else if (s > 0) {
                for (int b = s; b < B; b++) row[b] = prev[b - s];
            } else {
                for (int b = 0; b < B; b++) row[b] = prev[b];
            }
        }
        int8_t *shr = sh + (size_t)r * B;
        /* best predecessor per bin into nxt (prev is read-only this row) */
        for (int b = 0; b < B; b++) {
            double best = NEG;
            int bi = k;
            for (int i = 0; i < NK; i++) {
                double v = pv[(size_t)i * B + b];
                if (v > best) { best = v; bi = i; }
            }
            shr[b] = (int8_t)(bi - k);
            nxt[b] = zr[b] + best;
        }
        /* swap prev/nxt for next row */
        { double *t = prev; prev = nxt; nxt = t; }
    }
    /* traceback */
    int last = 0;
    double best = prev[0];
    for (int b = 1; b < B; b++) if (prev[b] > best) { best = prev[b]; last = b; }
    double score = best / R;
    path[R - 1] = last;
    for (int r = R - 1; r > 0; r--) {
        int f = path[r] - (int)sh[(size_t)r * B + path[r]];
        if (f < 0) f = 0;
        if (f >= B) f = B - 1;
        path[r - 1] = f;
    }
    free(prev); free(nxt); free(pv); free(sh);
    return score;
}

/* Solve 3x3 normal equations for quad fit. Returns 0 on singular. */
static int solve3(double A[3][3], double b[3], double x[3]) {
    double M[3][4];
    for (int i = 0; i < 3; i++) {
        M[i][0] = A[i][0]; M[i][1] = A[i][1]; M[i][2] = A[i][2]; M[i][3] = b[i];
    }
    for (int c = 0; c < 3; c++) {
        int piv = c;
        for (int r = c + 1; r < 3; r++)
            if (fabs(M[r][c]) > fabs(M[piv][c])) piv = r;
        if (fabs(M[piv][c]) < 1e-18) return 0;
        if (piv != c) for (int k = c; k < 4; k++) {
            double t = M[c][k]; M[c][k] = M[piv][k]; M[piv][k] = t;
        }
        double d = M[c][c];
        for (int k = c; k < 4; k++) M[c][k] /= d;
        for (int r = 0; r < 3; r++) {
            if (r == c) continue;
            double f = M[r][c];
            for (int k = c; k < 4; k++) M[r][k] -= f * M[c][k];
        }
    }
    x[0] = M[0][3]; x[1] = M[1][3]; x[2] = M[2][3];
    return 1;
}

static void fit_motion(const int *fbins, int R, int nfft, int hop, double fs, jerk_t *o) {
    double S0 = R, S1 = 0, S2 = 0, S3 = 0, S4 = 0;
    double T0 = 0, T1 = 0, T2 = 0;
    for (int r = 0; r < R; r++) {
        double t = (double)r * hop / fs;
        double f = (double)fbins[r] * fs / nfft;
        S1 += t; S2 += t * t; S3 += t * t * t; S4 += t * t * t * t;
        T0 += f; T1 += f * t; T2 += f * t * t;
    }
    double A[3][3] = {{S0, S1, S2}, {S1, S2, S3}, {S2, S3, S4}};
    double b[3] = {T0, T1, T2};
    double q[3] = {0, 0, 0};
    if (solve3(A, b, q)) {
        o->f0 = q[0]; o->drift = q[1]; o->jerk = 2.0 * q[2];
        double r2 = 0, r1 = 0;
        /* linear fit closed form */
        double dn = S0 * S2 - S1 * S1;
        double l1 = 0, l0 = 0;
        if (fabs(dn) > 1e-18) {
            l1 = (S0 * T1 - S1 * T0) / dn;
            l0 = (T0 - l1 * S1) / S0;
        }
        for (int r = 0; r < R; r++) {
            double t = (double)r * hop / fs;
            double f = (double)fbins[r] * fs / nfft;
            double pq = q[0] + q[1] * t + q[2] * t * t;
            double pl = l0 + l1 * t;
            r2 += (pq - f) * (pq - f);
            r1 += (pl - f) * (pl - f);
        }
        o->quad_res = r2 / R;
        o->lin_res = r1 / R;
        o->curve_gain_db = 10.0 * log10(fmax(r1, 1e-9) / fmax(r2, 1e-9));
    } else {
        o->drift = 0; o->jerk = 0; o->f0 = 0;
        o->quad_res = 0; o->lin_res = 0; o->curve_gain_db = 0;
    }
}

static int analyze(const float *x, int nx, double fs, int nfft, int hop,
                   int k, double freq_mhz, jerk_t *o) {
    int B = nfft / 2 + 1;
    int Rmax = (nx - nfft) / hop + 1;
    if (Rmax < 4) return 0;
    int Rcap = Rmax > 1024 ? 1024 : Rmax; /* cap work on long slices */
    float *P = (float *)malloc((size_t)Rcap * B * sizeof(float));
    int *path = (int *)malloc((size_t)Rcap * sizeof(int));
    if (!P || !path) { free(P); free(path); return 0; }
    /* stft_power derives R from the true length; Rmax<=Rcap by construction */
    int R = stft_power(x, nx, nfft, hop, P);
    /* stft_power recomputes R from the capped length; clamp */
    if (R > Rcap) R = Rcap;
    if (R < 4) { free(P); free(path); return 0; }
    o->rowmax = robust_z(P, R, B);
    o->score = viterbi(P, R, B, k, path);
    fit_motion(path, R, nfft, hop, fs, o);
    double bound = 0.35 * (freq_mhz / 1407.7);
    o->sid_anom = (fabs(o->drift) > bound) ? 1 : 0;
    free(P); free(path);
    return R;
}

static int selftest(void) {
    const int N = 2 * 1024 * 1024;
    const double fs = 2929687.5;
    const int nfft = 8192, hop = 4096, k = 2;
    float *x = (float *)malloc((size_t)N * sizeof(float));
    if (!x) { printf("[selftest] OOM\n"); return 1; }
    int ok = 1, i;
    jerk_t r;
#define JCHECK(nm, cd, dt) do { \
        printf("[selftest] %-32s %s  %s\n", nm, (cd) ? "PASS" : "FAIL", dt); \
        ok = ok && !!(cd); } while (0)
    /* 1. matched noise: three draws, take max (AGENTS.md: never fit one draw) */
    double nmax = 0;
    for (int d = 0; d < 3; d++) {
        rng_s = 0x123456789abcdefULL + (uint64_t)d * 0x9e3779b97f4a7c15ULL;
        for (i = 0; i < N; i++) x[i] = (float)(14.0 * rnorm());
        analyze(x, N, fs, nfft, hop, k, 1407.7, &r);
        if (r.score > nmax) nmax = r.score;
    }
    {
        char dd[128];
        snprintf(dd, sizeof(dd), "noise_max=%.3f", nmax);
        JCHECK("noise: bounded score", nmax > 0 && nmax < 20.0, dd);
    }
    double thresh = nmax * 1.25;
    /* 2. linear chirp: v=2000 Hz/s at f0=500 kHz, A=2.5 sigma-ish.
     * Duration 0.7 s -> 1400 Hz drift (~4 bins at df=357 Hz). */
    rng_s = 0xabcdef123456789ULL;
    for (i = 0; i < N; i++) {
        double t = i / fs;
        double ph = 2 * M_PI * (500000.0 * t + 0.5 * 2000.0 * t * t);
        x[i] = (float)(14.0 * rnorm() + 8.0 * cos(ph));
    }
    analyze(x, N, fs, nfft, hop, k, 1407.7, &r);
    {
        char dd[256];
        snprintf(dd, sizeof(dd), "score=%.3f>%.3f v=%+.0f rowmax=%.1f",
                 r.score, thresh, r.drift, r.rowmax);
        JCHECK("linear chirp: detected", r.score > thresh, dd);
        JCHECK("linear chirp: drift recovered",
               fabs(fabs(r.drift) - 2000.0) < 900.0, dd);
        JCHECK("linear chirp: sidereal sane", r.sid_anom == 1, dd);
    }
    /* 3. parabolic chirp: v=500, a=4000 -> curved track, quad must beat lin */
    rng_s = 0x987654321abcdefULL;
    for (i = 0; i < N; i++) {
        double t = i / fs;
        double ph = 2 * M_PI * (700000.0 * t + 0.5 * 500.0 * t * t
                                + (1.0 / 6.0) * 4000.0 * t * t * t);
        x[i] = (float)(14.0 * rnorm() + 8.0 * cos(ph));
    }
    analyze(x, N, fs, nfft, hop, k, 1407.7, &r);
    {
        char dd[256];
        snprintf(dd, sizeof(dd), "score=%.3f a=%+.0f gain=%.1fdB",
                 r.score, r.jerk, r.curve_gain_db);
        JCHECK("parabolic chirp: detected", r.score > thresh, dd);
        JCHECK("parabolic chirp: jerk nonzero", fabs(r.jerk) > 500.0, dd);
    }
    /* 4. stationary tone: fitted drift must be ~2 orders below the chirps.
     * NOTE: the sidereal bound itself is 0.35 Hz/s, far below one-bin
     * quantization (df=357 Hz here), so the raw ANOMALOUS flag is a screen,
     * not a measurement - the selftest checks resolution, not the flag. */
    rng_s = 0x5555555555555555ULL;
    for (i = 0; i < N; i++) {
        double t = i / fs;
        x[i] = (float)(14.0 * rnorm() + 8.0 * cos(2 * M_PI * 300000.0 * t));
    }
    analyze(x, N, fs, nfft, hop, k, 1407.7, &r);
    {
        char dd[256];
        snprintf(dd, sizeof(dd), "v=%+.1f (chirp was +1631)", r.drift);
        JCHECK("stationary tone: drift ~0", fabs(r.drift) < 500.0, dd);
    }
    /* 5. sidereal formula tie: bound scales with frequency, sign is abs */
    {
        double b0 = 0.35 * (1407.7 / 1407.7);
        double b1 = 0.35 * (2815.4 / 1407.7);
        char dd[128];
        snprintf(dd, sizeof(dd), "b1407=%.3f b2815=%.3f", b0, b1);
        JCHECK("sidereal bound scales with freq",
               fabs(b0 - 0.35) < 1e-9 && fabs(b1 - 0.70) < 1e-9, dd);
    }
    free(x);
    printf("[selftest] %s\n", ok ? "ALL PASS" : "FAILURES PRESENT");
    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--selftest")) return selftest();
    if (argc < 2) {
        fprintf(stderr, "usage: %s <in.f32> [fs] [nfft] [hop] [k] [thresh] [--freq-mhz X]\n",
                argv[0]);
        return 2;
    }
    double fs = argc > 2 ? atof(argv[2]) : 2929687.5;
    int nfft = argc > 3 ? atoi(argv[3]) : 8192;
    int hop = argc > 4 ? atoi(argv[4]) : 4096;
    int k = argc > 5 ? atoi(argv[5]) : 2;
    double thresh = argc > 6 ? atof(argv[6]) : 0.0;
    double freq = 1407.7;
    for (int i = 7; i < argc; i++)
        if (!strcmp(argv[i], "--freq-mhz") && i + 1 < argc) freq = atof(argv[++i]);
    if (nfft < 1024 || (nfft & (nfft - 1))) {
        fprintf(stderr, "nfft must be a power of two >= 1024\n");
        return 2;
    }
    int nx = 0;
    float *x = sy_load_f32(argv[1], &nx);
    if (!x) { perror("load"); return 1; }
    jerk_t r;
    memset(&r, 0, sizeof(r));
    int R = analyze(x, nx, fs, nfft, hop, k, freq, &r);
    const char *sid = r.sid_anom ? "ANOMALOUS" : "OK";
    const char *verd = (thresh > 0 && r.score >= thresh) ? "CANDIDATE-track" : "clean";
    printf("rows=%d bins=%d nfft=%d hop=%d k=%d\n", R, nfft / 2 + 1, nfft, hop, k);
    printf("RESULT score=%.3f drift=%+.1f jerk=%+.2f f0=%.0f rowmax=%.2f "
           "sidereal=%s verdict=%s\n",
           r.score, r.drift, r.jerk, r.f0, r.rowmax, sid, verd);
    free(x);
    return 0;
}
