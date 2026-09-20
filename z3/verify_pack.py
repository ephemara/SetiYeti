"""verify_pack.py — pack_bits roundtrip: exhaustive + differential + Z3.

1. EXHAUSTIVE: all 256 byte values through shipped pack_bits → unpack == identity.
2. DIFFERENTIAL: 500 random bitstreams (incl. non-multiple-of-8 lengths).
3. Z3 BV injectivity is proven in smt2/pack_bits.smt2 (run_smt2.py).
Usage: python z3/verify_pack.py [--root .]
"""
import argparse, os, random, sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import numpy as np
from bitslice import pack_bits  # noqa: E402  (shipped implementation)


def unpack(b, nbits):
    out = np.zeros(nbits, dtype=np.uint8)
    for i in range(nbits):
        out[i] = (b[i >> 3] >> (7 - (i & 7))) & 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    bad = 0
    for v in range(256):
        bits = np.array([(v >> (7 - i)) & 1 for i in range(8)], dtype=np.uint8)
        if not np.array_equal(unpack(pack_bits(bits), 8), bits):
            bad += 1
            print(f'  MISMATCH byte {v:#04x}')
    print(f"[{'PASS' if bad == 0 else 'FAIL'}] exhaustive 256/256 byte roundtrip")
    rng = random.Random(31337)
    for t in range(500):
        n = rng.randint(1, 300)
        bits = np.array([rng.randint(0, 1) for _ in range(n)], dtype=np.uint8)
        if not np.array_equal(unpack(pack_bits(bits), n), bits):
            bad += 1
            if bad <= 3:
                print(f'  MISMATCH stream len {n}')
    print(f"[{'PASS' if bad == 0 else 'FAIL'}] 500 random streams roundtrip")
    print('VERIFY_PACK: ' + ('ALL PASS' if bad == 0 else 'FAILURES PRESENT'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
