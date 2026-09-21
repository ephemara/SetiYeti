#!/usr/bin/env python
"""vm_dive.py - targeted alien-code battery over hot slices + controls.
Extracts 1-block .f32 per (file,block,chan,pol), runs:
  fam_scan (top peaks), comb_scan (comb/thicket/nongauss),
  xeno_scan (microscopic), bitslice sign/diff -> vm_sandbox (legacy Golay/SUBLEQ)
  + xvm_sandbox (6-machine) full stdout.
Prints one block per slice with every RESULT line verbatim.
"""
import os, subprocess, sys
import numpy as np

ROOT = os.getcwd()
EXT = '.exe' if os.name == 'nt' else ''
SL = os.path.join(ROOT, 'c', 'seti_slice' + EXT)
FAM = os.path.join(ROOT, 'c', 'fam_scan' + EXT)
COMB = os.path.join(ROOT, 'c', 'comb_scan' + EXT)
XENO = os.path.join(ROOT, 'c', 'xeno_scan' + EXT)
VM = os.path.join(ROOT, 'c', 'vm_sandbox' + EXT)
XVM = os.path.join(ROOT, 'c', 'xvm_sandbox' + EXT)
WORK = os.path.join(ROOT, 'data', 'mvp_tmp')
os.makedirs(WORK, exist_ok=True)

T15 = 'data/blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.raw'
T16 = 'data/blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw'
T17 = 'data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw'
K10 = 'data/blc44_guppi_59103_01984_DIAG_KEPLER-160_0010.0000.raw'
K11 = 'data/blc44_guppi_59103_02170_DIAG_KEPLER-160_OFF_0011.0000.raw'

TARGETS = [
    # (label, file, block, chan, pol)
    ('T15-ON b2/ch12 (new 7.6x)', T15, 2, 12, 0),
    ('T15-ON b4/ch44 179Hz-hum', T15, 4, 44, 0),
    ('T15-ON b4/ch44 179Hz-hum p1', T15, 4, 44, 1),
    ('T15-ON b4/ch12 1520Hz', T15, 4, 12, 0),
    ('T16-OFF b1/ch57 BURST p0', T16, 1, 57, 0),
    ('T16-OFF b1/ch57 BURST p1', T16, 1, 57, 1),
    ('T16-OFF b1/ch57 BURST p2', T16, 1, 57, 2),
    ('T16-OFF b1/ch57 BURST p3', T16, 1, 57, 3),
    ('T16-OFF b1/ch56', T16, 1, 56, 1),
    ('T17-ON b2/ch56 31x@268', T17, 2, 56, 0),
    ('T17-ON b3/ch4 20x@1520', T17, 3, 4, 0),
    ('T17-ON b0/ch56 10x@179', T17, 0, 56, 0),
    ('T17-ON b1/ch26 7x@1073', T17, 1, 26, 0),
    ('T17-ON b2/ch48 7x@805', T17, 2, 48, 0),
    ('T17-ON b0/ch24 4.6x@179', T17, 0, 24, 0),
    ('K10-ON b21/ch52 p0', K10, 21, 52, 0),
    ('K10-ON b21/ch52 p1', K10, 21, 52, 1),
    ('K10-ON b88/ch52 626Hz', K10, 88, 52, 0),
    ('K10-ON b71/ch53 WATCH', K10, 71, 53, 0),
    ('K10-ON b1/ch56', K10, 1, 56, 2),
    ('K11-OFF b55/ch52', K11, 55, 52, 0),
    ('K11-OFF b35/ch56 mega', K11, 35, 56, 0),
    ('K11-OFF b102/ch56 mega', K11, 102, 56, 1),
    ('K11-OFF b48/ch25 prot', K11, 48, 25, 2),
    ('K11-OFF b4/ch57', K11, 4, 57, 2),
    ('CTRL T15 b0/ch20', T15, 0, 20, 0),
    ('CTRL T17 b0/ch20', T17, 0, 20, 0),
    ('CTRL K10 b0/ch20', K10, 0, 20, 0),
    ('CTRL K11 b0/ch20', K11, 0, 20, 0),
]

def run(*args, timeout=300):
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'

def pack(bits):
    return np.packbits(np.asarray(bits, dtype=np.uint8), bitorder='big')

for i, (label, raw, b, ch, pol) in enumerate(TARGETS):
    print(f'=== [{i}] {label} ===')
    f32 = os.path.join(WORK, f'dive_{i}.f32')
    rc, so, se = run(SL, os.path.join(ROOT, raw), str(ch), f32, '1', '--pol', str(pol), '--start', str(b))
    if rc != 0 or not os.path.exists(f32):
        print(f'  EXTRACT FAIL rc={rc} {se[:200]}')
        continue
    x = np.fromfile(f32, dtype=np.float32)
    print(f'  [slice] n={len(x)} rms={x.std():.3f} mean={x.mean():+.4f} maxz={np.abs((x-x.mean())/x.std()).max():.1f}')
    rc, so, _ = run(FAM, f32, '2929687.5', '32768', '6', '-')
    for ln in so.splitlines():
        if 'peak' in ln or 'RESULT' in ln:
            print(f'  [fam] {ln.strip()}')
    rc, so, _ = run(COMB, f32, '2929687.5')
    for ln in so.splitlines():
        if ln.startswith('RESULT'):
            print(f'  [comb] {ln.strip()}')
    rc, so, _ = run(XENO, f32, '2929687.5')
    for ln in so.splitlines():
        if ln.startswith('RESULT'):
            print(f'  [xeno] {ln.strip()}')
    N = min(len(x), 200000)
    seg = x[:N]
    s = np.sign(seg); s[s == 0] = 1
    for name, bits in (('sign', (seg > 0).astype(np.uint8)), ('diff', (np.concatenate([[1], s[1:] * s[:-1]]) < 0).astype(np.uint8))):
        p = os.path.join(WORK, f'dive_{i}_{name}.bin')
        try:
            pack(bits).tofile(p)
            ones = float(bits.mean())
            rc, so, _ = run(VM, p)
            vm1 = ' '.join(l.strip() for l in so.splitlines() if l.strip())[:220]
            print(f'  [vm:{name} ones={ones:.3f}] {vm1}')
            rc, so, _ = run(XVM, p)
            xvm1 = ' '.join(l.strip() for l in so.splitlines() if l.strip())[:400]
            print(f'  [xvm:{name}] {xvm1}')
        finally:
            try: os.remove(p)
            except OSError: pass
    try: os.remove(f32)
    except OSError: pass
    sys.stdout.flush()
print('DIVE DONE')
