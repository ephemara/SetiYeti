// xvm_sandbox.c - SetiYeti XENO multi-architecture alien-code sandbox (C99, -lm only)
//
// WHY THIS EXISTS: vm_sandbox asks "does it compute" with ONE machine
// (SUBLEQ) and ONE code (Golay G24). A payload aimed at an unknown receiver
// must be architecture-agnostic, so our sandbox must be too: the only way to
// send a program to an unknown architecture is a universal abstract machine,
// and there are several mutually-unfamiliar ones. This tool runs FIVE:
//
//   SUBLEQ  one-instruction subtract-and-branch (the vm_sandbox baseline)
//   STACK   Forth-like push/add/mul/jump machine; structured code LOOPS,
//           noise runs off the end and halts
//   CA110   Rule-110 cellular automaton: periodic/seeded starts breathe
//           (density oscillates), random starts sit at flat ~50%
//   ACF     frame autocorrelation: packetised telemetry repeats at a fixed
//           stride, so bipolar bits correlate at lag = frame length; noise
//           never does (threshold 6 sigma over 4000 lags)
//   HAM     Hamming(7,4) syndrome-zero excess (random baseline 12.5%)
//   CRC     CRC-16/XModem zero-residual excess (random baseline 1/65536;
//           appended-CRC frames hit ~100% on alignment)
//
// Plus the ENTROPY GATE (AGENTS.md hard-won lesson: zero-runs pass every
// syndrome trivially - no verdict without information).
//
// Output contract:
//   xvm_sub=.. xvm_stk=..(ops,loops) xvm_ca=.. xvm_acf=..(lag,z) xvm_ham=..
//   xvm_crc=.. xvm_score=%.2f <XENO-CANDIDATE|XENO-WATCH|noise-like>
//
// Usage: xvm_sandbox <bits.bin>  (raw bytes, MSB-first bits)
//        xvm_sandbox --selftest   (noise quiet incl. dark input; hand-built
//                                 framed+coded+looping stream fires >=4/6)
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
#define HAM_MIN_RATE 0.25   /* vs 0.125 random baseline */
#define HAM_MIN_WINS 200
#define CRC_MIN_HITS 3      /* vs ~0.05 expected on noise */
#define CA_VAR_MIN 0.0015   /* density-trajectory variance floor. Calibrated over
                                9 noise seeds: 0.00056-0.00087, tight cluster
                                (sigma ~1e-4); structured mixes score 0.0025+.
                                0.0015 = 6 sigma above the noise mean. */
#define CA_WINDOWS 4         /* seed from 4 windows, take max: structure may sit
                                deeper than bit 0; noise max-of-4 stays ~0.001 */
#define STK_MIN_OPS 5000
#define STK_MIN_LOOPS 20

static uint64_t rng_s = 0x5EED5EED5EED5EEDULL;
static uint64_t rnext(void) { /* xorshift64* step for noise bytes */
    rng_s ^= rng_s >> 12; rng_s ^= rng_s << 25; rng_s ^= rng_s >> 27;
    return rng_s * 0x2545F4914F6CDD1DULL;
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
        int bit = (buf[i >> 3] >> (7 - (i & 7))) & 1;
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

/* ---------------- STACK Forth-like machine --------------------------- */
/* byte = op<<5|arg: 0 PUSH arg, 1 ADD, 2 SUB, 3 MUL, 4 DUP, 5 DROP,
 * 6 JZ rel(arg-16), 7 JMP rel(arg-16). Structured code loops; noise halts. */
static void stack_run(const uint8_t *prog, int plen, long *ops, long *loops, int *depth) {
    uint32_t st[256];
    int sp = 0, maxd = 0, pc = 0;
    long n = 0, lp = 0;
    while (n < STK_BUDGET) {
        if (pc < 0 || pc >= plen) break;
        uint8_t ins = prog[pc];
        int op = ins >> 5, arg = ins & 31;
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

/* ---------------- Rule-110 CA ---------------------------------------- */
static double ca110_window(const uint8_t *buf, long nbits, long off) {
    uint8_t cur[CA_W], nxt[CA_W];
    for (int i = 0; i < CA_W; i++) {
        long bi = (off + i) % nbits;
        cur[i] = (uint8_t)((buf[bi >> 3] >> (7 - (bi & 7))) & 1);
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
        b[i] = (int8_t)((((buf[i >> 3] >> (7 - (i & 7))) & 1) ? 1 : -1));
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

/* ---------------- Hamming(7,4): H=[I|P], syndrome 0 <=> codeword ------ */
static int ham_iscode(uint8_t w7) {
    int b[7];
    for (int i = 0; i < 7; i++) b[i] = (w7 >> (6 - i)) & 1;
    int s0 = b[0] ^ b[3] ^ b[5] ^ b[6];
    int s1 = b[1] ^ b[3] ^ b[4] ^ b[6];
    int s2 = b[2] ^ b[4] ^ b[5] ^ b[6];
    return (s0 | s1 | s2) == 0;
}
static double ham_best(const uint8_t *buf, long nbits) {
    double best = 0.0;
    for (int al = 0; al < 7; al++) {
        long wins = 0, hits = 0;
        for (long w = al; w + 7 <= nbits && wins < 20000; w += 7) {
            uint8_t wd = 0;
            for (int i = 0; i < 7; i++) {
                long bi = w + i;
                wd = (uint8_t)((wd << 1) | ((buf[bi >> 3] >> (7 - (bi & 7))) & 1));
            }
            wins++;
            if (ham_iscode(wd)) hits++;
        }
        if (wins >= HAM_MIN_WINS) {
            double f = (double)hits / (double)wins;
            if (f > best) best = f;
        }
    }
    return best;
}

/* ---------------- CRC-16/XModem zero-residual ------------------------- */
static uint16_t crc16(const uint8_t *d, int len) {
    uint16_t c = 0x0000;
    for (int i = 0; i < len; i++) {
        c ^= (uint16_t)d[i] << 8;
        for (int k = 0; k < 8; k++)
            c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x1021) : (uint16_t)(c << 1);
    }
    return c;
}
static int crc_hits(const uint8_t *buf, long nbits) {
    long nb = nbits / 8;
    int hits = 0;
    for (long w = 0; w + 8 <= nb; w += 8)
        if (crc16(buf + w, 8) == 0) hits++;
    return hits;
}

/* ---------------- combined verdict ------------------------------------ */
typedef struct {
    double sub, ca, acf_z, ham;
    long stk_ops, stk_loops;
    int stk_depth, acf_lag, crc;
    int f_sub, f_stk, f_ca, f_acf, f_ham, f_crc;
    double score;
} xvm_t;

static void analyze(const uint8_t *buf, long nb, xvm_t *r) {
    memset(r, 0, sizeof(*r));
    long nbits = nb * 8L;
    if (nbits > MAXB) nbits = MAXB;
    r->sub = subleq_score(buf, nbits);
    r->f_sub = (r->sub >= 0.6) ? 1 : 0;
    {
        int plen = (int)(nb > 4096 ? 4096 : nb);
        stack_run(buf, plen, &r->stk_ops, &r->stk_loops, &r->stk_depth);
        r->f_stk = (r->stk_ops >= STK_MIN_OPS && r->stk_loops >= STK_MIN_LOOPS) ? 1 : 0;
    }
    r->ca = ca110_variance(buf, nbits);
    r->f_ca = (r->ca >= CA_VAR_MIN) ? 1 : 0;
    r->acf_z = acf_best(buf, nbits, &r->acf_lag);
    r->f_acf = (fabs(r->acf_z) >= ACF_Z) ? 1 : 0;
    r->ham = ham_best(buf, nbits);
    r->f_ham = (r->ham >= HAM_MIN_RATE) ? 1 : 0;
    r->crc = crc_hits(buf, nbits);
    r->f_crc = (r->crc >= CRC_MIN_HITS) ? 1 : 0;
    r->score = (r->f_sub + r->f_stk + r->f_ca + r->f_acf + r->f_ham + r->f_crc) / 6.0;
}

static void print_result(const xvm_t *r) {
    const char *v = r->score >= 0.5 ? "XENO-CANDIDATE"
                  : (r->score > 0.0 ? "XENO-WATCH" : "noise-like");
    printf("xvm_sub=%.2f xvm_stk_ops=%ld xvm_stk_loops=%ld xvm_stk_depth=%d "
           "xvm_ca=%.5f xvm_acf_lag=%d xvm_acf_z=%.1f xvm_ham=%.3f xvm_crc=%d "
           "xvm_score=%.2f %s\n",
           r->sub, r->stk_ops, r->stk_loops, r->stk_depth,
           r->ca, r->acf_lag, r->acf_z, r->ham, r->crc, r->score, v);
}

/* Hamming(7,4) encoder: H=[I|P] with p0=d0^d2^d3, p1=d0^d1^d3, p2=d1^d2^d3 */
static uint8_t ham_enc(uint8_t nib) {
    int d[4];
    for (int i = 0; i < 4; i++) d[i] = (nib >> (3 - i)) & 1;
    int p0 = d[0] ^ d[2] ^ d[3], p1 = d[0] ^ d[1] ^ d[3], p2 = d[1] ^ d[2] ^ d[3];
    return (uint8_t)((p0 << 6) | (p1 << 5) | (p2 << 4) | (nib & 15));
}

static int selftest(void) {
    int ok = 1;
#define CHECK(nm, cd, dt) do { \
        printf("[selftest] %-30s %s  %s\n", nm, (cd) ? "PASS" : "FAIL", dt); \
        ok = ok && !!(cd); } while (0)

    /* 1. random bits: every machine quiet */
    {
        const int NB = 4096;
        uint8_t *rnd = (uint8_t *)malloc(NB);
        rng_s = 0x5EED5EED5EED5EEDULL;
        for (int i = 0; i < NB; i++) rnd[i] = (uint8_t)(rnext() >> 33);
        double fr; int nd;
        int gate = entropy_gate(rnd, NB, &fr, &nd);
        xvm_t r;
        analyze(rnd, NB, &r);
        char d[256];
        snprintf(d, sizeof(d),
                 "sub=%.2f ops=%ld loops=%ld ca=%.5f acf=%.1f@%d ham=%.3f crc=%d",
                 r.sub, r.stk_ops, r.stk_loops, r.ca, r.acf_z, r.acf_lag, r.ham, r.crc);
        CHECK("noise: gate passes (has information)", gate, d);
        CHECK("noise: zero machines fire", r.score == 0.0, d);
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
    /* 3. engineered stream: STACK loop prefix + Hamming/CRC frames */
    {
        const int NB = 4096;
        uint8_t *s = (uint8_t *)malloc(NB);
        /* balanced loop: PUSH21 PUSH11 ADD DROP JMP-4 (35% ones, net stack 0;
         * the earlier ADD-without-DROP version leaked +1/iter, hit the 256
         * stack cap and halted - a test-vector bug, not a machine bug). */
        uint8_t prog[5] = {0x15, 0x0B, 0x20, 0xA0, 0xEC};
        for (int i = 0; i < 512; i++) s[i] = prog[i % 5];
        /* code STRIPE: 1170 back-to-back Hamming(7,4) codewords from bit 4096.
         * A 64-bit frame is 64 = 1 mod 7, so frame-packed codewords drift
         * through all 7 alignments and no single alignment sees excess
         * (measured 0.149 vs 0.25 floor). A contiguous 7-stride stripe locks
         * alignment 1 at ~34% vs the 12.5% random baseline. */
        {
            long bit = 4096;
            for (int k = 0; k < 1170; k++) {
                uint8_t nib = (uint8_t)((k * 2654435761u + (k >> 4)) & 15);
                uint8_t cw = ham_enc(nib);
                for (int i = 0; i < 7; i++, bit++) {
                    /* bit is ABSOLUTE (starts at 4096 = byte 512) */
                    if (((cw >> (6 - i)) & 1))
                        s[bit >> 3] |= (uint8_t)(1 << (7 - (bit & 7)));
                    else
                        s[bit >> 3] &= (uint8_t)~(1 << (7 - (bit & 7)));
                }
            }
        }
        /* CRC FRAMES: 320 x [data48 | crc16(data48)] from byte 1536.
         * Frame starts sit on 64-bit multiples, so every aligned window
         * carries an appended CRC and the XModem residue hits 0 (~320x). */
        for (int f = 0; f < 320; f++) {
            uint8_t fr[8];
            uint16_t ctr = (uint16_t)(f * 2654435761u % 65536);
            fr[0] = 0xAA; fr[1] = (uint8_t)(ctr >> 8); fr[2] = (uint8_t)ctr;
            fr[3] = (uint8_t)(f >> 8); fr[4] = (uint8_t)f; fr[5] = 0x55;
            uint16_t c = crc16(fr, 6);
            fr[6] = (uint8_t)(c >> 8);
            fr[7] = (uint8_t)c;
            memcpy(s + 1536 + f * 8, fr, 8);
        }
        double fr_; int nd;
        int gate = entropy_gate(s, NB, &fr_, &nd);
        xvm_t r;
        analyze(s, NB, &r);
        char d[256];
        snprintf(d, sizeof(d),
                 "sub=%.2f ops=%ld loops=%ld ca=%.5f acf=%.1f@%d ham=%.3f crc=%d score=%.2f",
                 r.sub, r.stk_ops, r.stk_loops, r.ca, r.acf_z, r.acf_lag,
                 r.ham, r.crc, r.score);
        CHECK("coded: gate passes", gate, d);
        CHECK("coded: STACK loops fire", r.f_stk, d);
        CHECK("coded: frame ACF fires", r.f_acf, d);
        CHECK("coded: Hamming excess fires", r.f_ham, d);
        CHECK("coded: CRC excess fires", r.f_crc, d);
        CHECK("coded: CA breathes", r.f_ca, d);
        CHECK("coded: XENO-CANDIDATE (>=3/6)", r.score >= 0.5, d);
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
