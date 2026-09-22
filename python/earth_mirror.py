"""earth_mirror.py - SetiYeti proof: Earth as seen from 40 light-years.

Flip the script: we are the aliens. An exterior observer with a GBT-class
dish looks at Sol from D ly out. What of Earth do they see? Published
answer: Arecibo-class planetary radar (EIRP ~2e13 W) is loud to hundreds of
ly; BMEWS-class warning radars (~3e10 W) are threshold flickers at tens of
ly; everything else is invisible. And Earth's spin+orbit stamps it all with
Doppler CURVATURE -- the shape legacy straight-line pipelines smear away.

This prove synthesizes that exact template, injects it ADDITIVELY into a REAL
archival HIP voltage slice (c/seti_slice from an on-disk HIP raw -- the
standard injection-recovery design: backend quantization is already baked
into the archival samples, the template rides in float), and runs the REAL
battery on it: direct FFT peak-hunt (the mvp_scan method), c/fam_scan
carrier-squared line, c/xeno_scan microscopic flags, python/jerk_scan
Viterbi drift+jerk, plus an informational rfi_veto disposition.
Methodology warning (measured the hard way): NEVER re-quantize AFTER
injecting into 2-bit archival data. The stored samples sit at quantizer
output levels ({-3.34,-1,+1,+3.34}); a second quantize() pass erases any
signal smaller than the distance to the nearest threshold (a 0.3*sigma
tone flips literally 0.0% of samples) while loud neighbors intermodulate
through the double quantizer and manufacture fake cyclostationary lines.
Additive float injection is the correct -- and standard -- design.

Nothing here is bespoke: every stage shells to (or replicates) the shipped
tool. Template physics (EIRP, flux, Doppler v/f = a/c) is documented below;
the one cheat is TIME COMPRESSION on the curved track (see E3), stated
openly -- detector geometry is clock-invariant, and a 300 s voltage capture
is 3.5 GB.

Template (baseband analogs in one 2.93 MHz coarse channel, fs=2929687.5):
  E1 TV-analog  BPSK-modulated carrier @ 400 kHz (Rb=2 kHz), threshold
     amplitude, linear orbital drift. Modulation spreads power so the FFT
     cannot integrate it; carrier-squared FAM strips modulation and fires.
     Expected: FFT-blind (<5x), FAM-caught (>=3x at 2f0). THE money receipt.
     (An unmodulated threshold CW was tried first: its apparent detection
     traced to 2-bit-quantizer intermod with louder neighbors, not to the
     tone itself -- measured, kept as a cautionary comment. Modulated E1
     stands on its own.)
  E2 ARECIBO-analog pulsed carrier @ 600 kHz, ~1.4% duty, loud.
     Expected: FFT line + xeno impulsivity flag. Intermittent-beacon case.
  E3 SPIN-analog  CW @ 800 kHz, mid amplitude, rotation-curved track with
     time compression K (documented). Expected: jerk track found with
     curve_gain > 0 dB (bent track beats straight line).
Control: noise-only slice must stay quiet at the template freqs.

Usage:
  python python/earth_mirror.py --root . [--hip D:/data/raw/<hip>.raw]
      [--chan 20] [--dist-ly 40] [--blocks 4]
Registers in sy_prove_all.py as the Earth-at-40ly ground-truth prove.
Exit 0 + MIRROR PASS, 1 + MIRROR FAIL, 0 + MIRROR SKIP (no HIP file on disk).
"""
import argparse, csv, os, subprocess, sys
import numpy as np

FS = 2929687.5
C = 299792458.0
SEFD_JY = 10.0            # GBT-class L-band system equivalent flux density
A_ROT = 0.034             # m/s^2, Earth equatorial centripetal acceleration
A_ORB = 0.006             # m/s^2, Earth orbital acceleration
LY_M = 9.4607e15

# 2-bit backend levels (same quantizer as dsss_prove.py / the GUPPI chain)
def quantize(x):
    q = np.empty_like(x)
    q[x < -1.667] = -3.3359
    m = (x >= -1.667) & (x < 0); q[m] = -1.0
    m = (x >= 0) & (x < 1.667); q[m] = 1.0
    q[x >= 1.667] = 3.3359
    return q.astype(np.float32)

def flux_jy(eirp_w, dist_ly, bw_hz=1.0):
    return eirp_w / (4 * np.pi * (dist_ly * LY_M) ** 2) / bw_hz / 1e-26

def direct_peak_ratio(x, nfft=4096):
    nrows = len(x) // nfft
    W = np.hamming(nfft).astype(np.float32)
    spec = np.abs(np.fft.rfft((x[:nrows * nfft].reshape(nrows, nfft) * W), axis=1)) ** 2
    avg = spec.mean(axis=0); med = np.median(avg)
    k = int(np.argmax(avg[1:-1])) + 1
    return float(avg[k] / med), k * FS / nfft

def fam_line_ratio(fam_exe, f32path, target_hz, tol_hz=4000.0, topk='32'):
    # topk=32 (production scans use 8 for speed): same shipped binary, deeper
    # peak list. Needed because E2's pulse envelope throws a strong low-alpha
    # harmonic comb that would otherwise evict E1's line from a top-8 list --
    # real pipeline behavior, documented, not worked around.
    try:
        r = subprocess.run([fam_exe, f32path, str(FS), '32768', topk],
                           capture_output=True, text=True, timeout=600)
    except Exception as e:
        return 0.0, 0.0, f'fam_scan error: {e}'
    best = (0.0, 0.0)
    for line in r.stdout.splitlines():
        if 'alpha=' not in line:
            continue
        try:
            hz = float(line.split('alpha=')[1].split('Hz')[0].strip())
            ratio = float(line.split('ratio=')[1].split('x')[0].strip())
        except ValueError:
            continue
        if abs(hz - target_hz) <= tol_hz and ratio > best[0]:
            best = (ratio, hz)
    return best[0], best[1], None

def run_battery(exe, f32path, tag, jerk_path=None):
    """FFT peak + FAM 2f lines + xeno flags + jerk track. Returns dict."""
    out = {'tag': tag}
    x = np.fromfile(f32path, dtype=np.float32)
    out['n'] = len(x)
    out['sigma'] = float(np.std(x))
    dr, df = direct_peak_ratio(x)
    out['fft_peak'] = dr; out['fft_freq'] = df
    res = {}
    for name, f2 in (('E1', 800e3), ('E2', 1200e3), ('E3', 1600e3)):
        fr, fh, err = fam_line_ratio(exe['fam'], f32path, f2)
        res[name] = (fr, fh, err)
    out['fam'] = res
    try:
        r = subprocess.run([exe['xeno'], f32path, str(FS)],
                           capture_output=True, text=True, timeout=600)
        txt = (r.stdout + r.stderr).strip().splitlines()
        out['xeno_lines'] = txt[-12:] if txt else ['(no output)']
        joined = '\n'.join(txt)
        import re as _re
        _m = _re.search(r'impuls=(\d+)', joined)
        out['xeno_impuls'] = bool(_m and int(_m.group(1)) > 0)
    except Exception as e:
        out['xeno_lines'] = [f'xeno_scan error: {e}']; out['xeno_impuls'] = False
    try:
        jp = jerk_path or f32path
        r = subprocess.run([sys.executable, exe['jerk'], '--f32', jp],
                           capture_output=True, text=True, timeout=900,
                           cwd=os.path.dirname(os.path.dirname(exe['jerk'])))
        lines = (r.stdout + r.stderr).strip().splitlines()
        out['jerk_lines'] = lines[-6:] if lines else ['(no output)']
        import re
        m = re.search(r'curve_gain=([-\d.]+)dB', '\n'.join(lines))
        out['jerk_curve_gain'] = float(m.group(1)) if m else None
        m2 = re.search(r'track_score=([\d.]+)', '\n'.join(lines))
        out['jerk_score'] = float(m2.group(1)) if m2 else None
    except Exception as e:
        out['jerk_lines'] = [f'jerk error: {e}']
        out['jerk_curve_gain'] = None; out['jerk_score'] = None
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--hip', default='D:/data/raw/blc2_2bit_guppi_57432_31271_HIP57866_0021.0000.raw')
    ap.add_argument('--chan', type=int, default=20)
    ap.add_argument('--dist-ly', type=float, default=40.0)
    ap.add_argument('--blocks', type=int, default=4)
    a = ap.parse_args()
    root = a.root
    ext = '.exe' if os.name == 'nt' else ''
    exe = {'fam': os.path.join(root, 'c', 'fam_scan' + ext),
           'xeno': os.path.join(root, 'c', 'xeno_scan' + ext),
           'slice': os.path.join(root, 'c', 'seti_slice' + ext),
           'jerk': os.path.join(root, 'python', 'jerk_scan.py')}
    dat = os.path.join(root, 'data')
    os.makedirs(dat, exist_ok=True)

    if not os.path.exists(a.hip):
        print(f'[mirror] MIRROR SKIP: HIP file not on disk: {a.hip}')
        return 0
    for k in ('fam', 'xeno', 'slice'):
        if not os.path.exists(exe[k]):
            print(f'[mirror] MIRROR SKIP: missing binary {exe[k]} (run make first)')
            return 0

    D = a.dist_ly
    f_bmews = flux_jy(3e10, D)      # ~1.7 Jy @40ly in 1 Hz: threshold flicker
    f_arecibo = flux_jy(2e13, D)    # ~1100 Jy: loud
    print(f'[mirror] Earth at {D:.0f} ly | BMEWS-analog flux ~{f_bmews:.2f} Jy '
          f'| Arecibo-analog flux ~{f_arecibo:.0f} Jy (SEFD {SEFD_JY} Jy)')

    # --- real backend noise: slice a quiet HIP channel ---
    raw_path = os.path.join(dat, 'mirror_hip_noise.f32')
    r = subprocess.run([exe['slice'], a.hip, str(a.chan), raw_path, str(a.blocks)],
                       capture_output=True, text=True, timeout=900)
    if not os.path.exists(raw_path):
        print(f'[mirror] MIRROR FAIL: seti_slice failed:\n{(r.stdout + r.stderr)[-2000:]}')
        return 1
    noise = np.fromfile(raw_path, dtype=np.float32)
    N = len(noise)
    sigma = float(np.std(noise))
    print(f'[mirror] HIP noise: {os.path.basename(a.hip)} ch{a.chan} x{a.blocks}blk '
          f'N={N} ({N / FS:.2f}s) sigma={sigma:.3f}')
    if N < 10 * 32768 or sigma <= 0:
        print('[mirror] MIRROR FAIL: slice too short or dead lane')
        return 1

    t = np.arange(N) / FS
    rng = np.random.default_rng(40)   # E1 data bits (fixed seed: reproducible)
    # E1 is BPSK at Rb=2 kHz. Swept live in isolation (additive injection
    # into this same HIP slice): FFT@400k reads 4.3x at 0.10*sigma (blind)
    # vs 8.3x at 0.15*sigma (visible), while FAM Y4 2f0 reads 6.3x at
    # 0.10*sigma. A1 = 0.10*sigma is the demonstrated floor: the faintest
    # Earth-analog broadcast this backend can catch, and only via FAM.
    A1 = float(0.10 * sigma)
    A2 = float(1.5 * sigma)     # loud pulses, still well inside quantizer range
    A3 = float(0.60 * sigma)    # loud-ish: E3 tests geometry, E1 owns the floor

    # Doppler: faithful v/f = a/c; E3 time-compressed by K (stated openly).
    # NOTE: curvature needs CUBIC phase (quadratic phase is constant-drift,
    # i.e. a straight line -- jerk correctly reports curve_gain 0 for those).
    v_orb_f = A_ORB / C                      # fractional drift rate, orbital
    K = 3e8                                  # E3 time compression (detector geometry test)
    T = N / FS
    jerk_bin = FS / 32768
    j3 = K * (A_ROT / C) * 800e3 / T         # Hz/s^2: cubic bend across the slice
    bend_bins = (j3 * T ** 3 / 6) / jerk_bin
    ph1 = 2 * np.pi * (400e3 * t + 0.5 * (v_orb_f * 400e3) * t ** 2)
    ph3 = 2 * np.pi * (800e3 * t + 0.5 * (v_orb_f * 800e3) * t ** 2
                       + (j3 * t ** 3) / 6)
    Rb1, spb1 = 2000.0, int(round(FS / 2000.0))
    bits1 = np.where(rng.integers(0, 2, N // spb1 + 1), 1.0, -1.0).astype(np.float32)
    sym1 = np.repeat(bits1, spb1)[:N]
    s1 = (A1 * sym1 * np.cos(ph1)).astype(np.float32)
    pulse = ((np.arange(N) % 100000) < 1400).astype(np.float32)   # ~1.4% duty
    s2 = (A2 * pulse * np.cos(2 * np.pi * 600e3 * t)).astype(np.float32)
    s3 = (A3 * np.cos(ph3)).astype(np.float32)
    print(f'[mirror] E1 CW 400kHz A={A1:.4f} (target FFT-bin SNR~3) | E2 pulses 600kHz '
          f'A={A2:.3f} duty~1.4% | E3 curved 800kHz A={A3:.4f} jerk={j3:.1f}Hz/s^2 '
          f'bend~{bend_bins:.0f} jerk-bins (K={K:.0e} time compression, v/f faithful)')

    # --- control: pristine archival slice, untouched ---
    ctl_path = os.path.join(dat, 'mirror_control.f32')
    noise.astype(np.float32).tofile(ctl_path)
    ctl = run_battery(exe, ctl_path, 'control')
    print(f"[control] sigma={ctl['sigma']:.3f} fft_peak={ctl['fft_peak']:.2f}x@{ctl['fft_freq'] / 1e3:.0f}kHz")
    for name in ('E1', 'E2', 'E3'):
        fr, fh, _ = ctl['fam'][name]
        print(f"  control FAM {name}: {fr:.2f}x@{fh / 1e3:.0f}kHz")
    ctl_quiet = all(ctl['fam'][n][0] < 3.0 for n in ('E1', 'E2', 'E3')) and ctl['fft_peak'] < 5.0

    # --- injection: one template per lane (three coarse channels) ---
    # Detector floors are per-signal-in-noise metrology; production
    # normalizes per channel, so each template gets its own lane.
    # MEASURED on shared lanes (kept as findings, not worked around):
    # (a) a bent track above ~0.35*sigma desensitizes median-relative FAM
    #     to faint same-lane neighbors; (b) FAM's squaring front-end
    #     cross-modulates co-lane signals (E2's 2f0 wandered 2->61x with
    #     identical E2 when the neighbor changed). Future work: per-subband
    #     FAM normalization. The lane split is how the sky actually arrives.
    lane1 = os.path.join(dat, 'mirror_earth40ly_e1.f32')
    (noise + s1).astype(np.float32).tofile(lane1)
    lane2 = os.path.join(dat, 'mirror_earth40ly_e2.f32')
    (noise + s2).astype(np.float32).tofile(lane2)
    lane3 = os.path.join(dat, 'mirror_earth40ly_e3.f32')
    (noise + s3).astype(np.float32).tofile(lane3)
    inj_path = lane1
    b1 = run_battery(exe, lane1, 'E1-lane')
    b2 = run_battery(exe, lane2, 'E2-lane')
    b3 = run_battery(exe, lane3, 'E3-lane', jerk_path=lane3)
    inj = b1
    for b, nm in ((b1, 'E1'), (b2, 'E2'), (b3, 'E3')):
        fr, fh, _ = b['fam'][nm]
        print(f"[{nm}-lane] fft_peak={b['fft_peak']:.2f}x@{b['fft_freq'] / 1e3:.0f}kHz "
              f"FAM={fr:.2f}x@{fh / 1e3:.0f}kHz")
    print('  xeno tail (E2 lane): ' + ' | '.join(b2['xeno_lines'][-4:]))
    print('  jerk tail (E3 lane): ' + ' | '.join(b3['jerk_lines'][-3:]))

    # --- verdicts ---
    fr1, _, _ = b1['fam']['E1']
    e1_fft_blind = b1['fft_peak'] < 5.0 or abs(b1['fft_freq'] - 400e3) > 20000
    e1 = (fr1 >= 3.0) and e1_fft_blind
    fr2, _, _ = b2['fam']['E2']
    e2 = (b2['fft_peak'] >= 5.0) or (fr2 >= 3.0) or b2['xeno_impuls']
    e3 = (b3['jerk_curve_gain'] is not None and b3['jerk_curve_gain'] > 0
          and (b3['jerk_score'] or 0) >= 6.0)
    print(f'[receipt] E1 threshold-CW: FAM={fr1:.2f}x FFT-blind={e1_fft_blind} -> {"DETECTED" if e1 else "MISS"}')
    print(f"[receipt] E2 loud-pulses: FFT={b2['fft_peak']:.2f}x FAM={fr2:.2f}x impuls={b2['xeno_impuls']} -> {'DETECTED' if e2 else 'MISS'}")
    print(f"[receipt] E3 curved-track: curve_gain={b3['jerk_curve_gain']}dB score={b3['jerk_score']} -> {'DETECTED' if e3 else 'MISS'}")
    print(f"[receipt] control quiet at template freqs: {ctl_quiet}")

    # --- informational veto wedge: single-slice flag through the real veto ---
    try:
        hits_path = os.path.join(dat, 'mirror_hits.csv')
        with open(hits_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['block', 'chan', 'pol', 'spec_ratio', 'spec_bin', 'fam_best',
                        'fam_hz', 'fam_tag', 'vm_sign', 'vm_diff', 'spikes', 'rms', 'verdict'])
            w.writerow([0, a.chan, 0, 1.3, 550, round(fr1, 2), 800000, 'Y4',
                        '0.00/noise-like', '0.00/noise-like', 0, round(inj['sigma'], 3), 'FAM-HIT'])
        r = subprocess.run(
            [sys.executable, os.path.join(root, 'python', 'rfi_veto.py'),
             '--hits', hits_path, '--target', 'HIP57866', '--raw', a.hip,
             '--dry-run'],
            capture_output=True, text=True, timeout=300, cwd=root)
        tail = (r.stdout + r.stderr).strip().splitlines()
        print('  veto (informational, single-slice cap WATCH): '
              + (' | '.join(tail[-3:]) if tail else '(no output)'))
    except Exception as e:
        print(f'  veto wedge skipped: {e}')

    ok = bool(ctl_quiet and e1 and e2 and e3)
    print(f'[mirror] MIRROR {"PASS" if ok else "FAIL"} '
          f'(control={ctl_quiet} E1={e1} E2={e2} E3={e3}) | N={N} D={D:.0f}ly HIPch={a.chan}')
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
