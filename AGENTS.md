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

> **Verdicts are earned, not assumed.** The default disposition of an anomaly
> is `UNEXPLAINED`, not `EARTH`. Common-mode is a category, not a curse — the
> veto's job is to grade engineeredness, never to launder a prior as a result.
> "This looks like the interference everyone else found" is not an argument:
> our null history is explained by ~2% dwell and beacon-based aiming, and the
> target class is *engineered to look like noise*.

---

## What SetiYeti is

SetiYeti is an **unsupervised signal-analysis pipeline for radio signals in
just about any format**. It ingests GUPPI `.raw`, SigProc `.fil`, HDF5 `.h5`,
FITS, WAV, raw I/Q (GNU Radio / rtl-sdr / HackRF), numpy and CSV
(`python/univ_ingest.py` → one canonical stream), keeps phase
instead of squaring it into a spectrogram, searches **modulation space** rather
than only narrowband tones, grades every slice I0–I5
(`INTERSTELLAR_HIT_CRITERIA.md`), and automatically blocks terrestrial
interference.

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
| Dense intermod thickets | A forest of backend lines puts energy in every SCD bin, so top-N peak lists hallucinate harmonic combs (measured: comb score 1940 on pure thicket). Fenced by line-density (`thicket` rule), not by peak shape. |

Each is a measurable capability gap. The prove harnesses quantify exactly where
each detector's floor is.

**Guiding principle:** *a negative is a result only if it comes with a
noise-matched receipt.* Every detector is validated by injecting a known signal
into backend-matched quantized noise and confirming the detector fires while the
same test on noise alone stays quiet. No threshold ships without calibration.

---

## Pipeline

```
 anything  (GUPPI .raw / filterbank .fil / HDF5 .h5 / FITS / WAV / raw I-Q /
             numpy / CSV — python/univ_ingest.py sniffs → one canonical stream;
             voltage/complex get the FULL battery, detected power gets an
             honest SPECTRAL subset. See UNIVERSAL_INGEST.md.)
   │   c/seti_slice.c        GUPPI leg: header-parsed geometry, bit-depth-aware
   │                         unpack (other formats: their own readers, same contract)
   ▼
 .f32  (one coarse channel ≈ 2.93 MHz of real voltage)
   │
   ├── python/mvp_scan.py    direct FFT peak-hunt + Welch averaging (first sieve)
   ├── c/fam_scan.c          Y²/Y⁴ cyclostationary scan (the f=0 SCD slice)
   ├── python/scd_frf.py     full (α, f) SCD plane + dechirp bank
   ├── python/jerk_scan.py   Viterbi track-before-detect + quadratic motion fit
   ├── python/bitslice.py    sign / transition bitstreams ──► c/vm_sandbox.c
   │                                                          (SUBLEQ locality + Golay G₂₄)
   ├── c/xeno_scan           SK fraction / coherence / cepstral ladder /
   │                         dispersion-order sign / impulsivity (microscopic)
   ├── c/xvm_sandbox         6-machine alien-code battery (STACK/CA110/ACF/HAM/
   │                         CRC + SUBLEQ, entropy-gated)
   ├── python/scint_pol.py   ISM scintillation + cross-pol agreement (sky markers)
   ├── python/exotic_pass.py neg-DM / clock / prime trains / precursors (bizarre)
   ├── python/pulsar_fold.py envelope FFT + harmonic sum (1 Hz–2 kHz)
   ├── python/transient_dm.py DM sweep + boxcar bank (single-pulse)
   ├── python/raster_hunt.py semiprime fold + sync search (payload framing)
   └── python/xeno_pass.py  I0–I5 interstellar grades (one per slice)
   ▼
 hits.csv ──► python/rfi_veto.py ──► BLOCK / WATCH / CANDIDATE
                    │                  (band allocation, α zone, persistence,
                    │                   channel coincidence, VM structure, catalog,
                    │                   thicket fence + comb discount)
                    ▼
              python/latent_pca.py ──► outlier ranking across the whole corpus
                    │
                    ▼
              houdini/export_triage.py ──► 3D waterfall terrain (appeal court)

 Cross-cutting: python/satpass.py (TLE conjunction, attribution evidence),
 python/cadence_pair.py (the only WATCH→CANDIDATE gate), python/corpus.py
 (the MASS-DATA library: all slices/flags/floors/proves in one SQLite DB),
 z3/ (machine-checked specs + code ties for veto, grades, dispatch, corpus,
 packing, median, comb).
```

---

## Repo layout

```
c/          C99 tools, zero dependencies — seti_slice, fam_scan, vm_sandbox,
            comb_scan (+thicket fence), xeno_scan (microscopic), xvm_sandbox
            (6-machine alien-code), jerk_track (Viterbi TBD), fold_dm
            (pulsar+DM), scd_dechirp (SCD plane+dechirp). Build with `make` (9 binaries).
python/     detectors, prove harnesses, RFI veto, latent triage,
            univ_ingest/univ_scan (any-format front-end), satpass (TLE check),
            xeno_pass (I0–I5 grades), pipeline.py / longhaul.py (orchestrators)
houdini/    triage terrain exporter + Houdini shelf script (appeal court only)
z3/         formal specs (smt2/*.smt2) + code ties (verify_*.py) — veto,
            grades, ingest dispatch, packing, median, comb
configs/    TOML presets (header geometry wins, preset fills, CLI overrides)
runs/       per-run scans/evidence/grades/REPORTs (machine-readable record)
reports/    write-ups with receipts (xeno_overhaul.md = latest full campaign)
data/       raw + derived signal files — GITIGNORED, see data/README.md
spec.md     original design brief
README.md   what is actually built + proven results
INTERSTELLAR_HIT_CRITERIA.md   what I0–I5 mean (read before grading anything)
UNIVERSAL_INGEST.md            format table + canonical-stream contract
_objective/objective_1.md      the mission (bystander traffic/monuments/payloads)
hits*.csv   per-observation scan results — THIS IS THE SCIENTIFIC RECORD
rfi_catalog.json   accumulated interference signature catalog
catalog.tsv    master ledger of EVERY sky file in storage (E:/data + D:/data):
               exact filename, target, ON/OFF, location, size, format,
               scan_status, coverage, runs evidence, result — rebuilt with
               `python python/build_catalog.py`; read it before scanning anything
archive/     retired root files (old hits_*.csv, catalog backups) — not live
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

**`catalog.tsv` is the ledger of it all.** Before scanning anything, grep
`catalog.tsv` for the exact filename — if it is already SCANNED at equal or
deeper coverage, do not rescan; if it is NOT_SCANNED, that is your target
list. OFF legs whose ON leg is already scanned are the highest-value targets
(they unlock ON–OFF cadence gating).

---

## Build & run

```bash
# Build the C tools (C99, no deps beyond -lm) — 9 binaries, never by hand:
make                # build all (seti_slice fam_scan vm_sandbox comb_scan xeno_scan xvm_sandbox jerk_track fold_dm scd_dechirp)
make check          # build + verify each binary runs + probe real-file layouts
make prove-quick    # fast gate. Full gate: make prove

# ALWAYS prove detectors before trusting them on data (34/34 green = gate)
python python/sy_prove_all.py --root . --quick   # fast gate (29 checks)
python python/sy_prove_all.py --root .           # full gate (all 34: adds dsss/scd/jerk/latent slows)

# Scan a GUPPI file (stride channels to keep it cheap)
python python/mvp_scan.py --raw data/<file>.raw --b0 0 --b1 48 --chans 0,8,16,24,32,40,48,56

# Fetch data from the BL archive (public API, no AWS creds; aria2c -x16 ~90 MB/s)
python python/bl_download.py targets --grep HIP
python python/bl_download.py query --target MESSIER031 --file-types 'baseband data' --limit 8
python python/bl_download.py get  --target HIP57328 --file-types 'baseband data' \
    --limit 4 --outdir D:/data/raw --jobs 3 --conns 16

# ...or scan literally anything (WAV/FIL/H5/FITS/I-Q/npy/CSV)
python python/univ_scan.py --in signal.wav --outdir runs/univ_wav
python python/univ_scan.py --in capture.cu8 --fs 2000000 --outdir runs/univ_rtl

# Grade top candidates I0–I5 (needs structure + evidence + OFF for full power)
python python/structure_pass.py --scan scan.csv --raw data/<file>.raw --out struct.csv
python python/xeno_pass.py --scan struct.csv --raw data/<file>.raw --out xeno.csv \
    --off scan_off.csv --evidence evidence.csv --target NAME --xpol

# Disposition every flag before a human reads it
python python/rfi_veto.py --hits hits.csv --evidence evidence.csv --target M31

# Satellite-overhead check for a flag's timestamp (attribution evidence)
python python/satpass.py --guppi-at data/<file>.raw --block 21 --dur 30 --site GBT

# Rank the corpus for outliers
python python/latent_pca.py --slices hits.csv
```

Python 3.12+, `numpy` required. `pip install -r requirements-science.txt`
adds the science stack (`h5py`/`astropy`/`scipy` + `sgp4` for satpass).
C tools are dependency-free. Windows shop: `make` needs MinGW on PATH
(`C:/scoop/apps/mingw/current/bin`), python is `C:/scoop/apps/python/current`.

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
   `WATCH`. Only an ON–OFF cadence pair promotes `WATCH → CANDIDATE`, via
   `python/cadence_pair.py` — and single-file grades from `xeno_pass.py` cap
   at I2 by construction. **No CANDIDATE can be legitimately issued
   from a single file.**
5. **`hits.csv` / `evidence.csv` / `rfi_catalog.json` are the scientific
   record.** Treat them as append-only truth. Don't rewrite history; add rows.
   `corpus/setiyeti.db` is the DERIVED query layer (one SQLite file: every
   slice, flag, floor, prove — rebuilt by `python/corpus.py --auto`, never
   committed). Query the DB, cite the record.
6. **Raw data is never committed.** `.raw/.f32/.bin/.png` are gitignored. S3 is
   requester-pays — see `data/README.md`. Bulk raw/derived files go on the
   external **`D:/data/`** tier (1 TB, outside the repo), not on `E:`.
7. **Attribution needs a receipt — symmetric burden of proof.** A detector must
   earn its negative with a noise-matched receipt; a *disposition* must earn
   its negative the same way. No flag may be called terrestrial, RFI, receiver
   artifact, or "consistent with human activity" without (a) the rule id that
   fired, (b) the numeric margin, and (c) the physical mechanism (band
   allocation, α-zone, fs/4 spur, backend-wander fingerprint, catalog match).
   "Likely RFI" with no rule id + number is refusal-worthy — like guessing
   geometry on a headerless format. If you cannot produce the receipt, the
   disposition is `UNEXPLAINED`, not `BLOCK`.
8. **Steelman the exotic first, then audit the mundane.** Before naming a
   terrestrial cause, state the best non-terrestrial explanation and the one
   measurement that would separate them. If the anomaly has structure (FAM
   fires where the spectrum is flat, a comb outside a thicket, common-mode
   *with* engineered structure), the slow path is mandatory: **open the raw
   file and inspect it** before disposition. Cheap-to-verify dismissals
   (catalog hit, exact fs/4, band-allocation match) may stay instant.
9. **Dismissals are part of the record.** A `BLOCK` on a structure-bearing flag
   is a claim we can be audited on — log its receipt (rule id, margin,
   mechanism, counter-hypothesis) to the dismissal ledger, never delete it
   quietly. Mirrors "never delete or hide a flag."
10. **The catalog is updated after every scan and every download — no exceptions.**
   Finishing a scan (or landing a new file on either drive) is not done until
   `catalog.tsv` says so:
   - `python python/build_catalog.py` rebuilds the storage inventory and
     re-joins every `runs/**/*.manifest.json` for coverage/flag counts.
   - Then hand-edit the row: exact `filename`, star system (`target`), ON/OFF
     (`pointing`), honest `scan_status` (`SCANNED_FULL` / `SCANNED_PARTIAL` /
     `SMOKE` / `NOT_SCANNED` / `QUARANTINED`), `coverage` (blocks/chans/pols),
     `runs_evidence` (the CSVs/REPORTs), and a one-line `result_summary`
     (flag counts, veto dispositions, grades — no adjectives without numbers).
   - Always emit a manifest with `mvp_scan` (it is what feeds the catalog's
     coverage column); a scan with no manifest is a scan that never happened.
   - Commit the updated `catalog.tsv` with the run. A re-scan of an already
     SCANNED file without new coverage is a bug, not diligence.
11. **Don't overclaim.** This is a blind-spot specialist, not a survey. Known
   winners: spread spectrum, jerk/chirp, bit structure, dense-comb fencing
   (thicket rule), any-format ingest. Known losers: stable narrowband
   (turboSETI is better). Former losers now covered, with caveats:
   pulsars (`pulsar_fold.py` — envelope methods report burst envelopes as
   rotation on sub-second slices; periods longer than the span are
   meaningless), FRBs (`transient_dm.py` — single-channel DM is a proxy;
   full-band coherent dedispersion is the follow-up lever).

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
  quarantined, not scanned. See `archive/root_20260921/hits_hip_b6.QUARANTINED.csv`
  (and the W75N lane, ledgered QUARANTINED in `catalog.tsv`). Phantom flags
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
- **Dense thickets game the comb rule.** 60+ intermod lines at 20–80× score
  comb 1940 with 7 members (vs 859 for a real AM comb). The fence is
  line-density (`nlines10 ≥ 25`), and a comb inside a thicket contributes
  +0.00 STRUCTURE (discounted, not merely outweighed). A lone comb never
  reaches engineered alone — it needs a partner marker (nongauss/frame/VM).
- **Cepstral shelves fire at the search edge.** Red log-spectra inflate low
  quefrencies; every real slice fired the ladder at q=10. Whiten in
  QUEFRENCY (±60 median, floored at the global median — unfloored division
  manufactured ratios of 1332 from nulls). Whitening in frequency instead
  blinds wide combs (measured, reverted). Never trust a q=10 line.
- **SK must be per-bin, never grouped.** Grouped-bin SK sits at 0.98
  deviation on pure noise (Gamma, not exponential). Use per-bin SK with a
  deviant-fraction gate (≥2% of bins).
- **Injection symmetry can zero a test.** A gate period equal to the STFT
  length makes every frame identical, so SK sits at 1 by construction.
  Keep synthetic cadences incommensurate with analysis windows.
- **Frame stride vs code stride drift.** 64-bit frames are 1 mod 7, so
  frame-packed Hamming codewords cycle all 7 alignments and no alignment
  sees excess (measured 0.149). Test vectors needing alignment-locked
  codes must use a contiguous stride-matched stripe.
- **Sandbox outputs must be written on every exit.** An early-halt `return`
  that skips writing metrics turns a looping program into ops=0. `goto done`
  pattern; the selftest caught it.
- **DM fits need ≥8 sub-bands.** 4 bands give a 29% null r²>0.5 rate (false
  +1 order on 10 random spikes). 8 bands + r²≥0.8 + span gate.
- **Broadband gain is not scintillation.** A single gain process moves all
  bands together (xcorr ~1 = COMMON/backend). Real diffractive scintillation
  DECORRELATES across frequency — that decorrelation is the ISM fingerprint
  the classifier keys on. Inject per-band gains or prove nothing.
- **Peak-hold, not median, for precursors.** A median over the pre-window
  dilutes a narrow echo with clean sky (measured 0.20 vs a 0.30 gate).
- **TLEs age in days.** 2026 elements at a 2020 timestamp return
  lunar-distance LEO ranges — confidently wrong unless flagged.
  `satpass.py` warns past 30 days; archive elements for old observations.
- **Order matters around bare excepts.** A staleness guard placed before its
  `jd0` assignment raised NameError into a bare `except: pass` and went
  silent. Initialise before guarding; log guard failures.
- **Sub-bin drift grids report the grid edge.** When drift displacement over
  the stare is << channel width, every rate ties and argmax order picks an
  edge (measured: phantom −2.0 Hz/s drifters on steady lines). Tie-prefer
  rate 0; warn when resolution >> step. Zero unless drift proven.
- **Test-harness units kill injections silently.** Adding Hz to MHz puts the
  tone 70 MHz away from the first spectrum on — the injection is invisible
  and the detector looks broken (measured, twice). Assert the injection
  lands (argmax trace) before asserting recovery.
- **Archive hi-spectral products can't show fast pulsars.** tsamp ~1–17 s
  caps detection at ~0.03–0.5 Hz; a 173 Hz MSP is physically invisible no
  matter the span. Match the calibrator to the product or state the abstention.
- **A line at exactly fs/4 is the digitizer, not the sky.** ADC-interleaving
  spurs sit at fs/4 (732,422 Hz at the 2.93 MHz GUPPI rate) across dozens of
  channels at up to 277×. The corpus noise-watch named it (`--noise-watch`);
  multichannel + exact-fs/4 coincidence is the fingerprint. Never promote an
  fs/4 (or fs/2) line without explaining the converter first.

---

## Status

See `README.md` for the full scorecard. Summary:

- **Real:** any-format ingest (GUPPI/FIL/H5/FITS/WAV/raw-IQ/npy/CSV),
  f=0 cyclostationary, full SCD + dechirp, Viterbi non-linear tracking,
  Golay/VM + 6-machine xeno sandbox, folding search, DM sweep, raster
  framing, RFI veto + catalog + thicket fence, ON–OFF cadence gate,
  I0–I5 grades (SMT2-verified), TLE conjunction checks, latent triage.
- **Substitute:** Neural ODE replaced by Viterbi TBD (MLP could not beat it on
  spike-riding energy; dead ends documented in `neural_track.py`).
- **Missing (priority order):**
  1. Cross-observation matcher (M9) — monument recurrence across nights.
  2. Full-polarization sweeps (currently top-candidates only via `--xpol`).
  3. Parallel scanning (`mvp_scan` is embarrassingly parallel).
  4. Complex-native C detectors (today the canonical real is the I channel).
  5. Archive TLEs for historical satellite attribution (hook exists).
  6. Chunked HDF5 streaming for GB-scale filterbanks (currently windowed).
  7. Full-band coherent dedispersion (single-channel DM is a proxy).

---

## Conventions

- **C** in `c/`: C99, no external deps, `-lm` only. Comment the *why*, keep the
  hot loop clean. Deterministic, no I/O in inner loops.
- **Python** in `python/`: stdlib + `numpy` (optional `scipy`/`matplotlib`).
  Every detector file should carry a `--prove` path or a sibling prove script.
- **New detector checklist:** prove harness → noise floor number → integrate
  into `mvp_scan`/`hits.csv` schema → veto rule → README status row.
- **New grade/veto logic checklist:** mirror it in `z3/smt2/*.smt2`, tie it
  in `z3/verify_*.py` (fuzz vs shipped code), keep the three in sync — a
  property the prover can't see (e.g. a missing `flagged` conjunct, caught
  live in X2) is a bug with a certificate.
- **New format checklist** (see `UNIVERSAL_INGEST.md`): reader → canonical
  contract + honest caveats → dispatch entry (magic-first if
  self-describing) → SMT2 mirror + verifier model → round-trip prove leg →
  doc table row. Headerless inputs REQUIRE explicit geometry (`--fs` etc.);
  guessing is refusal-worthy.
- **Thresholds are calibration numbers, dispositions are theorems.** Prove
  the floor with gap receipts; prove the *logic consuming it* with Z3.
  Never the reverse.
- **The corpus proposes, the proves dispose.** `corpus.py --suggest` reports
distributions, trigger margins and flag rates with HOLDS/REVIEW verdicts —
never numeric auto-proposals (clean distributions are truncated at the
trigger, so p999×margin measures the trigger's own shadow; full-distribution
extrema are contaminants). A REVIEW goes to a human with a prove harness,
never to a config. No silent auto-tuning, ever.
- **Corpus ingest is pinned and idempotent.** Flags join (block,chan,pol)
  within the SCORED hits file (veto logs omit pol; filename or `--veto-pol`
  supplies it) — never target-wide. Re-ingest replaces (UNIQUE + wipes),
  never duplicates. Resume-dups in old CSVs resolve last-wins, loudly.
- **Naming:** raw files follow
  `blc<N>_<2bit|8bit>_guppi_<MJD>_<TARGET>_<SCAN>.<NNNN>.raw`. `blcN` = a
  different 187.5 MHz node on the *same* observation; same MJD+TARGET = same
  pointing. Comparing bands requires reading the bank number.
- **Houdini** is an appeal court, not a primary sieve. Only already-flagged
  slices get terrain.

---

## What "found something" looks like

Grades are the shared language now (see `INTERSTELLAR_HIT_CRITERIA.md`):
I0 clean → I1 notable-but-unstructured → I2 engineered without sky context
→ I3 +ISM/pol/cadence sky marker → I4 +exotic/Doppler/code → I5 full house
(persistent + xvm-CANDIDATE). Monotonic, machine-checked, common-mode
bystanders eligible by design; exotic alone never engineers; single files
cap at I2.

No single detector firing is a detection. The jackpot signature is **all of**:
FAM fires where the spectrum is silent → microscopic battery backs it (SK
fraction, ladder, coherence) → multi-machine sandbox goes red (loops,
breathing CA, frame stride, code excess) → a sky marker signs it (decorrelated
scintillation, cross-pol agreement, ON-only persistence) → anomalous Doppler
or forbidden physics (negative DM, prime rhythm, precursor) → the veto fails
to kill it → latent triage ranks it isolated at the top. Any one is a
curiosity; all of them have no known natural or human explanation.

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
