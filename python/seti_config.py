"""seti_config.py — BEAST config-driven CLI (M7: kill hardcoded constants).

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

One TOML/YAML/JSON preset drives every detector: header-derived FS/geometry
wins, preset fills the rest, CLI flags win over preset. No new hardcoded
constants — freeze a value here with a comment explaining why.

  python seti_config.py --preset configs/kepler_L.toml --show
  python pipeline.py --preset configs/kepler_L.toml --on data/x.raw ...

Optional deps (scipy/astropy/tqdm) are imported lazily by the *detectors*,
never here — this module is stdlib-only so it always loads.
"""
import argparse, json, os

try:
    import tomllib as _toml
except ImportError:
    _toml = None
try:
    import yaml as _yaml
except ImportError:
    _yaml = None

import seti_common as SC

# Every tunable in one table: (default, why). Detectors read via cfg.get().
DEFAULTS = {
    # geometry (None = from raw header TBIN/OBSFREQ/OBSBW; DEFAULT_FS fallback)
    'fs': None, 'freq_mhz': None, 'bw_mhz': None, 'nchan': 64,
    # mvp_scan gates
    'fam_trig': 3.0,      # block-0 smoke noise sits 2.2–2.8; 3.0 clears it
    'spec_line': 5.0,     # direct-FFT line needs 5x median (legacy-visible)
    'spec_hump': 2.5,     # hump-note below line, above noise ripple
    'sparkle_max': 25,    # clean slices 0–1 spikes; corruption bursts 50–700
    'seg': 32768,         # FAM segment: 89.4 Hz bins at 2.93 MHz FS
    'topk': 15,           # peaks per Y2/Y4 spectrum kept for comb rule
    # structure_pass (M1)
    'comb_min_members': 3, 'comb_min_score': 6.0,  # THE COMB RULE thresholds
    'kurt_thresh': 1.0, 'tail_thresh': 3.0,        # nongauss gates
    # frame_hunt (M2)
    'frame_sigma': 40.0,  # 3x above 16-draw noise tail (~14σ), 40x below weakest inject
    'frame_dec': 512, 'frame_hp': 2.0,
    # pulsar_fold (new): 1 Hz–2 kHz rotation band, harmonic summing
    'fold_fmin': 1.0, 'fold_fmax': 2000.0, 'fold_harms': 8, 'fold_sigma': 16.0,  # 8-draw noise max ~10.8; weakest inject 3400
    # transient_dm (new): boxcar widths + DM trials for L-band
    'dm_min': 0.0, 'dm_max': 1000.0, 'dm_trials': 32,
    'boxcar_widths': [1, 2, 4, 8, 16, 32, 64, 128],
    'pulse_sigma': 14.0,  # DM x width trial max ~10.8 on noise; injects 168+
    # cadence / veto
    'alpha_tol': 2000.0, 'persist_min': 4, 'multichan_min': 3,
    # xeno (overhaul): microscopic + exotic + alien-code battery
    'xeno_min_fam': 4.0, 'xeno_topk': 40,     # candidates entering the battery
    'xeno_sk_frac': 0.02,                     # SK deviant-bin fraction gate
    'xeno_ladder': 20.0,                      # cepstral comb ratio gate
    'xeno_dm_r2': 0.80, 'xeno_dm_min': 50.0,  # arrival-order fit + |DM| floor
    'xeno_coh': 6.0,                          # zero-crossing regularity gate
    'xeno_acf_z': 6.0, 'xeno_ham': 0.25,      # frame ACF + Hamming gates
    'xeno_crc_min': 3, 'xeno_ca_var': 0.0015, # CRC hits + CA breathing floor
    'scint_m_quiet': 0.15, 'scint_xcorr': 0.80,  # ISM scintillation gates
    # pipeline
    'workers': 4, 'pol_list': [0, 1, 2, 3], 'blocks': '0-127',
    'line_exclude': [0],  # ch0 standing-line channels excluded from SCD top-k
}


def load_preset(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, 'rb' if path.endswith('.toml') else 'r') as f:
        txt = f.read()
    if path.endswith('.toml') and _toml:
        return dict(_toml.loads(txt.decode() if isinstance(txt, bytes) else txt))
    if path.endswith('.json'):
        return json.loads(txt if isinstance(txt, str) else txt.decode())
    if _yaml and path.endswith(('.yaml', '.yml')):
        return dict(_yaml.safe_load(txt if isinstance(txt, str) else txt.decode()))
    raise SystemExit(f'cannot parse preset {path} (need tomllib/pyyaml/json)')


def resolve(raw=None, preset=None, overrides=None):
    cfg = dict(DEFAULTS)
    cfg.update(load_preset(preset) if preset else {})
    for k, v in (overrides or {}).items():
        if v is not None:
            cfg[k] = v
    cfg['preset'] = preset
    if raw and os.path.exists(raw):
        hfs = SC.fs_from_header(raw)
        if hfs and cfg.get('fs') is None:
            cfg['fs'] = hfs
            cfg['fs_src'] = 'header TBIN'
        else:
            cfg.setdefault('fs_src', 'preset/cli/default')
        freq, bw, nchan, npol, nbits, bs, spb = SC.geometry_from_header(raw)
        if cfg.get('freq_mhz') is None and freq:
            cfg['freq_mhz'] = freq
        if cfg.get('bw_mhz') is None and bw:
            cfg['bw_mhz'] = bw
        if freq is None:
            cfg.setdefault('band_warn', 'no geometry: band priors disabled')
    if cfg.get('fs') is None:
        cfg['fs'] = SC.DEFAULT_FS
        cfg['fs_src'] = 'default'
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preset', default='')
    ap.add_argument('--raw', default='')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    cfg = resolve(a.raw or None, a.preset or None)
    if a.show or not a.out:
        print(json.dumps(cfg, indent=1, default=str))
    if a.out:
        with open(a.out, 'w') as f:
            json.dump(cfg, f, indent=1, default=str)
        print(f'[config] wrote {a.out}')


if __name__ == '__main__':
    main()
