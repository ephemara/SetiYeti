# BEAST overhaul — what was added (2026-09-20, commit `06f693e`)

## Fast C core (`c/vendor/`, single-header, C99, `-lm` only)
- `sy_fft.h` — cached-twiddle radix-2 FFT (was: cos/sin per butterfly per segment).
  Verified 8.4e-12 vs naive DFT; pure tone lands in one bin.
- `sy_stats.h` — quickselect median (was: full qsort per segment), streaming
  kurtosis/tail, THE COMB RULE shared verbatim with `structure_pass.py`.
- `sy_io.h` — 64-bit offsets, checked `.f32` loader.
- `fam_scan` + `comb_scan` route through the core; Makefile adds `-march=native`,
  `comb_scan` target, `prove` / `prove-quick` / `pytest` targets.

## New detectors (prove: fires on inject, quiet on matched noise)
| module | closes | receipt |
|---|---|---|
| `pulsar_fold.py` | blind spot #1 (deaf to pulsars): envelope FFT + 8-harmonic sum, 1 Hz–2 kHz | 5/5 — noise max 10.8σ, thresh 16σ, weakest inject 3400σ |
| `transient_dm.py` | blind spot #2 (no FRB shots): DM sweep + boxcar bank | 3/3 — noise 10.8σ, thresh 14σ, injects 168σ+ |
| `raster_hunt.py` | M8 payload framing: semiprime fold vs shuffled control + sync search | 2/2 — 23×73 Arecibo 9.4σ, noise 1.7σ |
| `burst_zoom.py` | kepler1 §5.4 spiky giants: RADAR / CARRIER-BURST / GLINT / SPARKLE-CORRUPT | 3/3 |
| `cadence_pair.py` | ON–OFF gate (only legal WATCH→CANDIDATE path) + catalog audit | veto 9/9; audit suspended 2 bystander-family keys of 1387 |
| `seti_config.py` + `configs/kepler_L.toml` | M7 hardcoded constants: header FS/geometry wins, preset fills, CLI overrides | pytest |
| `pipeline.py` | one command: scans (4 pols) → structure → evidence → veto w/ evidence → burst → fold/DM → cadence → REPORT.md | TRAPPIST smoke live |

## Testing framework
- `tests/test_beast_fast.py` — 9 deterministic unit tests, ~1.5 s, no data.
- `tests/test_beast_prove.py` — 8 prove wrappers (failures localise).
- `python/sy_prove_all.py [--quick]` — enterprise gate. Full suite: **17/17 green**.
- Re-verified legacy: frame 9/9, jerk PASS, DSSS −12 dB (FFT 2.02× blind /
  FAM 7.35× DETECTED / despread 5×), SCD comb 4.1× + chirp 7279× exact rate,
  comb-C ALL PASS, veto 9/9.

## Bugs found by calibration (fixed with receipts)
- DM threshold 7→14σ, fold 8→16σ (DM×width / harmonic-trial multiplicity
  inflates the noise max; thresholds now sit 1.5× above worst noise, 12–200×
  below weakest inject).
- Burst regularity now on burst *onsets* (within-burst sample diffs zeroed it);
  regularity checked before sparkle count (a periodic train is radar).
- "Single tone never combs" selftest used a 200-amplitude fantasy tone whose
  sidelobes genuinely comb — now the realistic ch0 proxy (A=4, Y2 ~5×).

## Formal verification (`z3/`, z3-solver 5.1.0, one pip dep)
- `smt2/comb_rule.smt2` — single peak can never reach 3 members (UNSAT);
  Kepler family fires at b0=4 (SAT). `smt2/veto_disposition.smt2` — P1–P4
  safety (UNSAT-of-violation) + all dispositions reachable (SAT).
  `smt2/pack_bits.smt2` — pack injectivity (UNSAT-of-collision). 10/10 pass.
- `verify_c_median.py` — **FULL PROOF**: unrolled Lomuto quickselect N=5 ==
  sorted median over ALL 1024 inputs (UNSAT, caught+fixed an off-by-one in
  the *model*, code was right) + compiled C header vs statistics.median.
- `verify_c_comb.py` — rule semantics vs shipped code, 2000/2000 agree.
- `verify_veto.py` — disposition transcription vs real `score_slice`,
  3000/3000 agree, P1/P2/P3 zero violations (backs every SMT2 property).
- `verify_pack.py` — shipped `pack_bits` roundtrip, exhaustive 256 + 500.

## End-to-end (`configs/beast_e2e.toml`, TRAPPIST ON+OFF PART files)
1024 real slices in 0.9 min: quarantines held (dark lanes), veto with
  evidence 8 BLOCK / 0 WATCH / 0 CANDIDATE (correct — 2-block sip earns
  nothing), 13 bursts classified, 10 fold+DM deep passes, cadence 0/26
  promote (correct). 6 E2E smoke keys purged from catalog after (test
  pollution is the ratchet); verdicts preserved in `runs/beast_e2e/`.

## Honest limits
- Latent patch-mode floor is HIGH (0 dB det 0.16) — ranks texture, doesn't own
  sub-noise; cyclo owns sub-noise.
- `transient_dm` intra-channel DM is a proxy (2.93 MHz channel); full-band
  coherent dedispersion is the follow-up lever.
- Single pointing caps at WATCH. `jerk_scan`'s sidereal flag needs a
  track_score gate before trusting (follow-up).
- Full receipts: `README_BEAST.md`. Run: `python pipeline.py --preset
  configs/kepler_L.toml --on data/A.raw --off data/B.raw --outdir runs/beast_X`.
