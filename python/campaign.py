#!/usr/bin/env python
"""campaign.py — overnight mega-campaign orchestrator (unattended, resumable).

Reads catalog.tsv (the ledger), builds ONE folder per ON/OFF unit (target +
bank + MJD), and runs the proven chain per unit:

    sweep  -> mvp_scan p0, 8 channels, all blocks  (cheap first sieve)
    full   -> mvp_scan p0+p1, 64 chans, both legs
              -> structure_pass (correct raw per leg!)
              -> build_evidence (persistence + multichan, both legs)
              -> rfi_veto WITH evidence (per pol, appends to rfi_catalog.json)
              -> cadence_pair (the ONLY WATCH->CANDIDATE gate)
              -> xeno_pass (I0-I5 grades + microscopic battery + xvm sandbox)
    deep   -> per-slice battery on the corpus-wide top candidates
    univ   -> univ_scan on filterbank / HDF5 (power-only: honest subset)
    synt   -> latent_pca, corpus DB, catalog rebuild, NOVELTY.md

Everything bulk is written under runs/campaigns/<name>/ which is a junction
to D:/data/runs/campaigns (repo drive E: has ~17 GB free; D: has ~490 GB).
Scratch .f32 slices go to $SETIYETI_TMP (defaults onto D:).

Design rules bought with blood (AGENTS.md):
  * rfi_veto must ALWAYS get --evidence and the correct --raw per leg
  * cadence pairs must be SAME BANK (same 187.5 MHz window), same target
  * never edit history: this writes new files only; rfi_catalog.json grows
  * every unit writes a manifest + RUN.md so an LLM can resume anywhere
  * CANDIDATE only through cadence_pair; single-leg units cap at I2

Usage:
  python python/campaign.py --phase plan
  python python/campaign.py --phase all --deadline-hours 16
  python python/campaign.py --phase full --only HIP11048_57403_blc2
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC  # noqa: E402

PY = sys.executable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
#  catalog selection policy
# ---------------------------------------------------------------------------
EXCLUDE_TARGETS = {'VOYAGER1'}          # explicit user request
POWER_FORMATS = ('filterbank_fil', 'filterbank_h5', 'filterbank_fil(power)',
                 'filterbank_h5(power)')

# High-value files the default policy would skip (already SCANNED_*), needed
# as an ON partner so an unscanned OFF leg can be cadence-gated. Rescanning
# them is deliberate: the pair is the science unit.
FOCUS_INCLUDE = {
    'blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw':
        'ON partner for unscanned OFF 0018 (same bank 4): inferno leg cadence',
}


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def is_signal_verdict(v):
    """A quarantine row holds no sky information (AGENTS.md: dark digitizer
    lanes must be quarantined before analysis). It is NOT a flag."""
    v = v or 'clean'
    return v != 'clean' and not v.startswith(('QUARANTINE', 'ERROR'))


def parse_time(name):
    """(mjd_day, seconds_of_day, fractional mjd) from a GUPPI filename.

    GUPPI names are ``..._guppi_<MJD_day>_<SMJD_sec>_<TARGET>_<SCAN>.<PART>.raw``
    (e.g. 57807_75885 = day 57807 + 75885 s). Some archives drop the SMJD
    (MESSIER031 files use ``guppi_57396_MESSIER031_...``): then SMJD is None
    and only the day is authoritative. Using the day alone silently pairs the
    wrong ON/OFF legs (all same-day files tie at delta 0) - don't.
    """
    m = re.search(r'guppi_(\d{5})_(\d{5})_', name)
    if m:
        day, smjd = int(m.group(1)), int(m.group(2))
        return day, smjd, day + smjd / 86400.0
    m = re.search(r'guppi_(\d{5})_', name)
    if m:
        return int(m.group(1)), None, float(m.group(1))
    return None, None, None


def parse_bank(name):
    m = re.match(r'(blc\d+)', name)
    return m.group(1) if m else 'blc?'


def parse_scan_num(name):
    m = re.search(r'guppi_\d+_.*?_(\d{4})\.(\d{4})\.raw$', name)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def pointing_of(path, name):
    """Header SRC_NAME wins over filename (never trust a label alone)."""
    try:
        hdr = SC.read_header(path)
        src = str(hdr.get('SRC_NAME', '') or '')
        if 'OFF' in src.upper():
            return 'OFF'
        if src:
            return 'ON'
    except Exception:
        pass
    return 'OFF' if '_OFF_' in name else 'ON'


def nblocks_of(path):
    """Scannable block count: full BLOCSIZE blocks + a substantial tail part.

    GUPPI files carry a small ASCII header, so size//BLOCSIZE alone can lose
    the last partial block (HIP 3.9 GB files: 31 full + 1 partial = 32).
    """
    try:
        hdr = SC.read_header(path)
        bs = float(hdr.get('BLOCSIZE', 0) or 0)
        if bs <= 0:
            return None
        sz = os.path.getsize(path)
        n, rem = divmod(sz, int(bs))
        if rem > 2_000_000:
            n += 1
        return max(1, n)
    except OSError:
        return None


def header_band(path):
    try:
        hdr = SC.read_header(path)
        f = float(hdr.get('OBSFREQ', 0) or 0)
        b = float(hdr.get('OBSBW', 0) or 0)
        return f, b
    except Exception:
        return 0.0, 0.0


# ---------------------------------------------------------------------------
#  campaign
# ---------------------------------------------------------------------------
class Campaign:
    def __init__(self, a):
        self.a = a
        self.root = os.path.abspath(a.root)
        self.cdir = os.path.join(self.root, a.campaign)
        self.units_dir = os.path.join(self.cdir, 'targets')
        self.state_p = os.path.join(self.cdir, '_campaign', 'state.json')
        self.log_p = os.path.join(self.cdir, '_campaign', 'master.log')
        self.hb_p = os.path.join(self.cdir, '_campaign', 'HEARTBEAT.txt')
        self.t0 = time.time()
        self.deadline = self.t0 + a.deadline_hours * 3600.0
        self.state = {'units': {}, 'started': now(), 'phases_done': []}
        self.units = []
        self.only = set()
        os.makedirs(os.path.join(self.cdir, '_campaign'), exist_ok=True)
        os.makedirs(self.units_dir, exist_ok=True)
        os.environ.setdefault('SETIYETI_TMP', 'D:/data/tmp/sy_campaign')
        os.makedirs(os.environ['SETIYETI_TMP'], exist_ok=True)
        if os.path.exists(self.state_p):
            try:
                self.state = json.load(open(self.state_p))
            except Exception:
                self.log('WARN: unreadable state.json; starting fresh state')

    # ------------------------------------------------------------- plumbing --
    def log(self, msg, echo=True):
        line = f'[{now()}] {msg}'
        if echo:
            print(line, flush=True)
        with open(self.log_p, 'a', encoding='utf-8', errors='replace') as f:
            f.write(line + '\n')

    def heartbeat(self, phase, unit=''):
        el = (time.time() - self.t0) / 60.0
        with open(self.hb_p, 'w', encoding='utf-8') as f:
            f.write(f'time: {now()}\nphase: {phase}\nunit: {unit}\n'
                    f'elapsed_min: {el:.1f}\ndeadline_min: '
                    f'{self.a.deadline_hours * 60:.0f}\n')

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_p), exist_ok=True)
        tmp = self.state_p + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, self.state_p)
        self.write_status()

    def past_deadline(self):
        return time.time() > self.deadline

    def run(self, cmd, logp, timeout=None, quiet=False):
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        with open(logp, 'a', encoding='utf-8', errors='replace') as lf:
            lf.write(f'\n$ {" ".join(cmd)}   [{now()}]\n')
            lf.flush()
            try:
                r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                   timeout=timeout, cwd=self.root,
                                   env=os.environ)
                return r.returncode
            except subprocess.TimeoutExpired:
                lf.write(f'\n[TIMEOUT {timeout}s]\n')
                return 124
            except Exception as e:
                lf.write(f'\n[RUN FAILED: {type(e).__name__}: {e}]\n')
                return 127

    # ------------------------------------------------------------ selection --
    def load_catalog_rows(self):
        p = os.path.join(self.root, self.a.catalog)
        with open(p, newline='', encoding='utf-8', errors='replace') as f:
            return list(csv.DictReader(f, delimiter='\t'))

    def select(self):
        rows = self.load_catalog_rows()
        kept, excl = [], []
        for r in rows:
            name = r['filename']
            target = (r.get('target') or '').upper()
            status = (r.get('scan_status') or '').strip()
            fmt = (r.get('format') or '').strip()
            loc = (r.get('location') or '').strip()
            kind = (r.get('kind') or '').strip()
            summary = (r.get('result_summary') or '')
            coverage = (r.get('coverage') or '')
            reason = None

            if target in EXCLUDE_TARGETS:
                reason = 'excluded target (VOYAGER1)'
            elif kind != 'raw_storage':
                reason = f'kind={kind} (not sky storage)'
            elif status in ('QUARANTINED', 'SMOKE', 'PARTIAL_FILE'):
                reason = f'scan_status={status}'
            elif 'PART1GB' in name or 'probe' in name:
                reason = 'engineering excerpt / probe'
            elif fmt not in ('guppi_raw',) and fmt not in POWER_FORMATS \
                    and not fmt.startswith('guppi_raw'):
                reason = f'format={fmt} (not this wave)'
            elif status == 'SCANNED_FULL' and name not in FOCUS_INCLUDE:
                reason = 'already SCANNED_FULL (complete record exists)'
            elif status == 'SCANNED_PARTIAL' and 'gated CLEAN' in summary:
                reason = 'already cadence-gated CLEAN (2026-09-21)'
            elif status == 'SCANNED_PARTIAL' and 'ch 0,1,2' in coverage and \
                    'blocks 0-31' in coverage:
                reason = 'full census already present in coverage column'
            elif status == 'SCANNED_PARTIAL' and 'ch 0-63' in coverage and \
                    ('blocks 0-31' in coverage or 'blocks 0-127' in coverage):
                reason = 'full census already present in coverage column'
            elif status == 'SCANNED_PARTIAL' and not self.a.complete_partial:
                reason = 'SCANNED_PARTIAL (pass --complete-partial to revisit)'

            if reason:
                excl.append((name, target, status, reason))
                continue

            path = self.resolve_path(loc, name)
            if not path:
                excl.append((name, target, status, f'missing on disk ({loc})'))
                continue
            if os.path.exists(path + '.aria2'):
                excl.append((name, target, status, 'incomplete aria2 download'))
                continue

            kept.append({
                'name': name, 'path': path, 'target': target or 'UNKNOWN',
                'status': status, 'format': fmt, 'location': loc,
                'pointing': (r.get('pointing') or '').upper(),
                'mjd_day': parse_time(name)[0], 'smjd': parse_time(name)[1],
                't': parse_time(name)[2],
                'bank': parse_bank(name),
                'scan': parse_scan_num(name)[0], 'part': parse_scan_num(name)[1],
                'summary': r.get('result_summary', ''), 'notes': r.get('notes', ''),
                'power': fmt in POWER_FORMATS or not fmt.startswith('guppi_raw'),
            })
        self.exclusions = excl
        return kept

    def resolve_path(self, loc, name):
        norm = loc.replace('\\', '/').rstrip('/')
        bases = [loc]
        # catalog uses the repo-relative convention "E:/data" for E:/SetiYeti/data
        if norm.lower() in ('e:/data', 'e:/setiyeti/data', 'data'):
            bases.insert(0, os.path.join(ROOT, 'data'))
        bases += [os.path.join(ROOT, 'data'), 'D:/data/raw', 'E:/data',
                  'D:/data/gc', 'D:/data/fil']
        for base in bases:
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
        return None

    def build_units(self, files):
        """One unit per (target, bank, ON scan); OFF matched same bank within
        0.5 d. Pointing from header, never filename alone."""
        groups = {}
        units = []
        for f in files:
            if f['power']:
                units.append(self.make_unit('power', f['target'], f['bank'],
                                            None, None, [f]))
                continue
            f['pointing'] = pointing_of(f['path'], f['name'])
            groups.setdefault((f['target'], f['bank']), []).append(f)

        for (target, bank), fs in sorted(groups.items(), key=lambda kv: str(kv[0])):
            # An "observation" = one scan = one filename SMJD; its files are
            # continuation parts (.0000/.0001/...). Parts align in time, so
            # pair part k of the ON observation with part k of the OFF.
            ons, offs = {}, {}
            for f in fs:
                d = ons if f['pointing'] == 'ON' else offs
                key = (f['mjd_day'], f['smjd']) if f['smjd'] is not None \
                    else ('scan', f['scan'], f['part'])
                d.setdefault(key, []).append(f)
            for d in (ons, offs):
                for k in d:
                    d[k].sort(key=lambda x: (x['smjd'] or 0, x['part'] or 0))
            t_of = lambda fl: (fl['t'] if fl['t'] is not None else 0.0)
            on_keys = sorted(ons, key=lambda k: t_of(ons[k][0]))
            off_keys = sorted(offs, key=lambda k: t_of(offs[k][0]))
            used = set()
            for ok in on_keys:
                parts, t_on = ons[ok], t_of(ons[ok][0])
                # DIAG observations alternate ON/OFF every ~80 s, so the
                # NEAREST OFF can be the PREVIOUS scan's OFF. Require the OFF
                # to follow the ON (the observing script's order).
                cands = [bk for bk in off_keys if bk not in used
                         and 0 < t_of(offs[bk][0]) - t_on <= 0.5]
                bk = min(cands, key=lambda k: t_of(offs[k][0]) - t_on) \
                    if cands else None
                if bk is None:
                    for x in parts:
                        units.append(self.make_unit('solo', target, bank,
                                                    x, None, [x]))
                    continue
                used.add(bk)
                oparts, bparts = parts, offs[bk]
                n = min(len(oparts), len(bparts))
                for i in range(n):
                    units.append(self.make_unit('pair', target, bank,
                                                oparts[i], bparts[i],
                                                [oparts[i], bparts[i]]))
                for x in oparts[n:]:
                    units.append(self.make_unit('solo', target, bank,
                                                x, None, [x]))
                for x in bparts[n:]:
                    units.append(self.make_unit('solo_off', target, bank,
                                                None, x, [x]))
            for bk in off_keys:
                if bk not in used:
                    for x in offs[bk]:
                        units.append(self.make_unit('solo_off', target, bank,
                                                    None, x, [x]))
        for u in units:
            u['priority'] = self.priority_of(u)
        units.sort(key=lambda u: (u['priority'], u['uid']))
        return units

    def make_unit(self, kind, target, bank, on, off, files):
        head = on or off or files[0]
        day, smjd = head['mjd_day'], head['smjd']
        scan, part = head['scan'], head['part']
        uid = f'{target}_{day}_{bank}'
        if smjd is not None:
            uid += f'_{smjd}'
        if scan is not None:
            uid += f'_s{scan}'
        if part is not None:
            uid += f'_part{part:04d}'
        if kind == 'power':
            import hashlib
            base = re.sub(r'[^A-Za-z0-9_.+-]+', '_', os.path.basename(files[0]['name']))[:60]
            uid = f'{target}_{base}_{hashlib.md5(files[0]["name"].encode()).hexdigest()[:8]}'
        return {
            'uid': uid, 'kind': kind, 'target': target, 'bank': bank,
            'mjd_day': day, 'smjd': smjd, 't': head['t'],
            'on': on['name'] if on else '', 'off': off['name'] if off else '',
            'on_path': on['path'] if on else '', 'off_path': off['path'] if off else '',
            'files': [f['name'] for f in files],
            'paths': {f['name']: f['path'] for f in files},
            'power': files[0]['power'],
            'notes': ' | '.join(f.get('notes', '') for f in files[:-1]),
        }

    def priority_of(self, u):
        t = u['target']
        if t == 'TRAPPIST1':
            return 0
        if t == 'KEPLER-160':
            return 1
        if u['kind'] == 'pair' and t.startswith('HIP'):
            return 2
        if not u['power']:
            return 3
        return 4   # power/univ last

    # ------------------------------------------------------------- planning --
    def write_status(self):
        cols = ['unit', 'target', 'bank', 'kind', 'priority', 'phase',
                'sweep_flags', 'full_flags', 'watch', 'candidate', 'grade',
                'started', 'finished', 'note']
        p = os.path.join(self.cdir, 'STATUS.tsv')
        tmp = p + '.tmp'
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter='\t')
            w.writerow(cols)
            for u in self.units:
                st = self.state['units'].get(u['uid'], {})
                w.writerow([u['uid'], u['target'], u['bank'], u['kind'],
                            u.get('priority', ''), st.get('phase', 'planned'),
                            st.get('sweep_flags', ''), st.get('full_flags', ''),
                            st.get('watch', ''), st.get('candidate', ''),
                            st.get('grade', ''), st.get('started', ''),
                            st.get('finished', ''), st.get('note', '')])
        os.replace(tmp, p)

    def unit_dir(self, u):
        return os.path.join(self.units_dir, u['uid'])

    def write_plan(self):
        open(os.path.join(self.cdir, '_campaign', 'PROVE_GATE.log'), 'a').close()
        # exclusions ledger
        p = os.path.join(self.cdir, 'EXCLUSIONS.tsv')
        with open(p, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter='\t')
            w.writerow(['filename', 'target', 'scan_status', 'reason'])
            for row in sorted(self.exclusions):
                w.writerow(row)
        # per-unit plan + RUN.md skeleton
        for u in self.units:
            d = self.unit_dir(u)
            os.makedirs(os.path.join(d, 'sweep'), exist_ok=True)
            os.makedirs(os.path.join(d, 'deep'), exist_ok=True)
            plan = dict(u)
            plan['band_mhz'] = {}
            for nm, pth in u['paths'].items():
                fq, bw = header_band(pth)
                plan['band_mhz'][nm] = {'obsfreq': fq, 'obsbw': bw,
                                        'nblocks': nblocks_of(pth)}
            with open(os.path.join(d, 'PLAN.json'), 'w') as f:
                json.dump(plan, f, indent=1)
            self.write_run_md(u, plan)
        self.save_state()

    def write_run_md(self, u, plan=None):
        d = self.unit_dir(u)
        st = self.state['units'].get(u['uid'], {})
        plan = plan or json.load(open(os.path.join(d, 'PLAN.json')))
        lines = [f'# RUN — {u["uid"]}', '']
        lines += [f'- target: `{u["target"]}`  bank: `{u["bank"]}`  '
                  f'MJD: `{u["mjd_day"]}` fSMJD: `{u["smjd"]}`  kind: `{u["kind"]}`',
                  f'- phase: **{st.get("phase", "planned")}**  '
                  f'started: {st.get("started", "-")}  '
                  f'finished: {st.get("finished", "-")}',
                  f'- on:  `{u["on"] or "-"}`', f'- off: `{u["off"] or "-"}`', '']
        lines += ['## band / geometry', '']
        for nm, b in plan.get('band_mhz', {}).items():
            lines.append(f'- `{nm}`: {b["obsfreq"]:.2f} MHz center, '
                         f'{b["obsbw"]:.2f} MHz BW, {b["nblocks"]} blocks')
        lines += ['', '## files written (read in this order)', '',
                  '- `sweep/` — first sieve (p0, stride chans). Cheap receipts.',
                  '- `scan_<leg>_p<pol>.csv` — full census slices (schema: block,chan,pol,spec_ratio,spec_bin,fam_best,fam_hz,fam_tag,vm_sign,vm_diff,spikes,rms,verdict)',
                  '- `struct_<leg>_p<pol>.csv` — flags + comb/nongauss/frame columns',
                  '- `evidence.csv` — persistence + multichannel evidence',
                  '- `veto_p<pol>.log` — rfi_veto dispositions (BLOCK/WATCH/CANDIDATE)',
                  '- `cadence.json` — ONLY ON–OFF gate (pair units)',
                  '- `xeno_*.csv` — I0–I5 grades + microscopic battery',
                  '- `REPORT.md` — unit summary (written at the end)',
                  '- `deep/` — per-slice battery on top candidates', '']
        lines += ['## counts', '',
                  f'- sweep flags: {st.get("sweep_flags", "-")}',
                  f'- full flags: {st.get("full_flags", "-")}',
                  f'- veto WATCH: {st.get("watch", "-")}  '
                  f'CANDIDATE: {st.get("candidate", "-")}  '
                  f'grade: {st.get("grade", "-")}',
                  f'- note: {st.get("note", "-")}', '']
        with open(os.path.join(d, 'RUN.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    # ---------------------------------------------------------------- sweep --
    def sweep_unit(self, u):
        d = self.unit_dir(u)
        legs = [('on', u['on_path'])] if u['on_path'] else []
        if u['off_path']:
            legs.append(('off', u['off_path']))
        if u['power']:
            return self.univ_unit(u)
        jobs = []
        with ThreadPoolExecutor(max_workers=2) as ex:
            for leg, raw in legs:
                out = os.path.join(d, 'sweep', f'scan_{leg}_p0.csv')
                logp = os.path.join(d, 'sweep', f'{leg}_p0.log')
                # A killed scan leaves a partial CSV; only the log's DONE
                # marker proves the sweep completed (mvp_scan resumes the CSV).
                if self.file_done(logp) or (os.path.exists(out) and
                                            not os.path.exists(logp)):
                    continue
                nb = nblocks_of(raw)
                if not nb:
                    self.log(f'{u["uid"]}: cannot determine nblocks for {raw}')
                    continue
                cmd = [PY, 'python/mvp_scan.py', '--raw', raw, '--b0', '0',
                       '--b1', str(nb - 1), '--chans', self.a.sweep_chans,
                       '--pol', '0', '--out', out, '--root', self.root,
                       '--fam-trig', str(self.a.fam_trig)]
                jobs.append((leg, ex.submit(self.run, cmd, logp)))
            for leg, fu in jobs:
                self.log(f'{u["uid"]} sweep {leg}: rc={fu.result()}')
        n, flags = self.tally_sweep(u)
        st = self.state['units'].setdefault(u['uid'], {})
        st['sweep_flags'] = flags
        st['swept_n'] = n
        self.save_state()
        return flags

    def file_done(self, logp, token='DONE'):
        try:
            return os.path.exists(logp) and token in open(
                logp, errors='replace').read()
        except OSError:
            return False

    def tally_sweep(self, u):
        n = flags = quar = 0
        for leg in ('on', 'off'):
            p = os.path.join(self.unit_dir(u), 'sweep', f'scan_{leg}_p0.csv')
            if not os.path.exists(p):
                continue
            for r in csv.DictReader(open(p, newline='')):
                n += 1
                v = r.get('verdict') or 'clean'
                if v.startswith(('QUARANTINE', 'ERROR')):
                    quar += 1
                elif is_signal_verdict(v):
                    flags += 1
        st = self.state['units'].setdefault(u['uid'], {})
        st['sweep_quar'] = quar
        return n, flags

    def dark_lane(self, u):
        """True when the sweep says this node is a dark digitizer lane.

        AGENTS.md hard lesson: a probe that shows few distinct codes + low RMS
        must be quarantined, not scanned - phantom VM/line flags come from it
        (W75N). Rule: quarantine dominates the sweep and signal flags are few.
        """
        st = self.state['units'].get(u['uid'], {})
        n = st.get('swept_n', 0)
        if not n:
            return False
        return st.get('sweep_quar', 0) >= 0.5 * n and st.get('sweep_flags', 0) < 8

    def quarantine_unit(self, u):
        d = self.unit_dir(u)
        st = self.state['units'].setdefault(u['uid'], {})
        st['phase'] = 'QUARANTINED_LANE'
        st['finished'] = now()
        st['note'] = (f"dark digitizer lane: {st.get('sweep_quar')}/{st.get('swept_n')} "
                      f"sweep slices QUARANTINE, {st.get('sweep_flags')} signal flags - "
                      f"full scan refused (AGENTS.md W75N rule)")
        self.save_state()
        self.write_run_md(u)
        with open(os.path.join(d, 'REPORT.md'), 'w', encoding='utf-8') as f:
            f.write(f'# {u["uid"]} - QUARANTINED LANE\n\n' + st['note'] + '\n\n'
                    'Receipts: sweep/scan_*.csv (QUARANTINE verdicts, range/distinct '
                    'shown per slice). No full scan was run; a dark lane cannot '
                    'produce sky evidence and its flags would be digitizer '
                    'artifacts. See sweep/ for the probe.\n')
        SC.write_manifest(os.path.join(d, 'REPORT.md'), {
            'tool': 'campaign.py', 'unit': u['uid'], 'target': u['target'],
            'phase': 'QUARANTINED_LANE', 'sweep_quar': st.get('sweep_quar'),
            'swept_n': st.get('swept_n'), 'sweep_flags': st.get('sweep_flags')})
        self.log(f'{u["uid"]}: QUARANTINED LANE - full scan refused '
                 f'({st.get("sweep_quar")}/{st.get("swept_n")} quarantine)')

    # ----------------------------------------------------------------- full --
    def full_unit(self, u):
        if u['power']:
            return
        if self.dark_lane(u):
            return self.quarantine_unit(u)
        d = self.unit_dir(u)
        legs = [('on', u['on_path'])] if u['on_path'] else []
        if u['off_path']:
            legs.append(('off', u['off_path']))
        pols = [int(x) for x in self.a.full_pols.split(',')]

        # 1. scans (two legs in parallel, pols sequential per leg)
        def do_leg(leg, raw):
            for pol in pols:
                out = os.path.join(d, f'scan_{leg}_p{pol}.csv')
                logp = os.path.join(d, f'scan_{leg}_p{pol}.log')
                if self.file_done(logp) or (os.path.exists(out) and
                                            not os.path.exists(logp)):
                    continue
                nb = nblocks_of(raw)
                if not nb:
                    continue
                cmd = [PY, 'python/mvp_scan.py', '--raw', raw, '--b0', '0',
                       '--b1', str(nb - 1), '--chans', '0-63', '--pol',
                       str(pol), '--out', out, '--root', self.root,
                       '--fam-trig', str(self.a.fam_trig), '--workers', '2']
                self.run(cmd, logp, timeout=6 * 3600)
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(do_leg, leg, raw) for leg, raw in legs]
            for fu in futs:
                fu.result()

        # 2. structure per scan, with the CORRECT raw for its leg
        raw_of = {'on': u['on_path'], 'off': u['off_path']}
        structs = []
        for leg, raw in legs:
            for pol in pols:
                s = os.path.join(d, f'scan_{leg}_p{pol}.csv')
                if not os.path.exists(s):
                    continue
                o = os.path.join(d, f'struct_{leg}_p{pol}.csv')
                if not os.path.exists(o):
                    self.run([PY, 'python/structure_pass.py', '--scan', s,
                              '--raw', raw, '--out', o, '--root', self.root,
                              '--topk', str(self.a.struct_topk)],
                             os.path.join(d, f'struct_{leg}_p{pol}.log'),
                             timeout=3 * 3600)
                if os.path.exists(o):
                    structs.append(o)

        # 3. evidence across all legs/pols
        ev = os.path.join(d, 'evidence.csv')
        if structs and not os.path.exists(ev):
            cmd = [PY, 'python/build_evidence.py', '--target', u['target'],
                   '--out', ev, '--root', self.root,
                   '--persist-min', str(self.a.persist_min)]
            for s in structs:
                cmd += ['--scan', s]
            self.run(cmd, ev + '.log', timeout=3600)

        # 4. veto per pol WITH evidence; serialize (rfi_catalog.json is shared)
        for pol in pols:
            on_h = self.pick_hits(d, 'on', pol)
            off_h = self.pick_hits(d, 'off', pol)
            if not on_h:
                continue
            logp = os.path.join(d, f'veto_p{pol}.log')
            if self.file_done(logp, 'WATCH=') or self.file_done(logp, 'CANDIDATE='):
                continue
            cmd = [PY, 'python/rfi_veto.py', '--hits', on_h,
                   '--raw', u['on_path'], '--evidence',
                   ev if os.path.exists(ev) else '',
                   '--target', u['target'],
                   '--catalog', os.path.join(self.root, 'rfi_catalog.json'),
                   '--run-id', f'mega_{u["uid"]}_p{pol}']
            if off_h:
                cmd += ['--on', on_h, '--off', off_h]
            self.run(cmd, logp, timeout=3600)

        # 5. cadence gate (pair units only; the ONLY promotion path)
        if u['off_path']:
            on_h = self.pick_hits(d, 'on', pols[0])
            off_h = self.pick_hits(d, 'off', pols[0])
            cad = os.path.join(d, 'cadence.json')
            if on_h and off_h and not os.path.exists(cad):
                cmd = [PY, 'python/cadence_pair.py', '--on', on_h,
                       '--off', off_h, '--target', u['target'], '--out', cad,
                       '--root', self.root]
                if os.path.exists(ev):
                    cmd += ['--evidence', ev]
                self.run(cmd, os.path.join(d, 'cadence.log'), timeout=900)

        # 6. xeno grades, pols POOLED: every pol's struct/scan file is
        # passed (--scan repeatable) and topk is taken across the pool by
        # fam_best, so each (block,chan) is analysed at its highest-SNR
        # pol. (Before: pols[0] only - the mega run graded p0 while p1
        # held 1,708 veto candidates. Never again.)
        on_srcs = [s for p in pols for s in [self.pick_hits(d, 'on', p)] if s]
        off_srcs = [s for p in pols for s in [self.pick_hits(d, 'off', p)] if s]
        srcs = on_srcs or off_srcs
        if srcs and not os.path.exists(os.path.join(d, 'xeno.csv')):
            leg = 'on' if on_srcs else 'off'
            raw = u['on_path'] if leg == 'on' else u['off_path']
            cmd = [PY, 'python/xeno_pass.py', '--raw', raw,
                   '--target', u['target'], '--out', os.path.join(d, 'xeno.csv'),
                   '--root', self.root, '--topk', '20',
                   '--min-fam', str(self.a.min_fam_xeno)]
            for s in srcs:
                cmd += ['--scan', s]
            if leg == 'on':
                for s in off_srcs:
                    cmd += ['--off', s]
            if os.path.exists(ev):
                cmd += ['--evidence', ev]
            self.run(cmd, os.path.join(d, 'xeno.log'), timeout=3 * 3600)

        # 7. tally + report
        st = self.state['units'].setdefault(u['uid'], {})
        st['full_flags'], st['watch'], st['candidate'] = self.tally_full(u)
        st['grade'] = self.grade_summary(u)
        st['finished'] = now()
        st['phase'] = 'full'
        self.save_state()
        self.write_run_md(u)
        self.write_report(u)

    def pick_hits(self, d, leg, pol):
        s = os.path.join(d, f'struct_{leg}_p{pol}.csv')
        if os.path.exists(s) and os.path.getsize(s) > 30:
            return s
        s = os.path.join(d, f'scan_{leg}_p{pol}.csv')
        return s if os.path.exists(s) and os.path.getsize(s) > 30 else ''

    def tally_full(self, u):
        d = self.unit_dir(u)
        flags = watch = cand = 0
        for p in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not p.startswith('scan_') or not p.endswith('.csv'):
                continue
            for r in csv.DictReader(open(os.path.join(d, p), newline='')):
                if is_signal_verdict(r.get('verdict')):
                    flags += 1
        for p in os.listdir(d) if os.path.isdir(d) else []:
            if not p.startswith('veto_p') or not p.endswith('.log'):
                continue
            txt = open(os.path.join(d, p), errors='replace').read()
            m = re.findall(r'BLOCK=(\d+) WATCH=(\d+) CANDIDATE=(\d+)', txt)
            if m:
                watch += sum(int(x[1]) for x in m)
                cand += sum(int(x[2]) for x in m)
        return flags, watch, cand

    def grade_summary(self, u):
        d = self.unit_dir(u)
        x = os.path.join(d, 'xeno.csv')
        if not os.path.exists(x):
            return ''
        gc = {}
        for r in csv.DictReader(open(x, newline='')):
            gc[r.get('grade', '?')] = gc.get(r.get('grade', '?'), 0) + 1
        return ' '.join(f'{k}={gc[k]}' for k in sorted(gc))

    def write_report(self, u):
        d = self.unit_dir(u)
        st = self.state['units'].get(u['uid'], {})
        plan = json.load(open(os.path.join(d, 'PLAN.json')))
        lines = [f'# {u["uid"]} — REPORT', '',
                 f'generated: {now()}  phase: {st.get("phase")}', '',
                 f'- target **{u["target"]}**, bank **{u["bank"]}**, '
                 f'MJD {u["mjd_day"]} fSMJD {u["smjd"]}, kind **{u["kind"]}**',
                 f'- ON: `{u["on"] or "-"}`',
                 f'- OFF: `{u["off"] or "-"}`', '']
        for nm, b in plan.get('band_mhz', {}).items():
            lines.append(f'- `{nm}`: {b["obsfreq"]:.2f} MHz, '
                         f'{b["obsbw"]:.2f} MHz BW, {b["nblocks"]} blocks')
        lines += ['', '## summary', '',
                  f'- sweep flags: **{st.get("sweep_flags", "-")}**',
                  f'- full flags: **{st.get("full_flags", "-")}**',
                  f'- veto: WATCH **{st.get("watch", "-")}**, '
                  f'CANDIDATE **{st.get("candidate", "-")}**',
                  f'- xeno grades: {st.get("grade", "-")}', '']
        cad = os.path.join(d, 'cadence.json')
        if os.path.exists(cad):
            try:
                c = json.load(open(cad))
                lines += ['## cadence gate (pair)', '',
                          '```json', json.dumps(c, indent=1)[:2000], '```', '']
            except Exception:
                pass
        # top flagged slices across all scan CSVs
        tops = []
        for p in os.listdir(d):
            if p.startswith('scan_') and p.endswith('.csv'):
                try:
                    for r in csv.DictReader(open(os.path.join(d, p), newline='')):
                        if (r.get('verdict') or 'clean') == 'clean':
                            continue
                        sc = max(float(r.get('fam_best') or 0),
                                 float(r.get('spec_ratio') or 0))
                        tops.append((sc, p, r['block'], r['chan'], r['pol'],
                                     r.get('fam_tag', ''), r.get('fam_hz', '')))
                except Exception:
                    continue
        tops.sort(reverse=True)
        lines += ['## top flagged slices (score = max(fam, spec_ratio))', '']
        if tops:
            lines += ['| score | file | block | chan | pol | tag | alpha Hz |',
                      '|---|---|---|---|---|---|---|']
            for sc, p, b, c, po, tag, hz in tops[:25]:
                lines.append(f'| {sc:.2f} | {p} | {b} | {c} | {po} | {tag} | {hz} |')
        else:
            lines.append('_no flagged slices_')
        lines += ['', '## receipts', '',
                  '- veto: ' + ', '.join(sorted(
                      p for p in os.listdir(d) if p.startswith('veto_p'))) or '- none',
                  '- evidence: ' + ('evidence.csv' if os.path.exists(
                      os.path.join(d, 'evidence.csv')) else 'none'),
                  '- xeno: ' + ('xeno.csv' if os.path.exists(
                      os.path.join(d, 'xeno.csv')) else 'none'),
                  '- cadence: ' + ('cadence.json' if os.path.exists(cad) else 'none'),
                  '']
        with open(os.path.join(d, 'REPORT.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        SC.write_manifest(os.path.join(d, 'REPORT.md'), {
            'tool': 'campaign.py', 'unit': u['uid'], 'target': u['target'],
            'bank': u['bank'], 'kind': u['kind'], 'on': u['on'], 'off': u['off'],
            'phase': st.get('phase'), 'watch': st.get('watch'),
            'candidate': st.get('candidate'), 'grade': st.get('grade')})

    # ----------------------------------------------------------------- deep --
    def deep_candidates(self, cap_each=4):
        out = []
        for u in self.units:
            if u['power']:
                continue
            d = self.unit_dir(u)
            if not os.path.isdir(d):
                continue
            rows = []
            for p in os.listdir(d):
                if not (p.startswith('scan_') and p.endswith('.csv')):
                    continue
                leg = 'on' if p.startswith('scan_on_') else 'off'
                try:
                    for r in csv.DictReader(open(os.path.join(d, p), newline='')):
                        if (r.get('verdict') or 'clean') == 'clean':
                            continue
                        sc = max(float(r.get('fam_best') or 0),
                                 float(r.get('spec_ratio') or 0))
                        rows.append((sc, r['block'], r['chan'], r['pol'], leg, p))
                except Exception:
                    continue
            rows.sort(reverse=True)
            seen = set()
            for sc, b, c, pol, leg, p in rows:
                key = (b, c, pol, leg)
                if key in seen:
                    continue
                seen.add(key)
                out.append((sc, u, leg, b, c, pol, p))
                if len(seen) >= cap_each:
                    break
        out.sort(reverse=True, key=lambda t: t[0])
        return out

    def deep_unit(self, sc, u, leg, b, c, pol, src_csv):
        d = os.path.join(self.unit_dir(u), 'deep', f'b{b}_ch{c}_p{pol}_{leg}')
        if os.path.exists(os.path.join(d, 'DONE')):
            return
        os.makedirs(d, exist_ok=True)
        raw = u['on_path'] if leg == 'on' else u['off_path']
        f32 = os.path.join(os.environ['SETIYETI_TMP'],
                           f'deep_{u["uid"]}_b{b}_ch{c}_p{pol}.f32')
        ext = '.exe' if os.name == 'nt' else ''
        sl = os.path.join(self.root, 'c', 'seti_slice' + ext)
        rc = self.run([sl, raw, str(c), f32, '1', '--pol', str(pol),
                       '--start', str(b)], os.path.join(d, 'slice.log'))
        if rc != 0 or not os.path.exists(f32):
            self.log(f'deep {u["uid"]} b{b}/ch{c}: slice failed rc={rc}')
            return
        fs = SC.fs_from_header(raw) or SC.DEFAULT_FS
        f0, _ = header_band(raw)
        tools = [
            ('jerk', [PY, 'python/jerk_scan.py', '--f32', f32, '--fs', f'{fs:.4f}']),
            ('scd', [PY, 'python/scd_frf.py', '--f32', f32, '--fs', f'{fs:.4f}']),
            ('exotic', [PY, 'python/exotic_pass.py', '--f32', f32,
                        '--fs', f'{fs:.4f}', '--f0-mhz', f'{f0:.4f}', '--json']),
            ('scint', [PY, 'python/scint_pol.py', '--f32', f32, '--fs', f'{fs:.4f}', '--json']),
            ('fold', [PY, 'python/pulsar_fold.py', '--f32', f32, '--fs', f'{fs:.4f}', '--json']),
            ('dm', [PY, 'python/transient_dm.py', '--f32', f32, '--fs', f'{fs:.4f}',
                    '--f0-mhz', f'{f0:.4f}']),
            ('burst', [PY, 'python/burst_zoom.py', '--f32', f32]),
        ]
        for tag, cmd in tools:
            if tag in ('fold',) and self.a.skip_fold:
                continue
            self.run(cmd, os.path.join(d, f'{tag}.log'), timeout=1800)
        try:
            os.remove(f32)
        except OSError:
            pass
        with open(os.path.join(d, 'DONE'), 'w') as f:
            f.write(f'{now()} score={sc:.3f} src={src_csv}\n')

    # ---------------------------------------------------------------- univ --
    def univ_unit(self, u):
        d = self.unit_dir(u)
        for name, path in u['paths'].items():
            sub = os.path.join(d, 'univ_' + re.sub(r'[^A-Za-z0-9]+', '_', name)[:60])
            done = os.path.join(sub, 'REPORT.md')
            if os.path.exists(done):
                continue
            cmd = [PY, 'python/univ_scan.py', '--in', path, '--outdir', sub,
                   '--root', self.root]
            self.run(cmd, os.path.join(d, re.sub(r'[^A-Za-z0-9]+', '_', name)[:60] + '.log'),
                     timeout=4 * 3600)
        st = self.state['units'].setdefault(u['uid'], {})
        st['phase'] = 'univ'
        st['finished'] = now()
        st['full_flags'] = 'n/a(power)'
        self.save_state()
        self.write_run_md(u)

    # ---------------------------------------------------------------- synth --
    def synthesis(self):
        syn = os.path.join(self.cdir, 'synthesis')
        os.makedirs(syn, exist_ok=True)
        # latent_pca across every scan CSV produced
        lat = os.path.join(syn, 'latent_all.csv')
        rows = []
        for dirpath, _, names in os.walk(self.cdir):
            for n in names:
                if n.startswith('scan_') and n.endswith('.csv') and \
                        os.sep + 'sweep' + os.sep not in dirpath:
                    rows.append(os.path.join(dirpath, n))
        with open(lat, 'w', newline='', encoding='utf-8') as f:
            w = None
            for i, s in enumerate(sorted(rows)):
                out = os.path.join(syn, f'.latent_{i}.csv')
                rc = self.run([PY, 'python/latent_pca.py', '--slices', s],
                              out + '.log')
                if not os.path.exists(out):
                    continue
                for r in csv.DictReader(open(out, newline='')):
                    r['source'] = os.path.relpath(s, self.cdir)
                    if w is None:
                        w = csv.DictWriter(f, fieldnames=list(r.keys()))
                        w.writeheader()
                    w.writerow(r)
        # catalog rebuild + corpus DB (generated record)
        self.run([PY, 'python/build_catalog.py'],
                 os.path.join(syn, 'build_catalog.log'), timeout=1800)
        self.run([PY, 'python/corpus.py', '--auto', '--root', self.root],
                 os.path.join(syn, 'corpus.log'), timeout=3600)
        self.write_novelty(syn)
        self.write_campaign_md()

    def write_novelty(self, syn):
        lines = ['# NOVELTY — what this campaign actually found', '',
                 'Generated by campaign.py from the machine record. No adjectives',
                 'without a number; every claim links to the file that proves it.', '']
        # collect every WATCH/CANDIDATE and every grade >= I3
        hits = []
        for u in self.units:
            st = self.state['units'].get(u['uid'], {})
            if st.get('watch') or st.get('candidate'):
                hits.append((u, st))
        lines += ['## veto WATCH / CANDIDATE', '']
        if hits:
            lines += ['| unit | WATCH | CAND | grade | report |', '|---|---|---|---|---|']
            for u, st in hits:
                lines.append(f'| {u["uid"]} | {st.get("watch", 0)} | '
                             f'{st.get("candidate", 0)} | {st.get("grade", "")} | '
                             f'`{os.path.relpath(self.unit_dir(u), self.cdir)}/REPORT.md` |')
        else:
            lines.append('_none: every flag dispositioned BLOCK or below threshold '
                         'on the records in `targets/*/veto_p*.log`._')
        lines += ['', '## I3+ grades (xeno_pass)', '']
        g3 = []
        for u in self.units:
            st = self.state['units'].get(u['uid'], {})
            if re.search(r'\bI[345]=[1-9]', st.get('grade', '')):
                g3.append((u['uid'], st.get('grade')))
        lines += [f'- {uid}: {g}' for uid, g in g3] or ['_none_']
        lines += ['', '## top latent outliers', '',
                  'See `synthesis/latent_all.csv`; ranking is `python/latent_pca.py`.',
                  '', '## honest ceilings', '',
                  '- Single-leg units cap at I2 (AGENTS.md rule 4).',
                  '- Power-only (filterbank/HDF5) data gets the spectral subset only.',
                  '- pulsar_fold PERIODIC verdicts are ADVISORY: the gate is known',
                  '  miscalibrated on full-length 2-bit channels (catalog: PSR_J2326).',
                  '- Voyager excluded by request; W75N remains QUARANTINED.']
        with open(os.path.join(self.cdir, 'NOVELTY.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    def write_campaign_md(self):
        n = len(self.units)
        done = sum(1 for u in self.units
                   if self.state['units'].get(u['uid'], {}).get('phase') in
                   ('full', 'univ'))
        lines = [f'# CAMPAIGN {self.a.name}', '',
                 f'started: {self.state.get("started")}  '
                 f'elapsed: {(time.time() - self.t0) / 60:.0f} min', '',
                 f'units: {n}  complete: {done}  '
                 f'deadline: {self.a.deadline_hours} h', '',
                 '## layout', '',
                 '- `STATUS.tsv` — one row per unit: phase, flags, WATCH/CANDIDATE, grade',
                 '- `targets/<unit>/RUN.md` — per-unit entry point',
                 '- `targets/<unit>/REPORT.md` — per-unit result with receipts',
                 '- `EXCLUSIONS.tsv` — every file deliberately NOT scanned + reason',
                 '- `NOVELTY.md` — the only place that collects candidate/grade hits',
                 '- `synthesis/` — latent ranking, catalog rebuild, corpus DB log', '',
                 '## read order for an analyst', '',
                 '1. `START_HERE.md`',
                 '2. `STATUS.tsv` (find rows with WATCH/CANDIDATE or I3+)',
                 '3. those units\' `REPORT.md` + `veto_p*.log` + `cadence.json`',
                 '4. `NOVELTY.md` for the cross-unit view',
                 '5. `synthesis/latent_all.csv` for corpus outliers', '']
        with open(os.path.join(self.cdir, 'CAMPAIGN.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    def write_start_here(self):
        lines = [f'# START HERE — {self.a.name}', '',
                 f'Unattended campaign, launched {self.state.get("started")}.',
                 f'Everything bulk is under this folder (physically on D:).', '',
                 '## what this is', '',
                 'A full battery over the not-yet-scanned radio backlog from',
                 '`catalog.tsv` (Voyager excluded by request). One folder per',
                 'ON/OFF unit under `targets/`.', '',
                 '## read in this order', '',
                 '1. `STATUS.tsv` — unit, phase, flags, WATCH/CANDIDATE, grade',
                 '2. `NOVELTY.md` — anything above BLOCK, with proof links',
                 '3. `targets/<unit>/RUN.md` — start of any unit',
                 '4. `targets/<unit>/REPORT.md` — the unit result + top slices table',
                 '5. `EXCLUSIONS.tsv` — what was skipped and why (never silent)',
                 '6. `synthesis/` — latent outliers + catalog rebuild logs',
                 '',
                 '## conventions', '',
                 '- `scan_*` = first sieve (mvp_scan), `struct_*` = +comb/nongauss,',
                 '  `evidence.csv` = persistence/multichan, `veto_*` = disposition,',
                 '  `cadence.json` = the only WATCH->CANDIDATE gate.',
                 '- A unit is `full` when REPORT.md exists. `sweep`-only units are',
                 '  honest negatives with receipts, not failures.',
                 '- Per AGENTS.md: no CANDIDATE from a single file; single-leg',
                 '  units cap at I2.',
                 '',
                 '## control', '',
                 '- master log: `_campaign/master.log`',
                 '- heartbeat: `_campaign/HEARTBEAT.txt`',
                 '- state: `_campaign/state.json` (resume is automatic)',
                 '- prove gate: `_campaign/PROVE_GATE.log`',
                 '']
        with open(os.path.join(self.cdir, 'START_HERE.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    # ------------------------------------------------------------------ go --
    def go(self):
        if self.a.phase in ('all', 'plan', 'sweep', 'full', 'deep', 'univ'):
            files = self.select()
            self.units = self.build_units(files)
            self.only = set(x for x in self.a.only.split(',') if x)
            self.log(f'selected {len(files)} files -> {len(self.units)} units '
                     f'({len(self.exclusions)} excluded)')
            self.write_plan()
            self.write_start_here()
            self.write_campaign_md()

        if self.a.phase in ('all', 'sweep', 'full'):
            for u in self.units:
                if u['power'] or (self.only and u['uid'] not in self.only):
                    continue
                self.heartbeat('sweep', u['uid'])
                try:
                    flags = self.sweep_unit(u)
                    self.log(f'{u["uid"]}: sweep done ({flags} flags)')
                except Exception as e:
                    self.log(f'{u["uid"]}: sweep FAILED {type(e).__name__}: {e}')
                    self.state['units'].setdefault(u['uid'], {})['note'] = \
                        f'sweep error: {e}'

        if self.a.phase in ('all', 'full'):
            for u in self.units:
                if u['power'] or (self.only and u['uid'] not in self.only):
                    continue
                st = self.state['units'].get(u['uid'], {})
                if st.get('phase') in ('full',):
                    continue
                if self.past_deadline():
                    self.log('DEADLINE reached: stopping full phase')
                    break
                self.heartbeat('full', u['uid'])
                try:
                    self.full_unit(u)
                    self.log(f'{u["uid"]}: full done '
                             f'(flags={self.state["units"][u["uid"]].get("full_flags")} '
                             f'WATCH={self.state["units"][u["uid"]].get("watch")} '
                             f'CAND={self.state["units"][u["uid"]].get("candidate")})')
                except Exception as e:
                    self.log(f'{u["uid"]}: full FAILED {type(e).__name__}: {e}')
                    self.log(traceback.format_exc())
                    self.state['units'].setdefault(u['uid'], {})['note'] = \
                        f'full error: {e}'
                    self.save_state()

        if self.a.phase in ('all', 'univ'):
            for u in self.units:
                if not u['power'] or (self.only and u['uid'] not in self.only):
                    continue
                self.heartbeat('univ', u['uid'])
                try:
                    self.univ_unit(u)
                    self.log(f'{u["uid"]}: univ done')
                except Exception as e:
                    self.log(f'{u["uid"]}: univ FAILED {type(e).__name__}: {e}')

        if self.a.phase in ('all', 'deep'):
            cands = self.deep_candidates(cap_each=self.a.deep_cap)
            self.log(f'deep: {len(cands)} top candidates selected')
            for i, (sc, u, leg, b, c, pol, src) in enumerate(
                    cands[:self.a.deep_max]):
                # Deep runs past the heavy-phase deadline by design: it is
                # cheap per slice (~1 min) and is the only route to structure
                # evidence on already-flagged slices.
                self.heartbeat(f'deep {i + 1}/{min(len(cands), self.a.deep_max)}',
                               u['uid'])
                try:
                    self.deep_unit(sc, u, leg, b, c, pol, src)
                except Exception as e:
                    self.log(f'deep {u["uid"]} b{b}ch{c}: FAILED {e}')

        if self.a.phase in ('all', 'synthesis'):
            self.heartbeat('synthesis')
            try:
                self.synthesis()
            except Exception as e:
                self.log(f'synthesis FAILED {type(e).__name__}: {e}')
                self.log(traceback.format_exc())

        self.state['finished'] = now()
        self.save_state()
        self.heartbeat('done')
        self.log('CAMPAIGN COMPLETE')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--catalog', default='catalog.tsv')
    ap.add_argument('--campaign', default='runs/campaigns/2026-09-21_mega')
    ap.add_argument('--name', default='2026-09-21_mega')
    ap.add_argument('--phase', default='all',
                    choices=['all', 'plan', 'sweep', 'full', 'deep', 'univ',
                             'synthesis'])
    ap.add_argument('--deadline-hours', type=float, default=16.0)
    ap.add_argument('--sweep-chans', default='0,8,16,24,32,40,48,56')
    ap.add_argument('--full-pols', default='0,1')
    ap.add_argument('--fam-trig', type=float, default=3.0)
    ap.add_argument('--min-fam-xeno', type=float, default=4.0)
    ap.add_argument('--struct-topk', type=int, default=600)
    ap.add_argument('--persist-min', type=int, default=2)
    ap.add_argument('--deep-cap', type=int, default=4,
                    help='candidates per unit (ranked)')
    ap.add_argument('--deep-max', type=int, default=40,
                    help='global cap on per-slice deep analyses')
    ap.add_argument('--skip-fold', action='store_true',
                    help='skip pulsar_fold (gate known miscalibrated)')
    ap.add_argument('--complete-partial', action='store_true')
    ap.add_argument('--only', default='', help='comma list of unit uids')
    a = ap.parse_args()
    if a.name == '2026-09-21_mega' and a.campaign != \
            'runs/campaigns/2026-09-21_mega':
        a.name = os.path.basename(a.campaign.rstrip('/\\'))
    Campaign(a).go()


if __name__ == '__main__':
    main()
