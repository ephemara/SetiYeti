# Data acquisition — high-value SETI targets from the Breakthrough Listen archive

**Date:** 2026-09 · **Destination:** `D:/data/` (external 1 TB tier) · **Status:** pulling

---

## 1. How to get BL data without AWS

The repo notes said the archive is on **AWS S3, requester-pays** (needs
credentials + egress). That is only half the story. The previous Kepler pull
actually came from a **public HTTP mirror**, and the whole archive is reachable
through the **BL Open Data Archive API** — no AWS account, no credentials:

```
https://seti.berkeley.edu/opendata/api/list-targets
https://seti.berkeley.edu/opendata/api/query-files?target=<T>&file-types=baseband%20data&limit=N
```

`query-files` returns target, telescope, UTC, MJD, RA/Dec, centre frequency,
size, quality and a **direct download URL** for every file. File types are
`baseband data` (raw voltage), `filterbank`, `HDF5`, `data`. We want
**`baseband data`** — that is what the pipeline ingests.

Two hosts serve the files:

| host | speed (single conn) | speed (aria2c −x16) |
|---|---|---|
| `storage.googleapis.com/gbt_guppi/` | ~65 MB/s | ~65 MB/s |
| `blpd0.ssl.berkeley.edu` | ~4 MB/s | **~90 MB/s** |
| `bldata.berkeley.edu`, `blpd12` | — | (GC / HDF5) |

The blpd servers cap a *single* connection but not the total — **aria2c with
`-x16 -s16` gets ~90 MB/s from them.** That is the key trick; a plain `curl`
would make the archive look unusably slow.

---

## 2. The Galactic Center — the bad news

**There is no raw voltage for the Galactic Center.** The BL Galactic Center
Survey (`BLGCSURVEY_CBAND_*`, AGBT19B_999_06) was recorded with the *spliced
GPU spectrometer*: 16 banks combined into spectrograms. The archive holds only
**filterbank** files for it. Likewise the GC-region source **Sgr B2**
(`DIAG_SGR_B2`) is **HDF5** spectrograms.

I confirmed this by querying every plausible GC target:

| target | file type | note |
|---|---|---|
| `BLGCSURVEY_CBAND_A00…C12` | filterbank | 1.9–495 GB spliced spectrograms |
| `BLGCSURVEY_J1744-1134` | filterbank | |
| `DIAG_SGR_B2` | HDF5 | `data` dataset shape (55, 1, 315392) float32 |
| `SGR_A`, `GALACTIC_CENTER` | — | no entries |

I downloaded samples anyway so the data is on hand:
- `D:/data/gc/gc_C07_sample.fil` — 1.9 GB, GC C-band filterbank
- `D:/data/gc/spliced_…_SGR_B2_*.h5` — 5 files, ~6 GB, Sgr B2 spectrograms

**These are spectrograms, not voltage.** The current pipeline cannot use them
(it keeps phase). A GC campaign needs a new spectrogram/filterbank front-end
(`blimpy`/`sigproc` + a fine-grained line search). That is a real capability
gap, and the GC is exactly where you'd want it.

---

## 3. What *is* available as raw voltage — and why I picked it

87 targets in the archive have baseband. They fall into four SETI-relevant
classes:

1. **Nearby stars (the gold standard).** ~35 `HIP` targets, each with an
   **ON + OFF cadence pair** — the single most important test in the pipeline
   (a signal only in ON is celestial; in both, it is local). Mostly L-band
   1593.75 / 1781.25 MHz (water-hole region) and C-band 6281.25 MHz.
2. **M31 / Andromeda** (`MESSIER031`, 1516 files) — the nearest galaxy, an
   intergalactic-beacon target. 2-bit, X-band 9281.25 MHz.
3. **Voyager 1** (169 files) — our own spacecraft; a **known** transmitter,
   ideal for validating a detector end-to-end.
4. **Pulsars** (`PSR_J2326+6113`, `PSR_J2321+6024`, …) — periodic broadband
   sources, for proving the transient/dedispersion path.

### Curated pull — 88 files, 436 GB

`D:/data/download_manifest.csv` (full index: `D:/data/archive_baseband_index.json`)

| class | targets | files |
|---|---|---|
| nearby-star ON/OFF pairs | 34 stars | 68 |
| deep single star | HIP113357 (8-bit L-band, 1406.25 MHz) | 6 |
| nearest galaxy | MESSIER031 (M31) | 12 |
| spacecraft calibration | VOYAGER1 | 3 |
| pulsars | PSR_J2326+6113, PSR_J2321+6024 | 4 |
| star-forming region | W3 | 2 |

Total 436 GB — comfortably inside the 1 TB tier. Downloaded with:

```bash
aria2c -i /d/data/aria_input.txt -d /d/data/raw -j3 -x16 -s16 \
       --file-allocation=none --continue=true
```

---

## 4. Notes for the pipeline

- The nearby-star / M31 files are **2-bit** (`blc2_2bit_…`), layout **0**
  (time-major `[t][chan][pol]`). `seti_slice.c` already handles this; the
  hand reader in `reports/handcrafted/handraw.py` detects it too.
- `HIP113357` files are **8-bit** (layout 2), same family as the Kepler data.
- X-band (8.5–9.3 GHz) is a new band for the pipeline — the RFI landscape and
  the receiver roll-off differ from L-band; **run a bandpass/quality recon
  before trusting any detector there.**
- The 2-bit files are ~4.2 GB each (~23 s of sky at 187.5 MHz); the 8-bit
  HIP113357 files are ~16.9 GB each.

---

## 5. Status

- **Raw voltage:** pulling in the background to `D:/data/raw/` (~45 GB in as of
  this writing; verified headers on the first files).
- **GC / Sgr B2:** spectrogram samples on disk under `D:/data/gc/`.
- **Manifest + archive index:** staged at `D:/data/`.

### Obvious next pulls (not yet queued)
- The rest of the `HIP` nearby-star sample (the archive has 5000+ more baseband
  files) — a proper all-sky nearby-star survey.
- `MESSIER031X` (offset field for M31) to complete that ON/OFF.
- The full `W75N` and `W3` sets.
- `HIP113357`'s full 8-bit set once we know which scan pairs are useful.
