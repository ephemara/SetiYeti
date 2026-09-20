"""neural_track.py - SetiYeti C-neural: learned continuous trajectory field.
MLP f_theta(t) [1-32-16-1, tanh, bounded to bin range] trained with hand-rolled
Adam to ride waterfall energy: loss = -mean(Z along path) + smoothness penalty.
Multi-start (Viterbi path + flat center), best energy wins. No polynomial order
assumed: drift, jerk, hops all expressible. Reuses jerk_scan waterfall/Z/synth.
Usage: --prove | --f32 PATH
"""
import argparse, os
import numpy as np
from jerk_scan import stft_power, robust_z, quantize, synth_chirp, fit_motion, viterbi, FS

def mklp(h1=32, h2=16, seed=0):
    r = np.random.default_rng(seed)
    return {'W1': r.normal(0, 1.0, (1, h1)), 'b1': np.zeros(h1),
            'W2': r.normal(0, np.sqrt(1/h1), (h1, h2)), 'b2': np.zeros(h2),
            'W3': r.normal(0, 0.5, (h2, 1)), 'b3': np.zeros(1)}

def out_of(P, t, B):
    z1 = t@P['W1']+P['b1']; a1 = np.tanh(z1)
    z2 = a1@P['W2']+P['b2']; a2 = np.tanh(z2)
    u = (a2@P['W3']+P['b3']).ravel()
    return (z1, a1, z2, a2, u, (B/2*(1+np.tanh(u))).ravel())

def backprop(P, t, B, do_bins, cache):
    z1, a1, z2, a2, u, o = cache
    th = np.tanh(u)
    du = (do_bins*(B/2)*(1-th*th))[:, None]
    gW3 = a2.T@du; gb3 = du.sum(0)
    da2 = (du@P['W3'].T)*(1-a2**2)
    gW2 = a1.T@da2; gb2 = da2.sum(0)
    da1 = (da2@P['W2'].T)*(1-a1**2)
    gW1 = t.T@da1; gb1 = da1.sum(0)
    return {'W1': gW1, 'b1': gb1, 'W2': gW2, 'b2': gb2, 'W3': gW3, 'b3': gb3}

def sample_path(Z, bins):
    R, B = Z.shape
    b = np.clip(bins, 0, B-1.001)
    i0 = b.astype(int); w = (b-i0).astype(np.float32)
    r = np.arange(R)
    return ((1-w)*Z[r, i0]+w*Z[r, np.minimum(i0+1, B-1)])

def adam_step(P, m, v, g, it, lr=3e-3):
    b1, b2, eps = 0.9, 0.999, 1e-8
    for k in P:
        m[k] = b1*m[k]+(1-b1)*g[k]; v[k] = b2*v[k]+(1-b2)*g[k]**2
        P[k] -= lr*np.sqrt(1-b2**it)/(1-b1**it)*m[k]/(np.sqrt(v[k])+eps)

def train_one(Z, warm, B, iters_w=150, iters_e=400, lam_b=0.01, seed=0):
    R = Z.shape[0]
    t = (np.arange(R)/max(R-1, 1)).reshape(-1, 1)
    P = mklp(seed=seed)
    m = {k: np.zeros_like(vv) for k, vv in P.items()}
    v = {k: np.zeros_like(vv) for k, vv in P.items()}
    it = 0
    for _ in range(iters_w):
        it += 1
        c = out_of(P, t, B)
        # normalized-range grads (Adam's eps starves 1e-11-scale grads; keep O(1e-3))
        do = 2*(c[5]-warm)/B/R
        adam_step(P, m, v, backprop(P, t, B, do, c), it)
    # fresh moments: warm-stage statistics would throttle the energy stage
    m = {k: np.zeros_like(vv) for k, vv in P.items()}
    v = {k: np.zeros_like(vv) for k, vv in P.items()}
    r = np.arange(R)
    for _ in range(iters_e):
        it += 1
        c = out_of(P, t, B)
        o = c[5]
        b = np.clip(o, 0, B-1.001)
        i0 = b.astype(int); w = (b-i0)
        v0 = Z[r, i0]; v1 = Z[r, np.minimum(i0+1, B-1)]
        d2 = np.zeros(R); d2[2:] = o[2:]-2*o[1:-1]+o[:-2]
        # LOSS = -mean(sampled) + smooth -> dLoss/do = -(v1-v0)/R + dd
        do = np.clip(-(v1-v0)/R, -2.0, 2.0)
        dd = np.zeros(R)
        dd[2:] += 2*lam_b*d2[2:]/R; dd[1:-1] += -4*lam_b*d2[2:]/R; dd[:-2] += 2*lam_b*d2[2:]/R
        adam_step(P, m, v, backprop(P, t, B, do+dd, c), it, lr=1e-2)
    c = out_of(P, t, B)
    o = np.clip(c[5], 0, B-1)
    return o, float(sample_path(Z, o).mean())

def train(Z, warm):
    B = Z.shape[1]
    R = Z.shape[0]
    cands = [warm,
             np.full(R, B/2),
             np.linspace(B/2-2000, B/2+2000, R),   # +slope start
             np.linspace(B/2+2000, B/2-2000, R)]   # -slope start
    best = (None, -1e18)
    for i, w in enumerate(cands):
        o, s = train_one(Z, np.clip(w, 0, B-1), B, seed=i)
        if s > best[1]: best = (o, s)
    return best

def run_all(x, nfft=32768, hop=16384, k=2, fs=FS, tag=''):
    P = stft_power(x, nfft, hop)
    Z = robust_z(P)
    vf, vs = viterbi(Z, k)
    mo_v = fit_motion(vf, nfft, hop, fs)
    nf, ns = train(Z, vf.astype(float))
    mo_n = fit_motion(nf.astype(int), nfft, hop, fs)
    print(f'[{tag}] viterbi={vs:.3f} v={mo_v["drift_hz_s"]:+.1f}a={mo_v["jerk_hz_s2"]:+.1f} | '
          f'neural={ns:.3f} v={mo_n["drift_hz_s"]:+.1f}a={mo_n["jerk_hz_s2"]:+.1f}')
    return (vs, mo_v), (ns, mo_n)

def prove():
    rng = np.random.default_rng(33)
    N = 16*1024*1024
    A = 0.05
    print(f'[prove] N={N} A={A}')
    xn = quantize(rng.normal(0, 2.07, N).astype(np.float32))
    n = run_all(xn, tag='noise')
    xl = quantize(rng.normal(0, 2.07, N).astype(np.float32)
                  + synth_chirp(N, FS, 500e3, 40.0, 0.0, A, rng))
    L = run_all(xl, tag='linear40')
    xp = quantize(rng.normal(0, 2.07, N).astype(np.float32)
                  + synth_chirp(N, FS, 700e3, 10.0, 18.0, A, rng))
    P = run_all(xp, tag='parab18')
    ok = (L[1][0] > n[1][0]*1.2 and P[1][0] > n[1][0]*1.2
          and abs(L[1][1]['drift_hz_s']-40) < 15 and abs(P[1][1]['jerk_hz_s2']-18) < 12)
    print('[prove] ' + ('PASS: neural field rides both tracks, params agree'
                        if ok else 'TUNE'))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--f32', default='')
    a = ap.parse_args()
    if a.prove: prove()
    else:
        x = np.fromfile(a.f32, dtype=np.float32)
        run_all(x, tag=os.path.basename(a.f32))

if __name__ == '__main__':
    main()
