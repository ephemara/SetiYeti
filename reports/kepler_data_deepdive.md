# Kepler-160 data deep-dive — what is actually in the CSVs

> Companion / correction to `reports/kepler1.md`.
> Scope: the **data**, not the code. Every claim below is computed from the
> scan CSVs and from the raw voltage re-extracted with `seti_slice`.
> Run: `runs/beast_kepler`, ON = `blc44…KEPLER-160_0010` (MJD 59103, GBT,
> L-band), OFF = `…_OFF_0011`. 66,752 slices, both pointings, all 4 pols.

True geometry from the header (not guessed):
`OBSFREQ 1407.71484375 MHz`, `OBSBW −187.5 MHz`, `NCHAN 64`,
`CHAN_BW −2.9296875 MHz` → **f(ch) = 1500.000 − 2.9296875·ch MHz**,
band 1315.4–1500.0 MHz. POL_TYPE `AABBCRCI` (p0=AA, p1=BB, p2=CR, p3=CI).

---

## 0. Verdict up front

**No astrophysical signal, no candidate, no anomaly requiring new physics.**
But the raw numbers in `kepler1.md` told the wrong story about *why*. The
strong "FAM family" in that report is **not** a coherent harmonic comb — it is a
fourth-power non-Gaussianity response to **wideband transient power bumps**, and
a standing DC offset. Correctly read, the corpus contains exactly four signal
classes, all local, plus one genuine ON-only transient worth a footnote.

| class | where | count | what it is |
|---|---|---|---|
| ADC DC offset | ch0 (1500.0 MHz), p1–p3 | 522 SPECTRAL-LINE | digitizer offset, proven |
| Band-edge rolloff + dark lanes | ch57–ch63 (1315–1333 MHz) | ~6,100 QUARANTINE | instrument edge |
| Wideband transient power bumps | ch52, 53, 56, 61 | ~30 events | RFI / receiver transient |
| Impulsive spikes | ch25 (1426.8, protected), ch57 | 143 + 67 | burst/spike RFI |

FAM-HIT totals: **363 (80 ON, 283 OFF)**. Tag split: **302 Y4, 61 Y2**. The
Y2/Y4 split is the whole story — see §2.

---

## 1. The ch0 "standing tone" is a DC offset, not a carrier

`kepler1.md` §4 called this "a receiver hum." Stricter answer: it is not even a
tone. Peak sits at **+5.588 Hz** from channel centre, which is exactly one FFT
bin of a 524,288-sample block (df = 5.588 Hz). Remove the mean and it vanishes:

| pol | peak ratio with mean | after mean removed |
|---|---|---|
| p0 | 0.8× (no offset) | 0.9× |
| p1 | 3451× | **2.6×** |
| p2 | 8026× | **1.3×** |

p0 (AA) has no offset; p1–p3 do. It recurs in all 128 blocks, both pointings,
only pols 1–3, at bin 1 of every channel's DC — a **digitizer DC offset**, no
carrier. It flooded 256/258 ON and 266/266 OFF SPECTRAL-LINE rows and should be
excluded at the source (bin 0/1), not catalogued as an emitter.

---

## 2. The "358 Hz harmonic family" was a Y4 / transient artifact

The single most important correction. `fam_scan` reports a peak from either the
square-law spectrum (`Y2 = x²`) or the fourth-power spectrum (`Y4 = (x²−m)²`),
tagged in `fam_tag`. Meaning:

- **Y2** = genuine periodic power modulation → real baud/chip/PRF.
- **Y4** = excess fourth moment → **non-Gaussianity / bursts / gain bumps**.
  A spiky or amplitude-hopping slice lights up Y4 at *every* alpha, because Y4
  is a kurtosis detector, not a periodicity detector.

Breakdown of all 363 Kepler FAM-HITs:

```
('off','Y4'):254  ('on','Y4'):48   ← strong hits are Y4
('on','Y2'): 32   ('off','Y2'):29  ← weak, all near the 3.0 trigger
```

Strongest rows, all Y4:

| fam | tag | pointing | block | ch | alpha Hz | spikes |
|---|---|---|---|---|---|---|
| 121.06 | Y4 | OFF | 102 | 56 | 1431 | 3 |
| 119.59 | Y4 | OFF | 102 | 56 | 1431 | 5 |
| 111.21 | Y4 | OFF | 35 | 56 | 1431 | 3 |
| 100.15 | Y4 | OFF | 35 | 56 | 1431 | 4 |
| 43.03 | Y4 | OFF | 55 | 52 | 358 | 0 |
| 41.00 | Y4 | OFF | 55 | 52 | 626 | 0 |
| 39.51 | Y4 | **ON** | 21 | 52 | 2861 | 1 |
| 37.04 | Y4 | **ON** | 21 | 52 | 2861 | 0 |
| 31.15 | Y4 | ON | 1 | 56 | 358 | 0 |

The **strongest Y2 hit in the entire run is 4.46×** (OFF b57/ch57, 25 spikes —
itself an artifact slice). The next are the b71/ch53 4-pol rows at 4.3×, 3.7×,
3.2×. Everything above ~5× is Y4.

Re-running the real C scanner on the raw voltage confirms it: ON b21/ch52 p0
shows a **broad plateau** of Y2 peaks (bins 4, 8, 14, 21, 25, 32, 39, 53 — not a
harmonic series) at 11–20×; OFF at the same block/channel is flat at 2.1–2.5×.
A broad plateau in cyclic frequency = **non-stationarity**, not a clock. A real
baud comb is a few sharp alphas, not a hedge.

**Conclusion: there is no coherent cyclostationary (baud-chip) signal anywhere
in either Kepler pointing above ~4.5×.** The "358/626/1431/2861 Hz family" was
an artifact of (a) Y4 non-Gaussianity and (b) the fact that all four values are
integer FFT bins of a red-noise continuum, not a comb.

---

## 3. The strong events are ~20–30 ms broadband power bumps

Re-extracting the raw slices and looking at local RMS in 20 bins of the
0.179 s block:

| slice | rms shape | interpretation |
|---|---|---|
| ON b21 ch52 p0 | 10.2 … 10.9 (rise over last ~30%) | ~10% power bump, ~30 ms |
| OFF b55 ch52 p0 | 10.3→10.9 mid-block | same class |
| OFF b102 ch56 p0 | 8.0→8.8 mid-block | same class, both pols |
| OFF b35 ch56 p0 | 8.0→8.7 mid-block | same class, both pols |
| OFF b48 ch25 p2 | flat; 19 samples \|z\|>6 | isolated spikes |
| OFF b10 ch57 p3 | flat; 6 samples \|z\|>10, crest 13.8 | isolated spikes |

The ch56 "megas" (119–121× Y4, at 1431 Hz) are **a single smooth ~30 ms bump in
total power, coincident across p0 and p1**, not a pulse train — the sub-band
time-frequency shows the bump concentrated in ~3 of 17 sub-bands. ch52 shows the
same bump class. These are the morphology of a **transmitter briefly entering a
sidelobe** (satellite/aircraft) or a **receiver gain jump** — broadband,
aperiodic, common-mode. They are *not* structured traffic.

---

## 4. Proven negatives (the important part)

### 4.1 No pulsar — the fold "PERIODIC" is the first FFT bin

`pulsar_fold` returns `PERIODIC` for the ON b21/ch52 slice at **1.47 Hz,
σ = 58.6**, and the "harmonics" 2.20/2.93/3.66/4.40 Hz are spaced exactly one
FFT bin (df = 0.733 Hz). Two independent reasons this is false:

1. **1.47 Hz = the second FFT bin** (i0 = ceil(1/df) = 2). The picker is biased
   to the lowest bin, and the envelope has 1/f (red) power there.
2. **A 0.179 s block cannot contain one 1.47 Hz period** (0.26 cycles). The
   period is unresolved by construction. The `--prove` machinery uses 2.1 M
   samples (0.72 s), so the calibration never meets the production block length.

The clincher: the **OFF** slice `off_b35_ch56_p0` — not from Kepler-160 —
returns `PERIODIC σ = 166.13` at the same 5.86 Hz ladder. The detector fires on
the power bump, not on rotation. **No pulsar.**

### 4.2 No FRB / dispersed pulse — the DM "SHOT" is a bump artifact

`transient_dm` returns `SHOT σ = 60.18 DM = 32` on ON b21/ch52. But it also
returns:

- OFF b35 ch56 (not Kepler-160): `SHOT σ = 50.98, DM = 0`
- OFF b48 ch25 (spike burst): `SHOT σ = 49.31, DM = 0`

DM = 0 means no dispersion at all — the boxcar matched filter is responding to
the smooth power bump, not a cold-plasma sweep. The prove's noise max is ~10.8,
so σ = 50–60 looks decisive, but the prove injected *shots into stationary
noise*; it never tested a non-stationary envelope. **No dispersed single pulse.**

*(Side note: the deep-pass runner extracts from `self.a.on` for every candidate,
including OFF flags, so the burst/DM logs labelled `b35`/`b102` were in fact
re-read from the ON file. The OFF-slice numbers above are my own extraction.)*

### 4.3 No narrowband carriers

SPECTRAL-LINE rows: 258 ON + 266 OFF, of which **256/258 and 266/266 are ch0**
(the DC offset). The only other row is ch61 (1321.29 MHz), which is the *same*
DC artifact at a baseline step (mean-removed → 2.6×). Delete ch0/ch61 DC and
**zero real spectral lines remain** in the whole 1315–1500 MHz band.

### 4.4 Nothing persists across pointings except instrument

Excluding ch0 (DC) and ch57–63 (edge), no FAM feature is present in both ON and
OFF at the same alpha and channel with significance. The ch52/ch56 events occur
in both pointings but at *different blocks* (different times), consistent with
transient RFI, not a fixed source in the beam.

---

## 5. The ch25 burst train (the scary-looking one)

`ch25 = 1426.76 MHz`, inside the ITU **1400–1427 MHz radio-astronomy protected
band**. 143 FAM-HITs, **all OFF**, 72 distinct blocks spanning b0–b126, all four
pols. This is the row that *looks* like a protected-band beacon.

Measured properties kill that reading:

- **alpha values span 358 Hz to 978,827 Hz**, median 6,169 Hz, **41% above
  10 kHz** — a broadband burst, not a comb.
- **44% are spiky** (spikes ≥ 6, max 25); slicing shows flat envelope with
  isolated `|z| > 6` samples, not a modulation.
- The FAM response is **Y4** (non-Gaussian), i.e., the detector is seeing the
  spikes.
- It appears in OFF (the reference beam) only — the opposite of a target signal.

This is a burst emitter — satellite downlink, radar, or an aircraft — passing
through the OFF sidelobe. Terrestrial. It was still worth one zoom to type it,
which `burst_zoom` now does; the verdict is not astronomical.

---

## 6. The one genuinely ON-only transient (b21 / ch52 / 1347.66 MHz)

The only event with an ON/OFF difference that survives raw inspection:

- ON b21 ch52 p0: Y4 37.04 at 2861 Hz; p1: Y4 39.51 — **both pols**.
- Local RMS rises 10.2→10.9 over the **last ~30 ms** of the block (a real power
  bump, not a DC step).
- OFF at the same block/channel: 2.3× noise, no bump, no fold, no DM.
- Cyclic response is a broad plateau (non-stationary), not a comb.

Interpretation: a ~30 ms, both-polarization, ~10% power transient that appears
only in the ON pointing. Most likely a satellite/aircraft or a receiver
transient that happened to fall in the ON block; there is an identical class in
OFF at b55/ch52. It is **not** periodic, **not** dispersed, and **not**
structured. Worth one high-time-resolution look to type it, not a candidate.

---

## 7. Universal-level reading (for a non-specialist)

The L-band (1.3–1.5 GHz) sky over a Kepler field is, from this dataset, quiet
in every way this pipeline can measure. What it *did* record is a photograph of
the instrument and the neighbourhood: an ADC with a DC offset, receiver chains
whose band edges roll off and go dark, and a steady drizzle of human
transmitters — radar, satellites, aircraft — blinking through the sidelobes.

There is exactly one standard astrophysical line in this band, neutral hydrogen
at 1420.4 MHz (ch27). It is a broad galactic feature and this pipeline — a
transient/periodicity detector on 0.18 s blocks — is not built to see it, so its
absence here says nothing about the sky.

The honest summary for an outsider: **tonight the machine listened to 23 seconds
of sky, twice, with four polarizations, and heard only itself and us.** No
pulsar, no burst, no beacon, no unexplained structure. That is a real result —
but it is an *upper limit over a 185 MHz window and a 23-second dwell*, not a
statement about the universe. The one thing that would change the verdict is
time: a beacon that repeats on an unknown cycle is invisible to a single stare,
which is why the cadence pairing and the cross-night matcher matter more than
any single scan.

---

## 8. Corrections to `kepler1.md`

1. §1 "358 Hz harmonic family … most engineered-looking candidate" — **withdrawn.**
   It is Y4 non-Gaussianity plus a red-noise continuum binned to integer
   alphas, not a comb. Strongest coherent (Y2) signal in the run is 4.46×.
2. §2 "b71/ch53 4-pol coincidence … best ON-only item" — downgraded. Slice
   Y2 excess is only 3.2–4.3×; three pols peak at 358 Hz (a low red-noise bin).
   Weak, not a coincidence of note.
3. §4 "standing tone at 1500 MHz" — **it is a DC offset**, present in p1–p3,
   absent in p0; vanishes on mean subtraction.
4. §6 "frame hunts no frame, tops near 330–390 Hz" — consistent with the above;
   no envelope frame exists.
5. New: fold `PERIODIC` and DM `SHOT` are **false positives on power bumps**
   (proven on OFF slices); the deep-pass runner reads OFF flags from the ON
   file. Both need calibration against non-stationary envelopes before use.

## 9. Receipts / reproduce

```bash
# true geometry
python -c "print([1500.0-2.9296875*ch for ch in (0,25,27,52,56,61)])"
# extract + scan any event
c/seti_slice <raw> <chan> out.f32 1 --pol P --start BLOCK
c/fam_scan  out.f32 2929687.5 32768 25 -
python python/pulsar_fold.py  --f32 out.f32
python python/transient_dm.py --f32 out.f32
```

Key files: `runs/beast_kepler/scan_{on,off}_p*.csv` (66,752 slices),
`struct_*.csv` (comb/frame/nongauss columns), `cadence.json`.
