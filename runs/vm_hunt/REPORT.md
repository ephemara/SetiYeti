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

## 8. REOBSERVE execution (archive raid + block-by-block sweep)
No telescope on the roof — executed the archive equivalent.
- Archive holds the full night: scans 0015→0026 (S-band 2157 MHz blc00,
  3057 MHz, X-band 7907 MHz). Fetched blc00 0017-ON + 0016-OFF (17 GB each,
  D:/data/raw): **blc00 node is dark all night** (rms ~1.3, 10–30 codes) —
  dead digitizer, quarantine correct, simultaneity test void by hardware.
  0018-blc00 skipped (same dead node). S/X-band same-night scans noted for
  a future multi-band raid.
- Missing census closed: 0015 full = 30 FAM (top b4/ch44 22.9 @179);
  0016 full = 29 FAM incl. a **SECOND OFF burst b68/ch57 42× @1431**
  (burst recurrence in OFF = relay/discharge repeating, mechanism lead).
- Per-block xvm sweep (`sweep_xvm.py`/`sweep.csv`, 256 blocks ch44+ch56):
  NO block executes (255 noise-like, 1 XENO-WATCH). Kill shots: the lone
  WATCH is a QUIET block (b107, fam 2.4, ops=1/loops=1); 256-loop max sits
  on a quiet block (b91, fam 2.3) — the loop metric is twitchy, period.
  z≥5.0 in 39/128 ch56 blocks (30% — routine on the flare channel) vs
  6/128 ch44; ch44 VM-dead despite mean fam 35×. Strongest joint remains
  b0/ch56 (250 loops + z5.8), a percent-level bursty-spectrum coincidence.
Final dispositions: ch44 = mechanical I3, analyst hold (backend-state
flare); monster b68/ch56 = I2/BLOCK; OFF burst pair = catalogued local.

## 9. ch44 possibilities — ranked, with killer tests (2026-09-21)
Fold (1–2000 Hz): no period (σ~1 vs 16σ). Frame (1 ms–2.86 s, 23 s span):
no frame (8.8σ vs 40σ). Stokes: V/I=−0.001, lin/circ split identical to
control — unpolarized; zero total-power excess (pure AM of existing noise).
1. Backend gain/oscillator state + intermod — ~65%. Onset in 80 s gap, 2×
   dark lanes, all-channel Y4 simmer, COMMON scint, hum family, pure-AM
   with no power/polarization signature. Killer test: S/X-band same-night
   (0020–0026) + re-observe (state recurs or it doesn't).
2. Terrestrial continuous emitter (1371 MHz = radar/mobile band) — ~12%.
   Killer: re-observe + sidereal-repeat check.
3. Satellite in beam/sidelobe — ~8%. Killer: retro-TLE match (satpass),
   re-observe (never repeats same way).
4. M-dwarf coherent burst — ~1% (was 5%). V/I=0 kills ECMI; 626 Hz AM 100×
   too fast for flare QPPs. Dead unless a polarized component turns up.
5. Scintillating background AGN — ~1%. L-band ISS modulation is percent-
   level; cannot make 50×. Dismissed quantitatively.
6. Bystander-link sidelobe — ~2%. Continuous + ON-only fits; no coding,
   no frame, no Doppler, FAM-loud-but-dumb is backwards for efficient links.
7. Monument/beacon — ~1%. Single night, wobbly α, no frame, no recurrence —
   fails every monument clause (needs cycles + delay tolerance).
Novel (real): first mechanical I3; 80 s onset window on the thicket family;
flicker-to-blaze in one channel across one night; 4-pol Y4 coherence at 50×;
pure-AM/no-power/no-pol constraint; second OFF burst; blc00 dead node.
Not novel: zero information content at every depth tried (fold/frame/VM to
14k bits); hum family known since 2017. P(sky) ≈ 5–10% total. The interest
is the survival itself: the only channel in 65k+ slices across three stars
to clear every filter except the final analyst hold.

## 10. Whole-record sweep for the ch44 pattern (`record_sweep.py`)
Swept 100+ scan CSVs (132 files) + 1512-class catalog. Duplicates noted:
same events reprocessed up to 8× (burst 91× in 8 files = ONE event).
WRONGLAYOUT 732 kHz rows (250–520× "Y2") excluded by provenance (known
unpack bug), not physics.
- 626 Hz (101 rows): burst, Kepler ON+OFF, 0017 ch4/12/20/28 — NEVER ch44
  outside 0017. ch44 flares in valid data: ONLY 0015-transient + 0017-
  continuous; never OFF, never Kepler/HIP/M31/Voyager.
- Persistent same-α (≥6 blocks): only 0017 (ch54@805, ch31@179) in valid
  data. 4-pol coincidences in record: 2 (Kepler, 3-pol each); b76/ch44 is
  the only 4/4-pol ON-only one — found by direct probe, in no CSV.
- Catalog already learned the family: TRAPPIST:179:terr @1371.09 MHz
  (=ch44, n_seen=8, auto hard-blocks — the ratchet would bury the I3 slice
  on sight); KEPLER160:626:terr structured=True yet BLOCKed; Y2:179/Y2:268
  at 9.19 GHz with n_seen=370/46 → 179-family spans L→X band = backend.
- Honesty debit: ch44's peak α WANDERS per block (625→1430→1877→1072→
  1788 Hz) — persistent in energy, not in alpha. A stable carrier sits
  still; this wobbles. b76's 4-pol agreement is single-block.
Verdict: full combination unique in the record; every component seen
elsewhere; α-wander + catalog + X-band lines tilt further backend. I3
stands mechanical; analyst hold stands.

## 11. Abuse phase A (compute backlog, no downloads)
- M9-v0 cross-file matcher on full p0 censuses: 424 multi-file keys, but all
  but two are intra-0017 pol pairs. Genuine cross-scan recurrence: ONLY
  ch44@179 (T15+T17) and ch56@358 (T15+T17) — same hum lines, ON-only,
  minutes apart. Nothing in OFF recurs anywhere.
- Frame hunts: ch44 p1/p2/p3 + ch56 p0, full 23 s spans — no frame anywhere
  (best 5–10σ vs 40σ). Packet hypothesis dead on all pols.
- Kepler p2/p3 vetoed for the first time (existing beast_kepler CSVs):
  p2 → b1/ch56 358 Hz WATCH (spike-free 31×, S=0.20); p3 → b1/ch56 WATCH +
  b27/ch61 1431 Hz WATCH (S=0.35, Y2 13.9×, comb discounted by thicket,
  xvm silent, no markers — held correctly, needs ON–OFF–ON).
- Raid: blc01-0017-ON @1970 MHz + blc02-0015-ON @1782 MHz + blc01-0016-OFF
  → D:/data/raw (51 GB). Simultaneity verdicts pending on landing.

## 12. Catalog ratchet repair — EXECUTED (2026-09-21)
All six pathologies fixed, proven, migrated. Per-file changelog:
- `python/rfi_veto.py`: v2 keys (SIG:int-MHz:int-Hz) + `catalog_tol()` +
  `catalog_lookup()` + `catalog_file()` (null-alpha refused); recurrence
  counts independent runs (`seen_in`, HARD_N_RUNS=3); score-BLOCK + hard-block
  both exempt engineered slices (WATCH + `review` queue); XENO micro-markers
  (skflag/cohflag/ladderq/dm_sign, x_ aliases) and `scint_class`
  (COMMON +0.30 / SCINT −0.20) wired into S/E; impuls deliberately excluded;
  data-fingerprinted run-ids; atomic saves; health + review summary lines;
  E/S/net rounded to 2dp (float-boundary verdict flips are impossible).
- `python/migrate_catalog.py` (new): rehearsal default, `--apply` with
  timestamped backup. Live result: 1512 -> 1497 keys, 13 merges healed
  (incl. Y4:1371:179 = ch44, targets TRAPPIST+TRAPPIST1), 1.44 MHz ex-trio
  split 9 ways, 2 null-alpha keys (5,492 sightings) quarantined to health,
  50 bare-key stragglers rescued, 5 structured review seeds, 392 entries
  grandfathered at n_runs=2 (one recurrence from hard-block).
- `python/veto_prove.py`: 26 -> 32 legs (C1-C7 catalog, SK1, IM1, SC1, SC2).
- `z3/verify_veto.py`: v2 planting, boundary-exact model, reasons-inspected
  P3 (old check was vacuous), new P5. `z3/smt2/veto_disposition.smt2`: P6.
Receipts: prove 32/32, tie 3000/3000 + P1/P2/P3/P5, SMT2 all green, pytest 9/9.
Live demo (read-only): b76/ch44 -> key Y4:1371:626 (first sight at this
channel), E=0.45 S=0.30 net=+0.15 -> WATCH, COMMON visibly holding off
CANDIDATE; ch44-179 live at n_runs=2 (disarmed, loaded, documented).
Honest notes: on THIS slice old code also said WATCH (via the candidacy cap,
not via reasoning) - the behavior changes are C4/SK1-type slices (BLOCK ->
WATCH+review), recurrence counting, null filing, fragmentation, COMMON/SCINT
inputs, boundary exactness. Backup: rfi_catalog.json.pre_v2.20260921-070240.bak.
