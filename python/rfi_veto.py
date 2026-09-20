"""rfi_veto.py - SetiYeti Earth-blocker: auto-disposition every flag as
BLOCK:earth-likely / WATCH / CANDIDATE with machine-readable reasons.
Inputs: hits.csv + evidence.csv (block,chan,persist,multichan from vet_coinc).
State: rfi_catalog.json - every processed feature logged; recurrences auto-BLOCK.
Physics baked in:
  - ITU allocations over 9187.5-9375 MHz (this file): 9200-9300 maritime
    radionav+radiolocation, 9300-9500 aeronautical/maritime radionav. The whole
    band is radar country -> baseline earth prior on everything.
  - Cyclic-frequency zones: 1Hz-2kHz = rotation-powered astrophysics band
    (pulsars/magnetars, breakup limit); 100kHz-5MHz = electronics zone
    (clocks, modulators, radar PRF harmonics) -> earth-leaning.
Usage: python rfi_veto.py --hits hits.csv --evidence evidence.csv
"""
import argparse, csv, json, os

FLO = 9187.5  # MHz, file bottom
CHBW = 2.9296875
ALLOC = [  # (f0,f1 MHz,label) covering this file's range
    (9187.5, 9200.0, 'aeronautical-radionav fringe'),
    (9200.0, 9300.0, 'maritime-radionav + radiolocation RADAR'),
    (9300.0, 9375.0, 'aeronautical/maritime radionav + radiolocation RADAR'),
]
CAT = 'rfi_catalog.json'

def chan_freq(ch): return FLO + (ch+0.5)*CHBW

def alloc_tag(f):
    for a, b, l in ALLOC:
        if a <= f < b: return l
    return 'unallocated'

def load_cat():
    if os.path.exists(CAT):
        return json.load(open(CAT))
    return {'features': []}

def save_cat(c): json.dump(c, open(CAT, 'w'), indent=1)

def sig_of(row):
    return f"{row['fam_tag']}:{float(row['fam_hz']):.0f}Hz"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hits', required=True)
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--target', default='', help='dataset tag; evidence keyed per-target')
    a = ap.parse_args()
    ev = {}
    for r in csv.DictReader(open(a.evidence)):
        key = (r.get('target', ''), r['block'], r['chan'])
        ev[key] = r
    cat = load_cat()
    n_block = n_watch = n_cand = 0
    for row in csv.DictReader(open(a.hits)):
        if row['verdict'] == 'clean': continue
        b, ch = row['block'], row['chan']
        f = chan_freq(int(ch))
        alpha = float(row['fam_hz'] or 0)
        e = ev.get((a.target, b, ch), {})
        persist = str(e.get('persist', '')).strip() == '1'
        multi = str(e.get('multichan', '')).strip() == '1'
        score, reasons = 0.0, []
        reasons.append(f'band {f:.1f}MHz [{alloc_tag(f)}]')
        score += 0.20; reasons.append('+0.20 radar-allocation country')
        if 1e5 <= alpha <= 5e6:
            score += 0.25; reasons.append(f'+0.25 alpha {alpha:.0f}Hz in electronics zone')
        elif 1 <= alpha <= 2000:
            score -= 0.30; reasons.append(f'-0.30 alpha {alpha:.0f}Hz in rotation-astro band')
        if not persist:
            score += 0.30; reasons.append('+0.30 transient (absent over full span)')
        else:
            score -= 0.20; reasons.append('-0.20 persistent across span')
        if not multi:
            score += 0.15; reasons.append('+0.15 single-channel only')
        else:
            # same-block multi-CHANNEL coincidence = backend/common-mode local
            # (power, clocks, digitizer). NOTE: this is the opposite of ON-OFF
            # multi-POINTING coincidence (different sky = celestial). ON-OFF gets
            # its own sky-leaning rule when cadence pairs arrive; until then,
            # same-time multifreq = the building humming to itself.
            score += 0.35; reasons.append('+0.35 common-mode across channels = backend/local')
        vm = (row.get('vm_sign', '') + row.get('vm_diff', ''))
        if 'CANDIDATE' in vm:
            score -= 0.40; reasons.append('-0.40 VM structure flag')
        elif 'noise-like' in vm:
            score += 0.10; reasons.append('+0.10 VM noise-like')
        # catalog recurrence: same signature within 2 kHz seen before -> hard BLOCK
        sig = sig_of(row)
        rec = [fe for fe in cat['features']
               if fe['sig'].split(':')[0] == sig.split(':')[0]
               and abs(float(fe['sig'].split(':')[1][:-2]) - alpha) < 2000]
        disp = None
        if rec:
            disp = 'BLOCK:earth-likely'
            reasons.append(f'HARD-BLOCK recurring signature {sig} (seen x{len(rec)})')
        if disp is None:
            if not persist and 'CANDIDATE' not in vm and float(row.get('spec_ratio', 0)) < 5:
                pass  # needs all three legs for candidacy; falls through to score
            if score >= 0.50: disp = 'BLOCK:earth-likely'
            elif score >= 0.20: disp = 'WATCH'
            else: disp = 'CANDIDATE'
            if disp == 'CANDIDATE' and not (persist and ('CANDIDATE' in vm or multi)):
                disp = 'WATCH'
                reasons.append('capped: candidacy requires persistence + structure/coincidence')
        print(f"[veto] b{b}/ch{ch} {sig} score={score:.2f} -> {disp}")
        for r in reasons: print(f'         - {r}')
        if disp.startswith('BLOCK'): n_block += 1
        elif disp == 'WATCH': n_watch += 1
        else: n_cand += 1
        if not any(fe['sig'] == sig and fe['block'] == b and fe['chan'] == ch
                  for fe in cat['features']):
            cat['features'].append({'sig': sig, 'block': b, 'chan': ch,
                                    'freq_mhz': round(f, 2), 'disp': disp})
    save_cat(cat)
    print(f'[veto] BLOCK={n_block} WATCH={n_watch} CANDIDATE={n_cand} | catalog={len(cat["features"])} features')

if __name__ == '__main__':
    main()
