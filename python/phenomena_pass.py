#!/usr/bin/env python
"""phenomena_pass.py - widen the workup, not the bar.

SetiYeti doubles as a weird-space-phenomena instrument: the same slices get
a physics battery (ISM scintillation, cross-pol agreement, rotation fold,
dispersion, Doppler curvature, exotic screens) IN ADDITION TO the ET
disposition chain. Nothing here changes a threshold, a veto rule, or a
grade - dispositions are theorems, this is triage. New files only.

Selection menu per unit (from full-census struct_*.csv, never sweep):
  veto-watch  veto marked WATCH/CANDIDATE (parsed from veto_p*.log)
  structured  comb/nongauss/frame present, any fam (S>0)
  loud-spec   spec_ratio >= 8 (spectral monsters incl. ch0, labeled)
  astro-band  1 Hz <= alpha <= 2 kHz (rotation/pulsar territory: fold+DM
              instead of dismissal - the hum zone gets worked up, not waved off)
  recurrer    alpha within 2 kHz of a cross-unit cluster (>=3 units)
  pol-coinc   same (block,chan) flagged in both pols
Ranked structured > veto > recurrer > astro-band > loud-spec > fam; cap/unit.

Battery per slice (re-sliced from raw; raw files stay on disk):
  scint_pol   ISM twinkle (SCINT) vs backend gain-wander (COMMON) + xpol agree
  pulsar_fold rotation fold 1 Hz-2 kHz (ADVISORY: gate known miscalibrated -
              needs a second instrument to count)
  transient_dm single-pulse DM sweep (single-channel proxy, stated openly)
  exotic_pass neg-DM / clock / primes / precursor screens
  jerk_scan   Viterbi curvature (curve_gain>0 = bent track beats straight)

Phenomena class `ph` (advisory triage, NOT a disposition, NOT an I-grade):
  ph0 workup quiet          ph1 flagged but battery quiet
  ph2 ONE non-advisory hit  ph3 TWO+ independent hits -> human review priority
Advisory hits (fold: gate proven to false-alarm at 35 sigma on pure
archival noise) NEVER promote alone; they count only beside a non-advisory
hit. A ph3 is a pointer, never a promotion. I-grades and veto verdicts untouched.

Safety vs a live campaign: reads campaign CSVs + raw files only; writes to
<campaign>/synthesis/phenomena/; own tmp prefix; skips the unit the campaign
heartbeat currently owns; own state.json for resume.

Usage:
  python python/phenomena_pass.py --campaign runs/campaigns/2026-09-21_mega
  python python/phenomena_pass.py --campaign ... --unit HIP11048_... --cap-per-unit 2 --max-slices 4
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC  # noqa: E402

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def log(msg, lf):
    line = f'[{now()}] {msg}'
    print(line, flush=True)
    lf.write(line + '\n')
    lf.flush()


def is_sig(v):
    v = v or 'clean'
    return v != 'clean' and not v.startswith(('QUARANTINE', 'ERROR'))


def fnum(x, d=0.0):
    try:
        return float(x)
    except (ValueError, TypeError):
        return d


class Pass:
    def __init__(self, a):
        self.a = a
        self.cdir = os.path.join(ROOT, a.campaign)
        self.out = os.path.join(self.cdir, 'synthesis', 'phenomena')
        os.makedirs(self.out, exist_ok=True)
        self.logf = open(os.path.join(self.out, 'phenomena.log'), 'a',
                         encoding='utf-8', errors='replace')
        self.state_p = os.path.join(self.out, 'state.json')
        self.state = {'units': {}, 'started': now()}
        if os.path.exists(self.state_p):
            try:
                self.state = json.load(open(self.state_p))
            except Exception:
                pass
        os.environ.setdefault('SETIYETI_TMP', 'D:/data/tmp/sy_campaign')
        os.makedirs(os.environ['SETIYETI_TMP'], exist_ok=True)
        self.units = sorted(os.path.basename(d) for d in
                            glob.glob(os.path.join(self.cdir, 'targets', '*'))
                            if os.path.isdir(d))
        if a.unit:
            keep = set(a.unit)
            self.units = [u for u in self.units if u in keep]

    def save(self):
        tmp = self.state_p + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, self.state_p)

    def active_unit(self):
        try:
            txt = open(os.path.join(self.cdir, '_campaign', 'HEARTBEAT.txt')).read()
            m = re.search(r'^unit:\s*(\S+)', txt, re.M)
            return m.group(1) if m else ''
        except OSError:
            return ''

    def run(self, cmd, logp, timeout=900):
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        with open(logp, 'w', encoding='utf-8', errors='replace') as lf:
            lf.write('$ ' + ' '.join(cmd) + '\n')
            try:
                r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                   timeout=timeout, cwd=ROOT, env=os.environ)
                return r.returncode
            except subprocess.TimeoutExpired:
                lf.write('[TIMEOUT]\n')
                return 124
        return 127

    # ------------------------------------------------------------ selection --
    def veto_hits(self, udir):
        """(block,chan,pol) -> disposition, parsed from veto logs."""
        out = {}
        for p in glob.glob(os.path.join(udir, 'veto_p*.log')):
            m = re.search(r'veto_p(\d+)\.log', os.path.basename(p))
            pol = m.group(1) if m else '?'
            try:
                txt = open(p, errors='replace').read()
            except OSError:
                continue
            for mm in re.finditer(r'\[veto\]\s*b(\d+)/ch(\d+)\s+\S+\s+.*?->\s*(WATCH|CANDIDATE)',
                                  txt):
                out[(mm.group(1), mm.group(2), pol)] = mm.group(3)
        return out

    def collect_rows(self):
        """uid -> list of flagged struct rows (full census only)."""
        data = {}
        for u in self.units:
            udir = os.path.join(self.cdir, 'targets', u)
            rows = []
            for p in glob.glob(os.path.join(udir, 'struct_*.csv')):
                m = re.search(r'struct_(on|off)_p(\d+)\.csv', os.path.basename(p))
                if not m:
                    continue
                leg, pol = m.group(1), m.group(2)
                try:
                    rd = list(csv.DictReader(open(p, newline='')))
                except OSError:
                    continue
                for r in rd:
                    if not is_sig(r.get('verdict')):
                        continue
                    r['_leg'], r['_pol'], r['_file'] = leg, pol, os.path.basename(p)
                    rows.append(r)
            if rows:
                data[u] = rows
        return data

    def recur_members(self, data):
        """Fixed 2 kHz bins (NO chaining: chaining merges the whole hum
        family into one blob - measured 8650 members in a single cluster).
        Bins with >=3 distinct units -> member (uid,block,chan) set."""
        bins = {}
        for u, rows in data.items():
            for r in rows:
                hz = fnum(r.get('fam_hz'))
                if hz > 0:
                    bins.setdefault(round(hz / 2000.0), []).append((u, r['block'], r['chan']))
        members = set()
        ncl = 0
        for _, pts in bins.items():
            if len(set(x[0] for x in pts)) >= 3:
                ncl += 1
                for x in pts:
                    members.add(x)
        return members, ncl

    def select(self, data):
        members, ncl = self.recur_members(data)
        log(f'recurrence: {ncl} alpha clusters, {len(members)} member slices', self.logf)
        sel = {}
        for u, rows in data.items():
            udir = os.path.join(self.cdir, 'targets', u)
            vh = self.veto_hits(udir)
            seen_pol = {}
            for r in rows:
                seen_pol.setdefault((r['block'], r['chan']), set()).add(r['_pol'])
            cands = []
            for r in rows:
                b, c, pol, leg = r['block'], r['chan'], r['_pol'], r['_leg']
                hz = fnum(r.get('fam_hz'))
                fb = fnum(r.get('fam_best'))
                sr = fnum(r.get('spec_ratio'))
                struct = (str(r.get('comb', '')) not in ('', '0', '0.0') or
                          str(r.get('nongauss', '')) not in ('', '0', '0.0') or
                          str(r.get('frame', '')) not in ('', '0', '0.0'))
                reasons = []
                rank = 0
                if struct:
                    reasons.append('structured'); rank += 100
                if (b, c, pol) in vh:
                    reasons.append('veto-' + vh[(b, c, pol)].lower()); rank += 50
                if (u, b, c) in members:
                    reasons.append('recurrer'); rank += 30
                if 1.0 <= hz <= 2000.0:
                    reasons.append('astro-band'); rank += 20
                if sr >= 8.0:
                    reasons.append('loud-spec'); rank += 10
                if len(seen_pol.get((b, c), ())) > 1:
                    reasons.append('pol-coinc'); rank += 40
                if not reasons:
                    if fb < 4.0:
                        continue
                    reasons.append('fam-rank')
                rank += min(fb, 200.0) / 100.0
                cands.append((rank, leg, b, c, pol, hz, fb, sr,
                              r.get('verdict', ''), '+'.join(reasons), r))
            cands.sort(reverse=True, key=lambda t: t[0])
            sel[u] = cands[:self.a.cap_per_unit]
        return sel

    # -------------------------------------------------------------- battery --
    def slice_raw(self, raw, ch, pol, blk, out):
        ext = '.exe' if os.name == 'nt' else ''
        sl = os.path.join(ROOT, 'c', 'seti_slice' + ext)
        r = self.run([sl, raw, str(ch), out, '1', '--pol', str(pol),
                      '--start', str(blk)], out + '.slice.log', timeout=600)
        return r == 0 and os.path.exists(out) and os.path.getsize(out) > 100000

    def parse_json_out(self, logp):
        try:
            txt = open(logp, errors='replace').read()
        except OSError:
            return None, ''
        m = re.search(r'\{.*\}', txt, re.S)
        if not m:
            return None, txt[-800:]
        try:
            return json.loads(m.group(0)), txt[-800:]
        except Exception:
            return None, txt[-800:]

    def workup(self, u, leg, b, c, pol, raw, fs, f0mhz, do_jerk=True):
        d = os.path.join(self.out, 'slices', f'{u}__{leg}_b{b}_ch{c}_p{pol}')
        if os.path.exists(os.path.join(d, 'DONE')):
            return self.read_done(d)
        os.makedirs(d, exist_ok=True)
        tmp = os.environ['SETIYETI_TMP']
        f1 = os.path.join(tmp, f'ph_{u}_{leg}_b{b}_ch{c}_p{pol}.f32')
        res = {'unit': u, 'leg': leg, 'block': b, 'chan': c, 'pol': pol,
               'instruments': []}
        if not self.slice_raw(raw, c, pol, b, f1):
            res['note'] = 'slice-failed'
            return self.finish(d, res)
        other = '1' if str(pol) == '0' else '0'
        f2 = os.path.join(tmp, f'ph_{u}_{leg}_b{b}_ch{c}_p{other}.f32')
        xpol_ok = self.slice_raw(raw, c, other, b, f2)
        # scint (+xpol)
        cmd = [PY, 'python/scint_pol.py', '--f32', f1, '--fs', f'{fs:.4f}', '--json']
        if xpol_ok:
            cmd += ['--f32-pol', f2]
        self.run(cmd, os.path.join(d, 'scint.log'))
        j, _ = self.parse_json_out(os.path.join(d, 'scint.log'))
        if j:
            sj = j.get('scint', {}) if isinstance(j.get('scint'), dict) else j
            pj = j.get('pol', {}) if isinstance(j.get('pol'), dict) else {}
            res['scint'] = sj.get('class', '')
            res['xpol'] = str(pj.get('verdict', ''))
            if res['scint'] == 'SCINT':
                res['instruments'].append('scint-ISM')
            if pj.get('agree') is True or res['xpol'].upper().startswith('SKY'):
                res['instruments'].append('xpol-agree')
        # fold (ADVISORY)
        self.run([PY, 'python/pulsar_fold.py', '--f32', f1, '--fs', f'{fs:.4f}',
                  '--json'], os.path.join(d, 'fold.log'))
        j, _ = self.parse_json_out(os.path.join(d, 'fold.log'))
        if j and j.get('detected'):
            top = (j.get('top') or [{}])[0]
            res['fold'] = f"PERIODIC(advisory) f={top.get('freq_hz')}Hz s={top.get('sigma')}"
            res['instruments'].append('fold-advisory')
        # transient DM
        self.run([PY, 'python/transient_dm.py', '--f32', f1, '--fs', f'{fs:.4f}',
                  '--f0-mhz', f'{f0mhz:.4f}'], os.path.join(d, 'dm.log'))
        try:
            txt = open(os.path.join(d, 'dm.log'), errors='replace').read()
        except OSError:
            txt = ''
        # Positive verdict is uppercase SHOT; 'no shot' is lowercase.
        # Case-insensitive matching here once manufactured a false
        # dm-shot out of the words 'no shot' - never again.
        m = re.search(r'best \u03c3=([\d.]+) DM=(-?[\d.]+)', txt)
        if m and re.search(r'\bSHOT\b', txt) and 'no shot' not in txt:
            res['dm'] = f"shot DM={m.group(2)} s={m.group(1)}"
            res['instruments'].append('dm-shot')
        # exotic
        self.run([PY, 'python/exotic_pass.py', '--f32', f1, '--fs', f'{fs:.4f}',
                  '--f0-mhz', f'{f0mhz:.4f}', '--json'], os.path.join(d, 'exotic.log'))
        j, _ = self.parse_json_out(os.path.join(d, 'exotic.log'))
        if j:
            # exotic_pass nests per-test dicts with a 'flag' field.
            hits = [k for k, v in j.items()
                    if isinstance(v, dict) and v.get('flag')]
            if not hits and isinstance(j.get('hits'), list):
                hits = j['hits']
            if hits:
                res['exotic'] = ','.join(map(str, hits))
                res['instruments'].append('exotic:' + res['exotic'])
        # jerk needs TIME: a 0.18 s single-block slice makes the sidereal
        # bound fire vacuously (measured: v=-12796Hz/s 'ANOMALOUS' on noise).
        # Run it on the full channel span when curvature could matter
        # (structure / veto-hit / astro-band slices); skip otherwise.
        if do_jerk:
            f3 = os.path.join(tmp, f'ph_{u}_{leg}_ch{c}_p{pol}_full.f32')
            ext2 = '.exe' if os.name == 'nt' else ''
            sl2 = os.path.join(ROOT, 'c', 'seti_slice' + ext2)
            ok3 = self.run([sl2, raw, str(c), f3, '10000', '--pol', str(pol)],
                           os.path.join(d, 'jerk_slice.log'),
                           timeout=1200) == 0 and os.path.exists(f3)
            if ok3:
                self.run([PY, 'python/jerk_scan.py', '--f32', f3,
                          '--fs', f'{fs:.4f}'],
                         os.path.join(d, 'jerk.log'), timeout=1800)
                try:
                    os.remove(f3)
                except OSError:
                    pass
        try:
            jtxt = open(os.path.join(d, 'jerk.log'), errors='replace').read()
        except OSError:
            jtxt = ''
        m = re.search(r'curve_gain=([-\d.]+)dB', jtxt)
        m2 = re.search(r'track_score=([\d.]+)', jtxt)
        m3 = re.search(r'sidereal=(\S+)', jtxt)
        if m and m2 and float(m.group(1)) > 0 and float(m2.group(1)) >= 6.0:
            sid = m3.group(1) if m3 else '?'
            res['jerk'] = f"curved gain={m.group(1)}dB score={m2.group(1)} sid={sid}"
            res['instruments'].append('jerk-curved')
        for f in (f1, f2):
            try:
                os.remove(f)
            except OSError:
                pass
        return self.finish(d, res)

    def finish(self, d, res):
        ins = res.get('instruments', [])
        # Advisory hits (fold) never promote alone: the gate false-alarms
        # at 34.7 sigma on pure archival noise. They count only beside a
        # non-advisory hit.
        hits = [i for i in ins if not i.endswith('advisory')]
        adv = [i for i in ins if i.endswith('advisory')]
        if len(hits) >= 2:
            res['ph'] = 'ph3'
        elif hits:
            res['ph'] = 'ph2'
        else:
            res['ph'] = 'ph1' if res.get('note') != 'slice-failed' else 'phX'
            if adv and res['ph'] == 'ph1':
                res['note'] = ((res.get('note') + '; ' if res.get('note') else '') +
                               'lone-advisory:' + '+'.join(adv))
        with open(os.path.join(d, 'DONE'), 'w') as f:
            json.dump(res, f, indent=1)
        return res

    def read_done(self, d):
        try:
            return json.load(open(os.path.join(d, 'DONE')))
        except Exception:
            return {'ph': 'phX', 'note': 'unreadable-DONE'}

    # ------------------------------------------------------------------- go --
    def unit_raw(self, u, leg):
        plan = os.path.join(self.cdir, 'targets', u, 'PLAN.json')
        try:
            d = json.load(open(plan))
            return d['on_path'] if leg == 'on' else d['off_path']
        except Exception:
            return ''

    def header_fs_f0(self, raw):
        try:
            fs = SC.fs_from_header(raw) or SC.DEFAULT_FS
            f0, _ = SC.geometry_from_header(raw)[0], None
            f0 = float(SC.read_header(raw).get('OBSFREQ', 0) or 0)
            return fs, f0
        except Exception:
            return SC.DEFAULT_FS, 1400.0

    def go(self):
        data = self.collect_rows()
        log(f'units with flags: {len(data)}', self.logf)
        sel = self.select(data)
        total = sum(len(v) for v in sel.values())
        log(f'selected {total} slices', self.logf)
        active = self.active_unit()
        if active:
            log(f'campaign owns {active}: skipping it this pass', self.logf)
        rows = []
        done_n = 0
        for u in sorted(sel):
            if u == active:
                continue
            st = self.state['units'].setdefault(u, {})
            for (rank, leg, b, c, pol, hz, fb, sr, verdict, reasons, _r) in sel[u]:
                if done_n >= self.a.max_slices:
                    break
                raw = self.unit_raw(u, leg)
                if not raw or not os.path.exists(raw):
                    continue
                fs, f0 = self.header_fs_f0(raw)
                do_jerk = any(k in reasons for k in
                              ('structured', 'veto-watch', 'veto-candidate',
                               'astro-band', 'recurrer', 'pol-coinc'))
                res = self.workup(u, leg, b, c, pol, raw, fs, f0, do_jerk)
                res.update({'fam_best': fb, 'fam_hz': hz, 'spec_ratio': sr,
                            'verdict': verdict, 'sel': reasons})
                rows.append(res)
                done_n += 1
                st['done'] = st.get('done', 0) + 1
                self.save()
            st['phase'] = 'phenomena'
            self.save()
            log(f'{u}: workup queued {len(sel[u])}', self.logf)
        self.write_csv(rows)
        self.write_report()

    def write_csv(self, rows):
        p = os.path.join(self.out, 'phenomena.csv')
        fields = ['unit', 'leg', 'block', 'chan', 'pol', 'fam_best', 'fam_hz',
                  'spec_ratio', 'verdict', 'sel', 'ph', 'instruments', 'scint',
                  'xpol', 'fold', 'dm', 'exotic', 'jerk', 'note']
        # Merge with prior runs (restarts re-rank): new rows win per slice.
        old = {}
        if os.path.exists(p):
            try:
                for r in csv.DictReader(open(p, newline='', encoding='utf-8')):
                    old[(r['unit'], r['leg'], r['block'], r['chan'], r['pol'])] = r
            except Exception:
                pass
        for r in rows:
            r = dict(r)
            if isinstance(r.get('instruments'), list):
                r['instruments'] = '+'.join(r['instruments'])
            old[(r['unit'], r['leg'], r['block'], r['chan'], r['pol'])] = \
                {k: r.get(k, '') for k in fields}
        with open(p, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in sorted(old.values(),
                            key=lambda x: (x['unit'], x['leg'], x['block'], x['chan'])):
                w.writerow(r)
        log(f'wrote {p} ({len(old)} rows total)', self.logf)

    def write_report(self):
        try:
            rows = list(csv.DictReader(open(os.path.join(self.out, 'phenomena.csv'),
                                             newline='', encoding='utf-8')))
        except OSError:
            rows = []
        p3 = [r for r in rows if r.get('ph') == 'ph3']
        p2 = [r for r in rows if r.get('ph') == 'ph2']
        lines = ['# PHENOMENA — widened workup over campaign flags', '',
                 f'generated: {now()}  slices worked: {len(rows)}', '',
                 'ph = advisory triage only (ph3 = human-review priority).',
                 'I-grades and veto dispositions are untouched.', '']
        lines += ['## ph3 (two+ independent instruments agree)', '']
        if p3:
            lines += ['| unit | slice | fam | instruments |', '|---|---|---|---|']
            for r in p3:
                ins = '+'.join(r['instruments']) if isinstance(r['instruments'], list) else r['instruments']
                lines.append(f"| {r['unit'][:40]} | {r['leg']} b{r['block']}/ch{r['chan']}p{r['pol']} | {r['fam_best']} | {ins} |")
        else:
            lines.append('_none_')
        lines += ['', '## ph2 (single instrument; fold = advisory, gate miscalibrated)', '']
        if p2:
            lines += ['| unit | slice | fam | instruments |', '|---|---|---|---|']
            for r in p2[:40]:
                ins = '+'.join(r['instruments']) if isinstance(r['instruments'], list) else r['instruments']
                lines.append(f"| {r['unit'][:40]} | {r['leg']} b{r['block']}/ch{r['chan']}p{r['pol']} | {r['fam_best']} | {ins} |")
        else:
            lines.append('_none_')
        lines += ['', '## census', '']
        from collections import Counter
        def _ins(r):
            v = r.get('instruments') or ''
            return v.split('+') if isinstance(v, str) else list(v)
        lines.append('- instruments fired: ' + str(dict(Counter(
            i for r in rows for i in _ins(r) if i))))
        lines.append(f"- ph classes: {dict(Counter(r.get('ph','?') for r in rows))}")
        with open(os.path.join(self.out, 'PHENOMENA.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        SC.write_manifest(os.path.join(self.out, 'PHENOMENA.md'),
                          {'tool': 'phenomena_pass.py', 'slices': len(rows),
                           'ph3': len(p3), 'ph2': len(p2)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign', default='runs/campaigns/2026-09-21_mega')
    ap.add_argument('--unit', action='append', default=[],
                    help='limit to unit(s); repeatable')
    ap.add_argument('--cap-per-unit', type=int, default=10)
    ap.add_argument('--max-slices', type=int, default=150)
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args()
    Pass(a).go()


if __name__ == '__main__':
    main()
