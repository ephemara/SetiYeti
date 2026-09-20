"""seti_common.py - SetiYeti shared plumbing (P0 foundation).

One place for the things every detector re-implements differently:
  * GUPPI header reading (previously three divergent parsers in
    rfi_veto / mvp_scan / frame_hunt, plus ad-hoc TBIN regexes)
  * sample-rate + block-geometry derivation from header cards
  * git revision + run-manifest writer (provenance: every CSV gets a
    sidecar that records exactly how it was made)

No detector logic here. Import, don't copy.
"""
import json
import os
import re
import subprocess
import time

DEFAULT_FS = 2929687.5          # GBT GUPPI coarse-channel rate (fallback only)
CARD = 80


def read_header(path, ncards=512):
    """Raw GUPPI cards -> {KEY: value-string}. Never raises ({} on failure)."""
    d = {}
    try:
        with open(path, 'rb') as fh:
            blob = fh.read(CARD * ncards)
    except OSError:
        return d
    for i in range(0, len(blob) - CARD, CARD):
        try:
            c = blob[i:i + CARD].decode('ascii', 'replace')
        except Exception:
            continue
        if c.startswith('END'):
            break
        if '=' in c:
            k, v = c.split('=', 1)
            d[k.strip()] = v.split('/')[0].strip().strip("'\"")
    return d


def _num(d, *names):
    for n in names:
        if n in d:
            try:
                return float(d[n])
            except (ValueError, TypeError):
                continue
    return None


def fs_from_header(path):
    """Sample rate from TBIN (1/TBIN), or None if the header is unreadable."""
    t = _num(read_header(path), 'TBIN')
    if t is None or t <= 0:
        return None
    return 1.0 / t


def geometry_from_header(path):
    """(freq_mhz, bw_mhz, nchan, npol, nbits, blocksize, samples_per_block)."""
    d = read_header(path)
    freq = _num(d, 'OBSFREQ')
    bw = _num(d, 'OBSBW')
    nchan = _num(d, 'OBSNCHAN', 'NCHAN')
    npol = _num(d, 'NPOL')
    nbits = _num(d, 'NBITS')
    bs = _num(d, 'BLOCSIZE')
    spb = None
    if bs and nchan and npol and nbits:
        bpt = nchan * npol * nbits / 8.0
        if bpt > 0:
            spb = int(bs // bpt)
    conv = lambda v: int(v) if v is not None else None
    return (freq, bw, conv(nchan), conv(npol), conv(nbits),
            conv(bs), spb)


def git_rev(root):
    """Short git revision of the working tree, or 'nogit'."""
    try:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=10,
                           cwd=root)
        rev = (r.stdout or '').strip()
        if not rev:
            return 'nogit'
        d = subprocess.run(['git', 'status', '--porcelain'],
                           capture_output=True, text=True, timeout=10,
                           cwd=root)
        if (d.stdout or '').strip():
            rev += '-dirty'
        return rev
    except Exception:
        return 'nogit'


def write_manifest(path, info):
    """Write path + '.manifest.json' recording how an output was produced."""
    info = dict(info)
    info.setdefault('timestamp', time.strftime('%Y-%m-%d %H:%M:%S'))
    try:
        info.setdefault('git_rev', git_rev(os.getcwd()))
    except Exception:
        info.setdefault('git_rev', 'nogit')
    mp = path + '.manifest.json'
    try:
        with open(mp, 'w') as f:
            json.dump(info, f, indent=1)
    except OSError:
        return None
    return mp
