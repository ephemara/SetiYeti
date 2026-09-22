#!/usr/bin/env python
"""longhaul.py - unattended deep-analysis chain for a GUPPI raw ON/OFF pair.

Purpose: run for hours without supervision, cover the whole detector set, and
leave a machine-readable record plus a human report. Designed after the
TRAPPIST shakedown, where block-by-block scanning turned out to be only half
the available depth: the time-axis detector (jerk_scan) and the full (alpha,f)
SCD + dechirp bank (scd_frf) were never pointed at real data.

Phases (each failure-isolated, resumable by output presence):
  1 preflight : layout/geometry probe + 1-block smoke scan on both files
  2 scans     : mvp_scan v2, all channels x all blocks x pols, 4-wide pool
  3 evidence  : build_evidence (persistence + multichan - the veto used to
                run without this and graded every flag transient/single)
  4 frames    : frame_hunt M2 on hot channels -> frame_results.json
  5 structure : structure_pass (comb + nongauss - the veto's STRUCTURE axis
                scored 0.00 on 2,700 flags before this existed)
  6 veto      : rfi_veto ON/OFF cadence on STRUCT csvs + evidence
  7 pca       : latent_pca corpus triage per scan CSV
  8 jerk      : per-channel 128-block time series -> Viterbi TBD (jerk_scan)
  9 scd       : scd_frf full SCD plane + dechirp bank on top candidates
  10 report   : REPORT.md + status.txt

Usage:
  python longhaul.py --on <raw> --off <raw> --target KEPLER160 \
      --outdir runs/longhaul_kepler [--pols 0,1,2,3] [--jerk-pols 0,1]
"""
import argparse, csv, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC  # noqa: E402  (header geometry, manifests)

PY = sys.executable


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


class Chain:
    def __init__(self, a):
        self.a = a
        self.root = a.root
        self.out = os.path.join(self.root, a.outdir)
        os.makedirs(self.out, exist_ok=True)
        # Campaign runs keep scratch on the big drive (SETIYETI_TMP);
        # fallback preserves the historical repo-local path.
        self.tmp = os.environ.get('SETIYETI_TMP') or os.path.join(self.root, 'data', 'longhaul_tmp')
        os.makedirs(self.tmp, exist_ok=True)
        self.lf = open(os.path.join(self.out, 'master.log'), 'a')
        self.status_p = os.path.join(self.out, 'status.txt')
        self.started = time.time()
        self.fs = SC.DEFAULT_FS
        self.freq = self.bw = None
        self.block_samples = None

    def log(self, msg):
        line = f'[{now()}] {msg}'
        print(line, flush=True)
        self.lf.write(line + '\n')
        self.lf.flush()

    def status(self, msg):
        with open(self.status_p, 'w') as f:
            f.write(f'updated: {now()}\nelapsed_min: '
                    f'{(time.time()-self.started)/60:.1f}\nstate: {msg}\n')

    def run(self, cmd, logpath, timeout=None):
        self.log('run: ' + ' '.join(os.path.basename(c) for c in cmd))
        with open(logpath, 'w') as lf:
            try:
                r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                   timeout=timeout, cwd=self.root)
                return r.returncode
            except subprocess.TimeoutExpired:
                lf.write(f'\n[TIMEOUT after {timeout}s]\n')
                return 124

    # ---------------------------------------------------------------- paths --
    def raw(self, tag):
        return os.path.join(self.root, self.a.on if tag == 'on' else self.a.off)

    def scan_csv(self, tag, pol):
        return os.path.join(self.out, f'scan_{tag}_p{pol}.csv')

    def hits_csv(self, tag, pol):
        """STRUCT-augmented hits when the structure phase ran, else raw scan."""
        s = os.path.join(self.out, f'struct_{tag}_p{pol}.csv')
        return s if os.path.exists(s) else self.scan_csv(tag, pol)

    def chan_freq_mhz(self, ch, nchan=64):
        if self.freq is None or self.bw is None:
            return 1407.7
        return self.freq + (ch - (nchan - 1) / 2.0) * (self.bw / nchan)

    def scan_log(self, tag, pol):
        return os.path.join(self.out, f'scan_{tag}_p{pol}.log')

    # ------------------------------------------------------------ phase 1 --
    def preflight(self):
        self.status('phase1: preflight')
        self.log('=== PHASE 1: preflight ===')
        self.layouts = {}
        for tag in ('on', 'off'):
            raw = self.raw(tag)
            out = os.path.join(self.tmp, f'pf_{tag}.f32')
            logp = os.path.join(self.out, f'preflight_{tag}.log')
            self.run([os.path.join(self.root, 'c', 'seti_slice.exe' if os.name == 'nt' else 'seti_slice'),
                      raw, '32', out, '1', '--pol', '0'], logp, timeout=1800)
            txt = open(logp).read()
            m = re.search(r'\(layout: ([^)]+)\)', txt)
            self.layouts[tag] = m.group(1) if m else 'unknown'
            self.log(f'{tag}: layout = {self.layouts[tag]}')
            try:
                os.remove(out)
            except OSError:
                pass
            # smoke scan: 1 block x 8 channels through the full gate stack
            smoke = os.path.join(self.out, f'smoke_{tag}.csv')
            self.run([PY, os.path.join('python', 'mvp_scan.py'), '--raw', raw,
                      '--b0', '0', '--b1', '0', '--chans', '0-63', '--pol', '0',
                      '--out', smoke], os.path.join(self.out, f'smoke_{tag}.log'),
                     timeout=1800)
            rows = list(csv.DictReader(open(smoke))) if os.path.exists(smoke) else []
            quar = sum(1 for r in rows if 'QUARANTINE' in r['verdict'])
            self.log(f'{tag}: smoke rows={len(rows)} quarantined={quar}')
        # header geometry once: drives jerk/scd sample rates, frame block
        # length, and per-channel sky frequencies (no more hardcoded FS).
        try:
            self.fs = SC.fs_from_header(self.raw('on')) or SC.DEFAULT_FS
            g = SC.geometry_from_header(self.raw('on'))
            self.freq, self.bw, _, _, _, _, self.block_samples = g[:7]
        except Exception as e:                      # noqa: BLE001
            self.log(f'geometry probe failed ({e}); using defaults')
        self.log(f'geometry: fs={self.fs:.1f} freq={self.freq} bw={self.bw} '
                 f'block_samples={self.block_samples}')

    # ------------------------------------------------------------ phase 2 --
    def scans(self):
        self.status('phase2: full scans')
        self.log('=== PHASE 2: full scans (all chans x all blocks x pols) ===')
        pols = [int(p) for p in self.a.pols.split(',') if p != '']
        jobs = [(tag, p) for tag in ('on', 'off') for p in pols]
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {}
            for tag, p in jobs:
                logp = self.scan_log(tag, p)
                done = os.path.exists(logp) and '[mvp] DONE' in open(logp).read()
                if done:
                    self.log(f'scan {tag} p{p}: already done, skip')
                    continue
                futs[ex.submit(
                    self.run,
                    [PY, os.path.join('python', 'mvp_scan.py'),
                     '--raw', self.raw(tag), '--b0', '0', '--b1', '127',
                     '--chans', '0-63', '--pol', str(p),
                     '--out', self.scan_csv(tag, p), '--workers', '1'],
                    logp, 14400)] = (tag, p)
            for fu in as_completed(futs):
                tag, p = futs[fu]
                rc = fu.result()
                self.log(f'scan {tag} p{p}: rc={rc}')
        self.status('phase2: done')

    # ------------------------------------------------------------ phase 3 --
    def evidence(self):
        self.status('phase3: build_evidence')
        self.log('=== PHASE 3: evidence (persistence + multichan) ===')
        evp = os.path.join(self.out, 'evidence.csv')
        if os.path.exists(evp) and os.path.getsize(evp) > 100:
            self.log('evidence exists, skip')
            return
        scans = []
        for tag in ('on', 'off'):
            for p in range(4):
                c = self.scan_csv(tag, p)
                if os.path.exists(c):
                    scans.append(c)
        if not scans:
            self.log('evidence: no scans yet, skip')
            return
        cmd = [PY, os.path.join('python', 'build_evidence.py')]
        for s in scans:
            cmd += ['--scan', s]
        cmd += ['--target', self.a.target, '--out', evp]
        self.run(cmd, os.path.join(self.out, 'evidence.log'), 3600)
        self.status('phase3: done')

    # ------------------------------------------------------------ phase 4 --
    def frames(self):
        self.status('phase4: frame_hunt')
        self.log('=== PHASE 4: frame-period hunt on hot channels (M2) ===')
        frp = os.path.join(self.out, 'frame_results.json')
        if os.path.exists(frp) and os.path.getsize(frp) > 10:
            self.log('frames exist, skip')
            return
        import collections
        counts = collections.Counter()
        for tag in ('on', 'off'):
            for p in (0, 1):
                c = self.scan_csv(tag, p)
                if not os.path.exists(c):
                    continue
                for r in csv.DictReader(open(c)):
                    if str(r.get('verdict', '')).startswith(
                            ('FAM-HIT', 'SPECTRAL-LINE')):
                        counts[(tag, int(r['chan']))] += 1
        top = [(t, ch) for (t, ch), n in counts.most_common(6) if n >= 2][:6]
        self.log(f'frame channels: {top or "none (no repeat flags)"}')
        import json
        chans = []
        for tag, ch in top:
            logp = os.path.join(self.out, f'frame_{tag}_ch{ch}.log')
            cmd = [PY, os.path.join('python', 'frame_hunt.py'),
                   '--raw', self.raw(tag), '--chan', str(ch), '--pol', '0',
                   '--blocks', '1000000', '--json']
            if self.block_samples:
                cmd += ['--block-samples', str(self.block_samples)]
            self.run(cmd, logp, 3600)
            try:
                res = json.loads(open(logp).read().strip().splitlines()[-1])
            except (OSError, ValueError, IndexError):
                continue
            res['chan'] = ch
            res['tag'] = tag
            chans.append(res)
            self.log(f"frame {tag} ch{ch}: {'FRAME' if res.get('frame_detected') else 'no frame'} "
                     f"sigma={res.get('sigma', 0):.1f}")
        with open(frp, 'w') as f:
            json.dump({'channels': chans}, f, indent=1)
        self.status('phase4: done')

    # ------------------------------------------------------------ phase 5 --
    def structure(self):
        self.status('phase5: structure_pass')
        self.log('=== PHASE 5: comb + nongauss STRUCTURE pass ===')
        frp = os.path.join(self.out, 'frame_results.json')
        for tag in ('on', 'off'):
            for p in range(4):
                c = self.scan_csv(tag, p)
                if not os.path.exists(c):
                    continue
                o = os.path.join(self.out, f'struct_{tag}_p{p}.csv')
                if os.path.exists(o) and os.path.getsize(o) > 100:
                    self.log(f'structure {tag} p{p}: exists, skip')
                    continue
                cmd = [PY, os.path.join('python', 'structure_pass.py'),
                       '--scan', c, '--raw', self.raw(tag), '--out', o,
                       '--frames', frp, '--min-fam', '4.0', '--topk', '400']
                self.run(cmd, os.path.join(self.out, f'structure_{tag}_p{p}.log'),
                         7200)
        self.status('phase5: done')

    # ------------------------------------------------------------ phase 6 --
    def veto(self):
        self.status('phase6: rfi_veto')
        self.log('=== PHASE 6: veto (ON/OFF cadence on STRUCT + evidence) ===')
        evp = os.path.join(self.out, 'evidence.csv')
        for p in range(4):
            if not os.path.exists(self.scan_csv('on', p)):
                continue
            logp = os.path.join(self.out, f'veto_p{p}.log')
            if os.path.exists(logp) and os.path.getsize(logp) > 200:
                self.log(f'veto p{p}: exists, skip')
                continue
            cmd = [PY, os.path.join('python', 'rfi_veto.py'),
                   '--hits', self.hits_csv('on', p),
                   '--raw', self.raw('on'),
                   '--on', self.hits_csv('on', p),
                   '--off', self.hits_csv('off', p),
                   '--target', self.a.target, '--quiet']
            if os.path.exists(evp):
                cmd += ['--evidence', evp]
            self.run(cmd, logp, 3600)
            tail = open(logp).read().strip().splitlines()
            self.log(f'veto p{p}: ' + (tail[-1] if tail else 'no output'))
        self.status('phase6: done')

    # ------------------------------------------------------------ phase 4 --
    def pca(self):
        self.status('phase7: latent_pca')
        self.log('=== PHASE 4: latent PCA triage ===')
        for tag in ('on', 'off'):
            for p in (0, 1):
                c = self.hits_csv(tag, p)
                if not os.path.exists(c):
                    continue
                logp = os.path.join(self.out, f'pca_{tag}_p{p}.log')
                if os.path.exists(logp) and os.path.getsize(logp) > 100:
                    continue
                self.run([PY, os.path.join('python', 'latent_pca.py'),
                          '--slices', c], logp, 3600)
                self.log(f'pca {tag} p{p}: done')
        self.status('phase7: done')

    # ------------------------------------------------------------ phase 8 --
    def jerk(self):
        self.status('phase8: jerk/Viterbi deep pass')
        self.log('=== PHASE 8: per-channel time-series Viterbi (jerk_scan) ===')
        # prove threshold once, reuse everywhere: the old code never passed
        # --thresh, so every track graded 'scored' against nothing.
        threshp = os.path.join(self.out, 'jerk_thresh.txt')
        if not (os.path.exists(threshp) and os.path.getsize(threshp) > 0):
            self.run([PY, os.path.join('python', 'jerk_scan.py'), '--prove',
                      '--fs', f'{self.fs:.1f}',
                      '--save-thresh', threshp],
                     os.path.join(self.out, 'jerk_prove.log'), 3600)
        res = os.path.join(self.out, 'jerk_results.csv')
        seen = set()
        if os.path.exists(res):
            for r in csv.DictReader(open(res)):
                seen.add((r['tag'], r['pol'], r['chan']))
        new = not os.path.exists(res)
        fh = open(res, 'a', newline='')
        w = csv.writer(fh)
        if new:
            w.writerow(['tag', 'pol', 'chan', 'rowmax_z', 'score', 'pf', 'v_hz_s',
                        'a_hz_s2', 'curve_gain_db', 'sidereal', 'seconds'])
        sl = os.path.join(self.root, 'c', 'seti_slice.exe' if os.name == 'nt' else 'seti_slice')
        jk = os.path.join('python', 'jerk_scan.py')
        tot = len([(t, p) for t in ('on', 'off')
                   for p in [int(x) for x in self.a.jerk_pols.split(',') if x != '']
                   for c in range(64)
                   if (t, str(p), str(c)) not in seen or True])
        n = 0
        for tag in ('on', 'off'):
            for p in [int(x) for x in self.a.jerk_pols.split(',') if x != '']:
                for ch in range(64):
                    if (tag, str(p), str(ch)) in seen:
                        n += 1
                        continue
                    f32 = os.path.join(self.tmp, f'{tag}_p{p}_ch{ch}.f32')
                    logp = os.path.join(self.out, f'jerk_{tag}_p{p}_ch{ch}.log')
                    rc = self.run([sl, self.raw(tag), str(ch), f32, '128',
                                   '--pol', str(p)], logp, 3600)
                    if rc != 0 or not os.path.exists(f32):
                        self.log(f'jerk {tag} p{p} ch{ch}: extract failed rc={rc}')
                        continue
                    jk_cmd = [PY, jk, '--f32', f32, '--fs', f'{self.fs:.1f}',
                              '--freq-mhz', f'{self.chan_freq_mhz(ch):.3f}']
                    if os.path.exists(threshp) and os.path.getsize(threshp) > 0:
                        jk_cmd += ['--load-thresh', threshp]
                    self.run(jk_cmd, logp, 3600)
                    txt = open(logp).read()
                    m = re.search(r'rowmax_z=([\d.]+)\s+track_score=([\d.]+)\s+'
                                  r'v=([+-]?[\d.]+)Hz/s\s+a=([+-]?[\d.]+)Hz/s\^2\s+'
                                  r'curve_gain=([-\d.]+)dB\s+sidereal=(\S+)', txt)
                    if m:
                        w.writerow([tag, p, ch, m.group(1), m.group(2), '',
                                    m.group(3), m.group(4), m.group(5),
                                    m.group(6), ''])
                        fh.flush()
                    try:
                        os.remove(f32)
                    except OSError:
                        pass
                    n += 1
                    if n % 16 == 0:
                        self.log(f'jerk progress {n}/{tot}')
        fh.close()
        self.status('phase8: done')

    # ------------------------------------------------------------ phase 9 --
    def scd(self):
        self.status('phase9: SCD + dechirp on candidates')
        self.log('=== PHASE 9: full (alpha,f) SCD + dechirp on top candidates ===')
        cands = []
        for tag in ('on', 'off'):
            for p in (0, 1):
                c = self.hits_csv(tag, p)
                if not os.path.exists(c):
                    continue
                rows = list(csv.DictReader(open(c)))
                # line-channels (standing tones like ch0) are SCD artifacts,
                # not baud candidates: exclude channels that read SPECTRAL
                # in over half the blocks. The old top-k drowned in them.
                spec_ct = {}
                for r in rows:
                    if str(r.get('verdict', '')).startswith('SPECTRAL'):
                        spec_ct[r['chan']] = spec_ct.get(r['chan'], 0) + 1
                nblocks = max((int(r['block']) for r in rows), default=0) + 1
                line_chans = {ch for ch, n in spec_ct.items()
                              if n > max(nblocks // 2, 4)}
                for r in rows:
                    v = r['verdict']
                    if r['chan'] in line_chans:
                        continue
                    if v.startswith('FAM-HIT') or v.startswith('SPECTRAL'):
                        try:
                            if int(r['spikes']) > 0:
                                continue
                            fam = float(r['fam_best'])
                            spec = float(r['spec_ratio'])
                        except (ValueError, KeyError):
                            continue
                        cands.append((max(fam, spec), tag, p, r['block'], r['chan'],
                                      r['fam_hz'], r['fam_tag']))
        cands.sort(reverse=True)
        cands = cands[:self.a.topk]
        self.log(f'candidates selected: {len(cands)}')
        res = os.path.join(self.out, 'scd_results.csv')
        new = not os.path.exists(res)
        fh = open(res, 'a', newline='')
        w = csv.writer(fh)
        if new:
            w.writerow(['tag', 'pol', 'block', 'chan', 'fam_hz', 'fam_tag',
                        'alpha_hz', 'f_hz', 'ratio', 'dechirp_x', 'dechirp_gamma'])
        sl = os.path.join(self.root, 'c', 'seti_slice.exe' if os.name == 'nt' else 'seti_slice')
        for (score, tag, p, b, ch, fhz, ftag) in cands:
            f32 = os.path.join(self.tmp, f'scd_{tag}_p{p}_b{b}_ch{ch}.f32')
            logp = os.path.join(self.out, f'scd_{tag}_p{p}_b{b}_ch{ch}.log')
            rc = self.run([sl, self.raw(tag), str(ch), f32, '1', '--pol', str(p),
                           '--start', str(b)], logp, 1800)
            if rc != 0 or not os.path.exists(f32):
                continue
            self.run([PY, os.path.join('python', 'scd_frf.py'), '--f32', f32,
                     '--fs', f'{self.fs:.1f}'],
                     logp, 7200)
            txt = open(logp).read()
            peaks = re.findall(r'alpha=\s*([\d.]+)Hz f=\s*([-\d.]+)Hz ratio=\s*([\d.]+)x', txt)
            d = re.search(r'\[dechirp\] best=([\d.]+)x @ gamma=([-\d.]+) Hz/s', txt)
            for (al, fr, ra) in peaks[:3]:
                w.writerow([tag, p, b, ch, fhz, ftag, al, fr, ra,
                            d.group(1) if d else '', d.group(2) if d else ''])
            fh.flush()
            try:
                os.remove(f32)
            except OSError:
                pass
        fh.close()
        self.status('phase9: done')

    # ------------------------------------------------------------ phase 10 --
    def report(self):
        self.status('phase10: report')
        lines = [f'# Long-haul report - {self.a.target}', '',
                 f'started: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started))}',
                 f'elapsed: {(time.time()-self.started)/60:.1f} min', '']
        for tag in ('on', 'off'):
            lines.append(f'## {tag.upper()}')
            for p in range(4):
                c = self.scan_csv(tag, p)
                if not os.path.exists(c):
                    continue
                rows = list(csv.DictReader(open(c)))
                import collections
                vc = collections.Counter()
                for r in rows:
                    v = r['verdict']
                    vc['QUARANTINE' if 'QUARANTINE' in v else
                       'ERROR' if v.startswith('ERROR') else v.split('+')[0]] += 1
                lines.append(f'- pol{p}: {len(rows)} slices; ' +
                             ', '.join(f'{k}={v}' for k, v in vc.most_common()))
            lines.append('')
        j = os.path.join(self.out, 'jerk_results.csv')
        if os.path.exists(j):
            rows = sorted(csv.DictReader(open(j)),
                          key=lambda r: -float(r['score'] or 0))
            lines.append('## Top Viterbi tracks (jerk_scan)')
            anom = [r for r in rows
                    if str(r.get('sidereal', '')).startswith('ANOMALOUS')]
            lines.append(f'- sidereal-anomalous drifts: {len(anom)} '
                         f'(Earth-bound transmitters stay within ~0.35 Hz/s)')
            for r in rows[:25]:
                lines.append(f"- {r['tag']} p{r['pol']} ch{r['chan']}: "
                             f"score={r['score']} rowmax_z={r['rowmax_z']} "
                             f"v={r['v_hz_s']}Hz/s a={r['a_hz_s2']}Hz/s^2 "
                             f"curve_gain={r['curve_gain_db']}dB "
                             f"sidereal={r.get('sidereal', '?')}")
            lines.append('')
        import json as _json
        evp = os.path.join(self.out, 'evidence.csv')
        if os.path.exists(evp):
            ev = list(csv.DictReader(open(evp)))
            lines.append(f"## Evidence: {len(ev)} rows "
                         f"(persist={sum(1 for r in ev if r.get('persist') == '1')}, "
                         f"multichan={sum(1 for r in ev if r.get('multichan') == '1')})")
            lines.append('')
        n_comb = n_ng = 0
        for tag in ('on', 'off'):
            for p in range(4):
                c = os.path.join(self.out, f'struct_{tag}_p{p}.csv')
                if not os.path.exists(c):
                    continue
                for r in csv.DictReader(open(c)):
                    if str(r.get('comb', '0')) == '1':
                        n_comb += 1
                    if str(r.get('nongauss', '0')) == '1':
                        n_ng += 1
        lines.append(f'## Structure: comb={n_comb} nongauss={n_ng} slices')
        frp = os.path.join(self.out, 'frame_results.json')
        if os.path.exists(frp):
            try:
                fr = _json.load(open(frp))
                det = [c for c in fr.get('channels', [])
                       if c.get('frame_detected')]
                lines.append(f"## Frames: {len(det)} channel(s) with frame periods: "
                             + (', '.join(
                                 f"{c.get('tag')} ch{c.get('chan')} "
                                 f"T={c.get('best_period_s', 0)*1e3:.2f}ms"
                                 for c in det) or 'none'))
            except (OSError, ValueError):
                lines.append('## Frames: results unreadable')
        lines.append('')
        s = os.path.join(self.out, 'scd_results.csv')
        if os.path.exists(s):
            rows = sorted(csv.DictReader(open(s)), key=lambda r: -float(r['ratio'] or 0))
            lines.append('## SCD/dechirp candidates')
            for r in rows[:25]:
                lines.append(f"- {r['tag']} p{r['pol']} b{r['block']}/ch{r['chan']} "
                             f"alpha={r['alpha_hz']}Hz f={r['f_hz']}Hz "
                             f"ratio={r['ratio']}x dechirp={r['dechirp_x']}x"
                             f"@{r['dechirp_gamma']}")
            lines.append('')
        open(os.path.join(self.out, 'REPORT.md'), 'w').write('\n'.join(lines))
        self.log('report written')
        self.status('done')

    def go(self):
        self.log('=========== LONGHAUL START ===========')
        for name, fn in [('preflight', self.preflight), ('scans', self.scans),
                         ('evidence', self.evidence), ('frames', self.frames),
                         ('structure', self.structure), ('veto', self.veto),
                         ('pca', self.pca), ('jerk', self.jerk),
                         ('scd', self.scd), ('report', self.report)]:
            try:
                fn()
            except Exception as e:                      # noqa: BLE001
                self.log(f'PHASE {name} FAILED: {type(e).__name__}: {e}')
        self.log('=========== LONGHAUL COMPLETE ===========')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--on', required=True)
    ap.add_argument('--off', required=True)
    ap.add_argument('--target', default='KEPLER160')
    ap.add_argument('--outdir', default='runs/longhaul_kepler')
    ap.add_argument('--pols', default='0,1,2,3')
    ap.add_argument('--jerk-pols', default='0,1')
    ap.add_argument('--topk', type=int, default=25)
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    Chain(a).go()


if __name__ == '__main__':
    main()
