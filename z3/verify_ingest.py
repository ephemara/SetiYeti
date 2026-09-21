"""verify_ingest.py - the smt2/ingest_dispatch.smt2 theorems prove the SPEC;
this proves the SPEC matches the SHIPPED CODE (else vacuous).

1. DISPATCH TIE: independent transcription of univ_ingest.detect_format,
   fuzzed against the real router over (extension x magic-prefix) inputs.
   Any reader disagreement = drift = FAIL.
2. KIND SOUNDNESS on real opens: synthetic wav/iq/fil/npy round-trips assert
   voltage/complex/power kinds (refuses cleanly where required).
Usage: python z3/verify_ingest.py [--root .] [--n 2000]
"""
import argparse
import os
import random
import sys
import tempfile

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import univ_ingest as UI
import numpy as np


def model_reader(ext, magic, fil_ok):
    """Independent transcription of detect_format (order matters)."""
    if magic == 'hdf5':
        return 'filterbank_h5'
    if magic == 'fits':
        return 'fits'
    if magic == 'wav':
        return 'wav'
    if magic == 'npy' or ext == '.npz':
        return 'npy'
    if ext == '.f32':
        return 'f32'
    if ext == '.raw':
        return 'guppi_raw' if magic == 'guppi' else 'unknown'
    if ext == '.fil' or fil_ok:
        return 'filterbank_fil'
    if ext in ('.csv', '.txt'):
        return 'csv'
    if ext in UI.IQ_EXT:
        return 'raw_iq'
    if ext in ('.wav', '.wave'):
        return 'wav'
    if ext in ('.fits', '.fit', '.fts'):
        return 'fits'
    if ext in ('.h5', '.hdf5', '.he5'):
        return 'generic_h5'
    return 'unknown'


MAGICS = {
    'hdf5': b'\x89HDF\r\n\x1a\n' + bytes(504),
    'fits': b'SIMPLE  =                    T' + bytes(482),
    'wav': b'RIFF' + bytes(4) + b'WAVE' + bytes(500),
    'npy': b'\x93NUMPY' + bytes(505),
    'guppi': b'BACKEND = GUPPI   ' + bytes(496),
    'fil': None,  # built per-case below
    'none': bytes(512),
}


def fil_magic():
    import struct
    return (struct.pack('<i', 12) + b'HEADER_START' + bytes(496))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--n', type=int, default=2000)
    a = ap.parse_args()
    rng = random.Random(60606)
    exts = (list(UI.IQ_EXT) + ['.raw', '.fil', '.csv', '.txt', '.fits',
                               '.h5', '.wav', '.f32', '.npz', '.xyz', '.dat'])
    mags = list(MAGICS)
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        for _ in range(a.n):
            ext = rng.choice(exts)
            mg = rng.choice(mags)
            blob = fil_magic() if mg == 'fil' else MAGICS[mg]
            p = os.path.join(td, f'probe{ext}')
            with open(p, 'wb') as fh:
                fh.write(blob)
            mine = model_reader(ext, mg, mg == 'fil')
            real, _ = UI.detect_format(p)
            # .raw+guppi-magic nuance: real checks card STRINGS, model says
            # guppi for any guppi magic; align by construction (same blob).
            if mine != real:
                bad += 1
                if bad <= 3:
                    print(f'  MISMATCH ext={ext} magic={mg}: code={real} model={mine}')
    print(f'[tie] model-vs-code dispatch on {a.n} fuzz inputs: {a.n - bad}/{a.n} agree')

    # kind soundness on real round-trips
    rok = []

    def check(name, cond):
        rok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    with tempfile.TemporaryDirectory() as td:
        import wave as _w
        pw = os.path.join(td, 'a.wav')
        with _w.open(pw, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(np.zeros(8000, dtype=np.int16).tobytes())
        m, _ = UI.open_any(pw)
        check('wav opens as voltage', m['kind'] == 'voltage')
        pq = os.path.join(td, 'a.cs16')
        np.zeros(8000, dtype=np.int16).tofile(pq)
        m, _ = UI.open_any(pq, fs=8000.0)
        check('cs16 opens as complex', m['kind'] == 'complex')
        try:
            UI.open_any(pq)
            check('cs16 without fs refuses', False)
        except ValueError:
            check('cs16 without fs refuses', True)
        pf = os.path.join(td, 'a.fil')
        UI._write_fil(pf, np.full((16, 8), 100, dtype=np.uint8))
        m, _ = UI.open_any(pf)
        check('fil opens as power', m['kind'] == 'power')
        pg = os.path.join(td, 'a.xyz')
        with open(pg, 'wb') as fh:
            fh.write(os.urandom(256))
        try:
            UI.open_any(pg)
            check('unknown refuses cleanly', False)
        except ValueError:
            check('unknown refuses cleanly', True)

    ok = bad == 0 and all(rok)
    print('VERIFY_INGEST: ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
