"""mvp_scan.py - SetiYeti full-file sweep (v2, robustness overhaul).

The engineer loop: slice -> data-quality gates -> FAM + direct spectrum ->
VM sandbox on flags only -> one CSV row per slice. Logs every slice; never
drops one silently. Resumable.

v2 changes (after the TRAPPIST data-quality campaign)
-----------------------------------------------------
* SPARKLE GATE. Node blc04 was found to emit uniform-random corrupted bytes
  ("sparkles") at time-variable rates (0% .. 0.17% of samples). They are
  isolated single samples with |x| >~ 6*rms and they manufacture spurious
  FAM / x^4 structure (fake "179 Hz lines", fs/4 ghosts). Every slice now
  records `spikes` (count of |x| > max(6*rms, 25)) and `rms`; slices above
  --sparkle-max are written as QUARANTINE:sparkle and never reach detectors.
* DARK-LANE GATE extended. v1 caught range>15 & distinct<64, but a fully dark
  8-bit lane (blc00 ch44: range 13, distinct 14) slipped through. New rule:
  distinct > 8 and range < 20 -> dark. (2-bit data has 4 distinct codes and
  is exempt by the distinct>8 condition.)
* LAYOUT probed once per file, then forced on every slice. v1 let every slice
  self-detect and the heuristic could flip between layouts, mixing two
  different reads inside one scan (which fabricates fs/4 lines).
* FS comes from the raw header (1/TBIN), not a hardcoded constant.
* Per-slice subprocess timeouts; one bad slice cannot kill a long run.
* Consecutive-empty-block early stop (bad --b1 / past EOF).
* Schema check on resume: refuses to append v2 rows to a v1 CSV.
* --chans accepts ranges ("0-63"); --workers N parallel slicing;
  progress + ETA; end-of-run disposition summary.

Usage:
  python mvp_scan.py --raw data/<file>.raw --b0 0 --b1 127 --chans 0-63 \
      --pol 0 --out runs/baseline.csv --workers 2
"""
import argparse, csv, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC  # noqa: E402  (header reading, run manifests)

DEFAULT_FS = SC.DEFAULT_FS          # fallback only; header TBIN wins
SCHEMA = ['block', 'chan', 'pol', 'spec_ratio', 'spec_bin', 'fam_best',
          'fam_hz', 'fam_tag', 'vm_sign', 'vm_diff', 'spikes', 'rms',
          'verdict']
SCHEMA_V1 = SCHEMA[:-3] + ['verdict']   # block..vm_diff, verdict


# --------------------------------------------------------------------- util --
class Proc:
    __slots__ = ('returncode', 'stdout', 'stderr')

    def __init__(self, rc, out, err):
        self.returncode, self.stdout, self.stderr = rc, out, err


def run(exe, *args, timeout=300):
    """Run a subprocess; never raise, never hang a long scan."""
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True,
                           timeout=timeout)
        return Proc(r.returncode, r.stdout, r.stderr)
    except subprocess.TimeoutExpired:
        return Proc(124, '', f'timeout after {timeout}s')
    except OSError as e:
        return Proc(127, '', f'spawn failed: {e}')


def parse_chans(s):
    """'0,8,16' or '0-63' or mixed -> sorted unique list."""
    out = []
    for tok in s.split(','):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r'^(\d+)\s*-\s*(\d+)$', tok)
        if m:
            out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        else:
            out.append(int(tok))
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def fs_from_header(raw):
    """Frame rate from TBIN card: fs = 1/TBIN (2.9296875e6 for GUPPI)."""
    return SC.fs_from_header(raw)


def probe_layout(sl, raw, chan, b0, pol, work, tag, timeout):
    """One throwaway slice to read the file's memory layout. Returns 0/1/2/None."""
    tmp = os.path.join(work, f'{tag}_layoutprobe.f32')
    r = run(sl, raw, str(chan), tmp, '1', '--pol', str(pol),
            '--start', str(b0), timeout=timeout)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if r.returncode != 0:
        return None
    if 'pol-interleaved' in r.stderr:
        return 2
    if 'pol-blocked' in r.stderr:
        return 1
    if 'time-major' in r.stderr:
        return 0
    return None


# ---------------------------------------------------------------- detectors --
def direct_peak(x, nfft=4096):
    nrows = len(x) // nfft
    if nrows < 4:
        return 0.0, -1
    W = np.hamming(nfft).astype(np.float32)
    spec = np.abs(np.fft.rfft(x[:nrows * nfft].reshape(nrows, nfft) * W,
                              axis=1)) ** 2
    avg = spec.mean(axis=0)
    med = np.median(avg)
    if med <= 0:
        return 0.0, -1
    k = int(np.argmax(avg[1:-1])) + 1
    return float(avg[k] / med), k


def parse_fam(out):
    peaks = []
    for line in out.splitlines():
        m = re.search(r'^(Y2|Y4) peak\s+\d+\s+bin=\d+\s+alpha=\s*([\d.]+) Hz'
                      r'\s+ratio=\s*([\d.]+)x', line)
        if m:
            peaks.append((m.group(1), float(m.group(2)), float(m.group(3))))
    return peaks


def pack_bits(bits):
    # MSB-first packing == numpy packbits bitorder='big' (byte j holds
    # stream bits 8j..8j+7 MSB first, zero-padded tail). Vectorized: the old
    # Python loop cost ~0.5 s per flagged slice (~30 min per long-haul).
    return np.packbits(np.asarray(bits, dtype=np.uint8), bitorder='big')


def vm_score(vm_exe, f32path, workdir, timeout):
    """Run vm_sandbox on sign/diff bitstreams of a slice. Detectors only."""
    x = np.fromfile(f32path, dtype=np.float32)
    N = min(len(x), 200000)
    seg = x[:N]
    s = np.sign(seg)
    s[s == 0] = 1
    diff = np.concatenate([[1], s[1:] * s[:-1]]) < 0
    res = {}
    for name, bits in [('sign', (seg > 0).astype(np.uint8)),
                       ('diff', diff.astype(np.uint8))]:
        p = os.path.join(workdir,
                         f'vm_{os.path.basename(f32path)}.{name}.bin')
        try:
            pack_bits(bits).tofile(p)
            r = run(vm_exe, p, timeout=timeout)
            m = re.search(r'combined=([\d.]+)\s+(\S+)', r.stdout)
            res[name] = (float(m.group(1)) if m else 0.0,
                         m.group(2) if m else '?', r.stdout)
        finally:
            try:
                os.remove(p)
            except OSError:
                pass
    return res


# ------------------------------------------------------------------ one slice --
def process_slice(b, ch, ctx):
    """Full per-slice pipeline. Always returns a CSV row (never raises out)."""
    tag, sl, fam, vm = ctx['tag'], ctx['sl'], ctx['fam'], ctx['vm']
    work, pol = ctx['work'], ctx['pol']
    tmp = os.path.join(work, f'{tag}_b{b}_ch{ch}.f32')

    def row(spec_r='0', spec_b='-1', fam_b='0', fam_hz='0', fam_t='-',
            vs='', vd='', spikes='0', rms='0', verdict='clean'):
        return [b, ch, pol, spec_r, spec_b, fam_b, fam_hz, fam_t,
                vs, vd, spikes, rms, verdict]

    try:
        args = [sl, ctx['raw'], str(ch), tmp, '1', '--pol', str(pol),
                '--start', str(b)]
        if ctx['layout'] is not None:
            args += ['--layout', str(ctx['layout'])]
        r = run(*args, timeout=ctx['timeout'])
        if r.returncode != 0 or not os.path.exists(tmp) \
                or os.path.getsize(tmp) < 1000000:
            return None                      # no data at this block
        x = np.fromfile(tmp, dtype=np.float32)
        if len(x) < 100000:
            return None

        # ---- data-quality gates -------------------------------------------
        v = x[:100000]
        vrange = float(v.max() - v.min())
        distinct = int(len(np.unique(v)))
        rms = float(x.std())
        thr = max(6.0 * rms, 25.0)
        spikes = int(np.count_nonzero(np.abs(x) > thr))

        if vrange > 15 and distinct < 64:
            return row(spikes=str(spikes), rms=f'{rms:.3f}',
                       verdict=f'QUARANTINE:dark-lane range={vrange:.0f} '
                               f'distinct={distinct}')
        if distinct > 8 and vrange < 20:
            return row(spikes=str(spikes), rms=f'{rms:.3f}',
                       verdict=f'QUARANTINE:dark-lane(weak) range={vrange:.0f} '
                               f'distinct={distinct}')
        if spikes > ctx['sparkle_max']:
            return row(spikes=str(spikes), rms=f'{rms:.3f}',
                       verdict=f'QUARANTINE:sparkle n={spikes}')

        # ---- detectors -----------------------------------------------------
        sr, sb = direct_peak(x)
        fr = run(fam, tmp, f"{ctx['fs']:.1f}", '32768', '6',
                 ctx.get('cand_path', '-'), timeout=ctx['timeout'])
        peaks = parse_fam(fr.stdout)
        fb = max([p[2] for p in peaks], default=0.0)
        frow = next((p for p in peaks if p[2] == fb), ('-', 0.0, 0.0))
        flag = (sr >= ctx['spec_hump']) or (fb >= ctx['fam_trig'])
        vs = vd = ''
        verdict = 'clean'
        if sr >= ctx['spec_line']:
            verdict = 'SPECTRAL-LINE'
        elif fb >= ctx['fam_trig']:
            verdict = 'FAM-HIT'
        elif sr >= ctx['spec_hump']:
            verdict = 'hump-note'
        if flag:
            res = vm_score(vm, tmp, work, ctx['timeout'])
            vs = f"{res['sign'][0]:.2f}/{res['sign'][1]}"
            vd = f"{res['diff'][0]:.2f}/{res['diff'][1]}"
            if 'CANDIDATE' in (res['sign'][1] + res['diff'][1]):
                verdict += '+VM-WATCH'
        return row(f'{sr:.2f}', sb, f'{fb:.2f}', f'{frow[1]:.0f}', frow[0],
                   vs, vd, str(spikes), f'{rms:.3f}', verdict)
    except Exception as e:                    # noqa: BLE001 - long-run safety
        return row(verdict=f'ERROR:{type(e).__name__}')
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True)
    ap.add_argument('--b0', type=int, default=0)
    ap.add_argument('--b1', type=int, default=48)
    ap.add_argument('--chans', default='0,8,16,24,32,40,48,56')
    ap.add_argument('--pol', type=int, default=0)
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--out', default='hits.csv')
    ap.add_argument('--workers', type=int, default=1,
                    help='parallel slices (default 1; disk-bound task)')
    ap.add_argument('--layout', default='auto',
                    help='auto | 0 (time-major) | 1 (pol-blocked) | 2 (interleaved)')
    ap.add_argument('--fs', type=float, default=None,
                    help='sample rate Hz; default: from header TBIN')
    ap.add_argument('--fam-trig', type=float, default=3.0)
    ap.add_argument('--spec-line', type=float, default=5.0)
    ap.add_argument('--spec-hump', type=float, default=2.5)
    ap.add_argument('--sparkle-max', type=int, default=25,
                    help='|x|>6*rms count above which a slice is quarantined '
                         '(clean slices measure 0-1; band-edge chans 10-50; '
                         'corruption bursts 50-700)')
    ap.add_argument('--timeout', type=float, default=300.0,
                    help='per-subprocess timeout, seconds')
    a = ap.parse_args()

    if a.pol < 0 or a.pol > 3:
        sys.exit('pol must be 0-3')
    ext = '.exe' if os.name == 'nt' else ''
    sl = os.path.join(a.root, 'c', 'seti_slice' + ext)
    fam = os.path.join(a.root, 'c', 'fam_scan' + ext)
    vm = os.path.join(a.root, 'c', 'vm_sandbox' + ext)
    for exe in (sl, fam, vm):
        if not os.path.exists(exe):
            sys.exit(f'missing {exe} - build the C tools first')

    chans = parse_chans(a.chans)
    if not chans or any(c < 0 or c > 63 for c in chans):
        sys.exit('bad --chans (0-63)')

    # SETIYETI_TMP lets the campaign put scratch .f32 slices on the big
    # drive (D:) instead of filling the repo drive; fallback is historical.
    work = os.environ.get('SETIYETI_TMP') or os.path.join(a.root, 'data', 'mvp_tmp')
    os.makedirs(work, exist_ok=True)
    csvp = os.path.join(a.root, a.out)
    os.makedirs(os.path.dirname(csvp) or '.', exist_ok=True)

    # fs: CLI > header > default
    fsrc = 'cli'
    fs = a.fs
    if fs is None:
        fs = fs_from_header(a.raw)
        fsrc = 'header TBIN'
        if fs is None:
            fs = DEFAULT_FS
            fsrc = 'default'
    print(f'[mvp] fs={fs:.1f} Hz ({fsrc}), pol={a.pol}, '
          f'{len(chans)} channels, blocks {a.b0}-{a.b1}', flush=True)

    # resume + schema guard
    new = not os.path.exists(csvp)
    seen = set()
    if not new:
        with open(csvp, newline='') as f:
            hdr = f.readline().strip()
            if hdr != ','.join(SCHEMA):
                if hdr == ','.join(SCHEMA_V1):
                    sys.exit(f'{csvp} is a v1 CSV; use a new --out path '
                             f'(schemas must not be mixed)')
                sys.exit(f'{csvp} has an unknown header; use a new --out')
        with open(csvp) as f:
            for r in csv.DictReader(f):
                seen.add((str(r['block']), str(r['chan']), str(r.get('pol', '0'))))
    cf = open(csvp, 'a', newline='')
    cw = csv.writer(cf)
    if new:
        cw.writerow(SCHEMA)
    cf.flush()

    # temp prefix must be unique per (raw file, pol): two concurrent jobs
    # scanning the same file for different polarizations must not collide on
    # data/mvp_tmp/<tag>_b<B>_ch<C>.f32 (v2.0 shipped without the pol suffix,
    # which cost 24 FileNotFoundError/PermissionError rows in the first
    # 4-way baseline run - they are recorded in the v1 CSVs as ERROR rows).
    tag = re.sub(r'[^A-Za-z0-9]+', '_', os.path.basename(a.raw))[:40] \
        + f'_p{a.pol}'

    # layout: probe once, then every slice is forced to the same read
    layout = None
    if a.layout != 'auto':
        layout = int(a.layout)
        print(f'[mvp] layout forced: {layout}', flush=True)
    else:
        layout = probe_layout(sl, a.raw, chans[0], a.b0, a.pol, work, tag,
                              a.timeout)
        print(f'[mvp] layout probe: '
              f'{ {2: "interleaved", 1: "pol-blocked", 0: "time-major", None: "unknown (auto per slice)"}[layout] }',
              flush=True)

    ctx = dict(tag=tag, sl=sl, fam=fam, vm=vm, work=work, raw=a.raw,
               pol=a.pol, fs=fs, layout=layout, timeout=a.timeout,
               fam_trig=a.fam_trig, spec_line=a.spec_line,
               spec_hump=a.spec_hump, sparkle_max=a.sparkle_max,
               cand_path='-')  # fam_scan sidecar off: it rewrote one CWD
                               # file 65k times (racy under --workers)

    total = (a.b1 - a.b0 + 1) * len(chans)
    done = hits = quar = errs = dropped = 0
    t0 = time.time()
    consec_empty = 0
    workers = max(1, a.workers)

    for b in range(a.b0, a.b1 + 1):
        todo = [ch for ch in chans
                if (str(b), str(ch), str(a.pol)) not in seen]
        if not todo:
            done += len(chans)
            print(f'[mvp] block {b}: already complete '
                  f'({done}/{total})', flush=True)
            continue
        rows = {}
        if workers == 1:
            for ch in todo:
                rows[ch] = process_slice(b, ch, ctx)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(process_slice, b, ch, ctx): ch
                        for ch in todo}
                for fu in as_completed(futs):
                    ch = futs[fu]
                    try:
                        rows[ch] = fu.result()
                    except Exception as e:            # noqa: BLE001
                        rows[ch] = [b, ch, a.pol, '0', '-1', '0', '0', '-',
                                    '', '', '0', '0', f'ERROR:{e}']
        ok = 0
        for ch in sorted(rows):
            r = rows[ch]
            if r is None:
                # short/empty read: COUNT it. A silent `continue` here hid
                # truncated blocks as clean coverage for months.
                dropped += 1
                continue
            ok += 1
            cw.writerow(r)
            done += 1
            v = str(r[-1])
            if v.startswith('QUARANTINE'):
                quar += 1
            elif v.startswith('ERROR'):
                errs += 1
            elif v != 'clean':
                hits += 1
        cf.flush()
        consec_empty = consec_empty + 1 if ok == 0 else 0
        el = time.time() - t0
        rate = done / el if el > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(f'[mvp] block {b}: done {done}/{total} ok={ok} hits={hits} '
              f'quar={quar} err={errs} drop={dropped} {rate:.1f} sl/s ETA {eta/60:.1f} min',
              flush=True)
        if consec_empty >= 3:
            print('[mvp] 3 empty blocks in a row - stopping (past EOF?)',
                  flush=True)
            break
    cf.close()

    el = time.time() - t0
    print(f'[mvp] DONE blocks {a.b0}-{a.b1} chans={len(chans)} pol={a.pol}: '
          f'{done} slices ({hits} flagged, {quar} quarantined, {errs} errors, '
          f'{dropped} dropped) '
          f'in {el/60:.1f} min -> {csvp}', flush=True)
    SC.write_manifest(csvp, {
        'tool': 'mvp_scan.py', 'raw': os.path.basename(a.raw),
        'blocks': [a.b0, a.b1], 'chans': a.chans, 'pol': a.pol,
        'fs_hz': fs, 'fs_src': fsrc, 'layout': layout,
        'fam_trig': a.fam_trig, 'spec_line': a.spec_line,
        'spec_hump': a.spec_hump, 'sparkle_max': a.sparkle_max,
        'slices': done, 'flagged': hits, 'quarantined': quar,
        'errors': errs, 'dropped': dropped, 'schema': SCHEMA})


if __name__ == '__main__':
    main()
