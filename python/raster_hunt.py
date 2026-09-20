"""raster_hunt.py — BEAST payload framing detector (M8: Arecibo-class raster).

Objective 1 §2.3: the factorisation IS the message. A prime-factor block
(n = p×q) folded to 2D with spatial autocorrelation above shuffled + 1D
controls = picture/page, not noise. Hooks:

  1. semiprime factorisation of candidate bitstream lengths / sync-word periods
  2. 2D fold into p×q + spatial autocorrelation score vs shuffled control
  3. sync-word search (repeating k-bit preamble, k=7..64)

  python raster_hunt.py --prove   # 23×73 Arecibo raster fires, noise does not
  python raster_hunt.py --bits x.sign.bin --p 23 --q 73
"""
import argparse, sys
import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _primes(n):
    sieve = bytearray(b'\x01') * (n + 1)
    sieve[:2] = b'\x00\x00'
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            sieve[i * i:n + 1:i] = b'\x00' * ((n - i * i) // i + 1)
    return [i for i, v in enumerate(sieve) if v]


def semiprime_splits(n, pmin=7):
    """All (p,q) with p*q==n, p<=q, p>=pmin. The Arecibo trick needs exactly this."""
    out = []
    for p in range(pmin, int(n ** 0.5) + 1):
        if n % p == 0:
            out.append((p, n // p))
    return out


def fold_score(bits, p, q, nshuffle=8, seed=0):
    """Spatial autocorrelation excess of p×q fold vs shuffled control."""
    rng = np.random.default_rng(seed)
    b = np.asarray(bits, dtype=float)[:p * q]
    if len(b) < p * q:
        return {'score': 0.0, 'ok': False}
    G = b.reshape(p, q) * 2 - 1  # ±1
    # neighbour agreement (right + down) — pictures cluster, noise ≈ 0
    agree = (np.mean(G[:, :-1] * G[:, 1:]) + np.mean(G[:-1, :] * G[1:, :])) / 2
    ctrl = []
    for _ in range(nshuffle):
        S = rng.permutation(b).reshape(p, q) * 2 - 1
        ctrl.append((np.mean(S[:, :-1] * S[:, 1:]) + np.mean(S[:-1, :] * S[1:, :])) / 2)
    mu, sd = float(np.mean(ctrl)), float(np.std(ctrl) or 1e-12)
    return {'score': float((agree - mu) / sd), 'agree': float(agree),
            'ctrl_mean': mu, 'p': p, 'q': q, 'ok': True}


def sync_search(bits, kmin=7, kmax=64):
    """Best repeating k-bit preamble: max over k of peak autocorrelation."""
    b = np.asarray(bits, dtype=float) * 2 - 1
    best = (0.0, 0)
    for k in range(kmin, min(kmax, len(b) // 4) + 1):
        n = (len(b) // k) * k
        if n < 4 * k:
            continue
        F = b[:n].reshape(-1, k).mean(axis=0)
        s = float(np.abs(F).mean())
        if s > best[0]:
            best = (s, k)
    return {'sync_score': best[0], 'sync_k': best[1]}


def analyze(bits):
    n = len(bits)
    splits = semiprime_splits(n)
    folds = []
    for p, q in splits[:12]:  # cap: biggest frames first is a follow-up pass
        fs = fold_score(bits, p, q)
        if fs['ok']:
            folds.append(fs)
    folds.sort(key=lambda d: -d['score'])
    sync = sync_search(bits)
    detected = bool(folds and folds[0]['score'] >= 5.0)
    return {'n': n, 'splits': splits, 'best_fold': folds[0] if folds else None,
            'sync': sync, 'detected': detected}


def _arecibo_bits():
    # 1679-bit message with a solid border + sparse interior: 2D-clustered,
    # 1D-random-looking. Catches exactly the fold-vs-shuffle excess.
    rng = np.random.default_rng(1974)
    p, q = 23, 73
    G = (rng.random((p, q)) < 0.35).astype(np.uint8)
    G[0, :] = 1; G[-1, :] = 1; G[:, 0] = 1; G[:, -1] = 1
    G[11, :] = 1
    return G.ravel(), p, q


def prove():
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    rng = np.random.default_rng(99)
    noise = rng.integers(0, 2, 1679).astype(np.uint8)
    rn = analyze(noise)
    check('CTRL noise no raster', not rn['detected'],
          f"best={rn['best_fold']['score']:.2f}σ" if rn['best_fold'] else 'no fold')
    msg, p, q = _arecibo_bits()
    ra = analyze(msg)
    check('INJECT 23×73 raster fires', ra['detected'] and ra['best_fold']['p'] == p,
          f"fold={ra['best_fold']['p']}×{ra['best_fold']['q']} σ={ra['best_fold']['score']:.1f}")
    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--bits', default='', help='.bin packed MSB-first (bitslice output)')
    ap.add_argument('--p', type=int, default=0)
    ap.add_argument('--q', type=int, default=0)
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    raw = np.fromfile(a.bits, dtype=np.uint8)
    bits = np.unpackbits(raw)[:200000]
    if a.p and a.q:
        fs = fold_score(bits, a.p, a.q)
        print(f"[raster] {a.p}×{a.q}: agree={fs['agree']:+.3f} σ={fs['score']:+.1f} "
              f"(ctrl {fs['ctrl_mean']:+.3f})")
    else:
        r = analyze(bits)
        b = r['best_fold']
        print(f"[raster] n={r['n']} splits={r['splits'][:6]} best=" +
              (f"{b['p']}×{b['q']} σ={b['score']:.1f}" if b else 'none') +
              f" sync_k={r['sync']['sync_k']} → " + ('RASTER' if r['detected'] else 'no raster'))


if __name__ == '__main__':
    main()
