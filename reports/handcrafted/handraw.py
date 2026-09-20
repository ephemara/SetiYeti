"""handraw.py — hand-crafted GUPPI RAW reader. No C tools, no pipeline.

Parses the FITS-style header per block, memory-maps the payload, and exposes
per-channel / per-pol voltage so we can look at the data directly.
"""
import os, numpy as np

def parse_header(f, off=0, maxread=131072):
    f.seek(off)
    d = f.read(maxread)
    # cards are 80 bytes until 'END'
    kv = {}
    i = 0
    end = None
    while i + 80 <= len(d):
        c = d[i:i+80]
        s = c.decode('latin1')
        key = s[:8].strip()
        if key == 'END':
            i += 80
            end = i
            break
        if len(key) and s[8:10] == '= ':
            val = s[10:].split('/')[0].strip()
            kv[key] = val
        i += 80
    return kv, end

def geom(kv):
    nchan = int(float(kv.get('OBSNCHAN', kv.get('NCHAN', 64))))
    npol  = int(float(kv.get('NPOL', 4)))
    nbits = int(float(kv.get('NBITS', 8)))
    blocsize = int(float(kv['BLOCSIZE']))
    tbin = float(kv.get('TBIN', 3.41333333333333e-07))
    freq = float(kv.get('OBSFREQ', 0.0))
    bw   = float(kv.get('OBSBW', 0.0))
    return dict(nchan=nchan, npol=npol, nbits=nbits, blocsize=blocsize,
                tbin=tbin, freq=freq, bw=bw)

class Raw:
    def __init__(self, path):
        self.path = path
        self.size = os.path.getsize(path)
        with open(path, 'rb') as f:
            self.kv, self.hdr0_end = parse_header(f)
        g = geom(self.kv)
        self.__dict__.update(g)
        # header stride: solve from file size. Assume constant stride.
        # stride = hdr + blocsize ; nblocks = size/stride
        # try candidate header sizes (padding to 256 or 2880)
        best = None
        for hdr in range(6400, 9000, 16):
            stride = hdr + self.blocsize
            if self.size % stride == 0:
                best = (hdr, stride, self.size // stride)
                break
        if best is None:
            # fall back: header from END offset, stride = blocsize + padded header
            hdr = self.hdr0_end
            while hdr % 256: hdr += 1
            stride = hdr + self.blocsize
            best = (hdr, stride, self.size // stride)
        self.hdr, self.stride, self.nblocks = best
        self.ntime = self.blocsize // (self.nchan * self.npol) if self.nbits == 8 else \
                     self.blocsize // (self.nchan * self.npol // 4) if self.nbits == 2 else None
        self.fs = 1.0 / self.tbin
        self.dur = self.ntime * self.tbin
        self.chan_bw = abs(self.bw) / self.nchan

    def block_bytes(self, b):
        with open(self.path, 'rb') as f:
            f.seek(b * self.stride + self.hdr)
            return f.read(self.blocsize)

    def block(self, b, pol=None, chan=None):
        """Return float32 array. Shape:
           pol/chan None -> (ntime, nchan, npol)
           chan given     -> (ntime, npol)
           pol given      -> (ntime, nchan)
           both           -> (ntime,)"""
        raw = np.frombuffer(self.block_bytes(b), dtype=np.uint8)
        if self.nbits == 8:
            a = raw.view(np.int8).astype(np.float32)
            a = a.reshape(self.ntime, self.nchan, self.npol)
        else:
            # 2-bit packed: 4 pols per byte, time-major
            codes = np.array([-3.34, -1.0, 1.0, 3.34], dtype=np.float32)
            sh = np.array([0, 2, 4, 6], dtype=np.uint8)
            bits = (raw[:, None] >> sh[None, :]) & 0x3
            a = codes[bits].reshape(self.ntime, self.nchan, self.npol)
        if pol is not None and chan is not None:
            return a[:, chan, pol]
        if pol is not None:
            return a[:, :, pol]
        if chan is not None:
            return a[:, chan, :]
        return a

    def chan_freq(self, ch):
        """Sky frequency of coarse channel ch (MHz).
        OBSFREQ is the band CENTRE; negative OBSBW => ch0 is high."""
        return self.freq - self.bw / 2.0 + self.bw * (ch + 0.5) / self.nchan

    def pktidx(self, b):
        with open(self.path, 'rb') as f:
            kv, _ = parse_header(f, b * self.stride, 8192)
        return kv

if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        r = Raw(p)
        print('='*70)
        print(os.path.basename(p))
        print(f"  src={r.kv.get('SRC_NAME')}  nchan={r.nchan} npol={r.npol} nbits={r.nbits}")
        print(f"  freq={r.freq} MHz  bw={r.bw}  chan_bw={r.chan_bw:.6f} MHz")
        print(f"  hdr={r.hdr} stride={r.stride} nblocks={r.nblocks} ntime/block={r.ntime}")
        print(f"  fs={r.fs/1e6:.6f} MHz  block={r.dur*1000:.3f} ms  total={r.nblocks*r.dur:.2f} s")
        print(f"  ch0={r.chan_freq(0):.4f} MHz  ch63={r.chan_freq(63):.4f} MHz")
