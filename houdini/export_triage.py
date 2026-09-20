"""export_triage.py - SetiYeti Houdini Tier-1 exporter (system python, no hou needed).
Reads hits.csv flags (verdict != clean), re-slices those (block,chan) from the
GUPPI .raw via c/seti_slice, and writes Houdini-readable triage assets:

  out/terrain_b<BB>c<CC>.png   16-bit waterfall heightfield (rows=time, cols=freq)
  out/terrain_b<BB>c<CC>.npy   float32 log-power waterfall (lossless, Python SOP)
  out/terrain_b<BB>c<CC>.exr   float32 EXR (best-effort, needs OpenEXR+Imath)
  out/macro_b<BB>.png          64-chan spectral-max overview (rows=chan, cols=freq)
  out/macro_b<BB>.npy          float32 overview
  out/hits_points.csv          flag points for Houdini File SOP (block,chan,score...)

Usage:
  python houdini/export_triage.py --root .
"""
import argparse, csv, os, subprocess, sys
import numpy as np

RAW_DEFAULT = "data/blc2_2bit_guppi_57396_MESSIER031_0056.0002.raw"
NFFT = 4096
HOP = 2048
MAX_ROWS = 256  # cap time rows so terrain stays viewable
OBJ_MAX_COLS = 512  # downsampled OBJ mesh width (freq axis)
OBJ_MAX_ROWS = 128  # downsampled OBJ mesh height (time axis)
OBJ_PLANE_CM = 1000.0  # 10m x 10m plane in UE5 (1 unit = 1 cm)
OBJ_H_CM = 200.0  # 2m peak height exaggeration for inspection


def run(exe, *args):
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{exe} {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
    return r


def waterfall(x, nfft=NFFT, hop=HOP):
    x = np.asarray(x, dtype=np.float32)
    nrows = max(1, (len(x) - nfft) // hop + 1)
    nrows = min(nrows, MAX_ROWS)
    P = np.empty((nrows, nfft // 2 + 1), dtype=np.float32)
    for r in range(nrows):
        F = np.fft.rfft(x[r * hop:r * hop + nfft])
        P[r] = (F.real * F.real + F.imag * F.imag)
    return P


def waterfall_y2(x, nfft=NFFT, hop=HOP):
    """Square-law waterfall: the FAM appeal domain. y=x^2 then STFT.
    A carrier-squared / DSSS-baud line shows here even when total-power
    waterfall is clean. Same geometry (rows=time, cols=freq) as waterfall()."""
    x = np.asarray(x, dtype=np.float64)
    y = x * x
    y -= y.mean()
    nrows = max(1, (len(y) - nfft) // hop + 1)
    nrows = min(nrows, MAX_ROWS)
    P = np.empty((nrows, nfft // 2 + 1), dtype=np.float32)
    for r in range(nrows):
        F = np.fft.rfft(y[r * hop:r * hop + nfft])
        P[r] = (F.real * F.real + F.imag * F.imag)
    return P


def downsample(H, max_rows=OBJ_MAX_ROWS, max_cols=OBJ_MAX_COLS):
    r, c = H.shape
    sy = max(1, int(np.ceil(r / max_rows)))
    sx = max(1, int(np.ceil(c / max_cols)))
    return np.ascontiguousarray(H[::sy, ::sx])


def write_obj(path, H01, mtl_name):
    """Y-up OBJ heightfield mesh (x=freq, y=height, z=time), UE5-ready.
    H01: 2D float array normalized 0..1. UVs map the terrain PNG as albedo
    via the companion .mtl. Import into UE5 with Convert Scene ON (default)."""
    H = np.clip(np.asarray(H01, dtype=np.float64), 0, 1)
    R, C = H.shape
    xs = np.linspace(-OBJ_PLANE_CM / 2, OBJ_PLANE_CM / 2, C)
    zs = np.linspace(-OBJ_PLANE_CM / 2, OBJ_PLANE_CM / 2, R)
    Y = H * OBJ_H_CM
    # normals from height gradient in cm units (y-up: n = (-dh/dx, 1, -dh/dz))
    dzdx = np.gradient(Y, xs, axis=1)
    dzdz = np.gradient(Y, zs, axis=0)
    n = np.stack((-dzdx, np.ones_like(Y), -dzdz), axis=-1)
    n /= (np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12)
    X, Z = np.meshgrid(xs, zs)
    U = np.tile(np.linspace(0, 1, C), (R, 1))
    V = np.tile(np.linspace(0, 1, R).reshape(-1, 1), (1, C))
    out = [f"# SetiYeti terrain {R}x{C} rows(time)xcols(freq), cm, y-up\n",
           f"mtllib {mtl_name}\n", "usemtl TerrainMat\n"]
    for i in range(R):
        for j in range(C):
            out.append(f"v {X[i,j]:.3f} {Y[i,j]:.3f} {Z[i,j]:.3f}\n")
    for i in range(R):
        for j in range(C):
            out.append(f"vt {U[i,j]:.5f} {V[i,j]:.5f}\n")
    for i in range(R):
        for j in range(C):
            out.append(f"vn {n[i,j,0]:.5f} {n[i,j,1]:.5f} {n[i,j,2]:.5f}\n")
    # faces (1-indexed, v/vt/vn)
    for i in range(R - 1):
        b0 = i * C + 1
        b1 = (i + 1) * C + 1
        for j in range(C - 1):
            v0, v1, v2, v3 = b0 + j, b0 + j + 1, b1 + j, b1 + j + 1
            out.append(f"f {v0}/{v0}/{v0} {v2}/{v2}/{v2} {v1}/{v1}/{v1}\n")
            out.append(f"f {v1}/{v1}/{v1} {v2}/{v2}/{v2} {v3}/{v3}/{v3}\n")
    with open(path, 'w') as f:
        f.writelines(out)


def write_mtl(path, tex_basename):
    with open(path, 'w') as f:
        f.write("newmtl TerrainMat\nKa 0.2 0.2 0.2\nKd 1.0 1.0 1.0\n"
                f"map_Kd {tex_basename}\n")


def lognorm(P):
    L = np.log10(P + 1.0).astype(np.float64)
    lo, hi = np.percentile(L, 1), np.percentile(L, 99.9)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros_like(L, dtype=np.float64)
    return np.clip((L - lo) / (hi - lo), 0, 1)


def save_png16(path, norm):
    from PIL import Image
    u16 = (np.clip(norm, 0, 1) * 65535).astype(np.uint16)
    Image.fromarray(u16).save(path)


def save_exr(path, arr):
    """Best-effort float EXR. Returns True on success."""
    try:
        import OpenEXR, Imath
        h, w = arr.shape
        hdr = OpenEXR.Header(w, h)
        hdr['channels'] = {'Y': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))}
        ex = OpenEXR.OutputFile(path, hdr)
        ex.writePixels({'Y': np.ascontiguousarray(arr, dtype=np.float32).tobytes()})
        ex.close()
        return True
    except Exception as e:
        print(f"  [exr skip] {os.path.basename(path)}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--raw', default=RAW_DEFAULT)
    ap.add_argument('--hits', default='hits.csv')
    ap.add_argument('--out', default='houdini/out')
    ap.add_argument('--pol', type=int, default=0)
    a = ap.parse_args()
    ext = '.exe' if os.name == 'nt' else ''
    sl = os.path.join(a.root, 'c', 'seti_slice' + ext)
    raw = a.raw if os.path.isabs(a.raw) else os.path.join(a.root, a.raw)
    hitsp = a.hits if os.path.isabs(a.hits) else os.path.join(a.root, a.hits)
    outd = a.out if os.path.isabs(a.out) else os.path.join(a.root, a.out)
    os.makedirs(outd, exist_ok=True)

    rows = list(csv.DictReader(open(hitsp)))
    flags = [r for r in rows if r.get('verdict', 'clean') != 'clean']
    print(f"slices={len(rows)} flags={len(flags)}")
    if not flags:
        print("no flags — nothing to export (pipeline clean).")
        return

    pts = []
    for f in flags:
        b, ch = int(f['block']), int(f['chan'])
        tmp = os.path.join(outd, f"_tmp_b{b}c{ch}.f32")
        run(sl, raw, str(ch), tmp, "1", "--pol", str(a.pol), "--start", str(b))
        x = np.fromfile(tmp, dtype=np.float32)
        os.remove(tmp)
        P = waterfall(x)
        N = lognorm(P)
        base = f"terrain_b{b:02d}c{ch:02d}"
        save_png16(os.path.join(outd, base + ".png"), N)
        np.save(os.path.join(outd, base + ".npy"),
                np.log10(P + 1.0).astype(np.float32))
        save_exr(os.path.join(outd, base + ".exr"),
                 np.log10(P + 1.0).astype(np.float32))
        # Y2 square-law terrain: the FAM appeal domain (fair appeal court)
        P2 = waterfall_y2(x)
        N2 = lognorm(P2)
        save_png16(os.path.join(outd, base + "_y2.png"), N2)
        np.save(os.path.join(outd, base + "_y2.npy"),
                np.log10(P2 + 1.0).astype(np.float32))
        save_exr(os.path.join(outd, base + "_y2.exr"),
                 np.log10(P2 + 1.0).astype(np.float32))
        # UE5-ready OBJ meshes (downsampled heightfields, cm, y-up, UV+MTL)
        for suffix, NN, tex in (("", N, base + ".png"),
                                ("_y2", N2, base + "_y2.png")):
            Hd = downsample(NN)
            mtl = base + suffix + ".mtl"
            write_mtl(os.path.join(outd, mtl), tex)
            write_obj(os.path.join(outd, base + suffix + ".obj"), Hd, mtl)
        print(f"flag b{b} c{ch}: rows={P.shape[0]} cols={P.shape[1]} "
              f"spec={f['spec_ratio']} fam={f['fam_best']}@{f['fam_hz']}Hz "
              f"+Y2 +2xOBJ({downsample(N).shape[0]}x{downsample(N).shape[1]})")

        # macro strip: spectral-max overview across all 64 chans, same block
        mtmp = os.path.join(outd, f"_mtmp_b{b}.npy")
        M = []
        for c in range(64):
            t2 = os.path.join(outd, f"_mtmp_b{b}c{c}.f32")
            run(sl, raw, str(c), t2, "1", "--pol", str(a.pol), "--start", str(b))
            y = np.fromfile(t2, dtype=np.float32)
            os.remove(t2)
            n = (len(y) // NFFT) * NFFT
            S = np.abs(np.fft.rfft(
                y[:n].reshape(-1, NFFT).astype(np.float32), axis=1)) ** 2
            avg = S.mean(axis=0)
            M.append(avg / (np.median(avg) + 1e-12))
        M = np.array(M, dtype=np.float32)  # (64, 2049)
        # downsample freq to 1024 for the PNG, keep full in npy
        step = M.shape[1] // 1024
        Mn = lognorm(M[:, :1024 * step].reshape(64, 1024, step).max(axis=2))
        save_png16(os.path.join(outd, f"macro_b{b:02d}.png"), Mn)
        np.save(os.path.join(outd, f"macro_b{b:02d}.npy"), M)
        print(f"  macro_b{b:02d}: 64 chans stacked")

        try:
            score = max(float(f.get('fam_best', 0) or 0),
                        float(f.get('spec_ratio', 0) or 0))
        except ValueError:
            score = 0.0
        pts.append((b, ch, score, f.get('fam_hz', ''), f.get('verdict', '')))

    pp = os.path.join(outd, "hits_points.csv")
    with open(pp, 'w', newline='') as cf:
        w = csv.writer(cf)
        w.writerow(['block', 'chan', 'x', 'y', 'score', 'fam_hz', 'verdict'])
        for b, ch, s, hz, v in pts:
            w.writerow([b, ch, f"{ch/63:.4f}", f"{b/48:.4f}", f"{s:.3f}", hz, v])
    print(f"wrote {pp} + {len(flags)} terrain(s) -> {outd}")


if __name__ == '__main__':
    main()
