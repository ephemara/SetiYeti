"""mvp_scan.py - SetiYeti first full-file MVP sweep (the engineer loop).
Stride: configurable channels x block range, pol0. Per slice:
  seti_slice (1 block) -> fam_scan (Y2/Y4) + direct spectrum peak -> gate:
  VM sandbox (sign/diff bits) ONLY on flagged slices.
Logs every slice to hits.csv; prints block progress + final hit table.
Usage:
  python mvp_scan.py --raw data/blc2....raw --b0 0 --b1 48 --chans 0,8,16,24,32,40,48,56
"""
import argparse, subprocess, os, sys, csv, re
import numpy as np

FS = 2929687.5
SPEC_LINE = 5.0   # actionable narrow-line trigger (turboSETI analogue)
SPEC_HUMP = 2.5   # wide-hump note threshold
FAM_TRIG = 3.0    # calibrated: noise max ~2.1x at SEG=32768

def run(exe, *args):
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    return r

def direct_peak(x, nfft=4096):
    nrows = len(x)//nfft
    if nrows < 4: return 0.0, -1
    W = np.hamming(nfft).astype(np.float32)
    spec = np.abs(np.fft.rfft((x[:nrows*nfft].reshape(nrows, nfft)*W), axis=1))**2
    avg = spec.mean(axis=0); med = np.median(avg)
    k = int(np.argmax(avg[1:-1]))+1
    return float(avg[k]/med), k

def parse_fam(out):
    peaks = []  # (tag, hz, ratio)
    for line in out.splitlines():
        m = re.search(r'^(Y2|Y4) peak\s+\d+\s+bin=\d+\s+alpha=\s*([\d.]+) Hz\s+ratio=\s*([\d.]+)x', line)
        if m: peaks.append((m.group(1), float(m.group(2)), float(m.group(3))))
    return peaks

def pack_bits(bits):
    out = np.zeros((len(bits)+7)//8, dtype=np.uint8)
    for i, b in enumerate(bits):
        if b: out[i >> 3] |= (1 << (7-(i & 7)))
    return out

def vm_score(vm_exe, f32path, workdir):
    x = np.fromfile(f32path, dtype=np.float32)
    N = min(len(x), 200000)
    seg = x[:N]
    s = np.sign(seg); s[s == 0] = 1
    diff = np.concatenate([[1], s[1:]*s[:-1]]) < 0
    res = {}
    for name, bits in [('sign', (seg > 0).astype(np.uint8)), ('diff', diff.astype(np.uint8))]:
        p = os.path.join(workdir, f'vm_{os.path.basename(f32path)}.{name}.bin')
        pack_bits(bits).tofile(p)
        r = run(vm_exe, p)
        m = re.search(r'combined=([\d.]+)\s+(\S+)', r.stdout)
        res[name] = (float(m.group(1)) if m else 0.0, m.group(2) if m else '?', r.stdout)
        os.remove(p)
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True)
    ap.add_argument('--b0', type=int, default=0)
    ap.add_argument('--b1', type=int, default=48)
    ap.add_argument('--chans', default='0,8,16,24,32,40,48,56')
    ap.add_argument('--pol', type=int, default=0)
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--out', default='hits.csv')
    a = ap.parse_args()
    ext = '.exe' if os.name == 'nt' else ''
    sl = os.path.join(a.root, 'c', 'seti_slice'+ext)
    fam = os.path.join(a.root, 'c', 'fam_scan'+ext)
    vm = os.path.join(a.root, 'c', 'vm_sandbox'+ext)
    chans = [int(c) for c in a.chans.split(',') if c != '']
    work = os.path.join(a.root, 'data', 'mvp_tmp')
    os.makedirs(work, exist_ok=True)
    csvp = os.path.join(a.root, a.out)
    # unique temp prefix per raw file so parallel scans can't clobber each other
    tag = re.sub(r'[^A-Za-z0-9]+', '_', os.path.basename(a.raw))[:48]
    new = not os.path.exists(csvp)
    cf = open(csvp, 'a', newline='')
    cw = csv.writer(cf)
    if new: cw.writerow(['block', 'chan', 'pol', 'spec_ratio', 'spec_bin',
                         'fam_best', 'fam_hz', 'fam_tag', 'vm_sign', 'vm_diff', 'verdict'])
    seen = set()
    if not new:
        with open(csvp) as f:
            for r in csv.DictReader(f):
                seen.add((r['block'], r['chan'], r.get('pol', '0')))
        # note: keys are (block, chan, pol) strings
    total = (a.b1-a.b0+1)*len(chans)
    done = hits = 0
    for b in range(a.b0, a.b1+1):
        for ch in chans:
            if (str(b), str(ch), str(a.pol)) in seen:
                done += 1
                continue
            tmp = os.path.join(work, f'{tag}_b{b}_ch{ch}.f32')
            r = run(sl, a.raw, str(ch), tmp, '1', '--pol', str(a.pol), '--start', str(b))
            if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) < 1000000:
                print(f'[skip] b{b} ch{ch}: no data (short file?)', flush=True)
                if os.path.exists(tmp): os.remove(tmp)
                continue
            x = np.fromfile(tmp, dtype=np.float32)
            # data-quality gates (mvp_scan): quarantine broken digitizer output.
            # blc6 lesson: dark 8-bit lane looks Gaussian but spans 21 of 256
            # codes (range 83, distinct 21) vs healthy blc4 (~200 range, 150+
            # distinct). 2-bit data (range ~6.7, 4 codes) is exempt by range.
            v = x[:100000]
            vrange = float(v.max()-v.min())
            distinct = int(len(np.unique(v)))
            if vrange > 15 and distinct < 64:
                cw.writerow([b, ch, a.pol, '0', '-1', '0', '0', '-', '', '',
                             f'QUARANTINE:dark-lane range={vrange:.0f} distinct={distinct}'])
                cf.flush()
                os.remove(tmp)
                done += 1
                continue
            sr, sb = direct_peak(x)
            fr = run(fam, tmp, str(FS), '32768', '6')
            peaks = parse_fam(fr.stdout)
            fb = max([p[2] for p in peaks], default=0.0)
            frow = next((p for p in peaks if p[2] == fb), ('-', 0.0, 0.0))
            flag = (sr >= SPEC_HUMP) or (fb >= FAM_TRIG)
            vs = vd = ''
            verdict = 'clean'
            if sr >= SPEC_LINE: verdict = 'SPECTRAL-LINE'
            elif fb >= FAM_TRIG: verdict = 'FAM-HIT'
            elif sr >= SPEC_HUMP: verdict = 'hump-note'
            if flag:
                hits += 1
                res = vm_score(vm, tmp, work)
                vs = f'{res["sign"][0]:.2f}/{res["sign"][1]}'
                vd = f'{res["diff"][0]:.2f}/{res["diff"][1]}'
                if 'CANDIDATE' in (res['sign'][1]+res['diff'][1]): verdict += '+VM-WATCH'
            cw.writerow([b, ch, a.pol, f'{sr:.2f}', sb, f'{fb:.2f}',
                         f'{frow[1]:.0f}', frow[0], vs, vd, verdict])
            cf.flush()
            os.remove(tmp)
            done += 1
        print(f'[mvp] block {b}: done {done}/{total}, hits {hits}', flush=True)
    cf.close()
    print(f'[mvp] DONE blocks {a.b0}-{a.b1} chans {chans}: {done} slices, {hits} flagged -> {csvp}')

if __name__ == '__main__':
    main()
