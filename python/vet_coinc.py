"""vet_coinc.py - SetiYeti hit adjudication: time persistence + freq coincidence.
For each FAM flag: (1) full-span (49-block) same-chan FAM at 22Hz resolution -
a stable modulation sharpens, a burst dilutes; (2) same-block neighbor-channel
scan for the same alpha - common across chans = backend clock / broadband event,
isolated = localized burst. Prints a deduction per flag.
"""
import subprocess, os, re, sys
import numpy as np

RAW = 'data/blc2_2bit_guppi_57396_MESSIER031_0056.0002.raw'
FS = 2929687.5
EXT = '.exe' if os.name == 'nt' else ''
SL = './c/seti_slice'+EXT
FAM = './c/fam_scan'+EXT
FLAGS = [(30, 56, 481099.0), (0, 4, 649810.0), (24, 27, 1438469.0)]

def run(*a):
    return subprocess.run(a, capture_output=True, text=True)

def ensure_full(ch):
    p = f'data/full_ch{ch}.f32'
    if os.path.exists(p) and os.path.getsize(p) > 90000000: return p
    parts = []
    for b in range(49):
        t = f'data/vc_b{b}_c{ch}.f32'
        run(SL, RAW, str(ch), t, '1', '--pol', '0', '--start', str(b))
        parts.append(t)
    with open(p, 'wb') as o:
        for t in parts:
            o.write(open(t, 'rb').read()); os.remove(t)
    return p

def fam(path, seg, topk):
    r = run(FAM, path, str(FS), str(seg), str(topk))
    out = []
    for ln in r.stdout.splitlines():
        m = re.search(r'^(Y2|Y4) peak\s+\d+\s+bin=\d+\s+alpha=\s*([\d.]+) Hz\s+ratio=\s*([\d.]+)x', ln)
        if m: out.append((m.group(1), float(m.group(2)), float(m.group(3))))
    return out

for (b0, ch0, al0) in FLAGS:
    print(f'=== flag b{b0}/ch{ch0} alpha={al0:.0f}Hz ===')
    # 1) time persistence over full 8.46 s span
    full = ensure_full(ch0)
    peaks = fam(full, 131072, 12)
    near = [(t, h, r) for (t, h, r) in peaks if abs(h-al0) < 2000]
    top = max(peaks, key=lambda p: p[2]) if peaks else ('-', 0, 0)
    print(f'  full-span: max={top[2]:.2f}x@{top[1]:.0f}Hz | near-flag: '
          + (', '.join(f'{t} {r:.2f}x@{h:.0f}' for t, h, r in near) if near else 'ABSENT'))
    # 2) neighbor channels, same block
    hits = []
    for ch in range(max(0, ch0-6), min(64, ch0+7)):
        t = f'data/vc_n_ch{ch}.f32'
        run(SL, RAW, str(ch), t, '1', '--pol', '0', '--start', str(b0))
        for (tg, h, r) in fam(t, 32768, 6):
            if tg == 'Y2' and abs(h-al0) < 3000 and r > 2.5:
                hits.append((ch, h, r))
        os.remove(t)
    own = [h for h in hits if h[0] == ch0]
    other = [h for h in hits if h[0] != ch0]
    print(f'  neighbors: flagged-chan re-hit={own} | other-chans={other if other else "none"}')
    if near and other:
        print('  DEDUCE: persistent + multi-chan => backend clock / common-mode RFI')
    elif near and not other:
        print('  DEDUCE: persistent + single-chan => stable local carrier (sat/ground), needs ON-OFF')
    elif not near and other:
        print('  DEDUCE: transient + multi-chan => broadband burst (radar/sat glint), diluted over span')
    else:
        print('  DEDUCE: transient + single-chan => localized burst OR noise excursion; no follow-up basis')
