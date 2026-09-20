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
   │
   ▼
 hits.csv ──► python/rfi_veto.py ──► BLOCK / WATCH / CANDIDATE
                    │                   (band allocation, α zone, persistence,
                    │                    channel coincidence, VM structure, recurrence)
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
| Full SCD (α, f) plane | ✅ real | harmonic baud comb detected 4.2× over noise |
| Chirp / FrFT angle search | ✅ real | 30 kHz/s chirp concentrated 360×, rate error 0 Hz |
| Non-linear tracking | ✅ real (not Neural ODE) | Viterbi TBD recovers drift and jerk at −35 dB |
| Learned trajectory field | ⚠️ deferred | MLP can't beat Viterbi on spike-riding energy; documented dead ends in `neural_track.py` |
| Latent anomaly | ✅ real | ranks all flags in the top 10–15% of the corpus |
| Golay / VM structure test | ✅ real | engineered codewords 100% vs 3.27% random baseline |
| RFI veto | ✅ real | 6/6 flags correctly BLOCKed; catalog + recurrence memory |
| ON–OFF cadence test | ❌ missing | needs a second pointing file — no code will substitute |
| Periodicity / folding search | ❌ missing | pipeline is currently deaf to pulsars by construction |
| Single-pulse + DM sweep | ❌ missing | no FRB-class coverage yet |

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

---

## Results so far

Three pointings, 2,264 slice-analyses, 70 cataloged interference signatures,
**zero surviving candidates.**

| Observation | Slices | Outcome |
|---|---|---|
| **M31** (X-band, 9.19–9.38 GHz) | 2,200 | 6 flags, all BLOCKed. Single-block, single-channel, MHz-rate bursts with no persistence and no harmonic structure → terrestrial radar in a radar-allocated band. FAM floor: mean 2.29, max 3.12. |
| **HIP 113357** (L-band, 1406 MHz, 8-bit) | 64 | 64/64 channels flagged at 4–10×, all at the same low-frequency α, each polarization peaking at a *different* frequency → receiver-chain wander, not sky. |
| **HIP 113357** (bank 6, same observation) | 64 | Digitizer essentially dark (21 distinct codes, all lanes RMS 1.1). Quarantined before analysis; zero-runs were passing the Golay test trivially. |
| **Voyager 1 coords** (X-band) | 64 | Null, as expected — the file's band is ~800 MHz above Voyager's 8.415 GHz downlink. Useful as a specificity check on a fresh pointing. |

The M31 negative is the substantive result: a real upper limit on that band over
that span, backed by a noise-matched threshold for every detector.

---

## Quick start

```bash
# 1. build the C tools (no dependencies, C99)
gcc -O3 -o c/seti_slice  c/seti_slice.c  -lm
gcc -O3 -o c/fam_scan    c/fam_scan.c    -lm
gcc -O3 -o c/vm_sandbox  c/vm_sandbox.c  -lm

# 2. verify the detectors before trusting them on data
python python/dsss_prove.py          # spread spectrum at −12 dB
python python/jerk_scan.py --prove   # drift + jerk at −35 dB
python python/scd_frf.py --prove     # baud comb + chirp de-smear

# 3. scan a file
python python/mvp_scan.py --raw data/<file>.raw --b0 0 --b1 48 --chans 0,8,16,24,32,40,48,56

# 4. disposition every flag
python python/rfi_veto.py --hits hits.csv --evidence evidence.csv --target M31

# 5. rank the whole corpus for outliers
python python/latent_pca.py --slices hits.csv
```

Requires Python 3.12+ with numpy (scipy/matplotlib optional — matplotlib only
for waterfall PNGs). The C tools are dependency-free.

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
channel coincidence, VM structure, and a growing signature catalog that hard-blocks
anything seen before. Emits BLOCK / WATCH / CANDIDATE with written reasons.

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
  Every claim so far is capped at WATCH for exactly this reason.
- **Deaf to periodicity.** No folding or harmonic-summing search, so millisecond
  pulsars and long-period rotators are invisible regardless of strength.
- **No single-pulse search.** No boxcar or dispersion-measure sweep; fast
  transients are only caught incidentally by the cyclostationary stage.
- **0.176 s per block.** A short file is a snapshot, not an observation. Drift
  fitting and persistence adjudication need tens of seconds to work properly.
- **One polarization at a time** in the current sweeps, and the sweep strides
  channels rather than covering every cell.
- **Not a survey.** This is a per-file analysis engine. Throughput is limited by
  download, not compute.

---

## Roadmap

1. **Periodicity search** — envelope FFT with harmonic summing over 1 Hz–2 kHz.
   Highest value per line of code; closes the pulsar/rotator blind spot.
2. **Single-pulse + DM sweep** — boxcar matched filtering with incoherent
   dedispersion, for FRB-class and magnetar-shot events.
3. **Cadence pairing** — pull A/B pairs from the archive and make the ON–OFF test
   the gate that promotes WATCH to CANDIDATE.
4. **Full-polarization sweeps** — currently the strongest discriminator against
   backend artifacts (see HIP 113357) and only used on demand.
5. **Parallel scanning** — `mvp_scan` is embarrassingly parallel; scale out to a
   worker fleet before scaling up file size.

---

## Layout

```
c/          C99 tools: raw unpacker, cyclo scanner, VM sandbox
python/     detectors, prove harnesses, RFI veto, latent triage
houdini/    triage terrain exporter + Houdini shelf script
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
