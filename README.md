# SetiYeti

An unsupervised signal-analysis pipeline for raw radio telescope baseband data.
It keeps complex phase, searches modulation space rather than only narrowband
tones, and blocks terrestrial interference automatically.

Most SETI software reduces incoming voltage to a 2D intensity spectrogram and
then looks for narrow tones drifting in a straight line. That's a good filter for
one class of signal and blind to several others. SetiYeti is built for the ones it
misses.

---

## The blind spots it targets

| Blind spot | Why legacy pipelines miss it |
|---|---|
| **Sub-noise spread spectrum** | Squaring voltages into power destroys phase. A DSSS beacon spread below the thermal floor is indistinguishable from flat Gaussian noise to a total-power detector. |
| **Non-linear drift** | Matched filters assume constant `dν/dt`. Orbiting, rotating or accelerating transmitters trace curves and get smeared below threshold. |
| **Chirped / dispersed transients** | A signal sweeping faster than the FFT integration time never concentrates in any single bin. |
| **Engineered bit structure** | Nobody demodulates candidates and asks whether the bits *compute*. Cyclostationary and error-correcting structure is never tested. |

Each of those is a real, measurable capability gap, not a philosophical one —
the proofs below quantify exactly where the floor is.

---

## Pipeline (what is actually implemented)

```
 .raw  (GUPPI: FITS-style header + binary payload, 2- or 8-bit)
   │
   │  c/seti_slice.c        header-parsed geometry, bit-depth aware unpack,
   │                        block-range seeking, per-lane statistics
   ▼
 .f32  (one coarse channel: 2.93 MHz of real voltage)
   │
   ├── python/mvp_scan.py ──── direct FFT peak-hunt + Welch averaging
   ├── c/fam_scan.c ────────── Y²/Y⁴ cyclostationary scan (the f=0 SCD slice)
   ├── python/scd_frf.py ───── full (α, f) spectral correlation plane + dechirp bank
   ├── python/jerk_scan.py ─── Viterbi track-before-detect + quadratic motion fit
   ├── python/bitslice.py ──── sign / transition bitstreams ──► c/vm_sandbox.c
   │                                                            (SUBLEQ locality + Golay G₂₄ syndrome)
   ├── c/xeno_scan ────────── microscopic battery: spectral kurtosis, coherence,
   │                           cepstral ladder, dispersion-order sign, impulsivity
   ├── c/xvm_sandbox ──────── 6-machine alien-code battery (SUBLEQ/stride-swept
   │                           STACK/CA110/frame-ACF/Berlekamp-Massey/2D-raster
   │                           behind the entropy gate; no human code assumed)
   ├── python/scint_pol.py ── ISM scintillation + cross-pol agreement
   ├── python/exotic_pass.py ─ negative-DM, clock stability, prime trains,
   │                           precursor echoes (bizarre-physics hunters)
   └── python/xeno_pass.py ── I0–I5 interstellar grades (see
                               INTERSTELLAR_HIT_CRITERIA.md)
   ▼
 hits.csv ──► python/rfi_veto.py ──► BLOCK / WATCH / CANDIDATE
                    │                   (band allocation, α zone, persistence,
                    │                    channel coincidence, VM structure, recurrence,
                    │                    thicket fence + comb discount)
                    ▼
              python/latent_pca.py ──► outlier ranking across all slices
                    │
                    ▼
              houdini/export_triage.py ──► 3D waterfall terrain (appeal court)
```

---

## Status

Honest split between what has been validated and what is a substitute.

| Component | State | Evidence |
|---|---|---|
| I/Q ingestion | ✅ real | 49/49 blocks parsed, zero packet loss, random access by block |
| Cyclostationary (f=0) | ✅ real | DSSS recovered at −12 dB; noise floor characterized |
| Full SCD (α, f) plane | ✅ real (C port too) | harmonic baud comb detected 4.2× over noise. C: `scd_dechirp` BPSK 124.8× vs 4.5× floor, chirp 28× concentration, SMT2 + CBMC proved |
| Chirp / FrFT angle search | ✅ real (C port too) | 30 kHz/s chirp concentrated 360×, rate error 0 Hz. C: `scd_dechirp` bank @30000 Hz/s exact |
| Non-linear tracking | ✅ real (C port too) | Viterbi TBD recovers drift and jerk at −35 dB. C: `jerk_track` noise 3.2, chirps 6.0, SMT2 + CBMC proved |
| Learned trajectory field | ⚠️ deferred | MLP can't beat Viterbi on spike-riding energy; documented dead ends in `neural_track.py` |
| Latent anomaly | ✅ real | ranks all flags in the top 10–15% of the corpus |
| Golay / VM structure test | ✅ real | engineered codewords 100% vs 3.27% random baseline |
| XENO microscopic battery | ✅ real | SK/coherence/ladder/DM-sign/impulsivity; up-chirp EXOTIC (−1), down-chirp normal (+1) |
| Alien-code xeno sandbox | ✅ real | 5/6 machines fire on framed+coded+looping stream; noise silent on all six |
| Scintillation + polarisation | ✅ real | decorrelated SCINT vs COMMON vs WANDER-LOCAL; 6/6 |
| Bizarre-physics hunters | ✅ real | neg-DM ±23000, prime trains (machinery quiet), precursors; 10/10 |
| Interstellar grades I0–I5 | ✅ real | 14/14 ladder checks; SMT2-verified, 5000/5000 code tie |
| Thicket fence | ✅ real | dense forest scores comb 1940 yet trips fence; real 9-line comb spared |
| RFI veto | ✅ real | 11/11 legs incl. thicket; catalog + recurrence memory |
| ON–OFF cadence gate | ✅ real | `cadence_pair.py`: only WATCH→CANDIDATE path + catalog audit |
| Periodicity / folding search | ✅ real (C port too) | envelope FFT + 8-harmonic sum, 1 Hz–2 kHz; 5/5 (burst-envelope caveat documented). C: `fold_dm` 29.68 Hz @4799σ, noise 9.4σ; SMT2 + CBMC proved |
| Single-pulse + DM sweep | ✅ real (C port too) | boxcar bank + incoherent dedispersion; 3/3 (single-channel proxy caveat). C: `fold_dm` fires 289σ on shot, 11.7σ noise; SMT2 + CBMC proved |
| Payload raster framing | ✅ real | 23×73 Arecibo fires at 9.4σ, noise 1.7σ |
| Universal ingest | ✅ real | 10 formats → one canonical stream; WAV≡NPY bit-identical batteries |
| Satellite conjunction | ✅ real | TLE/SGP4 overhead checks, staleness-guarded; attribution evidence |
| Corpus library | ✅ real | 258k slices / 1.5k signatures / 90 flags in one SQLite DB; review queue + recurrence + family + noise-watch queries |
| Threshold suggest | ✅ real (gated) | corpus distributions + margins + rates with HOLDS/REVIEW; proposes nothing numeric, tunes nothing automatically |

---

## Proof of sensitivity

Every detector is validated by injection: a known signal is placed in
quantized noise matching the real backend, and the detector must find it while
the same test on noise alone stays quiet.

**Spread spectrum — the headline result.** A 63-chip DSSS beacon at **−12 dB**,
bandwidth 1 MHz:

```
direct FFT peak-hunt :  2.02×  → no actionable line (this is what a legacy pipeline sees)
FAM carrier-squared  :  7.35×  at exactly 2×f₀
code-phase despread  :  5.00×  over noise → code recovered
```

**Non-linear drift.** Injected at −35 dB total (invisible in any single FFT row):

```
noise floor      : 3.155   threshold 3.944
linear 40 Hz/s   : 4.380   recovered v = +39.0 Hz/s
parabolic a=18   : 4.574   recovered a = +13.5 Hz/s²
```

**Chirp de-smearing.** A 30 kHz/s chirp spread across ~3700 FFT bins:

```
direct FFT      :  20×  (smeared plateau)
dechirp bank    : 7,278×  at γ = −30,000 Hz/s, error 0 Hz
```

**Golay structure.** Extended binary Golay G₂₄ codewords through the sandbox:
100% hit rate, versus 3.27% for random bits at the same window length. The
sandbox also refuses to render a verdict on low-entropy input, after a dark
digitizer lane produced false 100% hits on zero-runs.

**Universal ingest (2026-09-21).** `python/univ_ingest.py` sniffs GUPPI /
SigProc filterbank / HDF5 / FITS / WAV / raw I-Q (GNU Radio, rtl-sdr,
HackRF layouts) / numpy / CSV and delivers one canonical stream:
voltage/complex inputs get the FULL battery, detected-power inputs get an
honest SPECTRAL subset (phase was discarded at record time). 13/13
round-trips; the same real slice as WAV and NPY scores bit-identical
batteries. `python/satpass.py` adds TLE conjunction checks (SGP4,
offline-first, with a staleness guard) as attribution evidence.
See `UNIVERSAL_INGEST.md`. `python/univ_scan.py --in anything --outdir runs/x`.

**XENO results (2026-09-20 overhaul).** Full receipt table in
`reports/xeno_overhaul.md`: quick 29/29, full 34/34, SMT2 44/44 checks, all code ties
green. On real data (TRAPPIST-1 + Kepler-160, 65k+ slices): zero I3+,
zero CANDIDATE — with a named, fenced contaminant (the 179-family
intermod thicket: dense line forests that game the comb rule, caught by
line-density) and one fully-anatomised sub-second burst (OFF b1/ch57).
Strongest follow-up: Kepler OFF ch25, persistent protected-band combs in
all four OFF pols, absent ON — WATCH, needs ON–OFF–ON re-observation.

---

## Results so far

Seven pointings, 70,000+ slice-analyses, ~1,500 cataloged interference
signatures, **zero surviving candidates.**

| Observation | Slices | Outcome |
|---|---|---|
| **M31** (X-band, 9.19–9.38 GHz) | 2,200 | 6 flags, all BLOCKed. Single-block, single-channel, MHz-rate bursts with no persistence and no harmonic structure → terrestrial radar in a radar-allocated band. FAM floor: mean 2.29, max 3.12. |
| **HIP 113357** (L-band, 1406 MHz, 8-bit) | 64 | 64/64 channels flagged at 4–10×, all at the same low-frequency α, each polarization peaking at a *different* frequency → receiver-chain wander, not sky. |
| **HIP 113357** (bank 6, same observation) | 64 | Digitizer essentially dark (21 distinct codes, all lanes RMS 1.1). Quarantined before analysis; zero-runs were passing the Golay test trivially. |
| **Voyager 1 coords** (X-band) | 64 | Null, as expected — the file's band is ~800 MHz above Voyager's 8.415 GHz downlink. Useful as a specificity check on a fresh pointing. |
| **TRAPPIST-1** ON+OFF PART1GB (L-band, 2017) | 1,792 | 0 above I1. Richest slice: OFF b1/ch57 sub-second burst (91×, 60+ cyclic lines, both pols) → I2/WATCH, mechanism unidentified, fenced below candidacy. |
| **Kepler-160** ON+OFF full 128-block (L-band, 2020) | 65,536 | 1 I2 (OFF b66/ch57). 179-family intermod thicket named + fenced (36–108 lines>10× across both pointings, both epochs). Top follow-up: OFF ch25, persistent protected-band combs in all 4 OFF pols, absent ON → WATCH. |

The M31 negative is the substantive early result: a real upper limit on that
band over that span, backed by a noise-matched threshold for every detector.
The XENO campaign (`reports/xeno_overhaul.md`) is the substantive recent one:
grades I0–I5 across the whole corpus with per-marker receipts.

---

## Quick start

```bash
# 1. build the C tools (no dependencies, C99) — 9 binaries via make
make                # seti_slice fam_scan vm_sandbox comb_scan xeno_scan xvm_sandbox jerk_track fold_dm scd_dechirp
make check          # verify binaries run + probe real-file layouts

# 2. verify the detectors before trusting them on data (34/34 = gate)
python python/sy_prove_all.py --root . --quick   # fast gate (29 checks, ~8 min)
python python/sy_prove_all.py --root .           # full gate (all 34)

# 3. scan a file — GUPPI or literally anything (WAV/FIL/H5/FITS/I-Q/npy/CSV)
python python/mvp_scan.py --raw data/<file>.raw --b0 0 --b1 48 --chans 0,8,16,24,32,40,48,56
python python/univ_scan.py --in signal.wav --outdir runs/univ_wav
python python/univ_scan.py --in capture.cu8 --fs 2000000 --outdir runs/univ_rtl

# 4. grade top candidates I0–I5, then disposition every flag
python python/structure_pass.py --scan scan.csv --raw data/<file>.raw --out struct.csv
python python/xeno_pass.py --scan struct.csv --raw data/<file>.raw --out xeno.csv \
    --off scan_off.csv --evidence evidence.csv --target NAME --xpol
python python/rfi_veto.py --hits hits.csv --evidence evidence.csv --target M31

# 5. satellite-overhead check + corpus ranking
python python/satpass.py --guppi-at data/<file>.raw --block 21 --dur 30 --site GBT
python python/latent_pca.py --slices hits.csv
```

Requires Python 3.12+ with numpy; `pip install -r requirements-science.txt`
adds the science stack (`h5py`/`astropy`/`scipy` + `sgp4` for `satpass.py`).
The C tools are dependency-free. On Windows: MinGW on PATH for `make`,
Scoop Python at `C:/scoop/apps/python/current`.

---

## Detectors

**`c/seti_slice.c`** — the only thing that touches raw files. Parses the varying
header, reads geometry from the header rather than assuming it, unpacks 2-bit
and 8-bit layouts, seeks to any block without reading the preceding ones, and
reports per-lane RMS plus range/diversity so a dead digitizer is caught before
it reaches a detector.

**`c/fam_scan.c`** — square-law and fourth-power cyclostationary scan. For a
BPSK signal, `x²` produces a line at twice the carrier regardless of the data,
so a spread signal's energy can be found without knowing the code. Reports peaks
in cyclic frequency α with a median-relative ratio. This is the `f = 0` slice of
the spectral correlation function — cheap and broad.

**`python/scd_frf.py`** — the full `(α, f)` plane via an FFT-accumulation
estimator, plus a dechirp bank that acts as the operational fractional Fourier
transform. The dechirp bank searches chirp rate directly by derotating the
time-frequency plane; the peak concentration identifies the angle. Catches
dispersed pulses and accelerating transmitters that no single FFT bin resolves.

**`python/jerk_scan.py`** — Viterbi track-before-detect over a robust-z
waterfall. Tracks are penalized for frequency agility rather than assumed
straight, so arbitrary drift, jerk and frequency hops are expressible. The
winning path is fit to a quadratic to report drift (Hz/s) and jerk (Hz/s²).

**`c/vm_sandbox.c`** — takes a candidate bitstream and asks whether it looks
engineered. Runs a SUBLEQ one-instruction-set machine and measures memory-access
locality (real code clusters around hot addresses; noise sprays uniformly), then
tests for the extended binary Golay G₂₄ code across all 23 alignments. An entropy
gate refuses to score constant or rail-saturated input.

**`python/rfi_veto.py`** — the Earth blocker. Every flag is scored against ITU
band allocations, the cyclic-frequency zone (1 Hz–2 kHz is where rotation-powered
astrophysics lives; 100 kHz–5 MHz is where electronics live), time persistence,
channel coincidence, VM structure, a growing signature catalog that hard-blocks
anything seen before, and the thicket fence (dense intermod forests get +0.35
EARTH and their comb vote discounted to +0.00 — comb-by-density is not
modulation). Emits BLOCK / WATCH / CANDIDATE with written reasons.

**`c/xeno_scan`** — microscopic battery in one pass: per-bin spectral-kurtosis
fraction (packetised cadence), zero-crossing coherence (clock-grade oscillation),
whitened cepstral ladder (frequency combs), dispersion-order sign (up-chirp =
EXOTIC negative-DM, down-chirp = normal plasma), impulsivity. One `RESULT` line.

**`c/xvm_sandbox`** — 6-machine alien-code battery behind the entropy gate:
SUBLEQ, Forth-STACK swept over word widths 3–8 (bits that LOOP at their native
width vs noise that halts at every width), Rule-110 CA (breathing vs flat
density), frame-ACF (reports the fundamental stride), Berlekamp-Massey linear
complexity (ANY linear code/scrambler collapses L≪N/2 — no polynomial guessed;
replaces Hamming(7,4) + CRC-16, which demanded our 0x1021), 2D prime-raster
spatial coherence (Arecibo-style frames at natural width, proven w=23 in-test).
≥3/6 votes = XENO-CANDIDATE.

**`python/scint_pol.py`** — sky markers from the medium: decorrelated
scintillation (single-gain wander reads COMMON instead) and cross-polarisation
agreement (same frequency in every feed = SKY-LIKE; divergent = WANDER-LOCAL).

**`python/exotic_pass.py`** — bizarre-physics hunters: negative dispersion
(|DM|>50, r²≥0.8), clock-grade stability, prime-interval pulse trains
(machinery rhythms stay quiet), non-causal precursor echoes.

**`python/xeno_pass.py`** — one I0–I5 grade per slice from all of the above
plus veto/evidence/cadence context (single files cap at I2; exotic alone never
engineers; common-mode bystanders eligible by design).

**`python/univ_ingest.py` + `python/univ_scan.py`** — the any-format front-end:
sniff GUPPI/filterbank/HDF5/FITS/WAV/raw-IQ/numpy/CSV → one canonical stream
(voltage/complex: FULL battery; detected power: honest SPECTRAL subset) →
verdict + REPORT.md. See `UNIVERSAL_INGEST.md`.

**`python/satpass.py`** — TLE conjunction checks (SGP4, offline-first) for any
observatory: what metal was overhead at a flag's timestamp. Attribution
evidence with a staleness guard, not a veto rule.

**`python/cadence_pair.py`** — the only legal WATCH→CANDIDATE gate (ON-only +
structured + persistent) plus the cross-observation recurrence hook and the
catalog audit that keeps the bystander family unblockable without structure.

**`python/latent_pca.py`** — unsupervised triage. A PCA subspace is learned on
clean slices; every slice is scored by reconstruction residual plus latent
Mahalanobis distance. Purpose-built for ranking an entire corpus so a single
anomaly cannot hide in a large batch of near-threshold noise.

---

## Houdini triage

`houdini/` renders flagged slices as 3D waterfall terrain — frequency on X, time
on Y, log-power as relief. A carrier reads as a straight wall, a drifter as a
diagonal blade, radar speckle as popcorn. It is deliberately tiered: only slices
that already flagged get terrain, so it stays an appeal court rather than a
primary sieve. See `houdini/README.md`.

---

## Limits

- **No ON–OFF test.** A single pointing cannot distinguish celestial from local.
  Single pointings cap at WATCH (I2) for exactly this reason; the
  `cadence_pair.py` gate is the only promotion path.
- **Folding has a burst caveat.** `pulsar_fold.py` covers 1 Hz–2 kHz, but
envelope methods report bright transient envelopes as rotation on
sub-second slices; periods longer than the span are meaningless.
- **Single-channel DM is a proxy.** Intra-channel sweeps flag candidates;
  confirmation needs full-band coherent dedispersion.
- **0.176 s per block.** A short file is a snapshot, not an observation. Drift
  fitting and persistence adjudication need tens of seconds to work properly.
- **One polarization at a time** in the current sweeps, and the sweep strides
  channels rather than covering every cell.
- **Very strong carriers can trip the thicket fence.** Sidelobe forests read
  as line-density — errors point toward caution (BLOCK), never discovery.
- **Power inputs can't use phase tools.** Filterbank/FITS spectra get the
  spectral subset; the battery abstains where phase is required.
- **Not a survey.** This is a per-file (now any-format) analysis engine.
  Throughput is limited by download, not compute.

---

## Roadmap

1. **Cross-observation matcher (M9)** — the same signature recurring across
   nights is the only way to catch long-cycle monuments. Top missing piece.
2. **Full-polarization sweeps** — currently top-candidates only (`--xpol`);
   the strongest backend-artifact discriminator deserves full coverage.
3. **Parallel scanning** — `mvp_scan` is embarrassingly parallel; scale out
   to a worker fleet before scaling up file size.
4. **Complex-native C detectors** — today the canonical real is the I channel;
   Q carries half the story for PSK-class signals.
5. **Archive TLEs** — 2020-era satellite attribution needs space-track.org
elements; the `satpass.py` hook is ready.
6. **Chunked HDF5 streaming** — GB-scale filterbanks are currently windowed,
   not streamed.
7. **Full-band coherent dedispersion** — to confirm or kill DM-proxy shots
   like the b1/ch57 event.

---

## Layout

```
corpus/     setiyeti.db (DERIVED, gitignored — rebuild via `python/corpus.py --auto`)
c/          C99 tools: seti_slice, fam_scan, vm_sandbox, comb_scan (+thicket),
            xeno_scan (microscopic), xvm_sandbox (alien-code),
            jerk_track (Viterbi TBD), fold_dm (pulsar+DM), scd_dechirp
            (SCD plane+dechirp) — `make` builds 9
python/     detectors, prove harnesses, veto, triage, universal ingest/scan,
            satpass, xeno grades, pipeline/longhaul orchestrators
z3/         machine-checked specs + code ties (veto, grades, dispatch, ...)
configs/    TOML presets (header geometry wins, preset fills, CLI overrides)
runs/       per-run scans/evidence/grades/REPORTs (machine-readable record)
reports/    write-ups with receipts (xeno_overhaul.md = latest campaign)
houdini/    triage terrain exporter + Houdini shelf script
INTERSTELLAR_HIT_CRITERIA.md   what I0–I5 mean
data/       raw + derived signal files (gitignored — see data/README.md)
spec.md     the original design brief; README describes what is actually built
hits*.csv   per-observation scan results (the scientific record)
rfi_catalog.json   accumulated interference signature catalog
```

---

## References

- Enriquez et al. 2017 — `turboSETI`, the standard narrowband drift search
- Gardner 1991 — cyclostationary spectral correlation
- Ma et al. 2023 — unsupervised autoencoder search over 820 stars
- Price et al. 2020 — Breakthrough Listen's data formats and cadence design
- Lorimer 2011 — SigProc filterbank format (the `.fil` header contract)
- Lebofsky et al. 2019 — `blimpy` HDF5 filterbank convention
- Vallado et al. — SGP4 propagation (the `sgp4` package powers `satpass.py`)
