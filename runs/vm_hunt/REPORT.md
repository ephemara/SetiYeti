# VM-code hunt — TRAPPIST-1 + Kepler-160 (2026-09-21)

Target: self-executing VM code through the upgraded 6-machine battery (`c/xvm_sandbox`).
Verdict up front: **nothing executes. 0/58 XENO-CANDIDATE. Zero I3+. Zero CANDIDATE.**
What follows is what the net caught, what it proves, and the three things worth a second look.

## 1. Coverage (all fresh tonight)

- 10 new scans, blocks 0–3 × chans 0–63 × pols 0–1: TRAPPIST 0015 ON + 0016 OFF
  + **0017 ON (third file, first deep look)** + Kepler 0010 ON + 0011 OFF = 2,560 slices.
- `structure_pass` (comb/thicket/nongauss) + `build_evidence` + `rfi_veto --dry-run`
  + `xeno_pass --xpol` on the small-scan candidates.
- Targeted dive (`vm_dive.py`, log in `dive.log`): 29 slices × sign/diff = **58 full
  battery trials** — every hot slice from both reports (burst, 179-hum, b21/b88/b71-ch52,
  ch56 megas, ch25, ch57, T17 inferno) + 4 quiet controls.
- Follow-ups: `exotic_pass` + `scint_pol` on flagships; baud-matched demod
  (integrate-and-dump at fam α, demeaned) through the sandbox on the top 3.

## 2. The VM result (the actual ask)

| slice | best xvm (of 6 machines) | verdict |
|---|---|---|
| all 25 hot slices (sign+diff) | 0–1 machines flicker (STACK ≤1011 ops, ACF z ≤5.9, ham ≈0.125–0.135 = random, crc 0) | noise-like |
| T17 b2/ch56 sign | STACK 512 ops / 85 loops (needs 5000/20) | noise-like, most active hot slice |
| T17 b0/ch56 sign | STACK 1011/250, ACF z=5.8 (needs 6.0) | noise-like, closest approach |
| burst p2 sign | ACF z=6.0 single flicker | XENO-WATCH (1/6) |
| **CTRL K10 b0/ch20 diff (quiet control!)** | legacy `vm_sandbox`: steps=200000 locality=1.0 → **CANDIDATE-structure**; xvm: 1/6 → XENO-WATCH (ops=6, loops=1, ham random, crc 0) | **legacy false alarm, correctly held by the upgrade** |
| baud-demod (112/47 bits) | entropy gate BLOCKs (distinct 6–14) | refused, correctly — 10² symbols cannot hold a program |

Reading: the bits behind the strongest cyclostationary in the corpus do not loop,
do not breathe (CA), do not frame (ACF), and carry no ECC (Hamming/CRC).
Strong Y4 ≠ code — the hum is modulation-free power wobble. And the upgrade earned
its keep: the old single-machine rule fires CANDIDATE on a *control* slice's diff
bits; the 6-machine rule holds it at WATCH. That is a live-fire calibration of the
"massive update", on real data, tonight.

## 3. Weird shit, ranked

1. **TRAPPIST 0017 is on fire (new).** Blocks 0–3: 31+29 FAM-HITs vs 1–2 in 0015;
   b2/ch56 31.5×@268 Hz with **Y2 6.4×@358 Hz** (strongest coherent line in the dive)
   inside a **871-line forest** (fence holds, comb discounted); b3/ch4 20×@1520.
   Same 179-family, hotter backend state. Nobody had looked at this file.
2. **Burst pol split (new anatomy).** Same block/chan: p0/p1 = 91×/71× forest
   (90–101 lines>10×); p2/p3 = 3.5× + maxz-15 spikes, no comb. Sky appears in all
   feeds; this wears a different mask per receiver chain → local discharge, with receipt.
3. **Kepler b88/ch52: real comb + PRIME-TRAIN — downgraded with mechanism.**
   Genuine 9-line comb (thicket=0, spared by fence) + exotic `primes=1` (9/9 lock).
   Batch test shows the SAME 31–40-bin interval family in 6 unrelated hum slices
   (scores 0.47–1.0): 31.5 bins × 87 µs = 2.75 ms = **363 Hz = the hum period**.
   The picker traces hum cycles; base=min/11 manufactures the prime lock.
   New named confounder: hum-locked prime numerology. Still the top follow-up slice
   (real comb, ON), but not code, not sky-marked.
4. **New small-scan flag: T15 b2/ch12 7.6×@2593 Hz (Y4).** No comb, no markers,
   VM silent, veto BLOCK. Transient wobble; catalogued.
5. Ch0 standing line in every scan (instrument), ch57–63 dark lanes (quarantine worked;
   0017 has 2× the dark lanes of 0015 — backend-state note).

## 4. Universal-level reading

Two planetary systems, three pointings, five files: the machine heard its own
oscillator complex (the 179 Hz family, 2017→2020, both stars), its own digitizer
offset, one electrical sneeze (the burst), and human neighbourhood drizzle.
No bitstream anywhere loops, frames, or error-corrects. The one physical law that
bites hardest tonight: **a 0.18 s block at ~600 baud holds ~112 symbols — programs
do not fit in sips.** Executable-code SETI needs chained blocks (dwell), not sharper
single-block tests. The battery is proven lethal (5/6 on hand-built code, silent on
noise); it is simply starved of demodulated dwell.

## 5. Follow-ups (priority)

1. Chain 128 blocks on T17 ch56/ch4 (dwell = the only sensitivity lever left).
2. Prime-guard: require exotic `primes` intervals inconsistent with the hum family
   before it can escalate (filed as confounder with receipt above).
3. ON–OFF–ON on Kepler b88/ch52 (real comb) and Kepler OFF ch25 (protected band).
4. Recurrence search for the b1/ch57 burst signature across full 17 GB files (M9).

Files: scans `trap_* kep_* trap17_*`, structs `struct_*`, evidence `evidence_*`,
grades `xeno_*`, full battery transcript `dive.log`, driver `vm_dive.py` — all in
`runs/vm_hunt/`. Veto ran `--dry-run` (catalog untouched).

## 6. Rarity audit — the (1011 ops / 250 loops / ACF z=5.8) coincidence
Claim under test: P_joint ≈ 2.4e-11 (1 in 41B). Method: 500 phase-randomized
surrogates of the actual slice (spectrum incl. 179 Hz wobble preserved EXACTLY,
coded phase info destroyed) + 500 pure-noise trials, all through `xvm_sandbox`.
- Loops (ops≥1000 & loops≥85): surr 3/500 (maxloops **25000**), noise 0/500
  (but one 256-loop event with ops<1000). Verdict: spectrum alone manufactures
  loops; loop metric has ~zero specificity on hum-contaminated data — which is
  WHY the battery requires 3/6. Claimed P_loop=1/4096 falsified by 2+ orders.
- ACF |z|≥5.8: surr 0/500 (max 5.2), noise 0/500 (max 4.8). Fat-tailed vs the
  Gaussian 3.3e-9/lag story, but genuinely the rarer half of the pair.
- Joint: 0/1000 in MC vs 1/58 streams in the hot-slice dive (~2%).
Honest rarity: percent-level under a hum-aware null — ~9 orders of magnitude
more common than claimed. Four breaks in the 41B math: (1) ~4000 lags searched,
not 30; (2) Gaussian tail on non-Gaussian, hum-modulated, spiky data —
falsified by our own 4× z≥5.6-in-58 observation; (3) P_loop uncalibrated and
contradicted by controls (253 loops) and surrogates (25000 loops);
(4) independence assumed between two metrics reading the SAME bits through the
SAME spectrum, then framed as single-trial while selected as max-of-116-streams
from thousands of slices. Driver: `runs/vm_hunt/rarity_mc.py`, log `mc.log`.

## 7. TRAPPIST-0017 deep dive (the file nobody had opened)
Headers confirm a natural ON–OFF–ON triple, 80 s apart: 0015 ON (RA 346.62,
DEC −5.04) → 0016 OFF (RA 347.61, DEC −5.56, ~1° away) → 0017 ON (RA 346.63,
DEC −5.03). Full 0017 scan: 16,384 slices, ~3,200 FAM (20%), only 14 Y2
(max 8.2×) — an all-channel, all-block, Y4-only simmer. Cadence strips
(9 chans × 32 blocks × 3 files, `strip17.py`/`strips.csv`): 0015 flickers
(3% >4×), 0016 stone silent (max 2.9×, 0% >4×), 0017 blazes (67% >4×,
mean 17×, max 398×). Onset hides in the 80 s gap before 0017 block 0.
- **ch44: first mechanical I3.** Continuous blocks 0–124 (8–69×), same
  α=626 Hz in ALL FOUR pols (49–58×, SKY-LIKE), ON-only across the triple
  (0015: 3 flicker blocks; 0016: zero; 0017: 32/32) → eng (skflag+impuls)
  + sky (persist+on_only, plus pol) + no strong markers = I3 LEAN.
  Chained baud demod (128 blocks → 14,336 bits @626 Hz, 4,096 @179 Hz):
  stone noise-like (ops=2, ham ~0.13, crc 0). No code at 128× dwell.
  Analyst hold: backend-state flare (state flip in gap, 2× dark lanes,
  all-channel simmer, COMMON scintillation, hum family) — I3's prescription
  (re-observe + archive check) is the follow-up, not a detection.
- **Monster b68/ch56:** 398× Y4 + Y2 369× (p0/p1 @1430 Hz) / 612–666×
  (p2/p3 @358 Hz) — strongest coherent lines ever measured here;
  skflag=1 (14% bins), kurt 5.0, single 0.18 s flare, pol-divergent
  harmonics, scint COMMON → I2, veto BLOCK (thicket+transient+COMMON).
  Local discharge through chain-dependent filtering.
- Reframe: the thicket family is STATE-dependent (quiet→inferno between
  scans 80 s apart), same 179-family, 2017→2020, both stars. Mechanism
  hunt now has an onset window.
Follow-ups: re-observe ch44 ON–OFF–ON; full 0015/0016 census (strips only
so far); M9 recurrence search for b68-type flares; SK-tuning note (skflag
fires on COMMON bursty data — microstructure alone never implies sky).
