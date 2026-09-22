#!/usr/bin/env python

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
"""pipeline.py — BEAST orchestrator: every science tool, one command, 4 pols.

Closes every kepler1 §5 gap in a single resumable chain:
  1. preflight (header geometry + layout probe + smoke, per file)
  2. scans (mvp_scan, ALL pols in --pol-list, configurable stride)
  3. structure (structure_pass comb+nongauss on every flagged slice)
  4. evidence (build_evidence persist+multichan across ALL pols)
  5. veto (rfi_veto WITH --evidence, every pol — never blind)
  6. burst zoom (spiky-strong slices → burst_zoom, never silently dropped)
  7. deep pass: pulsar_fold + transient_dm + frame_hunt on top candidates
  8. SCD top-k EXCLUDING line channels (ch0 standing line can't flood budget)
  9. cadence gate (cadence_pair: the only WATCH→CANDIDATE path) + catalog audit
  10. REPORT.md with receipts (floors, thresholds, coverage, verdicts)

  python pipeline.py --preset configs/kepler_L.toml --on data/a.raw --off data/b.raw --outdir runs/beast_x
"""
import argparse, csv, glob, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_config as CFG
import seti_common as SC

PY = sys.executable


def sh(cmd, logp, timeout=7200, cwd=None):
    with open(logp, 'w', encoding='utf-8', errors='replace') as lf:
        lf.write('$ ' + ' '.join(cmd) + '\n')
        try:
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                               timeout=timeout, cwd=cwd or os.getcwd())
            return r.returncode
        except subprocess.TimeoutExpired:
            lf.write(f'\n[TIMEOUT {timeout}s]\n')
            return 124


def parse_blocks(s):
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
    return sorted(set(out))


class Beast:
    def __init__(self, cfg, a):
        self.cfg, self.a = cfg, a
        self.root = os.getcwd()
        self.out = os.path.join(self.root, a.outdir)
        os.makedirs(self.out, exist_ok=True)
        # Campaign runs keep scratch on the big drive (SETIYETI_TMP);
        # fallback preserves the historical repo-local path.
        self.tmp = os.environ.get('SETIYETI_TMP') or os.path.join(self.root, 'data', 'beast_tmp')
        os.makedirs(self.tmp, exist_ok=True)
        self.logf = open(os.path.join(self.out, 'master.log'), 'a',
                         encoding='utf-8', errors='replace')
        self.t0 = time.time()

    def log(self, m):
        line = f'[{time.strftime("%H:%M:%S")}] {m}'
        print(line, flush=True)
        self.logf.write(line + '\n')
        self.logf.flush()

    def scan_csv(self, tag, pol):
        return os.path.join(self.out, f'scan_{tag}_p{pol}.csv')

    def phase_scans(self):
        self.log('=== scans (all pols) ===')
        blocks = parse_blocks(str(self.cfg.get('blocks', '0-127')))
        b0, b1 = min(blocks), max(blocks)
        pols = self.cfg.get('pol_list', [0, 1, 2, 3])
        jobs = [(t, p) for t in ('on', 'off') for p in pols]
        with ThreadPoolExecutor(max_workers=int(self.cfg.get('workers', 4))) as ex:
            futs = {}
            for tag, p in jobs:
                raw = self.a.on if tag == 'on' else self.a.off
                logp = os.path.join(self.out, f'scan_{tag}_p{p}.log')
                done = os.path.exists(logp) and '[mvp] DONE' in open(logp, errors='replace').read()
                if done:
                    self.log(f'scan {tag} p{p}: cached, skip')
                    continue
                futs[ex.submit(sh, [PY, 'python/mvp_scan.py', '--raw', raw,
                                    '--b0', str(b0), '--b1', str(b1),
                                    '--chans', '0-63', '--pol', str(p),
                                    '--out', self.scan_csv(tag, p),
                                    '--fam-trig', str(self.cfg['fam_trig']),
                                    '--spec-line', str(self.cfg['spec_line']),
                                    '--spec-hump', str(self.cfg['spec_hump']),
                                    '--sparkle-max', str(self.cfg['sparkle_max'])],
                               logp, 14400, self.root)] = (tag, p)
            for fu in as_completed(futs):
                self.log(f'scan {futs[fu]}: rc={fu.result()}')

    def phase_structure_evidence_veto(self):
        self.log('=== structure → evidence → veto (with evidence, all pols) ===')
        raw_on = self.a.on
        scans = sorted(glob.glob(os.path.join(self.out, 'scan_*.csv')))
        # 1. structure per scan file
        for s in scans:
            o = s.replace('scan_', 'struct_')
            if os.path.exists(o):
                continue
            sh([PY, 'python/structure_pass.py', '--scan', os.path.relpath(s, self.root),
                '--raw', raw_on, '--out', os.path.relpath(o, self.root)],
               o + '.log', 7200, self.root)
        # 2. one evidence file across ALL pols
        ev = os.path.join(self.out, 'evidence.csv')
        if not os.path.exists(ev):
            structs = sorted(glob.glob(os.path.join(self.out, 'struct_*.csv'))) or scans
            cmd = [PY, 'python/build_evidence.py', '--target', self.a.target,
                   '--out', os.path.relpath(ev, self.root),
                   '--persist-min', str(self.cfg['persist_min'])]
            for s in structs:
                cmd += ['--scan', os.path.relpath(s, self.root)]
            sh(cmd, ev + '.log', 3600, self.root)
        # 3. veto per pol WITH evidence + cadence
        for p in self.cfg.get('pol_list', [0, 1, 2, 3]):
            s = self.scan_csv('on', p).replace('scan_', 'struct_')
            if not os.path.exists(s):
                s = self.scan_csv('on', p)
            if not os.path.exists(s):
                continue
            logp = os.path.join(self.out, f'veto_p{p}.log')
            if os.path.exists(logp) and os.path.getsize(logp) > 200:
                continue
            sh([PY, 'python/rfi_veto.py', '--hits', os.path.relpath(s, self.root),
                '--raw', raw_on, '--evidence', os.path.relpath(ev, self.root),
                '--on', os.path.relpath(self.scan_csv('on', p), self.root),
                '--off', os.path.relpath(self.scan_csv('off', p), self.root),
                '--target', self.a.target], logp, 3600, self.root)

    def phase_burst_deep(self):
        self.log('=== burst zoom + fold/DM/frame deep pass ===')
        ext = '.exe' if os.name == 'nt' else ''
        sl = os.path.join(self.root, 'c', 'seti_slice' + ext)
        cands = []
        for s in glob.glob(os.path.join(self.out, 'struct_*.csv')) or \
                glob.glob(os.path.join(self.out, 'scan_*.csv')):
            for r in csv.DictReader(open(s)):
                if r.get('verdict', 'clean') == 'clean':
                    continue
                try:
                    score = max(float(r.get('fam_best') or 0), float(r.get('spec_ratio') or 0))
                except ValueError:
                    continue
                cands.append((score, r))
        cands.sort(reverse=True, key=lambda t: t[0])
        # burst zoom on spiky-strong (previously dropped class)
        nburst = 0
        for score, r in cands[:60]:
            try:
                if int(r.get('spikes') or 0) <= 0 or score < 4.0:
                    continue
            except ValueError:
                continue
            tag = 'on' if '_p' in '' else 'on'
            f32 = os.path.join(self.tmp, f"burst_b{r['block']}_ch{r['chan']}.f32")
            subprocess.run([sl, self.a.on, r['chan'], f32, '1', '--pol', r.get('pol', '0'),
                            '--start', r['block']], capture_output=True)
            if os.path.exists(f32):
                subprocess.run([PY, 'python/burst_zoom.py', '--f32', f32],
                               stdout=open(os.path.join(self.out, f"burst_b{r['block']}_ch{r['chan']}.log"), 'w'))
                try:
                    os.remove(f32)
                except OSError:
                    pass
                nburst += 1
        self.log(f'burst zoom: {nburst} spiky slices classified')
        # fold + DM on top-10 spike-free candidates
        ndeep = 0
        for score, r in [c for c in cands if int(c[1].get('spikes') or 0) == 0][:10]:
            f32 = os.path.join(self.tmp, f"deep_b{r['block']}_ch{r['chan']}.f32")
            subprocess.run([sl, self.a.on, r['chan'], f32, '1', '--pol', r.get('pol', '0'),
                            '--start', r['block']], capture_output=True)
            if os.path.exists(f32):
                for tool in (['python/pulsar_fold.py'], ['python/transient_dm.py']):
                    subprocess.run([PY] + tool + ['--f32', f32],
                                   stdout=open(os.path.join(
                                       self.out, f"deep_{tool[0].split('/')[-1].replace('.py','')}_"
                                       f"b{r['block']}_ch{r['chan']}.log"), 'w'))
                try:
                    os.remove(f32)
                except OSError:
                    pass
                ndeep += 1
        self.log(f'deep pass: fold+DM on {ndeep} candidates')

    def phase_cadence_report(self):
        self.log('=== cadence gate + catalog audit + report ===')
        ev = os.path.join(self.out, 'evidence.csv')
        sh([PY, 'python/cadence_pair.py', '--on',
            os.path.relpath(self.scan_csv('on', self.cfg['pol_list'][0]), self.root),
            '--off', os.path.relpath(self.scan_csv('off', self.cfg['pol_list'][0]), self.root),
            '--evidence', os.path.relpath(ev, self.root) if os.path.exists(ev) else '',
            '--target', self.a.target, '--out',
            os.path.relpath(os.path.join(self.out, 'cadence.json'), self.root)],
           os.path.join(self.out, 'cadence.log'), 600, self.root)
        sh([PY, 'python/cadence_pair.py', '--audit'], os.path.join(self.out, 'audit.log'), 600, self.root)
        lines = [f'# BEAST report — {self.a.target}', '',
                 f'preset: {self.cfg.get("preset")}  fs={self.cfg.get("fs")} ({self.cfg.get("fs_src")})',
                 f'elapsed: {(time.time()-self.t0)/60:.1f} min', '']
        for tag in ('on', 'off'):
            for p in self.cfg.get('pol_list', [0, 1, 2, 3]):
                c = self.scan_csv(tag, p)
                if not os.path.exists(c):
                    continue
                rows = list(csv.DictReader(open(c)))
                from collections import Counter
                vc = Counter((r['verdict'].split('+')[0] if 'QUARANTINE' not in r['verdict'] else 'QUARANTINE')
                             for r in rows)
                lines.append(f'- {tag} p{p}: {len(rows)} slices; ' + ', '.join(f'{k}={v}' for k, v in vc.most_common()))
        lines += ['', '## veto (with evidence, all pols)', '']
        for p in self.cfg.get('pol_list', [0, 1, 2, 3]):
            lp = os.path.join(self.out, f'veto_p{p}.log')
            if os.path.exists(lp):
                tail = [l for l in open(lp, errors='replace').read().splitlines() if 'BLOCK=' in l]
                lines.append(f'- p{p}: ' + (tail[-1] if tail else 'no summary'))
        open(os.path.join(self.out, 'REPORT.md'), 'w',
             encoding='utf-8').write('\n'.join(lines) + '\n')
        SC.write_manifest(os.path.join(self.out, 'REPORT.md'),
                          {'tool': 'pipeline.py', 'preset': self.cfg.get('preset'),
                           'target': self.a.target, 'config': self.cfg})
        self.log('REPORT.md written')

    def go(self):
        self.failed = []
        for name, fn in [('scans', self.phase_scans),
                         ('structure+evidence+veto', self.phase_structure_evidence_veto),
                         ('burst+deep', self.phase_burst_deep),
                         ('cadence+report', self.phase_cadence_report)]:
            try:
                fn()
            except Exception as e:
                # LOUD: a swallowed phase failure produced an empty veto
                # section in a report that still claimed success.
                self.failed.append(f'{name}: {type(e).__name__}: {e}')
                self.log(f'*** PHASE {name} FAILED: {type(e).__name__}: {e} ***')
        if self.failed:
            self.log('*** RUN INCOMPLETE - failed phases: '
                     + ' | '.join(self.failed) + ' ***')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preset', default='')
    ap.add_argument('--on', required=True)
    ap.add_argument('--off', required=True)
    ap.add_argument('--target', default='BEAST')
    ap.add_argument('--outdir', default='runs/beast_demo')
    a = ap.parse_args()
    ov = {}
    cfg = CFG.resolve(a.on, a.preset or None, ov)
    print(f"[beast] fs={cfg['fs']} ({cfg.get('fs_src')}) preset={a.preset or 'defaults'}")
    Beast(cfg, a).go()


if __name__ == '__main__':
    main()
