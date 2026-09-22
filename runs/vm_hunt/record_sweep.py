#!/usr/bin/env python
"""record_sweep.py - hunt the ch44 pattern across the whole scientific record.
Pattern components: (a) hum-family alpha (179/268/358/447/536/626/715/805/894/
1073/1162/1431/1699/2861 Hz), (b) strong (fam>=8), (c) chan 44, (d) alpha~=626,
(e) persistence (same chan+alpha, many blocks), (f) 4-pol same-alpha coincidence.
Walks every scan CSV under runs/ + root hits*.csv.
"""
import os, re, csv, json
from collections import defaultdict

HUM = [178.81, 268.22, 357.63, 447.04, 536.44, 625.85, 715.26, 804.66,
       894.07, 1072.88, 1162.29, 1341.10, 1430.51, 1698.73, 2056.36, 2861.02]
BIN = 89.406  # SEG=32768 grid

def is_hum(a):
    try: a = float(a)
    except (ValueError, TypeError): return False
    return any(abs(a - h) < BIN * 0.6 for h in HUM)

def near(a, target, tol=60.0):
    try: return abs(float(a) - target) < tol
    except (ValueError, TypeError): return False

files = []
for dp, _, fns in os.walk('runs'):
    for fn in fns:
        if fn.endswith('.csv') and ('scan' in fn or 'hits' in fn or 'trap' in fn
                                    or 'kep' in fn or 'baseline' in fn or 't1' in fn):
            files.append(os.path.join(dp, fn))
for fn in ('hits.csv', 'hits_hip.csv', 'hits_voyager.csv'):
    if os.path.exists(fn):
        files.append(fn)
print(f'[sweep] {len(files)} CSVs')

strong_hum, ch44_rows, a626_rows, y2_rows = [], [], [], []
persist = defaultdict(list)  # (file,chan,alpha_bin) -> blocks
pol4 = defaultdict(list)     # (dir,block,chan,alpha_bin) -> pols
for fp in files:
    try:
        rows = list(csv.DictReader(open(fp, errors='replace')))
    except Exception:
        continue
    if not rows or 'fam_best' not in rows[0]:
        continue
    for r in rows:
        v = r.get('verdict', 'clean')
        if 'FAM-HIT' not in v and 'SPECTRAL' not in v:
            continue
        try: fb = float(r.get('fam_best') or 0)
        except ValueError: continue
        ahz = r.get('fam_hz', '0')
        ch = r.get('chan', '?')
        blk = r.get('block', '?')
        pol = r.get('pol', '?')
        tag = r.get('fam_tag', '')
        abin = None
        try: abin = round(float(ahz) / BIN)
        except (ValueError, TypeError): pass
        base = (fp, blk, ch, pol, fb, ahz, tag, v)
        if 'FAM-HIT' in v and is_hum(ahz) and fb >= 8:
            strong_hum.append(base)
        if str(ch) == '44' and 'FAM-HIT' in v:
            ch44_rows.append(base)
        if near(ahz, 625.85) and 'FAM-HIT' in v:
            a626_rows.append(base)
        if tag == 'Y2' and fb >= 4 and 'FAM-HIT' in v:
            y2_rows.append(base)
        if 'FAM-HIT' in v and abin is not None:
            persist[(fp, ch, abin)].append(blk)
            d = 'ON' if ('_on_' in fp or 'trap_on' in fp or 'kep_on' in fp
                         or '0015' in fp or '0010' in fp or 't17' in fp) else (
                'OFF' if ('off' in fp.lower() or '0016' in fp or '0011' in fp) else '?')
            pol4[(d, blk, ch, abin)].append(pol)

print(f'\n== strong hum-family FAM>=8x: {len(strong_hum)} ==')
for r in sorted(strong_hum, key=lambda r: -r[4])[:25]:
    print('  %.1fx %sHz %s %s' % (r[4], r[5], r[7][:9], r[0].replace('runs/','')[:44]), 'b%s/ch%s/p%s' % (r[1], r[2], r[3]))
print(f'\n== chan-44 FAM rows anywhere: {len(ch44_rows)} ==')
for r in sorted(ch44_rows, key=lambda r: -r[4])[:20]:
    print('  %.1fx %sHz %s %s' % (r[4], r[5], r[7][:9], r[0].replace('runs/','')[:44]), 'b%s/p%s' % (r[1], r[3]))
print(f'\n== alpha~=626Hz FAM rows anywhere: {len(a626_rows)} ==')
for r in sorted(a626_rows, key=lambda r: -r[4])[:20]:
    print('  %.1fx ch%s %s %s' % (r[4], r[2], r[7][:9], r[0].replace('runs/','')[:44]), 'b%s/p%s' % (r[1], r[3]))
print(f'\n== Y2 FAM>=4x anywhere (coherent candidates): {len(y2_rows)} ==')
for r in sorted(y2_rows, key=lambda r: -r[4])[:15]:
    print('  %.1fx %sHz ch%s %s' % (r[4], r[5], r[2], r[0].replace('runs/','')[:44]), 'b%s/p%s' % (r[1], r[3]))
print('\n== persistent (same file+chan+alpha, >=6 blocks): ==')
n = 0
for (fp, ch, ab), blks in sorted(persist.items(), key=lambda kv: -len(set(kv[1]))):
    if len(set(blks)) >= 6:
        print('  %s ch%s a~%.0fHz: %d blocks' % (fp.replace('runs/','')[:40], ch, ab * BIN, len(set(blks))))
        n += 1
        if n > 15: break
print('\n== 4-pol same-alpha coincidences (same pointing,block,chan,alpha): ==')
n = 0
for (d, blk, ch, ab), pols in pol4.items():
    if len(set(pols)) >= 3 and '?' not in pols:
        print('  %s b%s ch%s a~%.0fHz pols=%s' % (d, blk, ch, ab * BIN, sorted(set(pols))))
        n += 1
        if n > 20: break
print('\n[sweep] DONE')
