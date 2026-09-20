# data/

Raw and derived signal files live here. **None of it is committed** — the folder
is ~2.5 GB and every file is either re-downloadable or regenerable. `.gitignore`
excludes `*.raw`, `*.f32`, `*.bin`, `*.png` and `mvp_tmp/`.

## Getting raw files

Breakthrough Listen's archive is on **AWS S3 and is requester-pays** — you pay
egress. Authenticate first (`aws configure`), then:

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
