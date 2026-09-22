"""drift_hunt.py - SetiYeti narrowband drift search on filterbank power.

WHY THIS EXISTS: the pipeline could track drift in VOLTAGE (jerk_scan) but
was blind to drifting tones in POWER data - which is what filterbank/FITS
archives actually are, and what turboSETI hunts. A 30-minute Parkes stare
at 3.8 Hz channels (the Proxima 14 GB file) is useless without de-Doppler:
an Earth-rotation drift of 0.1 Hz/s walks 180 channels over the stare and
no single bin ever exceeds threshold. This integrates along drift tracks.

Method (incoherent Taylor-style shift-and-add, memmap - never loads 14 GB):
  for each channel chunk (524288 chans):
    for each drift rate in [-drmax, +drmax]:
      shift spectrum t by rate*t*tsamp/chan_bw bins, sum over time
      robust-z vs running-median background; keep peaks >= thresh
  non-max suppression +-3 bins; top-K per chunk; hits CSV out.

  python drift_hunt.py --prove
  python drift_hunt.py --fil D:/raw/x.fil --drmax 2 --step 0.05 --out runs/drift_x.csv
"""
import argparse
import csv
import os
import sys

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import univ_ingest as UI

CHUNK = 1 << 19
THRESH_DEFAULT = 8.0


def memmap_fil(path):
    hdr, off = UI.parse_fil_header(path)
    nchans = int(hdr['nchans'])
    nifs = int(hdr.get('nifs', 1))
    nbits = int(hdr.get('nbits', 8))
    bps = nchans * nifs * nbits // 8
    ns = (os.path.getsize(path) - off) // bps
    dt = {8: np.uint8, 16: np.uint16, 32: np.float32}[nbits]
    mm = np.memmap(path, dtype=dt, mode='r', offset=off,
                   shape=(ns, nifs * nchans if nifs > 1 else nchans))
    return hdr, mm, ns


def bg_flatten(S):
    try:
        from scipy.ndimage import median_filter
        bg = median_filter(S, size=1001, mode='reflect')
    except ImportError:
        k = np.ones(101) / 101.0
        bg = np.convolve(np.pad(S, 50, mode='edge'), k, mode='valid')
        bg = np.interp(np.arange(len(S)),
                       np.linspace(0, len(S) - 1, len(bg)), bg)
    med = float(np.median(np.abs(S - bg))) or 1e-30
    return (S - bg) / (1.4826 * med), bg


def search_chunk(D, tsamp, chan_bw, rates, thresh, f0_mhz, c0):
    """D: (nt, nch) float32. Returns [(freq_mhz, rate, sigma)]."""
    nt, nch = D.shape
    t = np.arange(nt) * tsamp
    hits = []
    for r in rates:
        shifts = np.round(r * t / chan_bw).astype(int)
        acc = np.zeros(nch, dtype=np.float64)
        for i in range(nt):
            acc += np.roll(D[i].astype(np.float64), -int(shifts[i]))
        z, _ = bg_flatten(acc / nt)
        # edges contaminated by rollaround: mask max shift
        m = int(np.abs(shifts).max()) + 4
        z[:m] = 0
        z[-m:] = 0
        order = np.argsort(z)[::-1]
        taken = np.zeros(nch, bool)
        for k in order[:25]:
            if z[k] < thresh or taken[k]:
                continue
            taken[max(0, k - 3):k + 4] = True
            hits.append((f0_mhz + (c0 + k) * chan_bw / 1e6
                         if chan_bw else 0.0, float(r), float(z[k])))
    # cross-rate dedup: same line found at adjacent rates
    hits.sort(key=lambda h: -h[2])
    kept, used = [], []
    for f, r, s in hits:
        if any(abs(f - uf) < 3 * abs(chan_bw) / 1e6 for uf in used):
            continue
        used.append(f)
        kept.append((f, r, s))
    return kept


def run_fil_v2(path, drmax=2.0, step=0.05, thresh=THRESH_DEFAULT,
               out='', topk_total=300, log=None):
    hdr, mm, ns = memmap_fil(path)
    nchans = int(hdr['nchans'])
    tsamp = float(hdr['tsamp'])
    fch1 = float(hdr.get('fch1', 0.0))
    foff = float(hdr.get('foff', 0.0))
    chan_bw = abs(foff) * 1e6
    rates = np.arange(-drmax, drmax + step / 2, step)
    resol = chan_bw / max(ns * tsamp, 1e-30)
    msg = (f'[drift] {os.path.basename(path)}: {ns} spectra x {nchans} chans '
           f'({chan_bw:.1f} Hz), {len(rates)} rates +- {drmax} Hz/s, thresh={thresh}')
    (log or print)(msg)
    if resol > step:
        (log or print)(f'[drift] NOTE: drift resolution {resol:.2f} Hz/s >> step; '
                       f'rates below that are ties, reported as 0 unless proven')
    allhits = []
    nchunks = (nchans + CHUNK - 1) // CHUNK
    for ci in range(nchunks):
        c0 = ci * CHUNK
        c1 = min(c0 + CHUNK, nchans)
        D = np.asarray(mm[:, c0:c1], dtype=np.float32)
        nt, nch = D.shape
        t = np.arange(nt) * tsamp
        for r in rates:
            shifts = np.round(r * t / chan_bw).astype(int)
            acc = np.zeros(nch, dtype=np.float64)
            for i in range(nt):
                acc += np.roll(D[i].astype(np.float64), -int(shifts[i]))
            z, _ = bg_flatten(acc / nt)
            m = int(np.abs(shifts).max()) + 4
            z[:m] = 0
            z[-m:] = 0
            order = np.argsort(z)[::-1]
            taken = np.zeros(nch, bool)
            for k in order[:25]:
                if z[k] < thresh or taken[k]:
                    continue
                taken[max(0, k - 3):k + 4] = True
                fmhz = fch1 + (c0 + k) * foff
                allhits.append((fmhz, float(r), float(z[k])))
        if log and ci % 8 == 0:
            log(f'[drift] chunk {ci}/{nchunks} hits={len(allhits)}')
    allhits.sort(key=lambda h: h[0])
    complexes, cur = [], []
    for h in allhits:
        if cur and h[0] - cur[-1][0] > 0.5:
            complexes.append(cur)
            cur = []
        cur.append(h)
    if cur:
        complexes.append(cur)
    complexes.sort(key=lambda c: -max(h[2] for h in c))
    kept = []
    for c in complexes:
        # tie-prefer rate 0: a steady line scores identically at every rate
        # when drift displacement << channel width (measured: 2.86 kHz chans
        # x 300 s stare; all 81 rates tied, argmax order picked the grid edge
        # -2.0 and reported a phantom fast drifter). Zero unless drift proven.
        best = max(c, key=lambda h: (h[2], -abs(h[1])))
        kept.append((best[0], best[1], best[2], len(c), round(c[-1][0] - c[0][0], 3)))
    lo = fch1 + (0 if foff > 0 else (nchans - 1) * foff)
    strat = []
    for si in range(16):
        a, b = lo + si * 8.0, lo + (si + 1) * 8.0
        inb = [h for h in allhits if a <= h[0] < b]
        inb.sort(key=lambda h: -h[2])
        seen = []
        for h in inb:
            if all(abs(h[0] - s) > 0.05 for s in seen):
                seen.append(h[0])
                strat.append(h)
            if len(seen) >= 5:
                break
    if out:
        with open(out, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['freq_mhz', 'drift_hz_s', 'sigma', 'kind'])
            for f, r, s, n, span in kept[:topk_total]:
                w.writerow([f'{f:.6f}', f'{r:.4f}', f'{s:.2f}',
                            f'complex n={n} span={span}MHz'])
            for f, r, s in strat:
                w.writerow([f'{f:.6f}', f'{r:.4f}', f'{s:.2f}', 'stratified'])
        print(f'[drift] {len(complexes)} complexes + {len(strat)} stratified -> {out}')
    return hdr, kept


def prove():
    rng = np.random.default_rng(31)
    ns, nc = 64, 4096
    tsamp, cbw = 1.0, 1.0
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    noise = rng.normal(100, 5, (ns, nc)).astype(np.float32)
    # noise-only max over the grid (trial multiplicity is the calibration)
    zmax = 0.0
    t = np.arange(ns) * tsamp
    for r in np.arange(-2, 2.05, 0.25):
        sh = np.round(r * t / cbw).astype(int)
        acc = np.zeros(nc)
        for i in range(ns):
            acc += np.roll(noise[i].astype(np.float64), -int(sh[i]))
        z, _ = bg_flatten(acc / ns)
        zmax = max(zmax, z[8:-8].max())
    check('CTRL noise max below thresh', zmax < 8.0, f'max={zmax:.2f} < 8')
    # injected drifted tone +1.5 Hz/s
    y = noise.copy()
    for i in range(ns):
        k = 500 + int(round(1.5 * i * tsamp / cbw))
        y[i, k - 1:k + 2] += np.array([30.0, 50.0, 30.0])
    hits = search_chunk(y, tsamp, cbw, np.arange(-2, 2.05, 0.25), 8.0,
                        1400.0, 100)
    got = [h for h in hits if abs(h[0] - (1400.0 + (100 + 500) * cbw / 1e6)) < 5 * cbw / 1e6]
    rec = min([abs(h[1] - 1.5) for h in got]) if got else 9e9
    check('INJECT drift +1.5 recovered', bool(got) and rec <= 0.125,
          f'rate_err={rec:.3f} sigma={got[0][2]:.1f}' if got else 'missed')
    # zero-drift tone (hum-like): found at rate 0
    y2 = noise.copy()
    y2[:, 2000 - 1:2000 + 2] += np.array([30.0, 50.0, 30.0])
    hits2 = search_chunk(y2, tsamp, cbw, np.arange(-2, 2.05, 0.25), 8.0,
                         1400.0, 100)
    zero = [h for h in hits2 if abs(h[1]) < 1e-9]
    check('INJECT zero-drift found at 0', bool(zero),
          f'sigma={zero[0][2]:.1f}' if zero else 'missed')
    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def run_h5(path, drmax=2.0, step=0.05, thresh=THRESH_DEFAULT,
           out='', topk_total=300, log=None):
    import univ_ingest as UI
    meta, arr = UI.open_any(path)
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 3:
        a = a[:, 0, :]
    ns, nchans = a.shape
    tsamp = float(meta.get('tsamp') or 1.0)
    fch1 = float(meta.get('fch1_mhz') or 0.0)
    foff = float(meta.get('foff_mhz') or 0.0)
    chan_bw = abs(foff) * 1e6
    rates = np.arange(-drmax, drmax + step / 2, step)
    (log or print)(f'[drift] {os.path.basename(path)}: {ns} spectra x '
                    f'{nchans} chans ({chan_bw:.1f} Hz), {len(rates)} rates')
    allhits = []
    nchunks = (nchans + CHUNK - 1) // CHUNK
    for ci in range(nchunks):
        c0 = ci * CHUNK
        D = np.ascontiguousarray(a[:, c0:c0 + CHUNK], dtype=np.float32)
        nt, nch = D.shape
        t = np.arange(nt) * tsamp
        for r in rates:
            shifts = np.round(r * t / chan_bw).astype(int)
            acc = np.zeros(nch, dtype=np.float64)
            for i in range(nt):
                acc += np.roll(D[i].astype(np.float64), -int(shifts[i]))
            z, _ = bg_flatten(acc / nt)
            m = int(np.abs(shifts).max()) + 4
            z[:m] = 0
            z[-m:] = 0
            order = np.argsort(z)[::-1]
            taken = np.zeros(nch, bool)
            for k in order[:25]:
                if z[k] < thresh or taken[k]:
                    continue
                taken[max(0, k - 3):k + 4] = True
                allhits.append((fch1 + (c0 + k) * foff, float(r), float(z[k])))
    allhits.sort(key=lambda h: h[0])
    complexes, cur = [], []
    for h in allhits:
        if cur and abs(h[0] - cur[-1][0]) > 0.5:
            complexes.append(cur)
            cur = []
        cur.append(h)
    if cur:
        complexes.append(cur)
    complexes.sort(key=lambda c: -max(h[2] for h in c))
    kept = []
    for c in complexes:
        # tie-prefer rate 0 (see run_fil_v2 note: sub-bin grids tie).
        best = max(c, key=lambda h: (h[2], -abs(h[1])))
        kept.append((best[0], best[1], best[2], len(c),
                     round(abs(c[-1][0] - c[0][0]), 3)))
    if out:
        with open(out, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['freq_mhz', 'drift_hz_s', 'sigma', 'kind'])
            for f, r, s, n, span in kept[:topk_total]:
                w.writerow([f'{f:.6f}', f'{r:.4f}', f'{s:.2f}',
                            f'complex n={n} span={span}MHz'])
        print(f'[drift] {len(complexes)} complexes -> {out}')
    return {'fch1': fch1}, kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fil', default='')
    ap.add_argument('--h5', default='')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--drmax', type=float, default=2.0)
    ap.add_argument('--step', type=float, default=0.05)
    ap.add_argument('--thresh', type=float, default=THRESH_DEFAULT)
    ap.add_argument('--out', default='')
    ap.add_argument('--topk', type=int, default=300)
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove() else 1)
    if a.h5:
        run_h5(a.h5, a.drmax, a.step, a.thresh, a.out, a.topk, print)
    elif a.fil:
        run_fil_v2(a.fil, a.drmax, a.step, a.thresh, a.out, a.topk, print)
    else:
        sys.exit('need --fil or --h5 (or --prove)')


if __name__ == '__main__':
    main()
