# XENO overhaul — what was built, what the sky said (2026-09-20)

Overhaul mandate: scan for interstellar/bystander traffic, extraterrestrial
payloads, and physics outside the current paradigm — down to microscopic
detail — while fencing Earth noise harder than before, with clear markers for
what an interstellar hit is, support for alien code beyond one architecture,
and formal verification over the new rules.

**One-line verdict: no candidates. Zero I3+. One named contaminant family
with its mechanism identified, one genuinely weird transient fully
anatomised, and three detector bugs caught by real data before they could
promote anything.**

---

## 1. What was built (all proven, all receipted)

### New C tools (C99, `-lm` only, zero new dependencies)

| tool | markers | prove |
|---|---|---|
| `c/xeno_scan.c` | spectral-kurtosis fraction, zero-crossing coherence, whitened cepstral ladder, dispersion-order sign (±: normal plasma / EXOTIC), impulsivity | 11/11: pulsed cadence, 5-tone ladder, square clock, down-chirp NORMAL (+1), **up-chirp EXOTIC (−1)**, impulses; quiet on matched noise |
| `c/xvm_sandbox.c` | 6-machine alien-code battery: SUBLEQ + Forth-STACK (loop counting) + Rule-110 CA (breathing) + frame-ACF (fundamental walk-down) + Hamming(7,4) + CRC-16, behind the entropy gate | 10/10: noise silent on all six (Hamming measured 0.128 ≈ 12.5% baseline), dark input refused, hand-built loop+frame+code stream 5/6 → XENO-CANDIDATE |
| `c/comb_scan.c` +fence | `nlines10`/`thicket`: line-density count that fences comb-by-density | thicket60 leg: dense forest scores comb **1940 with 7 members** (vs 859 for a real AM comb) AND trips the fence; real comb holds 9 lines, fence down |

### New Python detectors (numpy only)

| module | markers | prove |
|---|---|---|
| `python/scint_pol.py` | ISM scintillation (m, timescale, cross-band decorrelation) + cross-pol agreement (SKY-LIKE vs WANDER-LOCAL) | 6/6, incl. the wander fingerprint (different tone per pol → LOCAL) |
| `python/exotic_pass.py` | negative-DM (forbidden), clock stability, cepstral ladder (2nd implementation), prime-interval trains, precursor echoes | 10/10, incl. machinery rhythm 2-4-8-16 staying quiet while 2-3-5-7-11 fires |
| `python/xeno_pass.py` | the I0–I5 grade ladder (see `INTERSTELLAR_HIT_CRITERIA.md`) | 14/14 ladder checks, incl. common-mode bystander reaching I5 by design |

### Veto rules added (`python/rfi_veto.py`, 11/11 legs)

- **THICKET**: `lines10 ≥ 25` → +0.35 EARTH (intermod forest, comb-by-density).
- **Comb discount**: a comb inside a thicket contributes +0.00 STRUCTURE
  (it is not evidence of modulation) instead of +0.20.

### Formal layer (`z3/`, z3-solver 5.1.0)

- `smt2/xeno_rules.smt2`: X1 (I5 ⇒ full house), X2 (eng∧sky∧exotic ⇒ ≥I4),
  X3 (silence ⇒ I0), X4 (exhaustive + exclusive), X5 (exotic alone never
  engineers) — 13/13 (one draft property caught missing `flagged` by Z3).
- `verify_xeno.py`: model-vs-code 5000/5000, X1/X2/X3/X5 zero violations.
- `verify_veto.py` extended with `lines10` fuzz; still 3000/3000.
- Full suite: **19/19 proves + 23/23 SMT2 + ties green.**

### Bugs real data caught (fixed with receipts, all in-code documented)

1. **Cepstral shelf**: every real slice fired the ladder at q=10 (search edge)
   from red-spectrum shelves. Fixed by quefrency-whitening (±60 median,
   floored at global median — unfloored division manufactured ratios of
   1332 from nulls). Frequency-domain whitening was tried first and
   **blinded wide combs** (reverted, documented).
2. **SK grouping fallacy**: grouped-bin SK sits at 0.98 deviation on pure
   noise (Gamma, not exponential). Per-bin SK + deviant-fraction metric.
3. **Gate-period = STFT-length symmetry**: every frame identical → SK=1 by
   construction. Calibration injection changed.
4. **Stack-machine output bug**: early halt skipped writing metrics (looping
   program read as ops=0) + test program leaked stack (+1/iter). Both fixed.
5. **Frame-packed Hamming drift**: 64-bit frames are 1 mod 7, so codewords
   cycle alignments and no alignment sees excess (measured 0.149). Fixed
   with a contiguous 7-stride code stripe (0.337).
6. **DM fit under-determined**: 4 sub-bands give 29% null r²>0.5 (false +1
   on 10 random spikes). 8 bands + r²≥0.8 + span gate.
7. **Fold false-periodic**: envelope period methods report burst envelopes
   as rotation on sub-second slices (period > span!). Caveat documented;
   `CLOCK` requires both-halves agreement at high sigma.

---

## 2. What ran on real data

| dataset | coverage | result |
|---|---|---|
| TRAPPIST-1 ON+OFF PART1GB (7 blocks, 2017) | 4 scans × 448 slices, structure + xeno + veto w/ evidence + cadence | 0 above I1; veto 11 BLOCK / 3 WATCH |
| Kepler-160 ON+OFF full 128-block (2020) | reused 8 longhaul scans (65,536 slices), structure + xeno + veto w/ evidence + jerk context | 1 I2 (OFF b66/ch57); veto all BLOCK/WATCH, 0 CANDIDATE |
| Deep slices | hi-res Y² (1.4 Hz bins), fold, DM, frame, full xeno battery | see §3–4 |

Grade census: **I0 ~16k, I1 ~900, I2 = 1, I3+ = 0.** Veto: 0 CANDIDATE everywhere.

---

## 3. Finding 1 — the thicket family (named contaminant, mechanism identified)

The strongest "structured common-mode" signals in both datasets resolve to
the same thing: a **dense intermodulation line forest**, 40–108 Y² lines
above 10×, quasi-regularly spaced (~6 Hz in the cases resolved), carrying
the 179/358/536/626/715/805/894/1162/1431/1699/2861 Hz family as members.

| slice | strength | lines10 | comb | disposition |
|---|---|---|---|---|
| TRAPPIST OFF b1/ch57 (626 Hz) | 91× | 101 | 59.7 (discounted) | BLOCK (thicket) |
| TRAPPIST ON b4/ch44 (179 Hz hum) | 23× | 108 | 21.7 (discounted) | BLOCK (thicket) |
| TRAPPIST ON b4/ch12 (1520 Hz) | 13× | 36 | 10.9 (discounted) | BLOCK (thicket) |
| Kepler ON b21/ch52 (2861 Hz) | 37× | 36 | 24.9 (discounted) | BLOCK (thicket) |
| Kepler ON b88/ch52 (626 Hz) | 23× | **9** | 16.9 (kept, real comb) | BLOCK (common-mode, sub-eng) |

Same backend family (GBT/GUPPI L-band), two stars, two epochs (2017→2020),
both pointings — **unambiguously instrumental**: a ~179 Hz switching-family
oscillator complex whose harmonic content varies with backend state
(thicket at high state, clean few-line combs at low state, e.g. Kepler
OFF ch25's persistent protected-band combs and b88/ch52's genuine 9-line
comb). The bystander-model "structured common-mode" category now has its
first fully-worked example, and the fence (thicket + comb discount) is
proven to catch it while sparing real combs.

A first hypothesis — pure 89.5 Hz harmonics — was **falsified by
measurement**: high-resolution Y² (1.4 Hz bins, 60 lines >20×) shows 3–12%
harmonic concentration for every trial base (89.5/179/60/50/44.75/715),
i.e. chance. The forest has no harmonic discipline; it is an intermod
thicket, not a multiplied clock. This kill is recorded because the process
matters: propose, resolve, retract.

---

## 4. Finding 2 — the OFF b1/ch57 burst (weirdest single slice, fully anatomised)

A sub-second transient in the TRAPPIST OFF pointing: weak in b0 (3–4×),
blazing in b1 (27–40× across 8+ cyclic lines, 60+ lines >20× at hi-res),
gone in b2. Present in both polarisations (tallest line differs: 626 Hz p0,
2861 Hz p1 — same forest, different tallest tree). Richest cyclostationary
structure in the corpus (comb 59.7, 6 members, nongauss, impulsivity).

- No harmonic base (falsified, §3). Line gaps cluster at 5.6–8.4 Hz.
- `pulsar_fold` reports PERIODIC (0.73 Hz rotator, σ=69) — **rejected**: the
  "period" (273 ms) exceeds the slice span (179 ms); it is the burst
  envelope in the first FFT bins, not rotation. Caveat now documented.
- `transient_dm` reports a narrow shot, σ=71, intra-channel DM 323 —
  **unconfirmed**: single-channel DM is a proxy; burst substructure can
  imitate sweep. Needs full-band coherent dedispersion.
- Final: **I2 / WATCH** — engineered-looking, no sky marker, transient,
  OFF-only. Closest mundane match: electrical discharge / relay event in
  the signal chain (broadband + line forest + narrow spikes, sub-second).
  Genuinely unidentified at the mechanism level; correctly held below
  candidacy by persistence + P2 guards. **Follow-up #1**: recurrence search
  for this signature across full 17 GB files.

---

## 5. Finding 3 — Kepler OFF ch25 (most candidate-like, still WATCH)

140 flags across **all four OFF pols**, zero in any ON pol: persistent
(blocks 4–108), protected-band (1426.8 MHz — no legal terrestrial
transmitters), real few-line combs on 179-family fundamentals
(179/358/536/626/805/894/1162/1699 Hz), fam 7–9×. All-pol + OFF-only rules
out receiver-chain specificity; ON-absence rules out the target. Veto:
WATCH everywhere (E≈0.40, S=0.20 — sub-eng comb, P2 cap holds: no promotion
without engineering). Reading: the 179-family oscillator at low state,
seen through OFF sidelobes/backend state — or an genuinely off-target
emitter in a band where nothing should emit. Either way the prescription
is identical: **re-observe with an ON–OFF–ON cadence**. It is the top
follow-up target precisely because every mundane attribution leaks
somewhere (protected band vs backend-state).

---

## 6. Universal-level reading (for the outsider)

Nothing in 65k+ slices cleared I2 with a sky marker. That is not a failure;
with receipts, it is three publishable negatives: (a) no persistent
engineered structure above I1 in two L-band pointings at these floors;
(b) the dominant "structured common-mode" contaminant is now a *named,
fenced* instrumental family, not an unsolved mystery — future structured
common-mode can be tested against the thicket fence instead of argued
about; (c) the battery demonstrably fires on every injected class
(spread-spectrum −12 dB, chirps ±, prime trains, precursor echoes,
multi-machine code, scintillation) — the net has no known holes left in
its design space, only integration-time limits (dwell = sensitivity).

The bystander model survived contact with data: its predicted
hard case — structured, common-mode, recurring — appeared (the thicket
family), and the pipeline's answer (fence by density, hold at
BLOCK/WATCH, never auto-delete, catalog everything) is exactly what the
model prescribes. The one thing that would have changed the verdicts:
persistence + a second pointing. Dwell and cadence remain the binding
constraints, not detectors.

---

## 7. Universal ingest + satellite cross-check (2026-09-21 extension)

SetiYeti stopped being GUPPI-only. `univ_ingest.py` (13/13 round-trips:
WAV/IQ-x4/FIL/H5/FITS/NPY/CSV/unknown-refusal) plus `univ_scan.py`
(any-file → canonical `.f32` → full or spectral-subset battery → capped
I2 + REPORT.md) plus `satpass.py` (TLE conjunction, 6/6 prove, offline
GMST cross-checked to astropy at 0.0003°). Formal: `ingest_dispatch.smt2`
(router totality, magic priority, kind soundness) + `verify_ingest.py`
(2000/2000 dispatch tie + kind soundness).

Format-invariance receipt: the TRAPPIST OFF b1/ch57 burst slice as WAV
and NPY scores bit-identical batteries (fam 91.09, comb+thicket, fold);
as FIL and H5 it agrees on kind with phase-needing markers abstaining.
Live satellite path verified over GBT (quiet sky >30°, sane LEO ranges);
the GUPPI-clock hook resolves Kepler b21 to 2020-09-11T00:33:08 UTC
(SMJD-consistent), with a staleness guard refusing silent misuse of
2026 elements at 2020 timestamps. See `UNIVERSAL_INGEST.md`.

## 8. Follow-ups (priority order)

1. Recurrence search for the b1/ch57 burst signature across full 17 GB
   TRAPPIST files (frame/channel matcher = M9, still unbuilt).
2. ON–OFF–ON re-observation of Kepler OFF ch25 (or archive mining for the
   same signature).
3. Full-band coherent dedispersion of the b1/ch57 shot (confirm/refute DM 323).
4. M9 cross-observation matcher (the only listed gap this overhaul did not
   close — monument recurrence needs it).
5. Full-polarisation xeno sweeps (this pass ran --xpol on top candidates
   only) + parallel scanning throughput.
6. Archive TLEs (space-track.org) for 2020-era satellite attribution of
   Kepler ch25/ch52; complex-native C detectors (use Q, not just I);
   PSRFITS folded-archive reader; chunked HDF5 streaming for GB-scale
   filterbanks (current ingest windows them).
