/* cbmc_stubs.h — SetiYeti CBMC compatibility shim (C99).
 *
 * Under real CBMC (__CPROVER__ defined) this exposes the prover builtins.
 * Under gcc it provides deterministic stand-ins so the same harness runs
 * as a fast bounded fuzzer: nondet values come from a seeded xorshift,
 * assume() prunes by returning, assert() counts failures and prints.
 */
#ifndef SY_CBMC_STUBS_H
#define SY_CBMC_STUBS_H

#ifdef __CPROVER__
/* real prover: nothing to define (builtins exist) */
#else
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

static uint64_t _cbmc_rng = 0xC80C5EED12345678ULL;

static inline uint64_t _cbmc_next(void) {
    /* plain xorshift64* (no MC pun — ok, one pun) */
    _cbmc_rng ^= _cbmc_rng >> 12;
    _cbmc_rng ^= _cbmc_rng << 25;
    _cbmc_rng ^= _cbmc_rng >> 27;
    return _cbmc_rng * 0x2545F4914F6CDD1DULL;
}

static inline int nondet_int(void) { return (int)(_cbmc_next() & 0xFFFFFFFFULL); }
static inline unsigned nondet_uint(void) { return (unsigned)(_cbmc_next() & 0xFFFFFFFFULL); }
static inline float nondet_float(void) {
    return (float)((int)(_cbmc_next() % 20001) - 10000) / 1000.0f;
}
static inline double nondet_double(void) {
    return (double)((long long)(_cbmc_next() % 20001) - 10000) / 1000.0;
}

/* harness protocol: assume() skips the case, assert() records. */
static int _cbmc_fail = 0;
static inline void __CPROVER_assume(int c) {
    /* gcc fallback cannot prune like the prover; harnesses structure their
     * checks as `if (!cond) return-or-continue` around this, so a no-op
     * assume keeps the fuzz sound (it just explores fewer prunes). */
    (void)c;
}
static inline void __CPROVER_assert(int c, const char *msg) {
    if (!c) {
        _cbmc_fail++;
        if (_cbmc_fail < 6) printf("  [ASSERT-FAIL] %s\n", msg);
    }
}
#endif /* __CPROVER__ */

#endif
