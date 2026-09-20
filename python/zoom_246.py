"""zoom_246.py - SetiYeti 245.9Hz inquest: sub-Hz zoom, cross-pol, harmonics.
1. Zoom FFT (zero-padded x4, Hann/Blackman-Harris/rect): razor line vs sidebands.
2. Same extraction on pol 0..3: single-pol screamer = hardware leak.
4. Harmonic table: 2x, 0.5x, 60/50Hz grids, DC-residual relation, clock rationalization.
"""
import subprocess, os
import numpy as np

RAW = 'data/blc4_guppi_57388_HIP113357_0014.0013.raw'
FS = 2929687.5
EXT = '.exe' if os.name == 'nt' else ''
SL = './c/seti_slice'+EXT
CHAN, TARGET = 32, 245.87

def sl(pol):
    p = 'data/zoom_p%d.f32' % pol
    subprocess.run([SL, RAW, str(CHAN), p, '1', '--pol', str(pol), '--start', '0'],
                   capture_output=True)
    return np.fromfile(p, dtype=np.float32)

def bhwin(n):
    return np.blackman(n)

WINS = {'rect': None, 'hann': np.hanning, 'bh': bhwin}
pols = {p: sl(p) for p in range(4)}
N = len(pols[0])
ZP = 1
while (1 << ZP) < N*4: ZP += 1
NF = 1 << ZP
print('N=%d zero-padded FFT=%d bin=%.2fHz' % (N, NF, FS/NF))

def zoom(y, wname):
    w = np.ones(N) if WINS[wname] is None else WINS[wname](N)
    yw = (y-y.mean())*w
    S = np.abs(np.fft.rfft(yw, NF))**2
    fr = np.fft.rfftfreq(NF, 1/FS)
    m = (fr > 150) & (fr < 350)
    idx = np.where(m)[0]
    i = int(np.argmax(S[m]))
    fpk = float(fr[idx][i])
    pk = float(S[idx][i])
    med = float(np.median(S[m]))
    ii = idx[i]
    half = (S[ii]+med)/2
    lo = ii
    while lo > 0 and S[lo] > half: lo -= 1
    hi = ii
    while hi < len(S)-1 and S[hi] > half: hi += 1
    step = int(40/(FS/NF))
    cand = []
    for j in range(max(1, ii-step), min(len(S), ii+step)):
        if j != ii and S[j] > 3*med and S[j] >= S[j-1] and S[j] >= S[j+1]:
            cand.append((round(float(fr[j]), 1), round(float(S[j]/med), 1)))
    return fpk, pk/med, (hi-lo)*(FS/NF), cand

print('--- test1: line shape per window (pol0 Y2) ---')
y2 = pols[0]*pols[0]
for w in ('rect', 'hann', 'bh'):
    f, r, wd, sb = zoom(y2, w)
    sbs = 'none' if not sb else sb
    print('  %s peak=%.2fHz ratio=%.1fx width=%.1fHz sidebands=%s' % (w, f, r, wd, sbs))

print('--- test2: cross-polarization at target band ---')
for p in range(4):
    y = pols[p]*pols[p]
    S = np.abs(np.fft.rfft((y-y.mean())*np.hanning(N), NF))**2
    fr = np.fft.rfftfreq(NF, 1/FS)
    m = (fr > 150) & (fr < 350)
    idx = np.where(m)[0]
    bi = int(np.argmax(S[m]))
    print('  pol%d: peak=%.2fHz ratio=%.1fx' % (p, float(fr[idx][bi]), float(S[idx][bi]/np.median(S[m]))))

print('--- test4: harmonic and grid table (pol0, hann) ---')
y = (y2-y2.mean())*np.hanning(N)
S = np.abs(np.fft.rfft(y, NF))**2
fr = np.fft.rfftfreq(NF, 1/FS)
med_all = float(np.median(S[(fr > 1000) & (fr < 100000)]))
probes = [('sub 0.5x', TARGET/2), ('fund', TARGET), ('2x', TARGET*2),
          ('3x', TARGET*3), ('mains4x60', 240.0), ('mains5x50', 250.0),
          ('dc-res', 44.70), ('dc-res4x', 178.8)]
for name, f0 in probes:
    i = int(np.argmin(abs(fr-f0)))
    print('  %s %.2fHz -> %.1fx' % (name, f0, S[i]/med_all))
print('--- clock rationalization f*2^k ---')
for clk, name in [(256e6, 'FPGA256'), (187.5e6, 'BW187.5'), (800e6, 'ADC800'),
                  (10e6, 'REF10'), (FS, 'FSchan')]:
    k = int(round(np.log2(clk/TARGET)))
    print('  %s: %.3e/2^%d = %.2fHz (err %.2fHz)' % (name, clk, k, clk/2**k, abs(clk/2**k-TARGET)))
for p in range(4):
    os.remove('data/zoom_p%d.f32' % p)
