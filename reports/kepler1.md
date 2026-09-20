# Kepler-160 long-haul inquest — report kepler1

- **Date of analysis:** 2026-09-20 (overnight run review)
- **Analyst:** agent shift review of `runs/longhaul_kepler/`
- **Objective served:** `_objective/objective_1.md` (bystander traffic / monuments / payloads)
- **Verdict in one line:** No candidate. Veto: 2,702 BLOCK / 3 WATCH / 0 CANDIDATE. One genuinely interesting structured family (358 Hz harmonics, common-mode), one good ON-only WATCH, several well-characterized artifacts — plus pipeline gaps that must be fixed before the next run.

---

## 1. What was observed and what ran

### 1.1 Data

| item | ON | OFF |
|---|---|---|
| file | `data/blc44_guppi_59103_01984_DIAG_KEPLER-160_0010.0000.raw` | `data/blc44_guppi_59103_02170_DIAG_KEPLER-160_OFF_0011.0000.raw` |
| size | ~17 GB | ~17 GB |
| MJD / date | 59103 (2020-09) | 59103 (same session, scan 0011 vs 0010) |
| target | KEPLER-160 (Sun-like exoplanet host, habitable-zone-candidate system) | KEPLER-160_OFF (~1° offset pointing) |
| telescope / backend | GBT, GUPPI (`Rcvr1_2`-class L-band path) | same |
| digitization | 8-bit | 8-bit |
| polarizations | 4 (p0–p3) | 4 |
| header | OBSFREQ 1407.71484375 MHz, OBSBW −187.5 MHz, TBIN 3.4133e-07 s → FS 2929687.5 Hz, BLOCSIZE 134217728 | same geometry |

Span per pointing: 128 blocks ≈ **22.906 s** (≈0.179 s/block). Block→time: b21≈3.8 s, b55≈9.8 s, b71≈12.7 s, b88≈15.8 s, b89≈15.9 s, b102≈18.3 s.

### 1.2 Band geometry (from header; veto `make_chan_freq`)

Centre 1407.715 MHz, 64 coarse channels, 2.9296875 MHz each, spanning 1315.4–1500.0 MHz (note: OBSBW negative, so ch0 is the TOP of the band):

| chan | freq (MHz) | allocation | earth prior used by veto |
|---|---|---|---|
| 0 | 1500.000 | fixed/mobile (terr) | +0.10 |
| 25 | 1426.758 | **RADIO ASTRONOMY protected 1400–1427 (ra)** | −0.10 |
| 27 | 1420.898 | **protected (ra)** | −0.10 |
| 41 | 1379.883 | fixed/mobile/radiolocation L-lower (terr) | +0.10 |
| 52 | 1347.656 | fixed/mobile/radiolocation L-lower (terr) | +0.10 |
| 53 | 1344.727 | terr (radar band) | +0.10 |
| 54–57 | 1341.8–1333.0 | terr (radar band) | +0.10 |
| 61/63 | 1321.3/1315.4 | terr | +0.10 |

### 1.3 Pipeline coverage (all phases completed, ~298 min wall)

- **Phase 1 preflight:** layout `chan-major, pol-interleaved`, 8-bit range sane (−67..+62 ON, −70..+70 OFF), block-0 smoke clean (ON 0 flagged; OFF 1 flagged + 7 quarantined dark lanes).
- **Phase 2 scans:** full 128 blocks × 64 ch × 4 pols × 2 files = **65,536 slices** (8,192 per pol per file). Thresholds: `fam_trig=3.0` (noise floor sits ~2.2–2.8), `spec_line=5.0`, `spec_hump=2.5`, `sparkle_max=25`.
- **Phase 3 veto:** ON/OFF cadence scoring, pols 0–1 only (`--jerk-pols 0,1`): p0 cadence ON=1291/OFF=1311 signatures; p1 ON=1414/OFF=1457.
- **Phase 4 PCA triage:** per-scan latent ranking (p0/p1, on/off).
- **Phase 5 jerk/Viterbi:** 256 channel-series (on/off × p0/p1 × 64 ch), 128 blocks each.
- **Phase 6 SCD+dechirp:** 25 candidates (spike-free only), full (α,f) plane + dechirp bank.
- **Phase 7 report:** `runs/longhaul_kepler/REPORT.md`.
- **This review added:** 4 full-span frame-period hunts (`frame_hunt.py`, M2) on ON ch52, OFF ch52, OFF ch25, ON ch53 (pol 0), plus cross-pol cadence audits of the WATCH slices from the scan CSVs.

---

## 2. Scan statistics

### 2.1 Per-pol verdict roll-up (from REPORT.md)

**ON (8,192 slices/pol):**

| pol | clean | QUARANTINE | hump-note | SPECTRAL-LINE | FAM-HIT |
|---|---|---|---|---|---|
| p0 | 6901 | 896 | 374 | 0 | 21 |
| p1 | 6778 | 898 | 369 | 128 | 19 |
| p2 | 6992 | 617 | 434 | 129 | 20 |
| p3 | 6933 | 620 | 618 | 1 | 20 |

**OFF (8,192 slices/pol):**

| pol | clean | QUARANTINE | hump-note | SPECTRAL-LINE | FAM-HIT |
|---|---|---|---|---|---|
| p0 | 6881 | 894 | 362 | 0 | 55 |
| p1 | 6735 | 895 | 377 | 128 | 57 |
| p2 | 6969 | 622 | 390 | 128 | 83 |
| p3 | 6880 | 619 | 613 | 0 | 80 |

Totals: **ON FAM-HIT = 80, OFF FAM-HIT = 275.** The OFF pointing is markedly hotter in cyclostationary flags (~3.4×). Quarantines (dark lanes) behave per-pol-pair (p0/p1 ≈ 895, p2/p3 ≈ 620) and never leaked phantom flags into the veto — the quarantine path worked as designed.

### 2.2 FAM-HIT channel distribution (the shape of the night)

| file | dominant FAM channels |
|---|---|
| ON p0 | ch52 ×3 (37.0 max), ch53 ×2, ch40 ×2, singles |
| ON p1 | ch52 ×4 (39.5 max), ch48 ×2, singles |
| ON p2 | ch56 ×2 (31.1 max), ch26 ×2, ch32 ×2, rest singles |
| ON p3 | ch41 ×4 (7.9 max), ch53 ×3, ch56 ×3 |
| OFF p0 | **ch25 ×38** (9.3 max), ch56 ×2 (**119.6 max**), ch54 ×2, ch57 ×2, ch52 ×1 (**41.0**) |
| OFF p1 | **ch25 ×40** (10.5 max), ch56 ×2 (**121.1 max**), ch52 ×1 (**43.0**) |
| OFF p2 | **ch25 ×33**, **ch57 ×29** (18.0 max), ch52 ×1 (13.2) |
| OFF p3 | **ch57 ×33** (23.1 max), **ch25 ×29** (11.2 max), ch52 ×2 (14.2) |

Three populations: (a) **ch52/ch56/ch53** — strong (up to 121×), both pointings, radar band; (b) **ch25** — OFF-only storm, ~140 slices, modest (≤11×), protected band; (c) **ch57** — OFF-only in p2/p3 (29–33 each), weak–moderate.

### 2.3 Strongest FAM-HIT rows (receipt table)

| slice | fam_best | α (fam_hz/tag) | spec | spikes | rms | note |
|---|---|---|---|---|---|---|
| OFF p1 b102/ch56 | 121.06 | 1431/Y4 | 2.86 | **3** | 8.18 | spiky mega-hit |
| OFF p0 b102/ch56 | 119.59 | 1431/Y4 | 2.90 | **5** | 8.17 | spiky mega-hit |
| OFF p0 b35/ch56 | 111.21 | 1431/Y4 | 2.42 | **3** | 8.17 | spiky mega-hit |
| OFF p1 b35/ch56 | 100.15 | 1431/Y4 | 2.88 | **4** | 8.17 | spiky mega-hit |
| OFF p1 b55/ch52 | 43.03 | 358/Y4 | 2.44 | 0 | 10.44 | **spike-free**, SCD'd |
| OFF p0 b55/ch52 | 41.00 | 626/Y4 | 2.17 | 0 | 10.46 | **spike-free**, SCD'd |
| ON p1 b21/ch52 | 39.51 | 2861/Y4 | 2.32 | **1** | 10.40 | strongest ON; 1 spike → skipped by SCD |
| ON p0 b21/ch52 | 37.04 | 2861/Y4 | 2.21 | 0 | 10.39 | **spike-free**, SCD'd |
| ON p2 b1/ch56 | 31.15 | 358/Y4 | 2.73 | 0 | 9.31 | **spike-free**, strongest clean ON ch56 |
| ON p0 b88/ch52 | 22.64 | 626/Y4 | 2.31 | 0 | 10.33 | **spike-free**, same α as OFF b55 |
| ON p1 b88/ch52 | 20.55 | 626/Y4 | 2.38 | 0 | 10.35 | **spike-free**, SCD'd |
| OFF p2 b4/ch57 | 18.00 | 2056/Y4 | 2.91 | 0 | 8.56 | spike-free OFF ch57 |
| ON p2 b2/ch56 | 10.37 | 1431/Y4 | 2.46 | 0 | 9.24 | **spike-free**, same α as OFF megas |
| ON p0 b89/ch52 | 6.73 | 1162/Y4 | 2.23 | 0 | 10.30 | spike-free, adjacent block to b88 |
| ON p0 b71/ch53 | 4.44 | 358/Y4 | 2.55 | 0 | 9.73 | **WATCH** (4-pol, §3) |
| ON p1 b71/ch53 | 4.34 | 358/Y4 | 2.44 | 0 | 9.75 | **WATCH** (4-pol, §3) |
| ON p0 b89/ch27 | 3.08 | 27627/Y2 | 1.83 | 0 | 14.91 | **WATCH**, marginal |

Key structural facts visible here:
- The four **100×+ events are all spiky** (3–5 spikes) — burst-like, and all at α=1431 Hz.
- The **spike-free** strong events (22–43×) share alphas across pointings: **626 Hz** (ON b88 ↔ OFF b55), **1431 Hz** (ON b2 ↔ OFF b35/b102), **358 Hz** (ON b1/b71 ↔ OFF b55), **2861 Hz** (ON b21; OFF b55/ch54 at 27.8× same α, different chan).
- 1431 ≈ 4×358 and 2861 ≈ 8×358: the family is a **harmonic comb on ~358 Hz** (§4.1).

---

## 3. Veto dispositions

- p0: **BLOCK=1289, WATCH=2, CANDIDATE=0** (catalog 1128 classes)
- p1: **BLOCK=1413, WATCH=1, CANDIDATE=0** (catalog 1387 classes)
- Veto ran on pols 0–1 only; p2/p3 flags were never dispositioned.

### 3.1 The three WATCH survivors

| veto line | slice | Earth/Structure/net |
|---|---|---|
| `b71/ch53 Y4:358Hz E=0.40 S=0.00 net=+0.40 → WATCH` | ON p0 b71/ch53 (fam 4.44, spec 2.55, spikes 0) | saved from BLOCK by −0.25 (α 358 Hz in rotation-astro band) |
| `b89/ch27 Y2:27627Hz E=0.45 S=0.00 net=+0.45 → WATCH` | ON p0 b89/ch27 (fam 3.08, spec 1.83, spikes 0) | saved by −0.10 protected-band prior |
| `b71/ch53 Y2:358Hz E=0.40 S=0.15 net=+0.25 → WATCH` | ON p1 b71/ch53 (fam 4.34, spec 2.44, spikes 0) | same event, other pol |

### 3.2 Cross-pol audit of the WATCH slices (from scan CSVs, this review)

**b71/ch53 (1344.7 MHz), block 71:**

| | p0 | p1 | p2 | p3 |
|---|---|---|---|---|
| ON | 4.44 @358 FAM-HIT | 4.34 @358 FAM-HIT | 3.67 @358 FAM-HIT | 3.22 @1073 FAM-HIT |
| OFF | 2.25 clean | 2.58 hump-note | 2.42 clean | 2.27 clean |

All four ON pols carry the 358 family in the same 0.18-s block (p3 at 1073≈3×358, the harmonic); OFF is quiet. Genuine ON-only multi-pol coincidence — but weak (3–4.4× vs 3.0 floor) and single-block. Best ON-only item in the run; capped at WATCH.

**b89/ch27 (1420.9 MHz, protected band):** ON p0 only (3.08×); all other pols and OFF clean (2.3–3.0). Single-pol, single-block, 0.08 above trigger. Noise-tail until proven otherwise.

---

## 4. Findings, ranked (the weird shit, with interpretation)

### 4.1 The 358 Hz harmonic family in the radar band — most engineered-looking, vetoed as earth-likely

Evidence: §2.3 rows — spike-free 22–43× cyclostationary on ch52/ch56/ch53 with α ∈ {358, 626, 1162, 1431, 2861}, harmonically related (1431≈4×358, 2861≈8×358), spectrum flat (spec ~2.2–2.7, no tone), present in **both** pointings but at different times (ON ~3.8 s & ~16 s; OFF ~10 s), SCD full-plane confirms multi-α peaks per slice (~10–12×, dechirp gamma=0 = stationary).

Reading: under Objective 1 §3.1/§6 this is the **common-mode + structured** class — the one the old veto was built to kill and the new two-axis veto was built to escalate. It did not escalate because **S scored 0.00 everywhere** (no comb/frame/pol flags are ever computed; §6.1). Prosaic hypothesis that fits everything: a continuous terrestrial emitter (radar/comms sidelobe) or backend oscillation illuminating each pointing at different times — but note the spike-free ON events do *not* look like pulsed radar, while the spiky 100× OFF events do. Split verdict: ch52/ch53-spike-free set = interesting, follow-up #1 (comb test); spiky ch56 megas = impulsive terrestrial, catalog.

### 4.2 b71/ch53 four-pol 358 event — best ON-only item, weak

Evidence: §3.2 table. Reading: ON-only + multi-pol + harmonic (358/1073) is exactly "polarisation coherence + baud family," two structure inputs the veto accepts but never received. Still: single 0.18-s block, ~4×. Follow-up: sub-Hz zoom + harmonics + re-observe. Cap: WATCH (single pointing, transient).

### 4.3 OFF-only ch25 burst storm in the protected band — terrestrial bursts, one zoom warranted

Evidence: ~140 OFF slices / 0 ON, 1426.8 MHz (protected), fam ≤11× with **scattered alphas** (2325, 4202, 1788, 1162, 3576, 82880… — no stable baud), spec_bin pinned at 204 (fixed intra-channel tone ~1.1 kHz offset, weak ~1.5–2.2×), **every row spiky (6–25 spikes)**, spread blocks 4–95. Reading: burst train through the OFF sidelobe (satellite/aircraft/ground emitter). The protected band makes it worth exactly one morphology zoom (identify the emitter), then catalog as local. Frame hunt on full-span OFF ch25: no frame (best 6.75σ vs 40σ) — bursts are aperiodic.

### 4.4 ch0 standing line at 1500 MHz — instrument/chain signature

Evidence: spec 15–17× @ bin 1, **all 128 blocks, both pointings, pols 1–2 only** (Y-chain), fam ~2.3 (no baud), rms ~20.5 (hot). Reading: backend DC/LO/filterbank artifact or local carrier, not sky. Cost tonight: 20 of 25 SCD slots re-detected it at 35–40× (spectral leakage into SCD, dechirp ~21–24k× @ gamma 0 = the same stationary line). Action: catalog as instrument class; exclude line-channels from SCD top-k.

### 4.5 OFF hotter than ON overall — asymmetry note

OFF p2/p3 carry 83/80 FAM vs ON's ~20/pol; OFF-only ch25 (140) and ch57 (60+) have no ON counterpart. ON's exclusives: b21/b88/b89-ch52, b1/b2-ch56, b71/ch53. Shared: ch52/ch56 alphas, ch0 line. A rotating illuminator (radar sweep) hitting each beam at different times fits the interleaved burst times; a sky source does not produce OFF-only storms. No statistic here favors celestial origin.

### 4.6 What is NOT there (negatives with receipts)

- **No persistent signal** except the ch0 artifact. Every FAM event is 1–3 blocks of 128. Traffic should sit in block 0 through 127 (Objective §3.2, §6-item-3). Nothing does.
- **No anomalous Doppler.** 256/256 Viterbi tracks at the ~6.0 noise ceiling (rowmax_z=6.00 everywhere), drift ≈0, curve gain 0 dB. Only outliers are ch0-artifact fits (ON ch0 v=+37.4, score 3.98; OFF ch0 v=+23.0, score 4.38) — fitting the instrument line, discounted. Prove rule: noise_max×1.25; nothing clears it.
- **No frame rhythm.** 4 full-span hunts: ON52 best 5.76σ, OFF52 6.98σ, OFF25 6.75σ, ON53 7.74σ — all vs 40σ detection threshold. No packet cadence at 1 ms–2.8 s.
- **No coded bits.** All VM verdicts noise-like — expected, since the sandbox was fed raw slices with no upstream demod candidate (step 5 of 5, starved).
- Against the traffic jackpot (structure / common-mode-engineered / persistence / Doppler / coding / geometry): roughly **one of six with an asterisk** (§4.1 minus persistence). Against monument (recurrence/host-independence/delay-tolerance): nothing repeats across a cycle; single night only. Against payload: unreachable, no detection to demodulate.

---

## 5. Pipeline gaps this run exposed (fix before next long-haul)

1. **Veto structure axis starved → the blindfold engaged.** Zero slices carried `comb`/`frame`/`nongauss`/`pol`; veto ran with no `--evidence` (so every flag took +0.30 transient +0.15 single-channel by default). Net = E − 0 everywhere; every strong structured event BLOCKed; only sub-5× weaklings survived as WATCH. The 358 family (§4.1) is the concrete re-score case: compute the baud-stack comb flag on b21/b88/b55-ch52 and re-run the veto with evidence.
2. **Catalog ratchet.** Tonight filed **552 new KEPLER160 classes as earth-likely** (catalog now 1387 classes total), including the 2861 Hz bucket (`KEPLER160:2.86e+03:terr`). At n_seen≥3 these become auto hard-blocks. Audit and remove/annotate the 358/626/1431/2861-family and ch25-burst keys before they permanently blind future searches — otherwise the pipeline will delete the bystander class by default.
3. **SCD top-k flooded by the known line.** 20/25 slots went to ch0 leakage (35–40×, gamma 0). Exclude flagged line-channels from candidate selection so the budget lands on ch52/ch56/ch25-zoom.
4. **Spiky giants fell between stools.** SCD selection skips spikes>0 (dropped the 100×+ OFF ch56, the 39.5× ON ch52-p1), but nothing ever characterized burst morphology either. Route spiky-strong events to a zoom/burst classifier instead of silently dropping them.
5. **Veto + Viterbi cover half the pols.** Veto ran p0–p1 only (p2/p3 flags undispositioned); jerk ran p0–p1 only. The b71/ch53 p2/p3 rows and all p2/p3 FAM were never scored or tracked.
6. **Dwell = a sip.** 22.9 s/pointing ≈ tens of bytes at plausible link rates vs kilobytes–megabytes for a bootstrap (Objective §3.2). Upper limits only; chained stares (M3) remain the sensitivity lever. And per the standing cap: a single pointing can never exceed WATCH; the ON–OFF pair exists here, but nothing earned promotion.

---

## 6. Numbers appendix (floors, thresholds, PCA, SCD, frames)

- **Detector floors:** fam trigger 3.0 (block-0 smoke noise 2.2–2.8); spectral line 5.0 / hump-note 2.5; sparkle quarantine >25 spikes (ch25 bursts at 6–25 sit just under it — flag for review); jerk noise ceiling ≈6.0 track score; SCD prove needs >2× noise-median ratio + comb structure (ch52 10–12× multi-α qualifies as structure-candidate; ch0 35–40× is leakage, not baud); frame detection threshold 40σ.
- **PCA triage tops:** ON p0 → b21/ch52 (235.4), b88/ch52 (139.6); OFF p1 → b102/ch56 (796.9), b35/ch56 (657.2), b55/ch52 (275.7), then the ch0 line train (~78–86). Synthetic-weird calibration scores [~4–48] vs best-real 235–797: the latent tail is dominated by known artifact classes (dark lanes, ch0 line, FAM bursts) — triage reads TUNE, i.e., no subtle novelty isolated.
- **SCD/dechirp (25 cands):** ch52 slices → α ratios ~10–12×, dechirp ~1.7–1.9k× @ gamma 0; ch0 slices → 34–40×, dechirp ~21–24k× @ gamma 0 (stationary-line confirmation, not chirps). No nonzero-gamma dechirp hit anywhere.
- **Frame hunts (this review, full 22.906 s span, env 5722 Hz, 1 ms–2.86 s):** ON ch52 no-frame (best 12.8 ms/77.9 Hz 5.76σ); OFF ch52 no-frame (best 2.97 ms/337 Hz 6.98σ); OFF ch25 no-frame (best 2.58 ms/388 Hz 6.75σ); ON ch53 no-frame (best 8.96 ms/111.6 Hz 7.74σ). Threshold 40σ in all runs.
- **Jerk exceptions (all else 6.00/6.000):** ON p0 ch0 3.976 (v+37.4/a−1.56), ch32 4.747; ON p1 ch48 4.129; OFF p0 ch0 4.379 (v+23.0/a−2.73); OFF p1 ch48 5.423, ch0 6.000-line. All consistent with noise ceiling + ch0 artifact fits.
- **Data hygiene:** preflight layouts sane; per-lane RMS/range quarantine caught dark lanes (p0/p1 ~895, p2/p3 ~620 per file) with no phantom leakage to veto; 17 GB files fully consumed (128/128 blocks, 0 errors).

---

## 7. Recommended next actions (concrete)

1. `baud_stack` comb test at 358 Hz on extracted `b21/b88-ON + b55-OFF ch52` slices → set `comb` → re-run `rfi_veto.py` **with** `--evidence` (persistence/multichan) on all 4 pols.
2. Sub-Hz zoom + harmonic table on ON `b71/ch53` (all pols) and one OFF `ch25` burst block (emitter ID), then catalog both outcomes.
3. Audit `rfi_catalog.json` KEPLER160 keys (552 added tonight), especially α-buckets 358/626/1431/2861 and ch25-burst classes; annotate, don't just accumulate.
4. Re-run SCD top-k excluding line-channels (ch0) and routing spiky-strong events to burst morphology.
5. Schedule chained stares (dwell = sensitivity) and, if anything re-fires, an ON–OFF–ON cadence — the only gate that can promote WATCH → CANDIDATE.

*Record note: scan CSVs, veto logs, PCA logs, jerk/SCD results, and REPORT.md live in `runs/longhaul_kepler/`; raw files in `data/` (gitignored, never committed). This file is the human-readable inquest; the CSVs remain the scientific record.*
