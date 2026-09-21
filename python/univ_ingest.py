"""univ_ingest.py - SetiYeti universal front-end: analyze just about anything.

WHY THIS EXISTS: SetiYeti was a GUPPI-only shop. The sky (and the SDR on
every desk) records in a dozen formats: Breakthrough Listen filterbank
(.fil) and HDF5 (.h5), FITS, WAV audio captures, raw GNU Radio complex
(.cfile/.iq/.cu8/.cs16), numpy dumps, CSV spectra. Every one of those is
either voltage (phase intact - the full battery applies) or detected power
(phase already gone at record time - the spectral subset applies, honestly
flagged). This module sniffs, parses, and delivers ONE canonical stream:

  Stream = meta dict + sample array, kind in {'voltage','complex','power'}

  voltage  real float32 time series, fs known        -> FULL battery
  complex  complex64 time series, fs known            -> FULL battery on I
             (Q dropped with a logged caveat; complex-native C tools are
             the follow-up lever, not a blocker)
  power    float32 spectra (nspec, nchan) or envelope -> SPECTRAL subset
             (spectrum peak, fold, scint-class, ladder-on-power, grades
             capped; nothing that needs phase is attempted)

Dispatch rule (mirrored in z3/smt2/ingest_dispatch.smt2 - change both):
  container magic wins for self-describing formats (HDF5/FITS/WAV/NumPy);
  GUPPI is recognised by ASCII header cards; SigProc by header-parse
  validation; headerless raw-IQ trusts the extension (+ --iq-format) and
  REQUIRES --fs (no header to read it from - guessing is forbidden).

Usage:
  python univ_ingest.py --in signal.wav --info
  python univ_ingest.py --in blc.h5 --t0 2.0 --dur 1.0 --out signal.f32
  python univ_ingest.py --prove        # round-trips every format
"""
import argparse
import json
import os
import struct
import sys
import wave

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC

READERS = ('guppi_raw', 'filterbank_fil', 'filterbank_h5', 'generic_h5',
           'fits', 'wav', 'raw_iq', 'npy', 'csv', 'f32')

IQ_FORMATS = ('cf32', 'cs16', 'cu8', 'cs8')
IQ_BYTES = {'cf32': 8, 'cs16': 4, 'cu8': 2, 'cs8': 2}
IQ_EXT = {'.cfile': 'cf32', '.cf32': 'cf32', '.complex': 'cf32',
          '.iq': None, '.bin': None,
          '.cu8': 'cu8', '.cs8': 'cs8', '.sc16': 'cs16', '.cs16': 'cs16',
          '.c16': 'cs16'}


# ------------------------------------------------------------- dispatch --
def detect_format(path):
    """Return (reader, why). Never raises; unknown -> ('unknown', reason)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, 'rb') as fh:
            magic = fh.read(512)
    except OSError as e:
        return 'unknown', f'unreadable: {e}'
    if len(magic) < 8:
        return 'unknown', 'file too small for any header'
    # container magic first (self-describing formats)
    if magic[:8] == b'\x89HDF\r\n\x1a\n':
        return 'filterbank_h5', 'HDF5 magic (blimpy layout probed on open)'
    if magic[:6] in (b'SIMPLE',) or magic[:30].startswith(b'SIMPLE  ='):
        return 'fits', 'FITS SIMPLE card'
    if magic[:4] == b'RIFF' and magic[8:12] == b'WAVE':
        return 'wav', 'RIFF/WAVE magic'
    if magic[:6] == b'\x93NUMPY':
        return 'npy', 'NumPy magic'
    if ext in ('.npz',):
        return 'npy', 'npz extension'
    if ext == '.f32':
        return 'f32', 'native .f32 extension'
    if ext == '.raw':
        txt = magic.decode('ascii', 'replace')
        if 'BACKEND' in txt or 'BLOCSIZE' in txt or 'OBSFREQ' in txt:
            return 'guppi_raw', 'GUPPI header cards'
        return 'unknown', '.raw without GUPPI cards (use --reader raw_iq + --fs?)'
    if ext == '.fil' or _looks_like_fil(magic):
        return 'filterbank_fil', 'SigProc header validates' if _looks_like_fil(magic) else 'fil extension'
    if ext == '.csv' or ext == '.txt':
        return 'csv', f'{ext} extension'
    if ext in IQ_EXT:
        return 'raw_iq', f'{ext} extension (headerless raw-IQ)'
    if ext in ('.wav', '.wave'):
        return 'wav', 'wav extension'
    if ext in ('.fits', '.fit', '.fts'):
        return 'fits', 'fits extension'
    if ext in ('.h5', '.hdf5', '.he5'):
        return 'generic_h5', 'HDF5 extension (layout probed on open)'
    return 'unknown', f'no rule for extension {ext!r} (try --reader)'


def _looks_like_fil(magic):
    """Validate SigProc header shape: first field is a length-prefixed key."""
    try:
        if len(magic) < 8:
            return False
        (ln,) = struct.unpack('<i', magic[:4])
        if ln <= 0 or ln > 80:
            return False
        key = magic[4:4 + ln].decode('ascii', 'replace')
        return key in ('HEADER_START', 'telescope_id', 'machine_id',
                       'data_type', 'source_name', 'nchans')
    except (struct.error, UnicodeDecodeError):
        return False


# ----------------------------------------------------------------- meta --
def base_meta(path, reader, kind):
    return {'format': reader, 'src': os.path.basename(path),
            'src_bytes': os.path.getsize(path), 'kind': kind,
            'fs': None, 'f_center_mhz': None, 'bw_mhz': None,
            'n_pol': 1, 'duration_s': None, 'caveats': []}


# ---------------------------------------------------------------- readers --
def read_f32(path, t0=0.0, dur=None):
    m = base_meta(path, 'f32', 'voltage')
    x = np.fromfile(path, dtype=np.float32)
    m['duration_s'] = None
    return m, x


def read_guppi_raw(path, t0=0.0, dur=None, pol=0, root=None):
    """Via c/seti_slice (no duplicated payload math - the C tool owns it)."""
    import subprocess
    import tempfile
    root = root or os.getcwd()
    ext = '.exe' if os.name == 'nt' else ''
    sl = os.path.join(root, 'c', 'seti_slice' + ext)
    if not os.path.exists(sl):
        raise RuntimeError(f'missing {sl} - build the C tools first')
    h = SC.read_header(path)
    try:
        fs = 1.0 / float(h.get('TBIN', 0)) if float(h.get('TBIN', 0)) > 0 else SC.DEFAULT_FS
    except (ValueError, TypeError):
        fs = SC.DEFAULT_FS
    try:
        freq = float(h.get('OBSFREQ', 'nan'))
    except (ValueError, TypeError):
        freq = float('nan')
    try:
        bw = float(h.get('OBSBW', 'nan'))
    except (ValueError, TypeError):
        bw = float('nan')
    try:
        spb = int(geometry_spb(h))
    except (ValueError, TypeError):
        spb = None
    m = base_meta(path, 'guppi_raw', 'voltage')
    m.update({'fs': fs, 'f_center_mhz': freq, 'bw_mhz': abs(bw) if bw == bw else None,
              'n_pol': 4, 'pol': pol, 'header': {k: h.get(k) for k in
                                                 ('TELESCOP', 'OBSERVER', 'SRC_NAME', 'OBSFREQ',
                                                  'OBSBW', 'TBIN', 'NBITS', 'NPOL', 'OBSNCHAN')}})
    start_block = 0
    nblocks = 1 << 30
    if spb:
        start_block = int(t0 * fs / spb)
        if dur:
            nblocks = max(1, int(dur * fs / spb) + 1)
    fd, tmp = tempfile.mkstemp(suffix='.f32',
                               dir=os.path.join(root, 'data', 'mvp_tmp'))
    os.close(fd)
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    r = subprocess.run([sl, path, '32', tmp, str(nblocks), '--pol', str(pol),
                        '--start', str(start_block)], capture_output=True,
                       text=True, timeout=600)
    if not os.path.exists(tmp) or os.path.getsize(tmp) < 1000:
        raise RuntimeError(f'seti_slice produced no data: {r.stderr[:300]}')
    x = np.fromfile(tmp, dtype=np.float32)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if dur and spb:
        x = x[:int(dur * fs)]
    m['duration_s'] = len(x) / fs
    return m, x


def geometry_spb(h):
    bs = float(h.get('BLOCSIZE', 0))
    nchan = float(h.get('OBSNCHAN', h.get('NCHAN', 0)))
    npol = float(h.get('NPOL', 0))
    nbits = float(h.get('NBITS', 0))
    return bs // (nchan * npol * nbits / 8.0)


# ---- SigProc filterbank (.fil): dependency-free header + data ----------
FIL_INT_KEYS = {'telescope_id', 'machine_id', 'data_type', 'barycentric',
                'pulsarcentric', 'nbits', 'nchans', 'nbeams', 'ibeam',
                'nifs', 'npuls', 'nbins', 'nsamples'}
FIL_DBL_KEYS = {'tstart', 'tsamp', 'fch1', 'foff', 'refdm', 'period',
                'az_start', 'za_start', 'src_raj', 'src_dej'}


def parse_fil_header(path):
    """Returns (header dict, data_offset). Raises ValueError if not filterbank."""
    with open(path, 'rb') as fh:
        blob = fh.read(1024 * 1024)
    off, hdr = 0, {}
    started = False
    while off + 4 <= len(blob):
        (ln,) = struct.unpack('<i', blob[off:off + 4])
        if ln <= 0 or ln > 80 or off + 4 + ln > len(blob):
            raise ValueError('not a SigProc header')
        key = blob[off + 4:off + 4 + ln].decode('ascii')
        off += 4 + ln
        if key == 'HEADER_START':
            started = True
            continue
        if key == 'HEADER_END':
            break
        if key in FIL_INT_KEYS:
            (v,) = struct.unpack('<i', blob[off:off + 4])
            off += 4
            hdr[key] = v
        elif key in FIL_DBL_KEYS:
            (v,) = struct.unpack('<d', blob[off:off + 8])
            off += 8
            hdr[key] = v
        elif key in ('source_name', 'rawdatafile'):
            (ln2,) = struct.unpack('<i', blob[off:off + 4])
            v = blob[off + 4:off + 4 + ln2].decode('ascii', 'replace')
            off += 4 + ln2
            hdr[key] = v
        else:
            raise ValueError(f'unknown fil key {key!r}')
    if not started:
        raise ValueError('no HEADER_START')
    return hdr, off


def read_filterbank_fil(path, t0=0.0, dur=None):
    hdr, off = parse_fil_header(path)
    nchans = int(hdr.get('nchans', 0))
    nifs = int(hdr.get('nifs', 1))
    nbits = int(hdr.get('nbits', 8))
    tsamp = float(hdr.get('tsamp', 0.0))
    if not nchans or not tsamp:
        raise ValueError('fil header missing nchans/tsamp')
    bps = nchans * nifs * nbits // 8
    total = (os.path.getsize(path) - off) // bps
    i0 = int(t0 / tsamp)
    n = total - i0 if dur is None else int(dur / tsamp)
    n = max(0, min(n, total - i0))
    m = base_meta(path, 'filterbank_fil', 'power')
    fch1 = float(hdr.get('fch1', 0.0))
    foff = float(hdr.get('foff', 0.0))
    m.update({'tsamp': tsamp, 'fch1_mhz': fch1, 'foff_mhz': foff,
              'nchans': nchans, 'n_pol': nifs,
              'f_center_mhz': fch1 + foff * (nchans - 1) / 2.0,
              'bw_mhz': abs(foff * nchans),
              'duration_s': n * tsamp, 'nspec': n,
              'source': hdr.get('source_name', ''),
              'telescope_id': hdr.get('telescope_id', -1)})
    m['caveats'].append('detected power: phase was discarded at record time; '
                        'spectral subset only')
    with open(path, 'rb') as fh:
        fh.seek(off + i0 * bps)
        raw = fh.read(n * bps)
    if nbits == 8:
        arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    elif nbits == 32:
        arr = np.frombuffer(raw, dtype=np.float32).copy()
    elif nbits == 16:
        arr = np.frombuffer(raw, dtype=np.uint16).astype(np.float32)
    else:
        raise ValueError(f'nbits={nbits} packed layouts not yet supported')
    arr = arr.reshape(n, nifs, nchans) if nifs > 1 else arr.reshape(n, nchans)
    return m, arr


# ---- HDF5 (blimpy filterbank + generic fallback; needs h5py) ------------
def _need_h5py():
    try:
        import h5py
        return h5py
    except ImportError:
        raise RuntimeError('h5py not installed: pip install h5py (see requirements-science.txt)')


def read_filterbank_h5(path, t0=0.0, dur=None):
    h5py = _need_h5py()
    m = base_meta(path, 'filterbank_h5', 'power')
    with h5py.File(path, 'r') as f:
        if 'data' not in f:
            return read_generic_h5(path, t0, dur)
        ds = f['data']
        a = ds.attrs
        fch1 = float(a.get('fch1', 0.0))
        foff = float(a.get('foff', 0.0))
        tsamp = float(a.get('tsamp', 0.0))
        shape = ds.shape
        if len(shape) == 3:
            ns, npol, nc = shape
        elif len(shape) == 2:
            ns, nc = shape
            npol = 1
        else:
            raise ValueError(f'blimpy data shape {shape} not understood')
        i0 = int(t0 / tsamp) if tsamp else 0
        n = ns - i0 if dur is None or not tsamp else int(dur / tsamp)
        n = max(0, min(n, ns - i0))
        arr = ds[i0:i0 + n].astype(np.float32)
        if arr.ndim == 3 and arr.shape[1] == 1:
            arr = arr[:, 0, :]
    m.update({'tsamp': tsamp, 'fch1_mhz': fch1, 'foff_mhz': foff,
              'nchans': int(arr.shape[-1]), 'n_pol': int(npol),
              'f_center_mhz': fch1 + foff * (int(arr.shape[-1]) - 1) / 2.0,
              'bw_mhz': abs(foff * int(arr.shape[-1])),
              'duration_s': n * tsamp if tsamp else None, 'nspec': n})
    m['caveats'].append('detected power: phase was discarded at record time; '
                        'spectral subset only')
    return m, arr


def read_generic_h5(path, t0=0.0, dur=None, hint=''):
    h5py = _need_h5py()
    best, bestn = None, -1
    with h5py.File(path, 'r') as f:
        def visit(name, obj):
            nonlocal best, bestn
            if isinstance(obj, h5py.Dataset) and obj.dtype.kind in 'fiuc':
                n = 1
                for d in obj.shape:
                    n *= d
                if n > bestn:
                    bestn, best = n, name
        f.visititems(visit)
        if best is None:
            raise ValueError('no numeric dataset found')
        arr = f[best][...]
        attrs = dict(f[best].attrs)
    nm = best.lower()
    if hint in ('voltage', 'complex', 'power'):
        kind = hint
    elif 'complex' in nm or 'iq' in nm or np.iscomplexobj(arr):
        kind = 'complex'
    elif 'volt' in nm or 'adc' in nm or 'raw' in nm:
        kind = 'voltage'
    elif 'spec' in nm or 'pow' in nm or 'data' in nm or 'water' in nm:
        kind = 'power'
    else:
        kind = 'power'
    m = base_meta(path, 'generic_h5', kind)
    m['dataset'] = best
    m['attrs'] = {k: str(v) for k, v in attrs.items()}
    for k in ('fs', 'sample_rate', 'samplerate', 'FS'):
        if k in attrs:
            try:
                m['fs'] = float(attrs[k])
            except (ValueError, TypeError):
                pass
    for k in ('f_center', 'fc', 'freq', 'fch1', 'frequency'):
        if k in attrs:
            try:
                m['f_center_mhz'] = float(attrs[k])
            except (ValueError, TypeError):
                pass
    m['caveats'].append(f'generic-HDF5 heuristic chose kind={kind!r} '
                        f'(dataset {best!r}); override with --hint')
    return m, np.asarray(arr)


# ---- FITS (needs astropy) -------------------------------------------------
def _need_astropy():
    try:
        from astropy.io import fits
        return fits
    except ImportError:
        raise RuntimeError('astropy not installed: pip install astropy')


def read_fits(path, t0=0.0, dur=None, hint=''):
    fits = _need_astropy()
    hdus = fits.open(path)
    data, hdr, hdu_i = None, None, 0
    for i, h in enumerate(hdus):
        if getattr(h, 'data', None) is not None and np.size(h.data) > 0:
            data, hdr, hdu_i = np.asarray(h.data), dict(h.header), i
            break
    hdus.close()
    if data is None:
        raise ValueError('no data HDU found')
    kind = hint or ('power' if data.ndim >= 2 else 'voltage')
    m = base_meta(path, 'fits', kind)
    m['hdu'] = hdu_i
    for k in ('TELESCOP', 'OBSERVER', 'OBJECT', 'INSTRUME', 'CTYPE1',
              'CTYPE2', 'CUNIT1', 'CUNIT2', 'CRVAL1', 'CRVAL2', 'CDELT1',
              'CDELT2', 'DATE-OBS'):
        if k in hdr:
            m[k.lower().replace('-', '_')] = str(hdr[k])
    try:
        if 'CRVAL1' in hdr and 'CDELT1' in hdr:
            n = data.shape[-1]
            m['f_center_mhz'] = (float(hdr['CRVAL1']) +
                                 float(hdr['CDELT1']) * (n - 1) / 2.0)
    except (ValueError, TypeError):
        pass
    m['caveats'].append(f'FITS HDU {hdu_i} shape {data.shape}; kind={kind!r} '
                        f'by {"hint" if hint else "ndim heuristic"}')
    return m, np.asarray(data)


# ---- WAV (stdlib only) ------------------------------------------------------
def read_wav(path, t0=0.0, dur=None):
    with wave.open(path, 'rb') as w:
        nch, sw, fs, nfr = (w.getnchannels(), w.getsampwidth(),
                            w.getframerate(), w.getnframes())
        i0 = int(t0 * fs)
        n = nfr - i0 if dur is None else int(dur * fs)
        n = max(0, min(n, nfr - i0))
        w.setpos(i0)
        raw = w.readframes(n)
    if sw == 1:
        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    elif sw == 2:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        arr = np.frombuffer(raw, dtype=np.float32).copy()
    else:
        raise ValueError(f'WAV sampwidth={sw} not supported')
    if nch > 1:
        arr = arr.reshape(n, nch)
        m_pol = nch
    else:
        m_pol = 1
    m = base_meta(path, 'wav', 'voltage')
    m.update({'fs': float(fs), 'n_pol': m_pol, 'duration_s': n / fs})
    m['caveats'].append('audio baseband: no sky frequency; Doppler/alloc '
                        'screens skipped')
    return m, arr


# ---- headerless raw I/Q (GNU Radio / rtl-sdr / HackRF conventions) ---------
def read_raw_iq(path, t0=0.0, dur=None, iq_format='', fs=None):
    ext = os.path.splitext(path)[1].lower()
    if not iq_format:
        iq_format = IQ_EXT.get(ext)
    if iq_format not in IQ_FORMATS:
        raise ValueError(f'cannot guess IQ layout for {ext!r}: pass --iq-format '
                         f"one of {', '.join(IQ_FORMATS)}")
    if not fs:
        raise ValueError('headerless raw-IQ REQUIRES --fs (guessing forbidden)')
    nb = os.path.getsize(path)
    # complex samples = bytes / bytes-per-complex-sample
    cbytes = {'cf32': 8, 'cs16': 4, 'cu8': 2, 'cs8': 2}[iq_format]
    total = nb // cbytes
    i0 = int(t0 * fs)
    n = total - i0 if dur is None else int(dur * fs)
    n = max(0, min(n, total - i0))
    with open(path, 'rb') as fh:
        fh.seek(i0 * cbytes)
        raw = fh.read(n * cbytes)
    if iq_format == 'cf32':
        arr = np.frombuffer(raw, dtype=np.complex64).copy()
    elif iq_format == 'cs16':
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32).copy()
        arr = (arr[0::2] + 1j * arr[1::2]) / 32768.0
    elif iq_format == 'cu8':
        arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        arr = ((arr[0::2] - 127.5) + 1j * (arr[1::2] - 127.5)) / 127.5
    elif iq_format == 'cs8':
        arr = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
        arr = (arr[0::2] + 1j * arr[1::2]) / 128.0
    m = base_meta(path, 'raw_iq', 'complex')
    m.update({'fs': float(fs), 'iq_format': iq_format,
              'duration_s': n / fs})
    m['caveats'].append('complex native; canonical real = I channel '
                        '(Q available, complex-native C tools are future work)')
    return m, arr.astype(np.complex64)


# ---- numpy / csv -------------------------------------------------------------
def read_npy(path, t0=0.0, dur=None, hint=''):
    if path.lower().endswith('.npz'):
        z = np.load(path)
        key = sorted(z.files, key=lambda k: z[k].size)[-1]
        arr = np.asarray(z[key])
    else:
        arr = np.load(path)
    kind = hint or ('complex' if np.iscomplexobj(arr) else
                    'power' if arr.ndim >= 2 else 'voltage')
    m = base_meta(path, 'npy', kind)
    m['shape'] = list(arr.shape)
    if kind == 'voltage' and not hint:
        m['caveats'].append('1-D array guessed as voltage; --hint power if spectrum')
    return m, np.asarray(arr)


def read_csv(path, t0=0.0, dur=None, hint=''):
    try:
        arr = np.loadtxt(path, delimiter=',', comments='#')
    except ValueError:
        arr = np.loadtxt(path, comments='#')
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 2 and arr.shape[1] == 2 and not hint:
        kind = 'power'
        m = base_meta(path, 'csv', kind)
        m['caveats'].append('2-column CSV read as (freq, power); --hint voltage to override')
    else:
        kind = hint or 'voltage'
        m = base_meta(path, 'csv', kind)
        if arr.ndim > 1:
            arr = arr[:, 0] if not hint else arr
            m['caveats'].append('multi-column CSV: first column taken')
    return m, arr


# --------------------------------------------------------------- open_any --
READER_FN = {
    'guppi_raw': read_guppi_raw,
    'filterbank_fil': read_filterbank_fil,
    'filterbank_h5': read_filterbank_h5,
    'generic_h5': read_generic_h5,
    'fits': read_fits,
    'wav': read_wav,
    'raw_iq': read_raw_iq,
    'npy': read_npy,
    'csv': read_csv,
    'f32': read_f32,
}


def open_any(path, t0=0.0, dur=None, reader='', fs=None, iq_format='',
             hint='', pol=0, root=None):
    """Detect (or force) a reader; return (meta, array). Never half-reads:
    unknown formats raise with install/hint guidance, never guess silently."""
    if not reader:
        reader, why = detect_format(path)
    else:
        why = 'forced via --reader'
    if reader == 'unknown':
        raise ValueError(f'unsupported input: {why}')
    if reader == 'filterbank_h5' and hint == 'generic':
        reader = 'generic_h5'
    fn = READER_FN[reader]
    kw = {}
    if reader in ('raw_iq',):
        kw = {'iq_format': iq_format, 'fs': fs}
    if reader in ('fits', 'npy', 'csv', 'generic_h5') and hint:
        kw = {'hint': hint}
    if reader == 'guppi_raw':
        kw = {'pol': pol, 'root': root}
    meta, arr = fn(path, t0=t0, dur=dur, **kw)
    meta['reader'] = reader
    meta['detect_why'] = why
    return meta, arr


def canonical_real(meta, arr):
    """Array -> real float32 voltage/envelope + updated meta."""
    if meta['kind'] == 'complex':
        meta['caveats'].append('canonical real = I channel (see raw_iq note)')
        return np.asarray(arr.real, dtype=np.float32)
    if meta['kind'] == 'power':
        a = np.asarray(arr, dtype=np.float32)
        if a.ndim == 3:
            a = a[:, 0, :] if a.shape[1] <= a.shape[2] else a[:, :, 0]
        if a.ndim == 2:
            # spectra (nspec, nchan): band-mean envelope preserves time axis
            meta['power_envelope'] = True
            return np.ascontiguousarray(a.mean(axis=1), dtype=np.float32)
        return np.ascontiguousarray(a.ravel(), dtype=np.float32)
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 2 and a.shape[1] <= 8:
        a = a[:, 0]  # multichannel audio: first channel, logged below
        meta['caveats'].append('multi-channel: first channel taken as canonical')
    return np.ascontiguousarray(a.ravel(), dtype=np.float32)


# ------------------------------------------------------------------ prove --
def _write_fil(path, data_u8, tsamp=0.001, fch1=1400.0, foff=-0.1,
               source='SYNTH'):
    nchans = data_u8.shape[1]

    def field(name, val):
        b = struct.pack('<i', len(name)) + name.encode()
        if isinstance(val, int):
            b += struct.pack('<i', val)
        elif isinstance(val, float):
            b += struct.pack('<d', val)
        elif isinstance(val, str):
            b += struct.pack('<i', len(val)) + val.encode()
        return b

    hdr = (field('HEADER_START', 0)[:4] + b'HEADER_START' +
           field('telescope_id', 6) + field('machine_id', 1) +
           field('data_type', 1) + field('source_name', source) +
           field('tsamp', float(tsamp)) + field('fch1', float(fch1)) +
           field('foff', float(foff)) + field('nchans', int(nchans)) +
           field('nbits', 8) + field('nifs', 1) +
           struct.pack('<i', 10) + b'HEADER_END')
    with open(path, 'wb') as fh:
        fh.write(hdr)
        fh.write(np.ascontiguousarray(data_u8, dtype=np.uint8).tobytes())


def prove(workdir='data'):
    import tempfile
    os.makedirs(workdir, exist_ok=True)
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    rng = np.random.default_rng(777)
    N = 1 << 20
    fs = 48000.0
    t = np.arange(N) / fs
    tone = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    noise = rng.normal(0, 0.1, N).astype(np.float32)
    sig = tone + noise

    # ---- WAV round-trip (stdlib-only path) --------------------------------
    import wave as _w
    pw = os.path.join(workdir, '_pv.wav')
    with _w.open(pw, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(fs))
        w.writeframes((np.clip(sig, -1, 1) * 32767).astype(np.int16).tobytes())
    m, a = open_any(pw)
    check('WAV autodetect+kind', m['reader'] == 'wav' and m['kind'] == 'voltage',
          f"{m['reader']}/{m['kind']} fs={m['fs']}")
    r = canonical_real(m, a)
    check('WAV round-trip (tone intact)', abs(r - sig).max() < 2e-4,
          f'maxerr={abs(r - sig).max():.2g}')

    # ---- raw-IQ round-trip (all four layouts) ------------------------------
    for fmt in IQ_FORMATS:
        pq = os.path.join(workdir, f'_pv.{fmt}')
        z = (sig + 1j * rng.normal(0, 0.1, N)).astype(np.complex64)
        if fmt == 'cf32':
            z.astype(np.complex64).tofile(pq)
        elif fmt == 'cs16':
            (np.clip(np.stack([z.real, z.imag], axis=1), -1, 1) * 32767).astype(
                np.int16).tofile(pq)
        elif fmt == 'cu8':
            (np.clip(np.stack([z.real, z.imag], axis=1), -1, 1) * 127.5 + 127.5).astype(
                np.uint8).tofile(pq)
        elif fmt == 'cs8':
            (np.clip(np.stack([z.real, z.imag], axis=1), -1, 1) * 127).astype(
                np.int8).tofile(pq)
        m, a = open_any(pq, fs=fs)
        r = canonical_real(m, a)
        tol = 0.02 if fmt in ('cu8', 'cs8') else 2e-4
        check(f'IQ/{fmt} round-trip', m['kind'] == 'complex' and
              abs(r - sig).max() < tol, f'maxerr={abs(r - sig).max():.2g}')
    # headerless without --fs must refuse, not guess
    try:
        open_any(os.path.join(workdir, '_pv.cs16'))
        check('IQ without --fs refuses', False, 'no error raised!')
    except ValueError as e:
        check('IQ without --fs refuses', True, str(e)[:60])

    # ---- SigProc filterbank round-trip ------------------------------------
    pf = os.path.join(workdir, '_pv.fil')
    nspec, nch = 512, 64
    fb = rng.normal(100, 5, (nspec, nch))
    fb[100:110, 30] += 60  # bright blip, chan 30
    _write_fil(pf, np.clip(fb, 0, 255).astype(np.uint8))
    m, a = open_any(pf)
    hot = a[100:110, 30].mean() > a.mean() + 5 * a.std()
    check('FIL autodetect+kind+blip', m['reader'] == 'filterbank_fil' and
          m['kind'] == 'power' and m['nchans'] == 64 and hot,
          f"{m['reader']} nch={m.get('nchans')} hot={hot}")

    # ---- HDF5 blimpy-style round-trip --------------------------------------
    try:
        import h5py
        ph = os.path.join(workdir, '_pv.h5')
        with h5py.File(ph, 'w') as f:
            d = f.create_dataset('data', data=fb.astype(np.float32))
            d.attrs['fch1'] = 1400.0
            d.attrs['foff'] = -0.1
            d.attrs['tsamp'] = 0.001
        m, a = open_any(ph)
        check('H5 autodetect+attrs', 'h5' in m['reader'] and
              abs(m['f_center_mhz'] - (1400.0 - 0.1 * 63 / 2)) < 0.01 and
              a.shape == (512, 64), f"{m['reader']} {a.shape}")
    except ImportError:
        print('  [skip] H5: h5py missing')

    # ---- FITS round-trip ----------------------------------------------------
    try:
        from astropy.io import fits as _fits
        pz = os.path.join(workdir, '_pv.fits')
        _fits.writeto(pz, fb.astype(np.float32), overwrite=True)
        m, a = open_any(pz)
        check('FITS autodetect', m['reader'] == 'fits' and a.shape == (512, 64),
              f"{m['reader']} {a.shape}")
    except ImportError:
        print('  [skip] FITS: astropy missing')

    # ---- npy / csv -----------------------------------------------------------
    pn = os.path.join(workdir, '_pv.npy')
    np.save(pn, sig)
    m, a = open_any(pn)
    check('NPY round-trip', m['kind'] == 'voltage' and
          abs(canonical_real(m, a) - sig).max() == 0, '')
    pc = os.path.join(workdir, '_pv.csv')
    np.savetxt(pc, np.column_stack([np.linspace(1400, 1401, 64),
                                    fb.mean(axis=0)]), delimiter=',')
    m, a = open_any(pc)
    check('CSV spectrum kind', m['kind'] == 'power', f"{m['kind']}")

    # ---- dispatch totality: garbage in, clean error out ----------------------
    pg = os.path.join(workdir, '_pv.xyz')
    with open(pg, 'wb') as fh:
        fh.write(os.urandom(256))
    try:
        open_any(pg)
        check('unknown extension refuses cleanly', False, 'no error!')
    except ValueError as e:
        check('unknown extension refuses cleanly', True, str(e)[:60])

    for f in os.listdir(workdir):
        if f.startswith('_pv.'):
            try:
                os.remove(os.path.join(workdir, f))
            except OSError:
                pass
    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', default='')
    ap.add_argument('--reader', default='')
    ap.add_argument('--fs', type=float, default=None)
    ap.add_argument('--iq-format', default='')
    ap.add_argument('--hint', default='')
    ap.add_argument('--pol', type=int, default=0)
    ap.add_argument('--t0', type=float, default=0.0)
    ap.add_argument('--dur', type=float, default=None)
    ap.add_argument('--out', default='')
    ap.add_argument('--info', action='store_true')
    ap.add_argument('--prove', action='store_true')
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    if a.prove:
        sys.exit(0 if prove(os.path.join(a.root, 'data')) else 1)
    if not a.inp:
        sys.exit('need --in (or --prove)')
    meta, arr = open_any(os.path.join(a.root, a.inp) if not os.path.isabs(a.inp) else a.inp,
                         t0=a.t0, dur=a.dur, reader=a.reader, fs=a.fs,
                         iq_format=a.iq_format, hint=a.hint, pol=a.pol,
                         root=a.root)
    print(f"[ingest] reader={meta['reader']} kind={meta['kind']} "
          f"shape={np.shape(arr)} ({meta['detect_why']})")
    for k in ('fs', 'f_center_mhz', 'bw_mhz', 'tsamp', 'nchans', 'duration_s'):
        if meta.get(k) is not None:
            print(f"         {k}={meta[k]}")
    for c in meta.get('caveats', []):
        print(f"         caveat: {c}")
    if a.info:
        print(json.dumps({k: str(v) for k, v in meta.items()}, indent=1))
        return
    if a.out:
        outp = os.path.join(a.root, a.out)
        canonical_real(meta, arr).tofile(outp)
        json.dump({k: str(v) for k, v in meta.items()},
                  open(outp + '.meta.json', 'w'), indent=1)
        print(f'[ingest] canonical f32 -> {a.out} (+ .meta.json)')


if __name__ == '__main__':
    main()
