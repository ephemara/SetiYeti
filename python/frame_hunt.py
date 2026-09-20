"""frame_hunt.py - M2: long-baseline repetition / frame-period hunter.

WHY THIS EXISTS (Objective 1, section 3.3)
------------------------------------------
Our target class is *traffic*, not beacons. Packetised traffic leaves a
signature a hum does not: a **repeating frame period**. Content has to restart
so a late listener can catch the beginning, and error-corrected frames mean
transmit power rises and falls on a fixed cadence.

A tone (beacon, hum, carrier) has no frame period. It has a *frequency*.
A modulated link has a *rhythm*. This tool hunts the rhythm.

METHOD - whitened envelope periodogram
--------------------------------------
    1. power envelope      env[n] = x[n]^2
    2. decimate            average D raw samples -> env_fs = fs/D
    3. high-pass           remove 1/f wander and DC
    4. periodogram         Hann-windowed, zero-padded FFT -> P(f)
    5. whiten              Q(f) = P(f) / running-median(P)  <- the key step:
                           correlated "red" noise is smooth in f, so dividing by
                           a running median flattens it and makes Q directly
                           interpretable (peaks of a periodic signal stand out
                           against a flat floor regardless of spectral shape)
    6. harmonic summation  a frame rate shows peaks at f0, 2f0, 3f0 ...
    7. fundamental         argmax, then walk DOWN sub-harmonics

WHY NOT AUTOCORRELATION
-----------------------
Three ACF variants were tried and measured before this:

  * unbiased ACF          divides by (N-L) -> variance blows up at long lags;
                          produced a fake z=+42 plateau that beat the real
                          period (z=+30)
  * flat r*sqrt(N)        assumes white ACF residuals; the envelope high-pass
                          correlates neighbouring lags -> noise-only hit 25 sigma
  * log-spaced z blocks   adapts locally but creates hard steps, breaking the
                          harmonic sum (T and 5T land in different blocks;
                          a 12 ms injection reported 36 ms)

The periodogram sidesteps all three because the noise floor is estimated as a
function of frequency, which is exactly where the red-noise shape lives.

HONEST LIMITATION
-----------------
A periodic local artifact (the 179 Hz backend hum) IS a periodic envelope
modulation and WILL be detected here. That is correct: this tool finds
periodicity, it does not decide origin. Attribution is the veto's job (M1).
Detection != attribution.

Usage
  python frame_hunt.py --raw data/<file>.raw --chan 27 --blocks 7 [--pol 0]
  python frame_hunt.py --f32 data/ch.f32 [--dec 512] [--topk 8]
  python frame_hunt.py --prove
  python frame_hunt.py --f32 ch.f32 --json      # one machine-readable line
"""
import argparse, json, os, subprocess, sys
import numpy as np

FS_DEFAULT = 2929687.5      # Hz, GBT GUPPI coarse-channel sample rate
DEC_DEFAULT = 512           # envelope decimation -> env_fs = FS/DEC
HP_FC_DEFAULT = 2.0         # Hz, high-pass corner on the envelope
HARMONICS = 6
PAD = 4                     # FFT zero-padding (period resolution)
K_SIGMA = 40.0              # score significance threshold.
                            # Calibrated from the prove: the noise-only maximum
                            # over 16 independent draws is ~14 sigma (heavy tail,
                            # because the score is a harmonic SUM and a chance
                            # alignment of bins inflates it). Injected frames
                            # land at 1900-27000 sigma. 40 sits in that ~140x
                            # gap: 3x above the measured noise tail and >40x
                            # below the weakest synthetic detection.

try:
    from scipy.signal import butter, filtfilt
    from scipy.ndimage import median_filter
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False


# -------------------------------------------------------------------- loading --
def load_f32(path):
    return np.fromfile(path, dtype=np.float32)


def slice_raw(root, raw, chan, blocks, pol, out):
    ext = '.exe' if os.name == 'nt' else ''
    exe = os.path.join(root, 'c', 'seti_slice' + ext)
    r = subprocess.run([exe, raw, str(chan), out, str(blocks), '--pol', str(pol)],
                       capture_output=True, text=True)
    if not os.path.exists(out) or os.path.getsize(out) < 100000:
        raise RuntimeError(f'seti_slice produced no data for chan {chan}: {r.stdout[:200]}')
    return out


# --------------------------------------------------------------------- stages --
def block_samples_from_raw(path):
    """Samples per acquisition block, read from the GUPPI header.

    bpt (bytes per time tick) = NCHAN * NPOL * NBITS/8; samples/block =
    BLOCSIZE / bpt. For TRAPPIST blc04: 64*4*1 = 256 and 134217728/256 = 524288.
    """
    try:
        with open(path, 'rb') as fh:
            blob = fh.read(80 * 512)
    except OSError:
        return None
    d = {}
    for i in range(0, len(blob) - 80, 80):
        c = blob[i:i + 80].decode('ascii', 'replace')
        if c.startswith('END'):
            break
        if '=' in c:
            k, v = c.split('=', 1)
            d[k.strip()] = v.split('/')[0].strip()
    try:
        bs = int(float(d.get('BLOCSIZE') or 0))
        nchan = int(float(d.get('OBSNCHAN') or d.get('NCHAN') or 0))
        npol = int(float(d.get('NPOL') or 0))
        nbits = int(float(d.get('NBITS') or 0))
    except (TypeError, ValueError):
        return None
    bpt = nchan * npol * nbits // 8
    if bs <= 0 or bpt <= 0:
        return None
    return bs // bpt


def envelope(x, dec):
    n = (len(x) // dec) * dec
    if n < dec * 16:
        return None, 0
    return (x[:n].astype(np.float64) ** 2).reshape(-1, dec).mean(axis=1), n


def highpass(env, fs_d, fc):
    if fc <= 0:
        return env - env.mean()
    if HAVE_SCIPY and fc < 0.9 * fs_d / 2:
        b, a = butter(2, fc / (fs_d / 2.0), 'high')
        return filtfilt(b, a, env)
    w = max(4, int(round(fs_d / max(fc, 1e-3))))
    if w >= len(env):
        return env - env.mean()
    return env - np.convolve(env, np.ones(w) / w, mode='same')


def periodogram(env, pad=PAD):
    n = len(env)
    e = env - env.mean()
    e = e * np.hanning(n)
    nfft = int(2 ** np.ceil(np.log2(max(n * pad, 16))))
    F = np.fft.rfft(e, n=nfft)
    return np.abs(F) ** 2, nfft


def normalize_blocks(env, block_env_len):
    """Divide the envelope by each acquisition block's own mean.

    Blocks are separate network captures, so their levels differ slightly
    (measured on real TRAPPIST data: per-block mean envelope 205.4 .. 206.9, a
    ~0.7% spread). That is only ~0.5% of a modulation, but with many blocks it is
    a coherent periodic signal at the BLOCK cadence and it dominates everything
    else: measured, the hunter reported a 116 sigma "frame" at half the block
    period that was completely absent when the same data was analysed one block
    at a time (1-3 blocks: no detection at all).

    NOTE: this also removes any genuine modulation at exactly the block cadence.
    That is the correct trade - an instrumental block rate is always present and
    would otherwise swamp the search.
    """
    if not block_env_len or block_env_len < 8:
        return env
    n = len(env)
    nb = n // block_env_len
    if nb < 2:
        return env
    out = env.copy()
    trimmed = nb * block_env_len
    seg = out[:trimmed].reshape(nb, block_env_len)
    m = seg.mean(axis=1, keepdims=True)
    seg /= np.maximum(m, 1e-30)
    out[:trimmed] = seg.reshape(-1)
    return out


def whiten(P, nbins=48):
    """Q = P(f) / continuum(f), where the continuum is a SMOOTH curve estimated
    in log-log space.

    A linear-space running median fails at the low-frequency end: the red-noise
    continuum falls steeply there, so a flat window drags the estimate down and
    manufactures a huge fake excess at the edge of the search band (measured on
    real TRAPPIST data: a spurious 40-3800 sigma "detection" sitting exactly at
    the maximum allowed period). Estimating the continuum in log-spaced bins and
    interpolating handles a power-law-shaped continuum correctly.
    """
    n = len(P)
    idx = np.arange(n, dtype=np.float64)
    edges = np.unique(np.geomspace(2, max(n - 1, 4), nbins + 1).astype(int))
    centers, vals = [], []
    for i in range(len(edges) - 1):
        lo, hi = int(edges[i]), int(edges[i + 1])
        if hi - lo < 2:
            continue
        centers.append(np.sqrt(float(lo) * float(hi)))
        vals.append(float(np.median(P[lo:hi])))
    if len(centers) < 3:
        return P / max(float(np.median(P)), 1e-30)
    cont = np.interp(idx, centers, vals)
    return P / np.maximum(cont, 1e-30)


def bin_of_period(period_s, fs_d, nfft, n):
    """Period (s) -> rfft bin index."""
    if period_s <= 0:
        return None
    f = 1.0 / period_s
    i = int(round(f * nfft / fs_d))
    return i if 0 < i < len(np.fft.rfft(np.zeros(n), n=nfft)) else None


def harmonic_score(Q, i0, H=HARMONICS, halfwin=1):
    """Sum of the first H harmonics at bin i0.., peak-picked within +-halfwin."""
    s = 0.0
    nh = 0
    n = len(Q)
    for h in range(1, H + 1):
        i = i0 * h
        if i >= n:
            break
        lo, hi = max(1, i - halfwin), min(n, i + halfwin + 1)
        s += float(Q[lo:hi].max()) / np.sqrt(h)
        nh += 1
    return s, nh


# -------------------------------------------------------------------- detect --
def detect(x, fs=FS_DEFAULT, dec=DEC_DEFAULT, fc=HP_FC_DEFAULT,
           min_period_s=1e-3, max_period_s=None, topk=8, block_samples=None):
    env, n_used = envelope(x, dec)
    if env is None:
        return {'frame_detected': False, 'reason': 'not enough samples'}
    fs_d = fs / float(dec)
    span_s = n_used / float(fs)
    block_env_len = int(round(block_samples / dec)) if block_samples else None
    env = normalize_blocks(env, block_env_len)
    if max_period_s is None:
        max_period_s = span_s / 8.0        # >=8 cycles: avoids searching at the
                                           # very edge of the band, where the
                                           # continuum estimate is least reliable

    env = highpass(env, fs_d, fc)
    P, nfft = periodogram(env)
    Q = whiten(P)
    nfreq = len(Q)
    df = fs_d / nfft

    i_min = max(2, int(np.ceil((1.0 / max_period_s) / df)))
    i_max = min(nfreq - 1, int(np.floor((1.0 / min_period_s) / df)))
    if i_max <= i_min + 2:
        return {'frame_detected': False, 'reason': 'frequency range empty'}

    # ---- harmonic scan over fundamental candidates -----------------------
    freqs = np.arange(i_min, i_max + 1)
    score = np.zeros(len(freqs), dtype=np.float64)
    for k, i0 in enumerate(freqs):
        s, _ = harmonic_score(Q, int(i0))
        score[k] = s
    med = float(np.median(score))
    mad = float(np.median(np.abs(score - med)))
    scale = 1.4826 * mad if mad > 0 else (float(score.std()) or 1e-12)
    sig = (float(score.max()) - med) / scale

    # ---- fundamental selection ------------------------------------------
    # A periodic signal has a periodic spectrum, so f0, 2f0, 3f0 all carry peaks
    # and near-identical harmonic sums (measured: a 12 ms injection scored 55 at
    # T and 70 at 5T). Taking the raw argmax reports an arbitrary multiple.
    # Standard fix: take the argmax, then walk DOWN sub-harmonics while the
    # score stays comparable. Lands on the true fundamental deterministically.
    kbest = int(np.argmax(score))
    i_best = int(freqs[kbest])
    s_best = float(score[kbest])
    for _ in range(10):
        moved = False
        for d in range(2, 9):
            ik = i_best // d
            if ik < i_min:
                continue
            sk, _ = harmonic_score(Q, ik)
            if sk >= 0.75 * s_best:
                i_best, s_best, moved = ik, sk, True
                break
        if not moved:
            break
    period_s = 1.0 / (i_best * df)
    sig_final = (s_best - med) / scale

    # ---- report -----------------------------------------------------------
    order = np.argsort(score)[::-1]
    tops, seen = [], [period_s]
    for k in order:
        i0 = int(freqs[k])
        ts = 1.0 / (i0 * df)
        if any(abs(ts - s) / s < 0.03 for s in seen):
            continue
        seen.append(ts)
        _, nh = harmonic_score(Q, i0)
        tops.append({'period_s': ts, 'freq_hz': i0 * df, 'bin': i0,
                     'score': float(score[k]),
                     'sigma': float((score[k] - med) / scale),
                     'n_harmonics': int(nh)})
        if len(tops) >= topk:
            break

    return {'frame_detected': bool(sig_final >= K_SIGMA),
            'best_period_s': period_s,
            'best_freq_hz': i_best * df,
            'best_bin': i_best,
            'best_score': s_best,
            'sigma': float(sig_final),
            'n_used': int(n_used), 'dec': dec, 'env_fs': fs_d,
            'span_s': span_s, 'block_samples': block_samples,
            'block_env_len': block_env_len,
            'min_period_s': 1.0 / (i_max * df), 'max_period_s': 1.0 / (i_min * df),
            'df_hz': df, 'n_fft': nfft,
            'floor_med': med, 'floor_scale': scale,
            'top': tops}


# --------------------------------------------------------------------- prove ---
def inject_frames(x, period_samples, duty=0.2, depth=0.35):
    """A packetised link: power rises on a fixed cadence. Mean-preserving."""
    n = len(x)
    t = np.arange(n, dtype=np.int64)
    phase = (t % int(period_samples)) / float(period_samples)
    gate = (phase < duty).astype(np.float64)
    scale = 1.0 + depth * (gate - duty) / np.sqrt(duty * (1 - duty)) * 0.5
    return (x * scale).astype(np.float32)


def prove(fs=FS_DEFAULT, verbose=True):
    rng = np.random.default_rng(2024)
    N = 7 * 524288
    results = []

    def check(name, ok, detail=''):
        results.append(bool(ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}   {detail}")

    if verbose:
        print(f"=== M2 frame-hunt prove ({N:,} samples, {N/fs:.2f} s, "
              f"{'scipy' if HAVE_SCIPY else 'fallback'}) ===\n")

    noise = rng.normal(0, 14.0, N).astype(np.float32)

    # ---- CONTROL: noise must not fire ------------------------------------
    res = detect(noise, fs=fs)
    check('CTRL noise-only does not fire', not res['frame_detected'],
          f"sigma={res['sigma']:.2f} < {K_SIGMA}")

    # ---- INJECTION: recover the frame period ------------------------------
    for period_s in (2.5e-3, 12e-3, 60e-3):
        y = inject_frames(noise, period_s * fs)
        res = detect(y, fs=fs)
        got = res.get('best_period_s', 0.0)
        err = abs(got - period_s) / period_s
        check(f'INJECT frame {period_s*1e3:5.1f} ms recovered',
              res['frame_detected'] and err < 0.05,
              f"got={got*1e3:8.3f} ms sigma={res['sigma']:5.1f} err={err*100:.2f}%")

    # ---- INJECTION under a strong local hum (the real-world case) --------
    t = np.arange(N) / fs
    hum = (0.8 * np.sin(2 * np.pi * 179.0 * t)
           + 0.4 * np.sin(2 * np.pi * 268.0 * t)).astype(np.float32)
    y = inject_frames(noise + hum, 12e-3 * fs)
    res = detect(y, fs=fs)
    got = res.get('best_period_s', 0.0)
    err = abs(got - 12e-3) / 12e-3
    check('INJECT frame 12 ms under 179+268 Hz hum',
          res['frame_detected'] and err < 0.05,
          f"got={got*1e3:.3f} ms sigma={res['sigma']:.1f}")

    # ---- DRIFT: instantaneous period wanders +/-5% -----------------------
    per0 = 12e-3 * fs
    tt = np.arange(N, dtype=np.float64)
    inst = per0 * (1.0 + 0.05 * np.sin(2 * np.pi * tt / N))
    phase = np.cumsum(1.0 / inst)
    gate = ((phase % 1.0) < 0.2).astype(np.float64)
    y = (noise * (1.0 + 0.35 * (gate - 0.2))).astype(np.float32)
    res = detect(y, fs=fs)
    got = res.get('best_period_s', 0.0)
    check('DRIFT +/-5% frame still found near 12 ms',
          res['frame_detected'] and abs(got - 12e-3) / 12e-3 < 0.10,
          f"got={got*1e3:.3f} ms sigma={res['sigma']:.1f}")

    # ---- BLOCK-LEVEL gain steps: must not be reported as a frame ----------
    # Separate network-capture blocks carry slightly different levels
    # (measured on real TRAPPIST: per-block mean envelope 205.4..206.9). That is
    # a coherent periodic modulation at the block cadence and must not be read
    # as traffic; per-block normalisation removes it.
    #
    # NOTE: the artifact actually hit on real data was a different and nastier
    # one, fixed elsewhere - a MEMORY-LAYOUT bug in c/seti_slice.c, which read
    # these files time-major when they are stored channel-major
    # ([chan][pol][time]). That swept the receiver bandpass end to end once per
    # block, producing a bit-identical sawtooth in every block and a 120-155
    # sigma phantom "frame" that disappeared when analysed 1-3 blocks at a time.
    BLK = 524288
    nblk = N // BLK
    lvl = 1.0 + 0.02 * np.array([(-1) ** b for b in range(nblk)], dtype=np.float64)
    y = (noise * np.repeat(lvl, BLK)).astype(np.float32)
    fixed_res = detect(y, fs=fs, block_samples=BLK)
    check('BLOCK-LEVEL gain steps not reported as a frame',
          not fixed_res['frame_detected'],
          f"sigma={fixed_res['sigma']:.1f} (threshold {K_SIGMA})")

    # and a real frame must SURVIVE the normalisation
    y = inject_frames(noise * np.repeat(lvl, BLK).astype(np.float32), 12e-3 * fs)
    res = detect(y, fs=fs, block_samples=BLK)
    got = res.get('best_period_s', 0.0)
    check('FRAME survives per-block normalisation alongside block-level junk',
          res['frame_detected'] and abs(got - 12e-3) / 12e-3 < 0.05,
          f"got={got*1e3:.3f} ms sigma={res['sigma']:.1f}")

    # ---- FALSE-POSITIVE RATE over independent noise realisations ---------
    fires = 0
    trials = 16
    worst = 0.0
    for i in range(trials):
        r2 = np.random.default_rng(9000 + i)
        nn = r2.normal(0, 14.0, N).astype(np.float32)
        rr = detect(nn, fs=fs)
        worst = max(worst, rr.get('sigma', 0.0))
        if rr['frame_detected']:
            fires += 1
    check(f'CONTROL false-positive rate over {trials} noise draws',
          fires == 0, f'fired {fires}/{trials}, worst sigma={worst:.1f} '
                      f'(threshold {K_SIGMA})')

    return results


# ---------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f32')
    ap.add_argument('--raw')
    ap.add_argument('--chan', type=int, default=27)
    ap.add_argument('--pol', type=int, default=0)
    ap.add_argument('--blocks', type=int, default=7)
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--fs', type=float, default=FS_DEFAULT)
    ap.add_argument('--dec', type=int, default=DEC_DEFAULT)
    ap.add_argument('--hp', type=float, default=HP_FC_DEFAULT)
    ap.add_argument('--min-period-s', type=float, default=1e-3)
    ap.add_argument('--max-period-s', type=float)
    ap.add_argument('--topk', type=int, default=8)
    ap.add_argument('--block-samples', type=int,
                    help='raw samples per acquisition block (auto-read from --raw); '
                         'enables per-block envelope normalisation')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    if a.prove:
        r = prove()
        ok = sum(1 for x in r if x)
        print(f"\n=== {ok}/{len(r)} checks passed ===")
        print('PROVE PASS: frame hunter recovers cadenced traffic and stays quiet on noise'
              if ok == len(r) else 'PROVE FAILED')
        return 0 if ok == len(r) else 1

    tmp = None
    blk_samples = a.block_samples
    if a.raw:
        if blk_samples is None:
            blk_samples = block_samples_from_raw(a.raw)
        tmp = os.path.join(a.root, 'data', f'_fh_{a.chan}.f32')
        slice_raw(a.root, a.raw, a.chan, a.blocks, a.pol, tmp)
        x = load_f32(tmp)
    elif a.f32:
        x = load_f32(a.f32)
    else:
        print('need --f32 or --raw', file=sys.stderr)
        return 2

    res = detect(x, fs=a.fs, dec=a.dec, fc=a.hp,
                 min_period_s=a.min_period_s, max_period_s=a.max_period_s,
                 topk=a.topk, block_samples=blk_samples)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)

    if a.json:
        print(json.dumps(res))
        return 0

    print(f"[frame] N={len(x):,}  span={res['span_s']:.3f}s  dec={res['dec']}  "
          f"env_fs={res['env_fs']:.1f}Hz  df={res['df_hz']*1e3:.2f} mHz")
    print(f"[frame] period range {res['min_period_s']*1e3:.2f} .. "
          f"{res['max_period_s']*1e3:.1f} ms   (floor med={res['floor_med']:.2f} "
          f"scale={res['floor_scale']:.2f}, threshold {K_SIGMA} sigma)")
    print(f"[frame] top candidates:")
    for t in res['top']:
        print(f"          period={t['period_s']*1e3:9.3f} ms  "
              f"({t['freq_hz']:8.2f} Hz)  sigma={t['sigma']:+7.2f}  "
              f"harmonics={t['n_harmonics']}")
    tag = 'FRAME DETECTED' if res['frame_detected'] else 'no frame'
    print(f"[frame] VERDICT: {tag}  (best {res['best_period_s']*1e3:.3f} ms / "
          f"{res['best_freq_hz']:.2f} Hz, {res['sigma']:.2f} sigma)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
