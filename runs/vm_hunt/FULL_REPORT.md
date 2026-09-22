# FULL REPORT — TRAPPIST-1 ch44 / scan-0017 anomaly campaign (2026-09-21)

All products live in `runs/vm_hunt/` (repo root `E:/SetiYeti`). Raw voltage is
gitignored and never committed. Veto ran `--dry-run` throughout: the shared
`rfi_catalog.json` was read, never mutated.

**Verdict in one line:** a continuous 23-second 179-family blaze, ON-only across
a natural ON–OFF–ON triple, mechanically grading I3 (first ever) and held on
analyst review as a backend-state flare; zero executing code at every depth
tried; the full combination is unique in the whole record.

---

## 1. Raw data files scanned

GBT/GUPPI, 8-bit, 64 channels × 4 pols (AABBCRCI), 128 blocks ≈ 22.9 s each
(0.179 s/block), unless noted. Geometry: OBSFREQ 1407.71484375 MHz,
OBSBW −187.5 MHz → f(ch) = 1500.000 − 2.9296875·ch MHz; **ch44 = 1371.09 MHz**
(fixed/mobile/radiolocation allocation, terrestrial prior).

| file | target / pointing | date / scan / start | band | size | role in this campaign |
|---|---|---|---|---|---|
| `data/blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.raw` | TRAPPIST-1 ON (RA 346.62, DEC −5.04) | 2017-02-23, scan 15, SMJD 75725 | L 1407 MHz (blc04) | 17 GB | ON leg #1: small scan (b0–3) + FULL census p0 |
| `data/blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw` | TRAPPIST-1 OFF (RA 347.61, DEC −5.56, ~1° away) | scan 16, SMJD 75805 (+80 s) | L 1407 MHz (blc04) | 17 GB | OFF leg: small scan + FULL census p0 |
| `data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw` | TRAPPIST-1 ON (RA 346.63, DEC −5.03) | scan 17, SMJD 75885 (+80 s) | L 1407 MHz (blc04) | 17 GB | ON leg #2, **first deep look ever**: small scan + FULL census p0/p1 + all battery work |
| `data/blc44_guppi_59103_01984_DIAG_KEPLER-160_0010.0000.raw` | Kepler-160 ON | 2020-09, scan 0010 | L 1407 MHz (blc44) | 17 GB | control target: small scan b0–3 p0/p1; hot slices reused in VM dive |
| `data/blc44_guppi_59103_02170_DIAG_KEPLER-160_OFF_0011.0000.raw` | Kepler-160 OFF | scan 0011 | L 1407 MHz (blc44) | 17 GB | control target: small scan b0–3 p0/p1; hot slices reused in VM dive |
| `D:/data/raw/blc00_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw` | TRAPPIST-1 ON, scan 17 | same 23 s as above | 2157 MHz (blc00) | 17 GB | simultaneity test → **node dark all night** (rms ~1.3, 10–30 codes); test void by hardware (see §7) |
| `D:/data/raw/blc00_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw` | OFF, scan 16 | same 23 s as above | 2157 MHz (blc00) | 17 GB | same: dark (rms ~1.3). Scan-0018 fetch skipped — same dead node |

Cadence: 0015 ON → 0016 OFF → 0017 ON, 80 s apart. A natural ON–OFF–ON triple.

---

## 2. Scan products (all in `runs/vm_hunt/`)

Small scans: blocks 0–3 × chans 0–63. Full scans: blocks 0–127 × chans 0–63.

| CSV | raw source | coverage | slices | FAM | SPEC | QUAR |
|---|---|---|---|---|---|---|
| `trap_on_p0.csv` | 0015 ON | b0–3, p0 | 256 | 1 | 4 | 29 |
| `trap_on_p1.csv` | 0015 ON | b0–3, p1 | 256 | 0 | 0 | 30 |
| `trap_off_p0.csv` | 0016 OFF | b0–3, p0 | 256 | 1 | 2 | 27 |
| `trap_off_p1.csv` | 0016 OFF | b0–3, p1 | 256 | 3 | 4 | 27 |
| `trap17_on_p0.csv` | 0017 ON | b0–3, p0 | 256 | 31 | 4 | 58 |
| `trap17_on_p1.csv` | 0017 ON | b0–3, p1 | 256 | 29 | 0 | 58 |
| `kep_on_p0.csv` / `kep_on_p1.csv` | Kepler ON | b0–3, p0/p1 | 256 ea | 0 / 1 | 0 / 4 | 28 ea |
| `kep_off_p0.csv` / `kep_off_p1.csv` | Kepler OFF | b0–3, p0/p1 | 256 ea | 0 / 0 | 0 / 4 | 28 ea |
| `t15_full_p0.csv` | 0015 ON | b0–127, p0 | 8192 | 30 (21 Y4 / 9 Y2) | 128 | 900 |
| `t16_full_p0.csv` | 0016 OFF | b0–127, p0 | 8192 | 29 (19 Y4 / 10 Y2) | 78 | 893 |
| `t17_full_p0.csv` | 0017 ON | b0–127, p0 | 8192 | **1618 (1610 Y4 / 8 Y2)** | 132 | 1653 |
| `t17_full_p1.csv` | 0017 ON | b0–127, p1 | 8192 | **1606 (1600 Y4 / 6 Y2)** | 2 | 1654 |
| `blc00_t17_p0.csv` | blc00 0017 | b60–75, p0 | 1024 | 0 | 47 | 977 (dark node) |

Downstream: `struct_*.csv` (comb/thicket/nongauss per scan), `evidence_trap.csv`
/ `evidence_kep.csv` (persistence/multichan), `xeno_trap_on_p0.csv` /
`xeno_trap_off_p0.csv` (I-grades, `--xpol`).

---

## 3. Derived analysis files (all in `runs/vm_hunt/`)

| file | contents |
|---|---|
| `dive.log` (60 KB) | full 6-machine battery transcript: 29 slices × sign/diff = 58 trials (`vm_dive.py`) |
| `sweep.csv` (256 rows) | per-block xvm sweep, 0017 ch44+ch56 × 128 blocks (`sweep_xvm.py`) |
| `strips.csv` (864 rows) | ON–OFF–ON persistence strips: 9 chans × 32 blocks × 3 files (`strip17.py`) |
| `mc.log` + `rarity_mc.py` | 500 spectrum-matched surrogates + 500 noise trials through `xvm_sandbox` |
| `record_sweep.py` | whole-record sweep (100+ CSVs under `runs/`, 1512-class catalog) — §8 |
| `REPORT.md` | running log (§1–10); this file is the consolidation |

---

## 4. Where the phenomenon happens

### 4.1 Per-file activity (fam top-1 strips, 9 hot channels, stride-4 blocks)

| file | mean fam | max fam | frac blocks >4× | character |
|---|---|---|---|---|
| 0015 ON | 2.62× | 22.9× (b4/ch44 @179 Hz) | 0.03 | flickers: b4 (22.9), b12 (6.1), b80 (5.2) on ch44; else noise |
| 0016 OFF | 2.43× | 3.84× | 0.00 | stone silent; full census adds only the two ch57 bursts (b1 91×, b68 42×) |
| 0017 ON | 17.21× | 397.6× (b68/ch56 @1431 Hz) | 0.67 | blazing; hot chans 4/12/28/36/44/56 (means 18–33×); quiet-ish 24/26/48 (3–5×) |

Onset hides in the 80 s gap before 0017 block 0. 0017 has 2× the dark lanes
(1653 vs ~900 quarantines) — receiver state demonstrably different.

### 4.2 ch44 block profiles (fam_best @ peak α, stride 4, pol 0)
- **0017:** `0:8, 4:65, 8:22, 12:36, 16:58, 20:35, 24:38, 28:10, 32:39, 36:22,
  40:32, 44:32, 48:64, 52:40, 56:25, 60:35, 64:18, 68:18, 72:21, 76:69, 80:38,
  84:15, 88:19, 92:50, 96:30, 100:36, 104:34, 108:43, 112:29, 116:59, 120:14,
  124:12` — 32/32 above 4×, always ≥8×. Continuous energy, **wandering peak α**
  (625→1430→1877→1072→1788 Hz across blocks).
- **0015:** single-block flare b4 (22.9×) + b12 (6.1×) + b80 (5.2×); else ~2.4×.
- **0016:** max 2.9×, zero blocks above 4×.

### 4.3 ch56 profile (0017): mostly quiet (2–13×) + flares — b68 398×, b92 21×.

---

## 5. Key slices (all voltages re-extracted with `c/seti_slice`, 524288 samples)

| slice | fam (Y2 / Y4) | comb / thicket | xeno micro | xvm (6-machine) | exotic / scint |
|---|---|---|---|---|---|
| 0017 b76/ch44 p0–p3 (the I3) | Y4 49–58× @626 Hz, **same α all 4 pols** | comb 6-member, DISCOUNTED (103 lines>10×) | skflag=1 (skdev 4.66), impuls=1, kurt 1.67 | silent (ops≤2, ham ~0.125, crc 0) | all quiet; COMMON |
| 0017 b68/ch56 p0 (monster) | Y4 398× @1431; Y2 369× p0/p1 @1430, 612–666× p2/p3 @358 | comb score 225, 8 members, DISCOUNTED (92 lines) | **skflag=1** (14% bins), kurt 5.0, tailx 80, impuls=1 | silent | all quiet; COMMON |
| 0017 b0/ch56 p0 | Y4 10.4× @179 | thicket | all 0 | STACK 1011 ops / 250 loops (needs 5000/20); rest dead | all quiet; QUIET |
| 0017 b91/ch56 | fam 2.3 (quiet) | — | — | 256 loops, z 4.7 — on a QUIET slice | — |
| 0016 b1/ch57 p0/p1 (burst) | Y4 91×/71× @626/2861 | comb ~60/52, DISCOUNTED (90–101 lines) | impuls=1 only | silent | all quiet |
| 0016 b68/ch57 (2nd burst) | Y4 42× @1431 | — | — | (catalogued; same family) | — |
| 0015 b4/ch44 (hum) | Y4 22.9× @179 | comb 21.7, DISCOUNTED (108 lines) | impuls=1 | silent | — |
| Kepler b88/ch52 | Y4 22.6× @626 | comb KEPT (9 lines, thicket 0) — genuine | all 0 | silent | PRIME-TRAIN=1 (hum-locked, see §9) |
| controls (ch20 ×4 files) | ~2× noise | none | all 0 | noise-like — except: legacy `vm_sandbox` fired CANDIDATE-structure on K10-diff bits; xvm held it at 1/6 WATCH | — |

---

## 6. Pipeline verdicts
- Veto (`--dry-run`, catalog untouched): everything BLOCK or WATCH, zero
  CANDIDATE. Burst: comb DISCOUNTED + thicket +0.35. Monster: same + transient
  + COMMON. ch44 b76: thicket-discounted comb, nongauss +0.15.
- Grades (`xeno_pass --xpol`): small-scan candidates I1 (flagged, unengineered).
  b76/ch44 by the ladder (`INTERSTELLAR_HIT_CRITERIA.md`): flagged=1,
  eng (skflag+impuls ≥2 markers), sky (persist+on_only; plus same-α 4-pol),
  strong=0 → **I3 INTERSTELLAR-LEAN — first in the campaign**. Analyst hold:
  backend-state flare (onset gap, 2× dark lanes, all-channel simmer, COMMON
  scint, hum family, pure-AM constraint). I3's prescription (re-observe +
  archive check) is the follow-up.
- Chained dwell: ch44 128 blocks → 14,336 bits @626 Hz + 4,096 @179 Hz:
  stone noise-like (ops=2, ham ~0.13, crc 0). No code at 128× dwell.

---

## 7. Twin-band test
blc00 node (2157 MHz) is dark in both scans (rms ~1.3, 10–30 distinct codes,
977/1024 quarantined) — dead digitizer all night, quarantine correct.
Simultaneity test void by hardware. Scan-0018 fetch skipped (same dead node).

---

## 8. Whole-record sweep (`record_sweep.py`: 100+ CSVs, 1512 catalog classes)
- Duplicates: same events reprocessed up to 8× (burst 91× in 8 files = 1 event).
  WRONGLAYOUT 732 kHz rows (250–520×) excluded by provenance (known unpack bug).
- 626 Hz (101 rows): burst, Kepler ON+OFF, 0017 multi-chan — **never ch44
  outside 0017**. ch44 flares in valid data: ONLY 0015-transient + 0017-
  continuous; never OFF, never Kepler/HIP/M31/Voyager.
- Persistent same-α (≥6 blocks) and 4-pol coincidences: only 0017 in valid
  data (b76/ch44 is the sole 4/4-pol ON-only case; the 2 historical 4-pol
  hits are Kepler 3-pol).
- Catalog already learned the family: `TRAPPIST:179:terr` @1371.09 MHz (=ch44,
  n_seen=8, auto hard-BLOCK — the ratchet would bury the I3 slice on sight);
  `KEPLER160:626:terr` structured=True yet BLOCKed; Y2:179/268 at 9.19 GHz,
  n_seen=370/46 → family spans L→X band = backend hardware.
- Prime-train on Kepler b88/ch52 downgraded: same 31–40-bin interval family in
  6 unrelated hum slices — 31.5 bins × 87 µs = 2.75 ms = 363 Hz = the hum
  period. New named confounder: hum-locked prime numerology.
- Rarity MC: loops≥85 at 3/500 surrogates (maxloops 25000 on random-phase
  data) — spectrum manufactures loops; joint loop+z≥5.8 at 0/1000 MC vs 1/58
  dive streams (percent-level, not 1-in-41B).

---

## 9. Hypothesis ranking (ch44)
Backend state + intermod ~65% | terrestrial continuous ~12% | satellite ~8% |
M-dwarf burst ~1% (V/I=0 kills ECMI; 626 Hz 100× too fast for QPPs) |
scintillating AGN ~1% (L-band ISS is percent-level) | bystander sidelobe ~2% |
monument ~1% (single night, wobbling α, no frame). Killed outright: rotation
(fold σ~1), packets (frame 8.8σ vs 40σ), code (14k chained bits silent),
polarized stellar (V/I=−0.001, lin/circ = control).

## 10. Follow-ups (priority)
1. Re-observe ch44 ON–OFF–ON (the only verdict in three stars that requires glass).
2. M9 burst-matcher across full 17 GB OFF files (two exemplars: b1, b68).
3. S/X-band same-night raid (scans 0020–0026) for the state-flip test.
4. Full 0015/0016 p1–p3 + 0017 p2/p3 census (p0-only so far, except 0017 p1).
5. Prime-guard + SK-tuning + catalog-ratchet audit (TRAPPIST:179:terr n=8).

## 11. Reproduce
```bash
# scans (example: full 0017 p0)
python python/mvp_scan.py --raw data/blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw \
  --b0 0 --b1 127 --chans 0-63 --pol 0 --out runs/vm_hunt/t17_full_p0.csv --workers 4
# any slice -> battery
c/seti_slice <raw> <chan> out.f32 1 --pol <p> --start <block>
c/fam_scan out.f32 2929687.5 32768 6 - ; c/comb_scan out.f32 2929687.5
c/xeno_scan out.f32 2929687.5   ; python python/bitslice.py --f32 out.f32
# sweeps: python runs/vm_hunt/strip17.py | sweep_xvm.py | rarity_mc.py | record_sweep.py
```
