# AGENTS.md — SetiYeti

Onboarding + operating rules for any AI agent working in this repository.
Read this before touching code or data.

> **START HERE: `_objective/objective_1.md`** — the mission.
> This file describes *how to work in this repo*. The objective file describes
> *what we are hunting and why* (bystander traffic, monuments from extinct
> civilisations, and payloads). If a task does not serve Objective 1, say so.
>
> Key consequence of Objective 1: **a signal present in both ON and OFF
> pointings is NOT automatically local.** Third-party links and omnidirectional
> monuments appear in both. `rfi_veto.py` was rewritten (2026-09) to score
> *engineeredness* rather than auto-blocking common-mode — see the two-axis
> model (EARTH / STRUCTURE) below.

---

## What SetiYeti is

SetiYeti is an **unsupervised signal-analysis pipeline for raw radio telescope
baseband**. It ingests complex `I/Q` voltage (GUPPI `.raw`), keeps phase
instead of squaring it into a spectrogram, searches **modulation space** rather
than only narrowband tones, and automatically blocks terrestrial interference.

Legacy SETI tooling (`turboSETI` et al.) reduces voltage to a 2D intensity
spectrogram and hunts narrow tones drifting in a straight line. That is a good
filter for one class of signal and blind to several others. SetiYeti exists to
cover the ones it misses:

| Blind spot | Why legacy pipelines miss it |
|---|---|
| Sub-noise spread spectrum (DSSS) | Squaring voltages destroys phase; a spread beacon below the thermal floor is indistinguishable from Gaussian noise to a total-power detector. |
| Non-linear drift (jerk, orbit, tumble) | Matched filters assume constant `dν/dt`; curved tracks smear below threshold. |
| Chirped / dispersed transients | A signal sweeping faster than the FFT integration never concentrates in one bin. |
| Engineered bit structure | Nobody demodulates candidates and asks whether the bits *compute*. |

Each is a measurable capability gap. The prove harnesses quantify exactly where
each detector's floor is.

**Guiding principle:** *a negative is a result only if it comes with a
noise-matched receipt.* Every detector is validated by injecting a known signal
into backend-matched quantized noise and confirming the detector fires while the
same test on noise alone stays quiet. No threshold ships without calibration.

---

## Pipeline

```
 .raw  (GUPPI: FITS-style header + binary payload, 2- or 8-bit)
   │   c/seti_slice.c        header-parsed geometry, bit-depth-aware unpack
   ▼
 .f32  (one coarse channel ≈ 2.93 MHz of real voltage)
   │
   ├── python/mvp_scan.py    direct FFT peak-hunt + Welch averaging (first sieve)
   ├── c/fam_scan.c          Y²/Y⁴ cyclostationary scan (the f=0 SCD slice)
   ├── python/scd_frf.py     full (α, f) SCD plane + dechirp bank
   ├── python/jerk_scan.py   Viterbi track-before-detect + quadratic motion fit
   ├── python/bitslice.py    sign / transition bitstreams ──► c/vm_sandbox.c
   │                                                          (SUBLEQ locality + Golay G₂₄)
   ▼
 hits.csv ──► python/rfi_veto.py ──► BLOCK / WATCH / CANDIDATE
                    │                  (band allocation, α zone, persistence,
                    │                   channel coincidence, VM structure, catalog)
                    ▼
              python/latent_pca.py ──► outlier ranking across the whole corpus
                    │
                    ▼
              houdini/export_triage.py ──► 3D waterfall terrain (appeal court)
```

---

## Repo layout

```
c/          C99 tools, zero dependencies — raw unpacker, cyclo scanner, VM sandbox
python/     detectors, prove harnesses, RFI veto, latent triage
houdini/    triage terrain exporter + Houdini shelf script (appeal court only)
data/       raw + derived signal files — GITIGNORED, see data/README.md
spec.md     original design brief
README.md   what is actually built + proven results
hits*.csv   per-observation scan results — THIS IS THE SCIENTIFIC RECORD
rfi_catalog.json   accumulated interference signature catalog
```

### Storage tiers

Two drives, deliberately split:

- **`E:/SetiYeti/data/`** — the small working set that lives beside the code.
  Gitignored, ~2.5 GB.
- **`D:/data/`** — external **1 TB** overflow tier (added 2026-09), **outside
  the repo** so nothing there is ever committed. Holds the archive:
  `D:/data/raw/` (GUPPI downloads), `D:/data/slices/` (`seti_slice` `.f32`
  extractions + power series), `D:/data/derived/` (`.npz`/`.npy`/`.csv`
  intermediates). See `D:/data/README.md`.

Rule of thumb: raw downloads land on `D:/data/`; only the current working set
sits on `E:`. **Never hardcode a `D:/` path in committed code** — take a
`--data-dir` / `$SETIYETI_DATA` so the repo still runs when the drive is
unplugged. Disk is not infinite (~58 GUPPI files); prune intermediates after a
write-up, keep the `.raw`.

---

## Build & run

```bash
# Build the C tools (C99, no deps beyond -lm)
gcc -O3 -o c/seti_slice c/seti_slice.c -lm
gcc -O3 -o c/fam_scan   c/fam_scan.c   -lm
gcc -O3 -o c/vm_sandbox c/vm_sandbox.c -lm

# ALWAYS prove detectors before trusting them on data
python python/dsss_prove.py          # spread spectrum at −12 dB
python python/jerk_scan.py --prove   # drift + jerk at −35 dB
python python/scd_frf.py --prove     # baud comb + chirp de-smear
python python/latent_pca.py --prove  # latent triage sensitivity/specificity

# Scan a file (stride channels to keep it cheap)
python python/mvp_scan.py --raw data/<file>.raw --b0 0 --b1 48 --chans 0,8,16,24,32,40,48,56

# Disposition every flag before a human reads it
python python/rfi_veto.py --hits hits.csv --evidence evidence.csv --target M31

# Rank the corpus for outliers
python python/latent_pca.py --slices hits.csv
```

Python 3.12+, `numpy` required. `scipy`/`matplotlib` optional (matplotlib only
for waterfall PNGs). C tools are dependency-free.

---

## Non-negotiable rules

1. **Prove before detect.** Any new detector or threshold change must ship with
   an injection prove that shows it fires on the target class *and* stays quiet
   on matched noise. Report the floor.
2. **Noise-matched calibration.** Thresholds come from realizations of the same
   quantized noise as the data, not from theory or a single noise run. Use
   median-relative ratios, not raw magnitudes.
3. **The veto runs before humans.** Every flag in `hits.csv` gets scored and
   dispositioned by `rfi_veto.py`. Never delete or hide a flag — the catalog
   learns from it.
4. **Verdicts are capped by evidence.** A single pointing can never exceed
   `WATCH`. Only an ON–OFF cadence pair promotes `WATCH → CANDIDATE`. There is
   currently no cadence-pair code, so **no CANDIDATE can be legitimately issued
   from a single file.**
5. **`hits.csv` / `evidence.csv` / `rfi_catalog.json` are the scientific
   record.** Treat them as append-only truth. Don't rewrite history; add rows.
6. **Raw data is never committed.** `.raw/.f32/.bin/.png` are gitignored. S3 is
   requester-pays — see `data/README.md`. Bulk raw/derived files go on the
   external **`D:/data/`** tier (1 TB, outside the repo), not on `E:`.
7. **Don't overclaim.** This is a blind-spot specialist, not a survey. Known
   winners: spread spectrum, jerk/chirp, bit structure. Known losers: stable
   narrowband (turboSETI is better), pulsars/FRBs (not built yet).

---

## Hard-won lessons (do not rediscover these)

- **One-sided SCD is blind to `2f₀` lines.** The SCD plane must be
  two-sided. This was found in the math; don't "simplify" it back.
- **Dark digitizers create false Golay hits.** Zero-runs pass Golay syndrome
  trivially (all-zero word → zero syndrome → "100% hit"). `vm_sandbox.c` now has
  an **entropy gate** (ones-fraction + code diversity) that refuses to score
  low-entropy input. Never remove it.
- **Quarantine bad lanes before analysis.** `seti_slice.c` reports per-lane RMS
  + range/diversity; a dark digitizer (few distinct codes, low RMS) must be
  quarantined, not scanned. See `hits_hip_b6.QUARANTINED.csv`. Phantom flags
  must never reach the veto or catalog.
- **Windows cost coherent gain.** Hamming/Blackman windows cost ~8 dB of
  coherent integration in the track-before-detect path. That path uses a
  **rectangular** window on purpose.
- **Thresholds need multiple noise realizations**, not one, or the floor is
  fitted to a single draw.
- **Backend wander is a real trap with a fingerprint:** multi-channel
  coincidence + polarization-divergent peaks + window-unstable frequency = local
  receiver drift, not sky. Square-law detection turns that breathing into fake
  cyclic lines. `rfi_veto.py` has a common-mode rule for exactly this.
- **Cyclic-frequency zone is diagnostic.** `1 Hz–2 kHz` α is where
  rotation-powered astrophysics lives. `100 kHz–5 MHz` α is where electronics
  live. A MHz-rate α from a single block is almost certainly human.
- **There is a DC-residual artifact at ~45 Hz** that appears in every full-span
  run. Discount it; don't chase it.
- **`scoop list <pkg>` false-positives.** (VPS setup) It prints the package name
  in its "could not find" message, so a naive `Select-String` helper thinks
  every package is installed. Check exit status / actual install, not text.

---

## Status

See `README.md` for the full scorecard. Summary:

- **Real:** I/Q ingestion, f=0 cyclostationary, full SCD + dechirp, Viterbi
  non-linear tracking, Golay/VM structure, RFI veto + catalog, latent triage.
- **Substitute:** Neural ODE replaced by Viterbi TBD (MLP could not beat it on
  spike-riding energy; dead ends documented in `neural_track.py`).
- **Missing (priority order):**
  1. Periodicity / folding search (1 Hz–2 kHz) — pipeline is deaf to pulsars.
  2. Single-pulse + DM sweep — no FRB-class coverage.
  3. ON–OFF cadence pairing — the gate that unlocks CANDIDATE.
  4. Full-polarization sweeps.
  5. Parallel scanning (`mvp_scan` is embarrassingly parallel).

---

## Conventions

- **C** in `c/`: C99, no external deps, `-lm` only. Comment the *why*, keep the
  hot loop clean. Deterministic, no I/O in inner loops.
- **Python** in `python/`: stdlib + `numpy` (optional `scipy`/`matplotlib`).
  Every detector file should carry a `--prove` path or a sibling prove script.
- **New detector checklist:** prove harness → noise floor number → integrate
  into `mvp_scan`/`hits.csv` schema → veto rule → README status row.
- **Naming:** raw files follow
  `blc<N>_<2bit|8bit>_guppi_<MJD>_<TARGET>_<SCAN>.<NNNN>.raw`. `blcN` = a
  different 187.5 MHz node on the *same* observation; same MJD+TARGET = same
  pointing. Comparing bands requires reading the bank number.
- **Houdini** is an appeal court, not a primary sieve. Only already-flagged
  slices get terrain.

---

## What "found something" looks like

No single detector firing is a detection. The jackpot signature is **all of**:
FAM fires where the spectrum is silent → VM sandbox goes red (Golay hit rate
near 1.0, memory-access locality clustered) → persistence holds across blocks
and vanishes in OFF pointings → the veto fails to kill it (rotation-band α,
non-terrestrial drift, multi-channel structure) → latent triage ranks it
isolated at the top. Any one is a curiosity; all five have no known natural or
human explanation.

Until then, the honest output is upper limits with receipts.



## Critical

If helping the user and or scanning files, don't just run this pipeline and say "all done the csv files are here"!
Analyze all data critically and report back to the user with what you found. Tell them all the weird shit in the data
Tell them if anything novel arose, Tell them if anything is worth inspecting and taking a deeper look at. 
Break down your findings on what they mean on a universal level as well. "Oh we got this data back and it looks like a pulsar spinning"
"We found this data and this is definitely something not currently present in the current paradigm of astronomy"
"We found this and believe this could be the definitive answer to interstellar communication"

This is the kind of agentic assistance we need, not boilerplate heres your csv files, you can scan them now. Half of your work here should be 
mission critical analysis with proof and following up on proof. Try and report back to the user if anything novel was found as well -
Assume they are an outsider to this field, so they need help understanding if something truly novel was found which is where you come in.

The key of it all is - This pipeline only exist, because the user is an outsider to the field of astronomy. If they were not an outsider, 
this would be a basic, drab boilerplate linear analysis codebase like everything else out there.
