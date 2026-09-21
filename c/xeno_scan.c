// xeno_scan.c - SetiYeti XENO microscopic + exotic-structure scanner (C99, -lm only)
//
// WHY THIS EXISTS: comb_scan answers "is there a baud comb?". The bystander
// hunt needs a FINER sieve: structure that lives below a single SCD peak -
// burstylanjitter, quantized tone ladders, clock-grade coherence, and
// dispersion-order violations that cold plasma FORBIDS. One pass, five
// orthogonal markers, all calibrated against matched noise:
//
//   SK      spectral kurtosis per freq group (Gaussian => 1.0; pulsed/RFI => >>1;
//           steady tone => dip toward 0). The microscopic intermittency meter.
//   COH     zero-crossing interval regularity mean/std (white noise ~1;
//           tone/square/clock => large). Oscillation coherence, not power.
//   LADDER  cepstral peak (equally spaced tones => quefrency peak). A frequency
//           comb is engineering until proven otherwise; pulsars do not do this.
//   DMSIGN  sub-band arrival order: normal plasma => high freq FIRST (dt/df<0,
//           sign +1). dt/df>0 with r^2>=0.5 is a NEGATIVE-DM event: superluminal
//           group delay, instrumental ... or genuinely new physics. NEVER veto
//           silently - report and escalate.
//   IMPULS  robust max-z + 4-sigma tail excess (spike/shot catcher).
//
// Output contract (single machine-readable line):
//   RESULT skdev=%.3f skflag=%d coh=%.2f cohflag=%d ladder=%.2f ladderq=%d
//          dm_sign=%+d dm_r2=%.3f impuls=%d maxz=%.1f kurt=%.2f tailx=%.2f
//
// Usage: xeno_scan <in.f32> [fs_Hz=2929687.5]
//        xeno_scan --selftest   (prove: each marker fires on its inject and
//                               stays quiet on matched noise; rc=0 on PASS)
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "vendor/sy_fft.h"   /* cached-twiddle FFT core */
#include "vendor/sy_stats.h" /* quickselect median */
#include "vendor/sy_io.h"    /* 64-bit .f32 loader */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define SEG 4096
#define HOP 2048
#define NB (SEG/2+1)
#define NGROUP 64            /* SK groups of 32 bins */
#define SK_FLAG_DEV 0.50     /* per-bin |SK-1| above this = deviant bin */
#define SK_FLAG_FRAC 0.02    /* >=2% deviant bins = non-stationary band */
#define COH_FLAG 6.0         /* interval mean/std above this = coherent */
#define LADDER_FLAG 20.0     /* cepstral peak ratio above this = ladder.
                                Calibrated over 6 seeds: noise 9-12, random
                                impulses 9-15 (heavy-tail lift), 5-tone ladder
                                ~110. 20 sits in the clean gap. A comb is
                                reported, never interpreted, here - the veto
                                decides attribution. */
#define DM_NSB 8             /* sub-bands for the arrival-order fit */
#define DM_R2_MIN 0.80       /* arrival-order fit quality for a DM verdict.
                                4 bands give a 29% null r^2>0.5 rate (measured
                                false +1 on 10 random spikes); 8 bands push the
                                null tail to ~0.5% and chirps still hit 0.98. */
#define DM_SPAN_MIN 4.0      /* peak-time spread across band, in STFT frames.
                                Spikes peak all bands in one frame (span ~0);
                                a band-sweeping chirp spans hundreds. */

/* deterministic PRNG (xorshift64*) so --selftest is exactly reproducible */
static uint64_t rng_s = 0x123456789abcdefULL;
static double rnorm(void) {
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u1 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16 + 1e-300;
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    double u2 = ((rng_s * 0x2545F4914F6CDD1DULL) >> 11) * 1.1102230246251565e-16;
    return sqrt(-2.0 * log(u1)) * cos(2 * M_PI * u2);
}

typedef struct {
    double skdev; double skfrac; int skflag;
    double coh; int cohflag;
    double ladder; int ladderq;
    int dm_sign; double dm_r2;
    int impuls; double maxz;
    double kurt, tailx;
} xeno_t;

/* STFT power: P[t][b], t<nseg frames, b<NB bins. Rectangular window
 * (detection-first: no window loss on coherent structure). */
static double *stft_power(const float *x, int nx, int *nseg_out) {
    int nseg = (nx - SEG) / HOP + 1;
    if (nseg < 8) { *nseg_out = 0; return NULL; }
    if (nseg > 512) nseg = 512;             /* cap work on long slices */
    double *P = (double *)malloc((size_t)nseg * NB * sizeof(double));
    double *re = (double *)malloc(SEG * sizeof(double));
    double *im = (double *)malloc(SEG * sizeof(double));
    double *pwr = (double *)malloc(SEG * sizeof(double));
    if (!P || !re || !im || !pwr) {
        free(P); free(re); free(im); free(pwr);
        *nseg_out = 0; return NULL;
    }
    for (int t = 0; t < nseg; t++) {
        const float *s = x + t * HOP;
        for (int i = 0; i < SEG; i++) { re[i] = s[i]; im[i] = 0.0; }
        sy_fft_mag2(re, im, SEG, pwr);
        for (int b = 0; b < NB; b++) P[(size_t)t * NB + b] = pwr[b];
    }
    free(re); free(im); free(pwr);
    *nseg_out = nseg;
    return P;
}

static void analyze(const float *x, int nx, double fs, xeno_t *r) {
    (void)fs;
    memset(r, 0, sizeof(*r));

    /* ---- time-domain stats: kurtosis, tail, max-z, zero-crossing ---- */
    sy_nongauss(x, nx, &r->kurt, &r->tailx);
    {
        int st = nx > 524288 ? 524288 : nx;
        double m = 0.0;
        for (int i = 0; i < st; i++) m += x[i];
        m /= st;
        double v = 0.0;
        for (int i = 0; i < st; i++) { double d = x[i] - m; v += d * d; }
        v /= st;
        double sd = sqrt(v);
        double mz = 0.0;
        if (sd > 0) {
            for (int i = 0; i < st; i++) {
                double z = fabs((x[i] - m) / sd);
                if (z > mz) mz = z;
            }
        }
        r->maxz = mz;
        r->impuls = (mz > 8.0 || r->tailx > 3.0) ? 1 : 0;
    }
    {   /* zero-crossing interval regularity */
        int st = nx > 524288 ? 524288 : nx;
        long last = -1, n = 0;
        double sm = 0.0, s2 = 0.0;
        int prev = (x[0] > 0) ? 1 : -1;
        for (int i = 1; i < st; i++) {
            int cur = (x[i] > 0) ? 1 : ((x[i] < 0) ? -1 : prev);
            if (cur != prev) {
                if (last >= 0) {
                    double iv = (double)(i - last);
                    n++; sm += iv; s2 += iv * iv;
                }
                last = i; prev = cur;
            }
        }
        if (n > 100) {
            double mu = sm / n, va = s2 / n - mu * mu;
            r->coh = (va > 0) ? mu / sqrt(va) : 999.0;
        } else {
            r->coh = 0.0;
        }
        r->cohflag = (r->coh >= COH_FLAG) ? 1 : 0;
    }

    /* ---- STFT-derived markers ---- */
    int nseg = 0;
    double *P = stft_power(x, nx, &nseg);
    if (!P) return;
    double M = (double)nseg;

    {   /* spectral kurtosis PER BIN: SK=(M+1)/(M-1)*(M*S2/S1^2-1).
         * Per-bin power of Gaussian noise is exponential => SK~1. Grouped
         * sums are Gamma-distributed and sit at SK~1/k (a measured 0.98
         * deviation on pure noise) - so never group before the estimator.
         * Flag = FRACTION of deviant bins: broadband cadence trips hundreds
         * of bins, a few tones trip a few, noise trips ~none. */
        double worst = 0.0;
        long bad = 0, nb = 0;
        for (int b = 2; b < NB; b++) {
            double s1 = 0.0, s2 = 0.0;
            for (int t = 0; t < nseg; t++) {
                double p = P[(size_t)t * NB + b];
                s1 += p; s2 += p * p;
            }
            nb++;
            if (s1 > 0) {
                double sk = (M + 1.0) / (M - 1.0) * (M * s2 / (s1 * s1) - 1.0);
                double dev = fabs(sk - 1.0);
                if (dev > worst) worst = dev;
                if (dev >= SK_FLAG_DEV) bad++;
            }
        }
        r->skdev = worst;
        r->skfrac = nb ? (double)bad / (double)nb : 0.0;
        r->skflag = (r->skfrac >= 0.02) ? 1 : 0;
    }

    {   /* cepstral ladder: log mean-spectrum -> FFT -> quefrency peak */
        double *avg = (double *)calloc(NB, sizeof(double));
        double *re = (double *)malloc(SEG * sizeof(double));
        double *im = (double *)malloc(SEG * sizeof(double));
        double *cp = (double *)malloc(SEG * sizeof(double));
        if (avg && re && im && cp) {
            for (int t = 0; t < nseg; t++)
                for (int b = 0; b < NB; b++) avg[b] += P[(size_t)t * NB + b];
            double *tmp = (double *)malloc(NB * sizeof(double));
            if (tmp) {
                for (int b = 0; b < NB; b++) tmp[b] = avg[b] / M;
                double med = sy_median(tmp + 2, NB - 3);
                if (med <= 0) med = 1.0;
                /* NO frequency-domain high-pass here: a running-median
                 * subtraction blinds wide combs (a 100 kHz tone spacing is
                 * a 140-bin ripple - background to a width-51 median, so
                 * the fundamental is subtracted away and only a harmonic
                 * survives; measured during calibration). Shelves are
                 * smooth in QUEFRENCY, so whiten THERE (below) instead:
                 * every comb spacing survives, shelves divide out. */
                int NC = 2048;
                for (int i = 0; i < NC; i++) {
                    double v = avg[i] / M / med;
                    re[i] = log(v + 1e-30); im[i] = 0.0;
                }
                for (int i = NC; i < SEG; i++) { re[i] = 0.0; im[i] = 0.0; }
                sy_fft_mag2(re, im, SEG, cp);
                double *cc = (double *)malloc((NC / 2 + 1) * sizeof(double));
                if (cc) {
                    for (int i = 0; i <= NC / 2; i++) cc[i] = cp[i];
                    double m2 = sy_median(cc + 10, NC / 2 - 10);
                    if (m2 <= 0) m2 = 1.0;
                    /* quefrency whitening: shelves (red log-spectra, hum
                     * skirts) are SMOOTH in q and divide out under a wide
                     * running median (+-60); comb lines are narrow and
                     * survive at any spacing. (Whitening in frequency
                     * instead blinds wide combs - measured, reverted.) */
                    double best = 0.0;
                    int bq = 0;
                    /* denom = max(local median, GLOBAL median): the cepstrum
                     * has near-zero nulls, and dividing by ~0 manufactures
                     * ratios of 1000+ out of nothing (measured 1332 on
                     * pulsing data). The global floor keeps nulls at ~0
                     * while shelves still divide out (local >> global). */
                    double floor = m2;
                    if (!(floor > 0)) floor = 1e-30;
                    {
                        double win[121];
                        for (int q = 10; q <= 700; q++) {
                            for (int k = 0; k < 121; k++) {
                                int j = q - 60 + k;
                                if (j < 10) j = 10;
                                if (j > 700) j = 700;
                                win[k] = cc[j];
                            }
                            double denom = sy_median(win, 121);
                            if (denom < floor) denom = floor;
                            double v = cc[q] / denom;
                            if (v > best) { best = v; bq = q; }
                        }
                    }
                    if (getenv("XENO_DEBUG")) {
                        fprintf(stderr, "[cep] best=%.2f@%d", best, bq);
                        for (int qq = 10; qq <= 700; qq++) {
                            double win2[121];
                            for (int k = 0; k < 121; k++) {
                                int j = qq - 60 + k;
                                if (j < 10) j = 10;
                                if (j > 700) j = 700;
                                win2[k] = cc[j];
                            }
                            if (cc[qq] / fmax(sy_median(win2, 121), 1e-30) > 4.0)
                                fprintf(stderr, " (%.1f@%d)",
                                        cc[qq] / fmax(sy_median(win2, 121), 1e-30), qq);
                        }
                        fprintf(stderr, "\n");
                    }
                    r->ladder = best;
                    r->ladderq = (best >= LADDER_FLAG) ? bq : 0;
                    free(cc);
                }
                free(tmp);
            }
        }
        free(avg); free(re); free(im); free(cp);
    }

    {   /* dispersion-order: peak arrival time vs sub-band centre */
        double tt[DM_NSB], ff[DM_NSB];
        int lo = 2, span = (NB - 2) / DM_NSB;
        for (int k = 0; k < DM_NSB; k++) {
            int b0 = lo + k * span, b1 = (k == DM_NSB - 1) ? NB : b0 + span;
            double bt = 0.0;
            int bi = 0;
            for (int t = 0; t < nseg; t++) {
                double p = 0.0;
                for (int b = b0; b < b1; b++) p += P[(size_t)t * NB + b];
                if (p > bt) { bt = p; bi = t; }
            }
            tt[k] = (double)bi;
            ff[k] = (double)(b0 + b1) / 2.0;
        }
        double mf = 0.0, mt = 0.0;
        for (int k = 0; k < DM_NSB; k++) { mf += ff[k]; mt += tt[k]; }
        mf /= DM_NSB; mt /= DM_NSB;
        double sxy = 0.0, sxx = 0.0, syy = 0.0;
        double tlo = tt[0], thi = tt[0];
        for (int k = 0; k < DM_NSB; k++) {
            sxy += (ff[k] - mf) * (tt[k] - mt);
            sxx += (ff[k] - mf) * (ff[k] - mf);
            syy += (tt[k] - mt) * (tt[k] - mt);
            if (tt[k] < tlo) tlo = tt[k];
            if (tt[k] > thi) thi = tt[k];
        }
        double r2 = (sxx > 0 && syy > 0) ? (sxy * sxy) / (sxx * syy) : 0.0;
        r->dm_r2 = r2;
        if (r2 >= DM_R2_MIN && (thi - tlo) >= DM_SPAN_MIN)
            r->dm_sign = (sxy < 0) ? 1 : -1;  /* -slope: high-freq first = plasma */
        else
            r->dm_sign = 0;
    }
    free(P);
}

static int selftest(void) {
    const int N = 524288;
    const double fs = 2929687.5;
    float *x = (float *)malloc((size_t)N * sizeof(float));
    if (!x) { printf("[selftest] OOM\n"); return 1; }
    int i, ok = 1;
    xeno_t r;

#define CHECK(name, cond, detail) do { \
        printf("[selftest] %-28s %s  %s\n", name, (cond) ? "PASS" : "FAIL", detail); \
        ok = ok && !!(cond); } while (0)

    /* 1. matched noise: everything quiet */
    rng_s = 0x123456789abcdefULL;
    for (i = 0; i < N; i++) x[i] = (float)(14.0 * rnorm());
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "sk=%.2f coh=%.1f lad=%.1f dm=%+d(r2=%.2f) imp=%d",
                 r.skdev, r.coh, r.ladder, r.dm_sign, r.dm_r2, r.impuls);
        CHECK("noise: all markers quiet",
              !r.skflag && !r.cohflag && !r.ladderq && r.dm_sign == 0 && !r.impuls, d);
    }
    /* 2. pulsed (packetised cadence): SK + impulsivity fire.
     * Gate period MUST NOT equal the STFT length (4096): every frame would
     * then hold identical gate content and SK would sit at 1 by symmetry
     * (measured during calibration). 6000 samples = honest cadence. */
    rng_s = 0xabcdef123456789ULL;
    for (i = 0; i < N; i++) {
        double gate = ((i % 6000) < 512) ? 4.0 : 1.0;
        x[i] = (float)(14.0 * rnorm() * gate);
    }
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "sk=%.2f frac=%.3f imp=%d", r.skdev, r.skfrac, r.impuls);
        CHECK("pulsed cadence: SK fires", r.skflag, d);
        CHECK("pulsed cadence: impulsivity fires", r.impuls, d);
    }
    /* 3. tone ladder (5 tones, 100 kHz spacing): cepstrum fires */
    rng_s = 0x1111111111111111ULL;
    for (i = 0; i < N; i++) {
        double t = i / fs, s = 0.0;
        for (int k = 1; k <= 5; k++) s += 6.0 * sin(2 * M_PI * 100000.0 * k * t);
        x[i] = (float)(14.0 * rnorm() + s);
    }
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "ladder=%.1f q=%d", r.ladder, r.ladderq);
        CHECK("tone ladder: cepstrum fires", r.ladderq > 0, d);
    }
    /* 4. clock-grade square wave: coherence fires */
    rng_s = 0x2222222222222222ULL;
    for (i = 0; i < N; i++)
        x[i] = (float)(((i % 64) < 32 ? 20.0 : -20.0) + 1.0 * rnorm());
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "coh=%.1f", r.coh);
        CHECK("square clock: coherence fires", r.cohflag, d);
    }
    /* 5a. descending chirp (high-freq first) = NORMAL plasma order */
    rng_s = 0x3333333333333333ULL;
    for (i = 0; i < N; i++) {
        double f = 1400000.0 - 1300000.0 * (double)i / (double)N;
        double ph = 2 * M_PI * (1400000.0 * i / fs - 1300000.0 * i * i / (2.0 * N * fs));
        (void)f;
        x[i] = (float)(14.0 * rnorm() + 25.0 * sin(ph));
    }
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "dm=%+d r2=%.2f", r.dm_sign, r.dm_r2);
        CHECK("down-chirp: NORMAL order (+1)", r.dm_sign == 1, d);
    }
    /* 5b. ascending chirp (low-freq first) = EXOTIC negative-DM order */
    rng_s = 0x4444444444444444ULL;
    for (i = 0; i < N; i++) {
        double ph = 2 * M_PI * (100000.0 * i / fs + 1300000.0 * i * i / (2.0 * N * fs));
        x[i] = (float)(14.0 * rnorm() + 25.0 * sin(ph));
    }
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "dm=%+d r2=%.2f", r.dm_sign, r.dm_r2);
        CHECK("up-chirp: EXOTIC order (-1)", r.dm_sign == -1, d);
    }
    /* 6. sparse giant impulses: impulsivity only */
    rng_s = 0x987654321abcdefULL;
    for (i = 0; i < N; i++) x[i] = (float)(14.0 * rnorm());
    /* aperiodic positions: a fixed stride is itself a periodic comb and
     * would imprint a REAL cepstral line (measured during calibration) */
    for (i = 0; i < 40; i++) {
        rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
        int pos = (int)((rng_s >> 11) % (uint64_t)N);
        x[pos] = (float)(20.0 * 14.0);
    }
    analyze(x, N, fs, &r);
    {
        char d[256];
        snprintf(d, sizeof(d), "imp=%d maxz=%.1f lad=%.1f dm=%+d(r2=%.2f)",
                 r.impuls, r.maxz, r.ladder, r.dm_sign, r.dm_r2);
        CHECK("impulses: impulsivity fires", r.impuls, d);
        CHECK("impulses: no fake ladder", !r.ladderq, d);
        CHECK("impulses: no fake DM order", r.dm_sign == 0, d);
        CHECK("impulses: SK stays quiet", !r.skflag, d);
    }

    free(x);
    printf("[selftest] %s\n", ok ? "ALL PASS" : "FAILURES PRESENT");
    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--selftest")) return selftest();
    if (argc < 2) {
        fprintf(stderr, "usage: %s <in.f32> [fs_Hz] | --selftest\n", argv[0]);
        return 2;
    }
    double fs = argc > 2 ? atof(argv[2]) : 2929687.5;
    int nx = 0;
    float *x = sy_load_f32(argv[1], &nx);
    if (!x) { perror("load"); return 1; }
    xeno_t r;
    analyze(x, nx, fs, &r);
    printf("samples=%d fs=%.1f\n", nx, fs);
    printf("RESULT skdev=%.3f skfrac=%.4f skflag=%d coh=%.2f cohflag=%d ladder=%.2f ladderq=%d "
           "dm_sign=%+d dm_r2=%.3f impuls=%d maxz=%.1f kurt=%.2f tailx=%.2f\n",
           r.skdev, r.skfrac, r.skflag, r.coh, r.cohflag, r.ladder, r.ladderq,
           r.dm_sign, r.dm_r2, r.impuls, r.maxz, r.kurt, r.tailx);
    free(x);
    return 0;
}
