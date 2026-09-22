# I4 PROOF — ch44 b76 TRAPPIST-1 0017 (2026-09-21, live re-run)

Target: `data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw` ch44 (1371.09 MHz) block 76, all 4 pols.
Question: does mechanical I3 clear any I4 strong gate? (negDM / primes / precursor / doppler_anom / xvm-CANDIDATE)

**Verdict: I3 STANDS, I4 FAILS 5/5. I5 impossible on this slice. Analyst hold stays: backend-state flare.**

All products in `runs/i4proof/` (f32 + bins + this file). Veto dry-run only, catalog untouched.

## 1. Re-extract (tonight, `c/seti_slice`)

```
c/seti_slice <0017.raw> 44 runs/i4proof/b76ch44_p<P>.f32 1 --pol <P> --start 76
p0 rms 14.11 / p1 14.13 / p2 12.18 / p3 12.19, n=524288 each
```

## 2. ENGINEERED + SKY (I3 base, re-confirmed stronger than report)

| pol | Y2 @625Hz | Y4 @625Hz | comb | thicket nlines10 | xeno |
|---|---|---|---|---|---|
| p0 | 49.5x | 68.8x | 47.8 6-mem | 103 | skflag=1 impuls=1 kurt 1.67 |
| p1 | 49.2x | 78.5x | 49.9 7-mem | 115 | skflag=0 impuls=1 kurt 1.60 |
| p2 | 50.7x | 44.7x | 35.4 7-mem | 105 | skflag=1 impuls=1 kurt 4.93 |
| p3 | 57.7x | 52.3x | 36.5 6-mem | 109 | skflag=1 impuls=1 kurt 4.98 |

Same cyclic α=625.85 Hz in ALL FOUR pols. Comb DISCOUNTED every pol (fence holds).
Eng: ≥2 markers on p0/p2/p3 (p1 only 1, but slice grades as unit + veto S=0.35).
Sky: persist+on_only from `strips.csv` (0015 flicker / 0016 silent / 0017 32/32) — formal `pol_sky=0`, `scint≠SCINT` (see below), so sky rests SOLELY on cadence persistence.

## 3. I4 STRONG gates (all fresh tonight)

| gate | threshold (prove) | measured b76/ch44 | result |
|---|---|---|---|
| **negDM** (`exotic_pass`) | DM<-50, r2≥0.8, 8 bands | p0 DM -1160 r2 0.005 / p1 -5911 r2 0.238 / p2 -84 r2 0.384 / p3 -1703 r2 0.248, all `quiet`, score 0/5 | FAIL |
| **primes** | exact prime multiples, machinery 2/4/8/16 quiet | score 0.41-0.54, `quiet` all pols | FAIL |
| **precursor** | one-sided pre-echo, peak-hold | echo_ratio 0.03-0.044, `quiet` | FAIL |
| **clock/ladder** | stable same-bin both halves / cepstral comb | all `quiet` | FAIL |
| **doppler_anom** (`jerk_scan`, M5 screen bound 0.35 Hz/s @L-band) | real track + |v|>bound | p0 v=+0.0 OK / p1 -186 ANOM / p2 -6.1 ANOM / p3 -271 ANOM — BUT track_score 6.0 = rowmax, curve_gain 0.0-0.2 dB, 0.18 s span. Viterbi following spike pixel, not a line. Noise-track ANOMALOUS is meaningless. Formal `doppler_anom=0` | FAIL (kill: no line to Doppler) |
| **xvm-CANDIDATE** (≥3/6 machines) | 5/6 on coded+framed+looping, silent on noise | 8/8 trials noise-like: ops=1, ham 0.125-0.131 (=0.125 random), crc 0, best z 4.9 single. Chained 8-block 4.19M samples (1.43 s): ops=1 ham 0.127 | FAIL |
| **fold/frame** | fold σ, frame 40σ | fold VERDICT no period (σ~1-3.8); frame best 2.87σ vs 40σ, VERDICT no frame | FAIL |
| **scint/pol** | SCINT decorrelated / SKY-LIKE agree | `COMMON m=0.174 xcorr=0.81` (single gain moves all bands = backend); pol `agree=False` freqs 510/230/619/51 kHz diverge | FAIL (sky-marker, anti-sky here) |
| **pulsar/transient** | — | no period; dm SHOT DM=0 w=16 (zero-lag spike, not dispersion) | FAIL |

Jerk detail (kills the tempting ANOMALOUS):
```
p0 rows=31 rowmax_z=6.00 score=6.000 v=+0.0  a=+0.00   gain=0.0dB sidereal=OK
p1 v=-186.0 a=+3216  gain=0.2dB ANOMALOUS
p2 v= -6.1  a=-1156  gain=0.0dB ANOMALOUS
p3 v=-271.4 a=+2312  gain=0.1dB ANOMALOUS
```
Score == rowmax → no integration gain. Gain ~0 → quadratic fits nothing better than linear. 0.18 s cannot measure orbital Doppler. Real M5 anomaly needs a *line* that drifts, e.g. Viterbi TBD prove: -35 dB recovers v=+39.0 vs 40 injected. Here there is no line, only hum wobble.

Satpass (attribution, not gate):
```
block 76 -> 2017-02-23T21:04:58Z, GBT, GPS max_el 40.1 tca+40s rng 22086km
[warn] TLE 3496 days off → positions unreliable, needs archive elements
```
One MEO bird up, no LEO train. Cannot attribute, cannot exclude. Staleness guard correct.

Veto / cadence (formal):
```
cadence_pair --on t17_full_p0 --off t16_full_p0: on_flags=3683 off_flags=1680 promote_eligible=0/3683
veto S=+0.35 (comb +0.20, nongauss +0.15, thicket-discounted) → BLOCK/WATCH, zero CANDIDATE
```

## 4. Chained dwell (the only sensitivity lever)

8 blocks p0 b72-79 → 4,194,304 samples, 1.43 s, ones 0.471 → xvm ops=1 ham 0.127 noise-like.
Full report's 128-block 14,336-bit baud demod: ops=2 ham ~0.13 crc 0. Same answer at 8× and 128× dwell: **no code at any depth tried.**

## 5. S/X-band same-night raid (state-flip test) — preflight DONE, fetch QUEUED

Archive holds the night (verified via `query-files?target=TRAPPIST1`):
- 0020-0023 S-band 1745/1932/2120/2307 MHz ON-OFF-ON-OFF
- 0025-0028 C-band 5095-5657 MHz
- 0030-0033 X-band 8045-8607 MHz

Range-GET 0-64KB tonight:
```
blc04_0020_...2307MHz PROJID AGBT17A_999_12 OBSFREQ 2307.71 NBITS 8 NPOL 4 SMJD 76582 SRC DIAG_TRAPPIST1 → 206 64KB OK
blc04_0021_...OFF SMJD 76662 → 206 OK
blc24_0030_...8607MHz SMJD 78776 → 206 OK
```
State-flip prediction: if backend, S/X shows its own contemporaneous simmer OR clean with 2× dark-lane flip; if sky (AGN/monument/bystander), L-only with no S/X counterpart is expected but still needs recurrence. Fetch via:
```
python python/bl_download.py get --target TRAPPIST1 --file-types 'baseband data' --outdir D:/data/raw  # then mvp_scan b0-127 ch0-63
```
Cost: 17 GB/file × ~3.6 MB/s/conn (≈90 MB/s aria2c x16). NOT fetched tonight — this proof does not need it to block I4 (5/5 gates already fail on L-band alone). Fetch closes the *mechanism* question, not the grade.

## 6. What would flip to I4 (receipt list, no vibes)

- exotic `NEGDM=1` with |DM|>50 r2≥0.8 8-band, or `PRIMES=1` inconsistent with hum family (31.5-bin guard), or `PRECURSOR=1` one-sided peak-hold
- `doppler_anom=1` on a *real* Viterbi line: score≫rowmax, curve_gain≫0, persisting across blocks, |v|>0.35 Hz/s at 1371 MHz, retro-TLE clean
- `xvm_cand=1` (≥3/6) on baud-matched demod at 626 Hz with chained dwell, entropy pass, ham≫0.125 / crc excess
- then `xeno_pass` recomputed grade I4 + `cadence_pair` promote_eligible + second-telescope repeat

None present. I3 = eng (skflag+impuls, S 0.35) + sky (persist+on_only ONLY). Strong = 0. Grade: **I3 LEAN, analyst HOLD (backend-state flare, ~65%)**.

Reproduce:
```bash
c/seti_slice data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw 44 runs/i4proof/b76ch44_p0.f32 1 --pol 0 --start 76
c/fam_scan runs/i4proof/b76ch44_p0.f32 2929687.5 32768 6 - ; c/comb_scan runs/i4proof/b76ch44_p0.f32 2929687.5
c/xeno_scan runs/i4proof/b76ch44_p0.f32 2929687.5
python python/exotic_pass.py --f32 runs/i4proof/b76ch44_p0.f32 --fs 2929687.5
python python/scint_pol.py --f32 runs/i4proof/b76ch44_p0.f32 --f32-pol runs/i4proof/b76ch44_p1.f32 --f32-pol runs/i4proof/b76ch44_p2.f32 --f32-pol runs/i4proof/b76ch44_p3.f32 --fs 2929687.5
python python/jerk_scan.py --f32 runs/i4proof/b76ch44_p0.f32 --fs 2929687.5 --freq-mhz 1371.09
python python/satpass.py --guppi-at data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw --block 76 --dur 30 --site GBT --sample
```
