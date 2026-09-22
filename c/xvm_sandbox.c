// xvm_sandbox.c - SetiYeti XENO multi-architecture alien-code sandbox (C99, -lm only)
//
// WHY THIS EXISTS: vm_sandbox asks "does it compute" with ONE machine
// (SUBLEQ) and ONE code (Golay G24). A payload aimed at an unknown receiver
// must be architecture-agnostic, so our sandbox must be too: the only way to
// send a program to an unknown architecture is a universal abstract machine,
// and there are several mutually-unfamiliar ones. This tool runs SIX,
// chosen for architecture-agnosticism (no human standard is assumed):
//
//   SUBLEQ  one-instruction subtract-and-branch (the vm_sandbox baseline)
//   STACK   Forth-like push/add/mul/jump machine, swept over word widths
//           3..8 bits (an 8-bit unpacker scrambles a 6/7-bit alien word;
//           noise halts at every width, structured code LOOPS at its own)
//   CA110   Rule-110 cellular automaton: periodic/seeded starts breathe
//           (density oscillates), random starts sit at flat ~50%
//   ACF     frame autocorrelation: packetised telemetry repeats at a fixed
//           stride, so bipolar bits correlate at lag = frame length; noise
//           never does (threshold 6 sigma over 4000 lags)
//   BM      Berlekamp-Massey linear complexity over GF(2): the length L of
//           the shortest LFSR generating the stream. Noise sits at L ~ N/2;
//           ANY linear code, scrambler, or polynomial check (CRC/BCH/RS,
//           LFSR cipher - no polynomial guessed, none named) collapses L.
//           This replaces the old Hamming(7,4) + CRC-16/XModem checks, which
//           demanded the alien use OUR 1970s telephony polynomial (0x1021).
//   RASTER  2D prime-raster spatial coherence: fold the stream at the ACF
//           stride (and its divisors) into a bitmap; an image/pictograph
//           (Arecibo-style) shows contiguous contours, noise shows salt.
//
// Plus the ENTROPY GATE (AGENTS.md hard-won lesson: zero-runs pass every
// syndrome trivially - no verdict without information).
//
// Output contract (parsed by python/xeno_pass.py parse_xvm_result):
//   xvm_sub=.. xvm_stk=..(ops,loops,depth,width) xvm_ca=.. xvm_acf=..(lag,z)
//   xvm_bm=..(L,z) xvm_raster=..(w,h,z)
//   xvm_score=%.2f <XENO-CANDIDATE|XENO-WATCH|noise-like>
//
// Usage: xvm_sandbox <bits.bin>  (raw bytes, MSB-first bits)
//        xvm_sandbox --selftest   (multi-seed noise quiet incl. dark input;
//                                 hand-built LFSR + looping + framed + bitmap
//                                 stream fires >=3/6 incl. BOTH LFSR windows)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define MAXB 200000L     /* bit cap (matches vm_sandbox window) */
#define STK_BUDGET 50000
#define SUB_BUDGET 200000
#define CA_W 256
#define CA_G 256
#define ACF_N 32768
#define ACF_LMIN 8
#define ACF_LMAX 4096
#define ACF_Z 6.0
#define BM_N 4096        /* Berlekamp-Massey window (O(N^2), N small by design) */
#define BM_WINS 3        /* windows at bit offsets {0,4096,8192}: structure may
                            sit deeper than bit 0 (same doctrine as CA_WINDOWS) */
#define BM_MIN_N 512     /* shorter spans carry no linear-complexity meaning */
#define BM_Z 6.0         /* deficit sigma vs the N/2 noise mean (mirrors ACF_Z:
                            per-window noise P(z>6) ~ 1e-9, inaudible) */
#define RASTER_N 32768   /* raster analysis cap (bits) */
#define RASTER_Z 6.0     /* spatial-coherence sigma (mirrors ACF_Z) */
#define CA_VAR_MIN 0.0015   /* density-trajectory variance floor. Calibrated over
                                9 noise seeds: 0.00056-0.00087, tight cluster
                                (sigma ~1e-4); structured mixes score 0.0025+.
                                0.0015 = 6 sigma above the noise mean. */
#define CA_WINDOWS 4         /* seed from 4 windows, take max: structure may sit
                                deeper than bit 0; noise max-of-4 stays ~0.001 */
#define STK_MIN_OPS 5000
#define STK_MIN_LOOPS 20
#define STK_MAXSYM 4096     /* instruction-symbol cap per width (matches the
                               old 4096-byte program cap at w=8) */

static uint64_t rng_s = 0x5EED5EED5EED5EEDULL;
static uint64_t rnext(void) { /* xorshift64* step for noise bytes */
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    return rng_s * 0x2545F4914F6CDD1DULL;
}

static int getbit(const uint8_t *buf, long i) {
    return (int)((buf[i >> 3] >> (7 - (i & 7))) & 1);
}

static void setbit(uint8_t *buf, long i, int v) {
    if (v) buf[i >> 3] |= (uint8_t)(1 << (7 - (i & 7)));
    else   buf[i >> 3] &= (uint8_t)~(1 << (7 - (i & 7)));
}

/* ---------------- entropy gate (identical rule to vm_sandbox) -------- */
static int entropy_gate(const uint8_t *buf, long nb, double *frac, int *distinct) {
    long ones = 0;
    int seen[256] = {0};
    int nd = 0;
    for (long i = 0; i < nb; i++) {
        ones += __builtin_popcount(buf[i]);
        if (!seen[buf[i]]) { seen[buf[i]] = 1; nd++; }
    }
    *frac = (double)ones / (double)(nb * 8);
    *distinct = nd;
    return (*frac >= 0.30 && *frac <= 0.70 && nd >= 16);
}

/* ---------------- SUBLEQ (baseline machine) -------------------------- */
static double subleq_score(const uint8_t *buf, long nbits) {
    int nwords = (int)((nbits + 31) / 32);
    if (nwords < 16) nwords = 16;
    if (nwords > 8192) nwords = 8192;
    int32_t *mem = (int32_t *)calloc((size_t)nwords, 4);
    if (!mem) return 0.0;
    for (long i = 0; i < (long)nwords * 32 && i < nbits; i++) {
        int bit = getbit(buf, i);
        mem[i >> 5] |= (int32_t)(bit << (31 - (i & 31)));
    }
    for (int i = 0; i < nwords; i++) mem[i] = abs(mem[i]) % nwords;
    int32_t pc = 0;
    int steps = 0;
    long writes = 0, local = 0;
    int32_t last_b = -1000000;
    while (steps < SUB_BUDGET) {
        if (pc < 0 || pc + 2 >= nwords) break;
        int32_t a = mem[pc], b = mem[pc + 1], c = mem[pc + 2];
        if (a < 0 || a >= nwords || b < 0 || b >= nwords) break;
        if (c < 0 || c >= nwords) break;
        mem[b] -= mem[a]; writes++;
        if (last_b >= 0 && abs(b - last_b) < 16) local++;
        last_b = b;
        pc = (mem[b] <= 0) ? c : pc + 3;
        steps++;
        if (steps > 10 && writes == 0) break;
    }
    free(mem);
    double loc = writes ? (double)local / (double)writes : 0.0;
    return (writes > 100 ? 0.4 : 0.0) + (loc > 0.3 ? 0.3 : 0.0)
         + ((steps > 5000 && steps < SUB_BUDGET) ? 0.3 : 0.0);
}

/* ---------------- STACK Forth-like machine, any word width ------------ */
/* Symbol = w-bit token: op = top 3 bits, arg = low (w-3) bits.
 * w=8 reproduces the original byte machine EXACTLY (op<<5|arg:
 * 0 PUSH arg, 1 ADD, 2 SUB, 3 MUL, 4 DUP, 5 DROP,
 * 6 JZ rel(arg-16), 7 JMP rel(arg-16)). Structured code loops at its
 * native width; noise halts at every width. */
static void stack_run(const uint8_t *prog, int plen, int w,
                      long *ops, long *loops, int *depth) {
    uint32_t st[256];
    int sp = 0, maxd = 0, pc = 0;
    long n = 0, lp = 0;
    int ashift = w - 3;
    int amask = (1 << ashift) - 1;
    while (n < STK_BUDGET) {
        if (pc < 0 || pc >= plen) break;
        uint8_t ins = prog[pc];
        int op = ins >> ashift, arg = ins & amask;
        n++;
        switch (op) {
        case 0: if (sp >= 256) goto done; st[sp++] = (uint32_t)arg; pc++; break;
        case 1: if (sp < 2) goto done; { uint32_t b = st[--sp], a = st[--sp]; st[sp++] = a + b; } pc++; break;
        case 2: if (sp < 2) goto done; { uint32_t b = st[--sp], a = st[--sp]; st[sp++] = a - b; } pc++; break;
        case 3: if (sp < 2) goto done; { uint32_t b = st[--sp], a = st[--sp]; st[sp++] = a * b; } pc++; break;
        case 4: if (sp < 1 || sp >= 256) goto done; st[sp] = st[sp - 1]; sp++; pc++; break;
        case 5: if (sp < 1) goto done; sp--; pc++; break;
        case 6: if (sp < 1) goto done; { uint32_t t = st[--sp]; int d = arg - 16; if (t == 0) { if (d < 0) lp++; pc += d; } else pc++; } break;
        case 7: { int d = arg - 16; if (d < 0) lp++; pc += d; } break;
        }
        if (sp > maxd) maxd = sp;
    }
done:
    /* outputs ALWAYS written: an early halt still reports how far the
     * machine got (a bare `return` here once silently zeroed every.
     * metric and made a looping program read as ops=0). */
    *ops = n; *loops = lp; *depth = maxd;
}

/* Sweep word widths 3..8: an executable payload on 6/7-bit words is
 * scrambled by an 8-bit unpacker and crashes instantly there, but LOOPS
 * at its native width. Winner = most backward jumps, ties = most ops.
 * Floors are unchanged (STK_MIN_OPS/LOOPS); the 6x trial inflation is
 * paid for by the multi-seed noise-quiet prove in --selftest. */
static void stack_best(const uint8_t *buf, long nbits,
                       long *ops, long *loops, int *depth, int *width) {
    static uint8_t bits[STK_MAXSYM * 8];
    static uint8_t sym[STK_MAXSYM];
    long n = nbits > (long)(STK_MAXSYM * 8) ? (long)(STK_MAXSYM * 8) : nbits;
    for (long i = 0; i < n; i++) bits[i] = (uint8_t)getbit(buf, i);
    *ops = 0; *loops = 0; *depth = 0; *width = 8;
    for (int w = 3; w <= 8; w++) {
        long ns = n / w;
        if (ns > STK_MAXSYM) ns = STK_MAXSYM;
        if (ns < 16) continue;
        for (long j = 0; j < ns; j++) {
            uint8_t v = 0;
            for (int k = 0; k < w; k++) v = (uint8_t)((v << 1) | bits[j * w + k]);
            sym[j] = v;
        }
        {
            long o = 0, l = 0;
            int d = 0;
            stack_run(sym, (int)ns, w, &o, &l, &d);
            if (l > *loops || (l == *loops && o > *ops)) {
                *ops = o; *loops = l; *depth = d; *width = w;
            }
        }
    }
}

/* ---------------- Rule-110 CA ---------------------------------------- */
static double ca110_window(const uint8_t *buf, long nbits, long off) {
    uint8_t cur[CA_W], nxt[CA_W];
    for (int i = 0; i < CA_W; i++) {
        long bi = (off + i) % nbits;
        cur[i] = (uint8_t)getbit(buf, bi);
    }
    double sm = 0.0, s2 = 0.0;
    for (int g = 0; g < CA_G; g++) {
        double d = 0.0;
        for (int i = 0; i < CA_W; i++) d += cur[i];
        d /= CA_W;
        sm += d; s2 += d * d;
        for (int i = 0; i < CA_W; i++) {
            int pat = (cur[(i + CA_W - 1) % CA_W] << 2) | (cur[i] << 1) | cur[(i + 1) % CA_W];
            static const uint8_t TAB[8] = {0, 1, 1, 1, 0, 1, 1, 0}; /* Rule 110 */
            nxt[i] = TAB[pat];
        }
        memcpy(cur, nxt, CA_W);
    }
    double mu = sm / CA_G;
    return s2 / CA_G - mu * mu;
}
static double ca110_variance(const uint8_t *buf, long nbits) {
    double best = 0.0;
    for (int w = 0; w < CA_WINDOWS; w++) {
        double v = ca110_window(buf, nbits, (long)w * CA_W);
        if (v > best) best = v;
    }
    return best;
}

/* ---------------- frame ACF ------------------------------------------ */
static double acf_best(const uint8_t *buf, long nbits, int *lag_out) {
    long n = nbits > ACF_N ? ACF_N : nbits;
    if (n < ACF_LMAX + 16) { *lag_out = 0; return 0.0; }
    /* bipolar cache */
    static int8_t b[ACF_N];
    for (long i = 0; i < n; i++)
        b[i] = (int8_t)(getbit(buf, i) ? 1 : -1);
    /* full lag scan, then walk DOWN to the fundamental: a framed stream
     * scores at 64, 128, 320, ... and the raw argmax lands on an arbitrary
     * multiple (measured: 320 with z=60 while 64 sat at ~22). Same standard
     * fix as frame_hunt: descend through divisors while |z| stays >= 30%
     * of the peak. The raster/payload hunters need the stride, not a
     * multiple of it. */
    static double ztab[ACF_LMAX + 1];
    for (int L = ACF_LMIN; L <= ACF_LMAX; L++) {
        long acc = 0;
        for (long i = 0; i + L < n; i++) acc += (long)b[i] * b[i + L];
        ztab[L] = (double)acc / sqrt((double)n);
    }
    double best = 0.0;
    int blag = 0;
    for (int L = ACF_LMIN; L <= ACF_LMAX; L++)
        if (fabs(ztab[L]) > fabs(best)) { best = ztab[L]; blag = L; }
    for (int d = 8; d >= 2 && blag > 0; d--) {
        if (blag % d) continue;
        int cand = blag / d;
        if (cand < ACF_LMIN) continue;
        if (fabs(ztab[cand]) >= 0.30 * fabs(best)) { blag = cand; best = ztab[cand]; }
    }
    *lag_out = blag;
    return best;
}

/* ---------------- Berlekamp-Massey linear complexity ------------------ */
/* L = length of the shortest LFSR over GF(2) generating the stream.
 * Pure noise: L ~= N/2 (sigma ~ sqrt(N/18)). ANY linear structure -
 * LFSR cipher, scrambler, CRC/BCH/Reed-Solomon parity, periodic frame -
 * collapses L << N/2. NO polynomial is guessed or named: the algorithm
 * FINDS the recurrence. z = deficit in noise-sigmas; fires at BM_Z.
 * (Caveat, documented: parity appended to INCOMPRESSIBLE random data
 * keeps L near the data-bit count, which can exceed N/2 - BM is a
 * low-complexity detector, not a parity detector. Periodic and LFSR
 * structure, the cheap alien choices, collapse it hard.) */
static int bm_complexity(const uint8_t *b, int n) {
    static int C[BM_N + 1], Bc[BM_N + 1], T[BM_N + 1];
    if (n > BM_N) n = BM_N;
    for (int i = 0; i <= n; i++) C[i] = Bc[i] = 0;
    C[0] = Bc[0] = 1;
    int L = 0, m = -1;
    for (int k = 0; k < n; k++) {
        int d = b[k];
        for (int i = 1; i <= L; i++) d ^= (C[i] & b[k - i]);
        if (!d) continue;
        for (int i = 0; i <= n; i++) T[i] = C[i];
        {
            int s = k - m;
            for (int i = 0; i + s <= n; i++) C[i + s] ^= Bc[i];
        }
        if (2 * L <= k) {
            L = k + 1 - L;
            for (int i = 0; i <= n; i++) Bc[i] = T[i];
            m = k;
        }
    }
    return L;
}

/* deficit sigma of one region starting at absolute bit `off`, length `len` */
static double bm_region(const uint8_t *buf, long off, int len, int *L_out) {
    static uint8_t b[BM_N];
    int n = len > BM_N ? BM_N : len;
    if (n < BM_MIN_N) { if (L_out) *L_out = 0; return 0.0; }
    for (int i = 0; i < n; i++) b[i] = (uint8_t)getbit(buf, off + i);
    {
        int L = bm_complexity(b, n);
        if (L_out) *L_out = L;
        return (n / 2.0 - (double)L) / sqrt((double)n / 18.0);
    }
}

static double bm_best(const uint8_t *buf, long nbits, int *L_out) {
    static const long offs[BM_WINS] = {0, 4096, 8192};
    double best = 0.0;
    int bestL = 0, any = 0;
    for (int q = 0; q < BM_WINS; q++) {
        long o = offs[q];
        if (o + BM_MIN_N > nbits) continue;
        {
            int L = 0;
            int len = (nbits - o > BM_N) ? BM_N : (int)(nbits - o);
            double z = bm_region(buf, o, len, &L);
            if (!any || z > best) { best = z; bestL = L; any = 1; }
        }
    }
    if (L_out) *L_out = bestL;
    return any ? best : 0.0;
}

/* ---------------- 2D prime-raster spatial coherence ------------------ */
/* Fold the stream at width w into a bitmap; count agreeing right+down
 * neighbour pairs. Noise: agreement ~= 1/2 (binomial sigma sqrt(.25/M)).
 * A pictographic payload (Arecibo-style) shows contiguous contours and
 * agreement >> 1/2. Widths tried: the ACF stride + its divisors (the
 * stride IS the raster width for framed images) + factor pairs of the
 * analysis length (a deliberate p1 x p2 framing divides N evenly) +
 * every prime <= 127 (the classic raster hypothesis space: a 23x73
 * Arecibo-style frame is found at its NATURAL width even when the
 * analysis window is not exactly p1*p2 bits long and the ACF is
 * diluted below threshold by surrounding filler).
 * Max ~48 grids; per-grid noise P(z>6) ~ 1e-9, family-wise inaudible
 * (proven: 5-seed noise max stays ~3 in --selftest). The vote means
 * 'spatially non-random at some width' - the winning width is
 * diagnostic, not verdict. */
static double raster_best(const uint8_t *buf, long nbits, int acf_lag,
                          int *w_out, int *h_out) {
    long n = nbits > RASTER_N ? RASTER_N : nbits;
    int widths[48];
    int nw = 0;
    if (acf_lag >= 8 && (long)acf_lag <= n / 4) widths[nw++] = acf_lag;
    /* classic raster primes first: natural-width recovery for
     * Arecibo-style frames at ANY window length (Drake 1679 = 23x73). */
    {
        static const int primes[] = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29,
            31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97,
            101, 103, 107, 109, 113, 127};
        unsigned pi;
        for (pi = 0; pi < sizeof(primes) / sizeof(primes[0]) && nw < 48; pi++) {
            if (primes[pi] >= 8 && (long)primes[pi] <= n / 4)
                widths[nw++] = primes[pi];
        }
    }
    if (acf_lag > 1) {
        for (int d = 2; (long)d * d <= acf_lag && nw < 48; d++) {
            if (acf_lag % d) continue;
            {
                int q = acf_lag / d;
                if (q >= 8 && (long)q <= n / 4) {
                    int dup = 0;
                    for (int k = 0; k < nw; k++) if (widths[k] == q) dup = 1;
                    if (!dup) widths[nw++] = q;
                }
                if (d >= 8 && (long)d <= n / 4 && nw < 16) {
                    int dup = 0;
                    for (int k = 0; k < nw; k++) if (widths[k] == d) dup = 1;
                    if (!dup) widths[nw++] = d;
                }
            }
        }
    }
    for (long f = 8; f * f <= n && nw < 48; f++) {
        if (n % f) continue;
        {
            int dup = 0;
            for (int k = 0; k < nw; k++) if (widths[k] == (int)f) dup = 1;
            if (!dup && f <= n / 4) widths[nw++] = (int)f;
            {
                long q = n / f;
                if (q >= 8 && q <= n / 4 && (int)q != (int)f && nw < 16) {
                    dup = 0;
                    for (int k = 0; k < nw; k++) if (widths[k] == (int)q) dup = 1;
                    if (!dup) widths[nw++] = (int)q;
                }
            }
        }
    }
    double best = 0.0;
    int bw = 0, bh = 0;
    for (int gi = 0; gi < nw; gi++) {
        int w = widths[gi];
        long rows = n / w;
        if (rows < 4) continue;
        {
            long M = (long)(w - 1) * rows + (long)w * (rows - 1);
            long agree = 0;
            long r, c;
            for (r = 0; r < rows; r++)
                for (c = 0; c + 1 < w; c++)
                    if (getbit(buf, r * w + c) == getbit(buf, r * w + c + 1))
                        agree++;
            for (r = 0; r + 1 < rows; r++)
                for (c = 0; c < w; c++)
                    if (getbit(buf, r * w + c) == getbit(buf, (r + 1) * w + c))
                        agree++;
            {
                double a = (double)agree / (double)M;
                double z = (a - 0.5) / sqrt(0.25 / (double)M);
                if (gi == 0 || z > best) { best = z; bw = w; bh = (int)rows; }
            }
        }
    }
    if (w_out) *w_out = bw;
    if (h_out) *h_out = bh;
    return best;
}

/* ---------------- combined verdict ------------------------------------ */
typedef struct {
    double sub, ca, acf_z, bm_z, raster_z;
    int bm_L, acf_lag, raster_w, raster_h, stk_w;
    long stk_ops, stk_loops;
    int stk_depth;
    int f_sub, f_stk, f_ca, f_acf, f_bm, f_raster;
    double score;
} xvm_t;

static void analyze(const uint8_t *buf, long nb, xvm_t *r) {
    memset(r, 0, sizeof(*r));
    long nbits = nb * 8L;
    if (nbits > MAXB) nbits = MAXB;
    r->sub = subleq_score(buf, nbits);
    r->f_sub = (r->sub >= 0.6) ? 1 : 0;
    stack_best(buf, nbits, &r->stk_ops, &r->stk_loops, &r->stk_depth, &r->stk_w);
    r->f_stk = (r->stk_ops >= STK_MIN_OPS && r->stk_loops >= STK_MIN_LOOPS) ? 1 : 0;
    r->ca = ca110_variance(buf, nbits);
    r->f_ca = (r->ca >= CA_VAR_MIN) ? 1 : 0;
    r->acf_z = acf_best(buf, nbits, &r->acf_lag);
    r->f_acf = (fabs(r->acf_z) >= ACF_Z) ? 1 : 0;
    r->bm_z = bm_best(buf, nbits, &r->bm_L);
    r->f_bm = (r->bm_z >= BM_Z) ? 1 : 0;
    r->raster_z = raster_best(buf, nbits, r->acf_lag, &r->raster_w, &r->raster_h);
    r->f_raster = (r->raster_z >= RASTER_Z) ? 1 : 0;
    r->score = (r->f_sub + r->f_stk + r->f_ca + r->f_acf + r->f_bm + r->f_raster) / 6.0;
}

static void print_result(const xvm_t *r) {
    const char *v = r->score >= 0.5 ? "XENO-CANDIDATE"
                  : (r->score > 0.0 ? "XENO-WATCH" : "noise-like");
    printf("xvm_sub=%.2f xvm_stk_ops=%ld xvm_stk_loops=%ld xvm_stk_depth=%d xvm_stk_w=%d "
           "xvm_ca=%.5f xvm_acf_lag=%d xvm_acf_z=%.1f xvm_bm_L=%d xvm_bm_z=%.1f "
           "xvm_raster_w=%d xvm_raster_h=%d xvm_raster_z=%.1f "
           "xvm_score=%.2f %s\n",
           r->sub, r->stk_ops, r->stk_loops, r->stk_depth, r->stk_w,
           r->ca, r->acf_lag, r->acf_z, r->bm_L, r->bm_z,
           r->raster_w, r->raster_h, r->raster_z, r->score, v);
}

/* Fibonacci LFSR filler: taps are ARBITRARY primitive polynomials the BM
 * stage is never told (that is the whole point - no polynomial guessed). */
static void lfsr_fill(uint8_t *s, long bit0, int len, uint16_t taps, uint16_t seed) {
    uint16_t st = seed ? seed : 0xACE1u;
    for (int i = 0; i < len; i++) {
        uint16_t v = (uint16_t)(st & taps);
        int nb = __builtin_parity(v);
        setbit(s, bit0 + i, (st & 1));
        st = (uint16_t)((st >> 1) | (nb << 15));
    }
}

static int selftest(void) {
    int ok = 1;
#define CHECK(nm, cd, dt) do { \
        printf("[selftest] %-30s %s  %s\n", nm, (cd) ? "PASS" : "FAIL", dt); \
        ok = ok && !!(cd); } while (0)

    /* 1. random bits, FIVE seeds: every machine quiet at every width.
     * (AGENTS.md: floors need multiple noise realizations, never one.) */
    {
        static const uint64_t seeds[5] = {
            0x5EED5EED5EED5EEDULL, 0x123456789ABCDEF1ULL,
            0x0FEDCBA987654321ULL, 0xAAAAAAAAAAAAAAAAULL, 0x173BEAD173BEAD1ULL};
        const int NB = 4096;
        uint8_t *rnd = (uint8_t *)malloc(NB);
        for (int s = 0; s < 5; s++) {
            rng_s = seeds[s];
            for (int i = 0; i < NB; i++) rnd[i] = (uint8_t)(rnext() >> 33);
            {
                double fr; int nd;
                int gate = entropy_gate(rnd, NB, &fr, &nd);
                xvm_t r;
                analyze(rnd, NB, &r);
                char d[256];
                snprintf(d, sizeof(d),
                         "seed%x sub=%.2f ops=%ld loops=%ld w=%d ca=%.5f acf=%.1f@%d bmL=%d bmz=%.1f rast=%.1f",
                         s, r.sub, r.stk_ops, r.stk_loops, r.stk_w, r.ca,
                         r.acf_z, r.acf_lag, r.bm_L, r.bm_z, r.raster_z);
                CHECK("noise: gate passes (has information)", gate, d);
                CHECK("noise: zero machines fire", r.score == 0.0, d);
            }
        }
        free(rnd);
    }
    /* 2. dark input: gate refuses (the Golay zero-run lesson) */
    {
        uint8_t *z = (uint8_t *)calloc(4096, 1);
        double fr; int nd;
        int gate = entropy_gate(z, 4096, &fr, &nd);
        char d[64];
        snprintf(d, sizeof(d), "ones=%.3f distinct=%d", fr, nd);
        CHECK("dark: gate refuses verdict", !gate, d);
        free(z);
    }
    /* 3. engineered stream: STACK loop prefix + two LFSR scrambles
     * (DIFFERENT arbitrary polynomials) + Arecibo-style 23x73 bitmap. */
    {
        const int NB = 4096;
        uint8_t *s = (uint8_t *)malloc(NB);
        rng_s = 0xC0DED11C0DED11ULL;
        for (int i = 0; i < NB; i++) s[i] = (uint8_t)(rnext() >> 33);
        /* balanced loop: PUSH21 PUSH11 ADD DROP JMP-4 (35% ones, net stack 0;
         * the earlier ADD-without-DROP version leaked +1/iter, hit the 256
         * stack cap and halted - a test-vector bug, not a machine bug). */
        {
            uint8_t prog[5] = {0x15, 0x0B, 0x20, 0xA0, 0xEC};
            for (int i = 0; i < 512; i++) s[i] = prog[i % 5];
        }
        /* LFSR-A at bit 4096, LFSR-B at bit 8192 (4096 bits each).
         * Taps x^16+x^15+x^13+x^4+1 (0xA011) vs x^16+x^12+x^9+x^6+1
         * (0x1241): neither is any human standard, and BM is never told
         * either. Firing on BOTH proves polynomial-agnosticism in-test. */
        lfsr_fill(s, 4096L, 4096, 0xA011u, 0xACE1u);
        lfsr_fill(s, 8192L, 4096, 0x1241u, 0xBEEFu);
        /* 23x73 bitmap at bit 12288: border + mid cross + 5x5 block.
         * Region cleared first (structured zeros, not filler). */
        {
            const int W = 23, H = 73;
            const long b0 = 12288L;
            for (int i = 0; i < W * H; i++) setbit(s, b0 + i, 0);
            for (int r = 0; r < H; r++)
                for (int c = 0; c < W; c++) {
                    int v = (r == 0 || r == H - 1 || c == 0 || c == W - 1 ||
                             r == H / 2 || c == W / 2 ||
                             (r >= 10 && r < 15 && c >= 30 && c < 35)) ? 1 : 0;
                    setbit(s, b0 + r * W + c, v);
                }
        }
        {
            double fr_; int nd;
            int gate = entropy_gate(s, NB, &fr_, &nd);
            xvm_t r;
            analyze(s, NB, &r);
            char d[256];
            snprintf(d, sizeof(d),
                     "sub=%.2f ops=%ld loops=%ld w=%d ca=%.5f acf=%.1f@%d bmL=%d bmz=%.1f rast=%.1f@%dx%d score=%.2f",
                     r.sub, r.stk_ops, r.stk_loops, r.stk_w, r.ca, r.acf_z,
                     r.acf_lag, r.bm_L, r.bm_z, r.raster_z,
                     r.raster_w, r.raster_h, r.score);
            CHECK("coded: gate passes", gate, d);
            CHECK("coded: STACK loops fire", r.f_stk, d);
            CHECK("coded: frame ACF fires", r.f_acf, d);
            CHECK("coded: BM linear collapse fires", r.f_bm, d);
            CHECK("coded: RASTER bitmap fires", r.f_raster, d);
            CHECK("coded: CA breathes", r.f_ca, d);
            CHECK("coded: XENO-CANDIDATE (>=3/6)", r.score >= 0.5, d);
        }
        /* natural-width raster recovery, proved directly: a 23x73 bitmap
         * filling 41% of a small window must fire the raster AT w=23
         * (the prime-width path), not merely at an incidental width. */
        {
            const int W = 23, H = 73;
            const int tot = 4096;
            uint8_t *im = (uint8_t *)calloc((size_t)(tot / 8), 1);
            uint64_t rs = rng_s;
            rng_s = 0x1234ABCD5678ULL;
            for (int i = 0; i < tot; i++)
                setbit(im, i, (int)(rnext() >> 33) & 1);
            rng_s = rs;
            for (int r = 0; r < H; r++)
                for (int c = 0; c < W; c++) {
                    int v = (r == 0 || r == H - 1 || c == 0 || c == W - 1 ||
                             r == H / 2 || c == W / 2 ||
                             (r >= 10 && r < 15 && c >= 30 && c < 35)) ? 1 : 0;
                    setbit(im, r * W + c, v);
                }
            {
                double fr_; int nd;
                int gate = entropy_gate(im, tot / 8, &fr_, &nd);
                xvm_t ri;
                analyze(im, tot / 8, &ri);
                char d[128];
                snprintf(d, sizeof(d), "rast=%.1f@%dx%d",
                         ri.raster_z, ri.raster_w, ri.raster_h);
                CHECK("raster: gate passes on image window", gate, d);
                CHECK("raster: fires at natural width 23",
                      ri.f_raster && ri.raster_w == 23, d);
            }
            free(im);
        }
        /* polynomial-agnosticism, proved directly: BM on each LFSR window
         * alone must report L ~= 16 (register length) at huge sigma. */
        {
            int LA = 0, LB = 0;
            double zA = bm_region(s, 4096L, 4096, &LA);
            double zB = bm_region(s, 8192L, 4096, &LB);
            char d[128];
            snprintf(d, sizeof(d), "L_A=%d zA=%.1f L_B=%d zB=%.1f", LA, zA, LB, zB);
            CHECK("coded: BM finds LFSR-A w/o its polynomial", LA <= 32 && zA >= BM_Z, d);
            CHECK("coded: BM finds LFSR-B w/o its polynomial", LB <= 32 && zB >= BM_Z, d);
        }
        free(s);
    }
    printf("[selftest] %s\n", ok ? "ALL PASS" : "FAILURES PRESENT");
    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--selftest")) return selftest();
    if (argc < 2) {
        fprintf(stderr, "usage: %s <bits.bin> | --selftest\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 1; }
    fseek(f, 0, SEEK_END);
    long nb = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = (uint8_t *)malloc((size_t)(nb > 0 ? nb : 1));
    if (nb > 0 && fread(buf, 1, (size_t)nb, f) != (size_t)nb) { perror("fread"); return 1; }
    fclose(f);
    double fr; int nd;
    if (!entropy_gate(buf, nb, &fr, &nd)) {
        printf("entropy_gate=BLOCK (ones=%.3f distinct=%d): no information, no verdict\n",
               fr, nd);
        free(buf);
        return 0;
    }
    printf("entropy_gate=pass (ones=%.3f distinct=%d)\n", fr, nd);
    xvm_t r;
    analyze(buf, nb, &r);
    print_result(&r);
    free(buf);
    return 0;
}
