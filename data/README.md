# data/

Raw and derived signal files live here. **None of it is committed** — the folder
is ~2.5 GB and every file is either re-downloadable or regenerable. `.gitignore`
excludes `*.raw`, `*.f32`, `*.bin`, `*.png` and `mvp_tmp/`.

## Getting raw files

**Do not go to AWS S3 first.** The archive is *also* on S3 requester-pays
(needs credentials + egress), but there is a public JSON API and public HTTP
mirrors with **no account and no payment**. Use the wrapper:

```bash
# what targets exist
python python/bl_download.py targets --grep 'SGR|HIP|MESSIER'

# inspect files for a target (no download)
python python/bl_download.py query --target MESSIER031 --file-types 'baseband data' --limit 8

# download (aria2c -x16: ~90 MB/s from blpd0, ~65 MB/s from Google)
python python/bl_download.py get --target HIP57328 --file-types 'baseband data' \
    --limit 4 --outdir D:/data/raw --jobs 3 --conns 16

# or replay a saved manifest
python python/bl_download.py from-manifest D:/data/download_manifest.csv --outdir D:/data/raw
```

Speed notes: a single `curl` to `blpd0.ssl.berkeley.edu` is only ~4 MB/s; the
same file with **aria2c `-x16 -s16`** is ~90 MB/s. The wrapper uses aria2c when
it is on PATH and falls back to single-threaded urllib (with a loud warning)
otherwise. `file-types` are `baseband data` (raw voltage), `filterbank`,
`HDF5`, `data`. See `python/bl_download.py --help`.

If you really want the S3 route:

```bash
aws s3 ls --request-payer requester s3://breakthrough-listen/
aws s3 cp --request-payer requester s3://breakthrough-listen/<key> data/
```

Expect ~100 MB–2 GB per file depending on node, band and bit depth.

## Naming convention

```
blc<N>_<2bit|8bit>_guppi_<MJD>_<TARGET>_<SCAN>.<NNNN>.raw
 │        │            │      │         │        └─ sequence number
 │        │            │      │         └─ scan id
 │        │            │      └─ source name as typed at the telescope
 │        │            └─ modified Julian date of the observation
 │        │
 │        └─ quantization of this node's digitizer
 └─ "bank" — a compute node covering one 187.5 MHz sub-band
```

`blc2`, `blc4`, `blc6` … are **independent nodes on the same observation**,
each holding a different 187.5 MHz window. Same `MJD` + `TARGET` = same pointing.
This matters: comparing bands, or discovering one node was misbehaving, requires
reading the bank number.

## File format (GUPPI RAW)

An ASCII FITS-style header (80-byte cards, padded to a 2880-byte multiple)
followed by a binary payload, repeated once per block. Header card count varies
per block, so **offsets must be parsed, never assumed**. `c/seti_slice.c` does
this and reads geometry (`NBITS`, `NPOL`, `OBSNCHAN`) from the header itself.

Fields worth knowing:

| Card | Meaning |
|---|---|
| `SRC_NAME` | target source |
| `OBSFREQ` | centre frequency, MHz |
| `OBSBW` | total bandwidth, MHz (187.5 here) |
| `OBSNCHAN` | coarse channels (64) |
| `CHAN_BW` | bandwidth per coarse channel, MHz (2.9296875) |
| `NPOL` | real-valued polarizations (4) |
| `NBITS` | bits per real sample (2 or 8) |
| `TBIN` | seconds per sample (3.413e-07) |
| `BLOCSIZE` | payload bytes in this block |
| `PKTIDX` | packet index — advances per block, use it to detect dropped data |

Payload layout differs by bit depth, and both are implemented in `seti_slice`:

```
2-bit  byte[t*64 + chan]   bits [1:0]=pol0 [3:2]=pol1 [5:4]=pol2 [7:6]=pol3
                           codes 00→-3.34  01→-1.0  10→+1.0  11→+3.34
8-bit  byte[t*256 + chan*4 + pol]   signed int8 per real sample
```

`TBIN` × samples-per-block gives block duration — **0.176 s** for the files below,
which is why a 1.5 GB file is only ~8.6 s of sky.

## Observation cadence (ON–OFF)

Targets are observed in an `A B A B A B` pattern: `A` points at the source, `B`
points ~1° away at blank sky. A signal present only in the `A` files is
celestial; present in both, it's local. **This is the single most important
test in the whole pipeline** and it requires two files per claim.

## Files used so far

| File | Bank | Freq | Bits | Size | Sky |
|---|---|---|---|---|---|
| `blc2_2bit_guppi_57396_MESSIER031_0056.0002.raw` | 2 | 9281.25 MHz | 2 | 1.5 GB | M31, X-band |
| `blc2_2bit_guppi_57396_VOYAGER1_0002.0013.raw` | 2 | 9281.25 MHz | 2 | 63 MB | Voyager 1 coords |
| `blc4_guppi_57388_HIP113357_0014.0013.raw` | 4 | 1406.25 MHz | 8 | 253 MB | HIP 113357, L-band |
| `blc6_guppi_57388_HIP113357_0014.0013.raw` | 6 | 1031.25 MHz | 8 | 253 MB | same obs, dark digitizer |

Note the Voyager file: its band is ~800 MHz above Voyager 1's actual 8.415 GHz
downlink, so a null result there is arithmetic, not a search failure.
