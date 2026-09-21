# INTERSTELLAR HIT CRITERIA — what counts as what, and why

> **Read this if you want to know whether we found something.**
> Every slice of every observation ends up with exactly one grade, I0–I5.
> This file defines each grade, the physical meaning of every marker that
> feeds it, and the decision rules. The grade ladder is machine-checked
> (`z3/smt2/xeno_rules.smt2`, 13/13) and tied to the shipped code
> (`z3/verify_xeno.py`, 5000/5000 fuzz agreement). Grades are computed by
> `python/xeno_pass.py --selftest` (14/14 ladder checks).

---

## 1. The grades (one per slice, monotonic: more evidence never lowers a grade)

| grade | name | meaning | what it takes |
|---|---|---|---|
| **I0** | CLEAN | nothing flagged; thermal noise | no detector fired |
| **I1** | NOTABLE | something is there, nothing engineered | a flag (FAM-HIT / SPECTRAL-LINE) with no structure: no coding, no comb, no frame, no exotic marker pair. A chirp with no coding lives here — astrophysical until proven otherwise |
| **I2** | ENGINEERED | the signal carries information-like structure | veto `S ≥ 0.25` (baud comb, frame, VM structure, non-Gaussian tail, pol coherence) **or** ≥2 independent XENO microscopic markers. No sky context yet — could be a very clever transmitter in Earth orbit |
| **I3** | INTERSTELLAR-LEAN | engineered **and** the medium or geometry says "sky" | I2 **plus** one of: scintillation (ISM-signed intensity breathing), cross-polarisation agreement (same frequency in every feed — the opposite of the backend-wander fingerprint), or persistence + ON-only cadence |
| **I4** | STRONG | I3 **plus** something physics cannot do casually | negative dispersion, prime-number pulse rhythm, non-causal precursor echo, Doppler inconsistent with anything bound to Earth, or a multi-machine code verdict |
| **I5** | JACKPOT | the full house | I4 **plus** the alien-code sandbox at CANDIDATE **plus** persistence across the span. Common-mode (present ON *and* OFF) does **not** disqualify — a third-party link or an omnidirectional monument is *expected* in both pointings |

**What each grade demands of a human:** I0–I1 → nothing. I2 → characterise
(dechirp, fold, deeper stare). I3 → schedule a second pointing and check the
archive for recurrence. I4 → drop everything and re-observe. I5 → independent
telescope, independent backend, before any public claim — plus the full receipt
chain below.

**What "found something" looks like** is I4+ with receipts: structure where the
spectrum is silent, a sky marker the backend cannot fake, persistence, and code
that computes. Any one is a curiosity. All of them have no known natural or
human explanation.

---

## 2. The markers (what each one physically means)

### 2.1 Microscopic structure (`c/xeno_scan`) — below a single SCD peak

| marker | what it measures | engineered reading | natural reading |
|---|---|---|---|
| `skflag` | spectral kurtosis: fraction of frequency bins whose power flickers non-Gaussianly | packetised traffic (power rises/falls on a frame cadence) | lightning, radar, gain jumps — the veto decides |
| `cohflag` | zero-crossing regularity (mean/std of sign-flip intervals; noise ≈ 1.4) | clock-grade oscillation: carrier, square-wave telemetry, coherent beacon | pulsars are coherent too — coherence is reported, never interpreted alone |
| `ladderq` | cepstral comb: equally spaced tones in frequency | a frequency comb is engineering until proven otherwise; nothing that spins makes one | filterbank artifacts make them — check the standing-line list first |
| `thicket` | line-density fence: count of Y2/Y4 bins above 10× (real baud comb: ~9; intermod forest: 25–108) | nothing — this marker *subtracts* evidence: a comb inside a thicket is comb-by-density (proven in-prove: synthetic thicket scores 1940 with 7 members vs 859 for a real AM comb), so the comb vote is discounted and +0.35 EARTH is added | very strong carriers grow sidelobe forests and can trip it — errors point toward caution (BLOCK), never toward false discovery |
| `dm_sign` | sub-band arrival order. `+1` = high frequencies first (cold plasma, normal). **`−1` = low frequencies first: forbidden by cold plasma** | a transmitter pre-compensating for the ISM (it knows the medium), or superluminal group delay | instrument filter ringing (lives at tiny delays — the `\|DM\| > 50` floor excludes it) |
| `impuls` | robust max-z + 4σ tail excess | shots, glints, Crab-like giant pulses | RFI pops — needs persistence to matter |

### 2.2 Alien code (`c/xvm_sandbox`) — six machines, one verdict

A payload for an unknown receiver must be architecture-agnostic, so the
sandbox is too. Each machine votes; ≥3/6 = XENO-CANDIDATE:

| machine | what it runs | what firing means |
|---|---|---|
| SUBLEQ | subtract-and-branch one-instruction computer | memory-access locality like stack/heap instead of uniform spray |
| STACK | Forth-like push/add/mul/jump machine | the bits LOOP (backward jumps taken, thousands of ops) instead of halting in a handful — noise always halts |
| CA110 | Rule-110 cellular automaton from the bitstream seed | the density trajectory breathes (periodic seed) instead of sitting at flat ~50% (random seed) |
| ACF | frame autocorrelation, lags 8–4096 | a repeat stride (telemetry frames); reports the fundamental, not a multiple |
| HAM | Hamming(7,4) syndrome-zero excess over 12.5% random | error-correcting code structure |
| CRC | CRC-16 zero-residual excess over ~0.05 expected | framed data with checksums |

The entropy gate refuses all-zero / rail-saturated input (a dark digitizer's
zero-runs pass every syndrome trivially — the false-Golay lesson).

### 2.3 Sky markers (`python/scint_pol`) — the medium signs the signal

- **SCINT**: intensity breathes with modulation index 0.15–1.2, timescale ≥2
  STFT frames, DECORRELATED across frequency. That decorrelation is the
  fingerprint: backend gain wander moves all frequencies together
  (cross-band correlation ~1, correctly classified COMMON, terrestrial-leaning).
- **SKY-LIKE polarisation**: the same peak frequency in every feed
  (envelope co-variation counts for bursts). The known-local fingerprint is
  the opposite: each polarisation peaking at a DIFFERENT frequency
  (receiver-chain wander, HIP-113357). Disagreement reads WANDER-LOCAL.

### 2.4 Bizarre physics (`python/exotic_pass`) — the current paradigm is the null

| test | forbidden / unprecedented signature | mundane confounders checked |
|---|---|---|
| NEGDM | negative dispersion, DM < −50 at r² ≥ 0.8 | filter ringing (DM ≪ 1), cables, dedispersion leakage — all orders of magnitude below the floor |
| CLOCK | same-bin period in both halves at high sigma | mains hum is also stable — stability escalates only with structure |
| LADDER | cepstral comb (independent re-implementation of the C marker) | standing lines, filterbank edges |
| PRIMES | pulse intervals at prime multiples of a base (2,3,5,7,11…) | machinery rhythms (2,4,8,16 stay quiet — verified), magnetar quasi-periodicity (not exact primes) |
| PRECURSOR | energy BEFORE the main pulse | sidelobes (symmetric — precursors are one-sided), reflections (which are themselves interesting geometry) |

### 2.5 Context (veto + cadence + Doppler)

`S` (veto engineeredness), `persist`/`multichan` (evidence), `on_only`
(cadence pair), `doppler_anom` (Viterbi drift outside the Earth-bound
0.35 Hz/s screen). None of these is new in the overhaul; the overhaul makes
them GRADE-GIVING instead of advisory.

---

## 3. Decision flowchart (per slice)

```
flagged? ──no──▶ I0
   │yes
engineered? (S≥0.25 or ≥2 xeno markers) ──no──▶ I1
   │yes
sky marker? (scint / pol-agree / persist+on_only) ──no──▶ I2
   │yes
strong? (negDM / primes / precursor / doppler-anom / xvm) ──no──▶ I3
   │yes
xvm-CANDIDATE and persistent? ──no──▶ I4
   │yes
I5 ──▶ re-observe, second telescope, archive recurrence, THEN talk
```

---

## 4. Receipts (a negative is a result only with these)

Every marker ships with an injection prove (fires on target, quiet on matched
noise): `xeno_scan` 11/11, `xvm_sandbox` 10/10, `scint_pol` 6/6,
`exotic_pass` 10/10, grade ladder 14/14, SMT2 libs 38/38, code ties
5000/5000 + 3000/3000 + 2000/2000. `univ_ingest` round-trips 13/13,
`satpass` 6/6. Thresholds come from multiple noise realisations, and
every calibration surprise is documented in the code where it was found
(SK-per-bin not grouped, gate-period ≠ STFT length, code-stripe stride,
broadband-vs-decorrelated scintillation, peak-hold precursors, stack balance).

No single pointing exceeds its evidence. No common-mode signal is auto-blocked.
No flag is ever deleted — the catalog learns from all of them.
