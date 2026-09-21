# UNIVERSAL INGEST — analyze just about anything

SetiYeti ingests by **format**, analyzes by **physics**. `python/univ_ingest.py`
sniffs any input and delivers ONE canonical stream; `python/univ_scan.py`
runs the battery on it; `python/satpass.py` checks what metal was overhead.

## Format table (prove: `univ_ingest.py --prove`, 13/13 round-trips)

| input | reader | kind | battery | notes |
|---|---|---|---|---|
| GUPPI `.raw` | `guppi_raw` (via `c/seti_slice`, never reimplemented) | voltage | FULL | header TBIN/OBSFREQ wins; `--pol` |
| SigProc `.fil` | `filterbank_fil` (dependency-free header parser) | power | SPECTRAL subset | phase was discarded at record time |
| HDF5 `.h5` (blimpy) | `filterbank_h5` (needs `h5py`) | power | SPECTRAL subset | `fch1`/`foff`/`tsamp` attrs honored |
| HDF5 other | `generic_h5` | heuristic + `--hint` | depends | largest numeric dataset; heuristic logged |
| FITS | `fits` (needs `astropy`) | ndim heuristic + `--hint` | depends | CTYPE/CRVAL mapped when present |
| WAV | `wav` (stdlib `wave`) | voltage | FULL | no sky frequency (caveat logged) |
| raw I/Q `.cfile/.cf32/.cu8/.cs8/.cs16/.iq/.bin` | `raw_iq` | complex → canonical real = I | FULL on I | **`--fs` REQUIRED (guessing forbidden)** |
| numpy `.npy/.npz` | `npy` | heuristic + `--hint` | depends | |
| CSV spectra | `csv` | power (2-col) / voltage (1-col + caveat) | depends | |
| native `.f32` | `f32` | voltage | FULL | zero-copy path |

**Dispatch rule** (mirrored in `z3/smt2/ingest_dispatch.smt2`, tied by
`z3/verify_ingest.py` 2000/2000): container magic wins for self-describing
formats; GUPPI needs ASCII cards; SigProc needs a validating header parse;
headerless raw-IQ trusts the extension and **refuses without `--fs`**;
anything else is a clean error suggesting `--reader`, never a silent guess.

**Kind contract:** `voltage`/`complex` → FULL battery (every C tool + python
detector via a canonical `.f32` handoff). `power` → SPECTRAL subset only
(spectrum peak, fold, scint-class, pulse hunters on long envelopes) and the
grade honestly caps at I2 — nothing needing phase is attempted. Verified
format-invariant: the same slice as WAV and NPY scores bit-identical
batteries (fam 91.09, comb+thicket, fold); as FIL and H5 it agrees on kind
with the phase-needing markers abstaining, not faking.

## Adding a format (checklist)

1. `read_<name>()` in `univ_ingest.py` returning `(meta, array)` with
   `base_meta()` + honest `caveats`.
2. Extension + magic in `detect_format()` (magic first if self-describing).
3. Mirror both in `z3/smt2/ingest_dispatch.smt2` + `verify_ingest.py` model.
4. Round-trip leg in `prove()` (synthesise → write → read → compare).
5. Row in this table. No threshold ships without a noise receipt (AGENTS.md 1).

## Satellite conjunction (`satpass.py`, 6/6 prove)

TLE propagation (open-source `sgp4`, the only pip add: `pip install sgp4`)
over an observation window for GBT/Parkes/MeerKAT/VLA/FAST or custom
`--lat/--lon`. Offline-first: hand-rolled GMST + topocentric math
(arcminute-grade, cross-checked vs astropy to 0.0003°).

- `--at ISO --dur S --site GBT` → passes above the mask (rise/TCA/set).
- `--guppi-at FILE.raw --block N` → exact UTC of that block from the
  STT_IMJD/SMJD header clock (verified: Kepler b21 → 2020-09-11T00:33:08,
  matching SMJD arithmetic).
- **Staleness guard**: TLEs >30 days from query time print an explicit
  warning (measured failure mode: 2026 elements at a 2020 timestamp return
  lunar-distance LEO ranges — confidently wrong unless flagged).
- `--update-tle --group stations|noaa|goes|gps-ops|iridium` fetches
  Celestrak when online; everything else works offline.

Status: attribution **evidence**, not a veto rule. Satellite-overhead does
not prove RFI (sidelobes and the bystander case complicate it), but
satellite-absent removes one mundane hypothesis per flag. Wiring it into
veto scoring needs a calibration campaign (TLE archive + measured
sidelobe response) — follow-up, not this pass. Historical note: 2020-era
attribution needs archive elements (space-track.org); current TLEs at old
timestamps are garbage, and the tool says so out loud.

## Pip surface (all open-source)

Already required: `numpy h5py astropy scipy`. New: **`sgp4`** (added to
`requirements-science.txt`). Everything else is stdlib. No compilers, no
licenses, no accounts.
