# Raw-data hand-carve — findings

**Scope.** Hand-written readers/analysers (no pipeline, no C detectors) applied to
the raw GUPPI files on disk. Goal: carve the data directly and see whether
anything real — astrophysical or otherwise — is in it, and whether hand analysis
sees things the automation does not.

Files carved:

| file | target | MJD | band | size | layout |
|---|---|---|---|---|---|
| `blc44_..._KEPLER-160_0010` | Kepler-160 (ON) | 59103 | 1315–1500 MHz | 17 GB | 2 |
| `blc44_..._KEPLER-160_OFF_0011` | Kepler-160 (OFF, +1°) | 59103 | 1315–1500 MHz | 17 GB | 2 |
| `blc04_..._TRAPPIST1_0015` | TRAPPIST-1 (ON) | 57807 | 1315–1500 MHz | 17 GB | 2 |
| `blc04_..._TRAPPIST1_OFF_0016` | TRAPPIST-1 (OFF, +1°) | 57807 | 1315–1500 MHz | 17 GB | 2 |
| `blc04_..._TRAPPIST1_0017` | TRAPPIST-1 (ON2) | 57807 | 1315–1500 MHz | 17 GB | 2 |
| `blc5_..._W75N_0002` | W75N | 57388 | 8025–8212 MHz | 17 GB | 2 |
| `blc00_probe` | DIAG_TRAPPIST1 | — | 1972–2156 MHz | 262 MB | 2 |

---

## TL;DR

1. **There is no astrophysics in these files.** No pulsars, no single pulses /
   FRBs, no periodicity beyond the 60 Hz mains line, no HI/OH/maser line above
   the noise. This confirms the earlier deep-dive.

2. **But there are real narrowband carriers the automated pipeline misses.**
   Hand analysis (full-block FFT + 16-block averaging) finds coherent,
   ~11 Hz-wide carriers in both sessions — e.g. **1426.90400 MHz at 101× the
   noise floor** in Kepler, which the pipeline's own detector scores at
   **1.56× and calls `clean`**. Nine carriers are catalogued in
   `carrier_catalog.csv`.

3. **Two concrete, reproducible pipeline blind spots** fall out of this:
   - `direct_peak()` uses a 4096-point FFT, which is ~30× less sensitive to
     coherent tones than a full-block FFT.
   - the dark-lane quarantine rejects **the entire low band edge, ch57–63
     (11% of the band)** because those channels are *weak*, not *dark* — and
     ch59 is exactly where one of the carriers lives.

4. **The GUPPI payload layout is not time-major.** Reading it time-major
   manufactures a fake 26×-per-block sawtooth that looks like a signal. The
   reader must detect the layout (the C tool does; my first hand reader didn't).

5. **`W75N` is a saturated / 1-bit recording** — 99.4% of samples sit on the two
   rails and the sign stream is white. Unusable for science.

---

## 1. Method — what "by hand" actually did

`reports/handcrafted/handraw.py` is a from-scratch GUPPI reader: it parses the
80-byte FITS cards per block, solves the header stride from the file size,
detects the payload layout with the same autocorrelation probe as
`seti_slice.c`, and exposes `(time, chan, pol)` voltage. On top of it:

- `recon.py` — per-channel/per-pol statistics.
- `narrow.py` / `multiblock.py` — full-block FFT spectra, averaged over blocks.
- `powerseries.py` + `burst_search2.py` — 0.25 ms total-power time series,
  transient + periodicity + dedispersion search.
- `carrier.py`, `catalog.py` — carrier characterisation and cataloguing.

Everything below was cross-checked against the C tool. Example: `seti_slice.exe`
on ch25 pol0 gives `rms=16.2161`, `peak ratio=121.3 @ 1426.90400 MHz` — identical
to the hand reader.

---

## 2. The layout trap (and why it matters)

`seti_slice.c` documents three payload layouts and warns that a wrong stride
"does NOT look like garbage — it looks like white noise … it also manufactures
strong spurious structure (a swept bandpass sawtooth…)."

My first hand reader assumed the classic time-major layout `[t][chan][pol]`.
It produced a **beautiful, perfectly reproducible signal**: the band power fell
by a factor of **26 within every 0.179 s block, identically in all 64 channels,
with block-to-block correlation +1.000**. That is a seductive fake — it survives
averaging, it repeats, it's coherent. It is entirely an artefact of walking a
`[chan][time][pol]` block with the wrong stride.

The real layout here is **2 = `[chan][time][pol]`** (`ac1=0.0012`, `ac4=0.0644`).
After the fix the sawtooth vanished (within-block `fracstd` dropped from 0.47 to
0.0038, i.e. the theoretical noise value) and the **true bandpass** appeared:

```
ch 0  1500.0 MHz  rms 20.3   ########################################
ch18  1447.3 MHz  rms 18.5   ####################################   <- local bump
ch32  1406.3 MHz  rms 14.0   ###########################
ch59  1327.1 MHz  rms  6.2   ############
ch63  1315.4 MHz  rms  3.3   ######
```

The receiver rolls off ~6× across the band. The earlier claim of a "flat
bandpass" was itself an artefact of the wrong layout.

---

## 3. The carriers — the actual signal in the data

A full-block FFT (524 288 points, 5.6 Hz bins) plus 16-block incoherent
averaging reveals narrowband carriers that are invisible to the pipeline's
4096-point FFT. All are ~11 Hz wide and stable to <0.01 Hz within a scan.

| frequency | session | pols | peak/median | notes |
|---|---|---|---|---|
| **1426.90400 MHz** | Kepler ON+OFF | 0,1 (feed A) | **101×** | strongest in the whole dataset; inside the **1400–1427 MHz protected band** |
| 1327.21630 MHz | Kepler ON+OFF | 0,1,2,3 | 18× | channel **quarantined** by the pipeline |
| 1380.00000 MHz | Kepler ON+OFF | 0,1 | 8.5× | *exactly* a round number; **zero** ON→OFF shift |
| 1441.94666 MHz | TRAPPIST 15/16/17 | 0,1,2 | 10× | stable to <3 Hz across scans ~80 s apart |
| 1445.00588 MHz | TRAPPIST 16/17 | 0,1 | 8.8× | stable to <3 Hz |
| 1318.51961 MHz | TRAPPIST 15/16/17 | 0,1 | 7.5× | stable to <2 Hz |
| 1450.59271 MHz | TRAPPIST 15/16/17 | 0,1 | 4.3× | stable to <3 Hz |
| 1426.89675 MHz | TRAPPIST 17 | 2,3 | 5.6× | same protected-band region as Kepler |

**Are they astrophysical? No, by the ON–OFF test.** Every carrier is present in
*both* the ON and the ~1°-offset OFF pointing. A signal from the target star
would be only in ON. So none of these is a detection of Kepler-160 or
TRAPPIST-1.

**What are they then?** The evidence points at two populations:

- **Post-LO instrumental spurs.** The TRAPPIST carriers are stable to a few Hz
  across scans taken ~80 s apart, and the Kepler 1380.00000 MHz carrier is
  *exactly* round and does not move between ON and OFF at all. That is
  synthesizer-locked behaviour, not sky.
- **External signals (RFI).** The 1426.904 and 1327.216 MHz carriers shift by
  −25 Hz between Kepler ON and OFF — the size expected from the Earth's diurnal
  Doppler over the 187 s between the two scans. That means they are down-converted
  *before* the LO, i.e. they arrive through the receiver from outside.

Either way they are not new physics. But they are real, and the pipeline does not
see them — see §4.

### The 1426.9 MHz carrier in detail
- frequency 1426.90400 MHz (Kepler), 1426.90398 MHz (OFF): shift −26 Hz.
- width ~11 Hz (2 bins); amplitude ~3% of the noise σ; continuous, not pulsed
  (envelope constant to ~5% over the block).
- present in feed A (pol0/pol1) at 70–100×, feed B (pol2/pol3) only at 4–8×.
- independent confirmation: `seti_slice.exe` ch25 pol0, 121.3× @ 1426.90400 MHz.
- inside the 1400–1427 MHz radio-astronomy protected band.

---

## 4. Pipeline blind spots (the actionable part)

### 4.1 `direct_peak()` — 4096-point FFT is ~30× too insensitive

`python/mvp_scan.py:114` computes the spectral-line statistic from a
4096-point FFT, Welch-averaged over 128 rows, threshold 5.0. For the
1426.904 MHz carrier it returns **1.56** and verdict `clean`. The same data
through a full-block FFT gives **121.3×**.

A synthetic-tone injection into the real data quantifies the gap:

| injected tone amplitude | full-block FFT ratio | pipeline (4096-FFT) ratio |
|---|---|---|
| 0.03 (≈ the real carrier) | 123× | 1.59× |
| 0.10 | 1246× | 7.05× |
| 0.30 | 10729× | 54.6× |

The pipeline's `spec_line=5.0` gate only fires for tones ~3× stronger than the
ones actually present. A 524 288-point FFT is free — the block is already
2¹⁹ samples — and would recover them.

### 4.2 Dark-lane quarantine eats the band edge

`python/mvp_scan.py` quarantines a slice when `vrange > 15 and distinct < 64`.
At the low-frequency band edge the signal is genuinely weak (ch63 rms 2.4), so
its range and distinct-code count are *naturally* small:

```
ch55 rms 8.85 range 74 distinct 74  -> ok
ch57 rms 6.76 range 60 distinct 57  -> QUARANTINE
ch58 rms 5.73 range 46 distinct 47  -> QUARANTINE
ch59 rms 4.87 range 40 distinct 41  -> QUARANTINE   <- 1327.216 MHz carrier lives here
ch60 rms 4.14 range 34 distinct 35  -> QUARANTINE
ch61 rms 3.55 range 28 distinct 29  -> QUARANTINE
ch62 rms 2.95 range 28 distinct 27  -> QUARANTINE
ch63 rms 2.40 range 22 distinct 22  -> QUARANTINE
```

In the Kepler ON scan **all 128 blocks of ch57–63 are quarantined** — 7 of 64
channels, ~20.5 MHz, silently dropped. The gate is meant to catch a *broken
digitizer*; it also catches a *weak but healthy* channel. A dark digitizer has a
degenerate distribution, not merely a small one; gating on the distribution
shape (or on the entropy of the *de-meaned* signal) would separate them.

### 4.3 Net effect
The strongest coherent signal in the Kepler dataset is scored 1.56 (`clean`),
and the channel holding the second-strongest is discarded before analysis.
Neither is a SETI detection — both are RFI/spurs — but a real narrowband
technosignature at that amplitude would have been missed the same way.

---

## 5. What I ruled out (with the numbers)

- **Single pulses / FRBs.** 0.25 ms total-power series over all 128 blocks
  (91 648 samples, 22.9 s): max band-power z = **4.3** (noise max ≈ 4.5).
  Dedispersion over DM 0–1500 (61 trials) with the edge bias masked gives a
  top z = **4.96** at DM 425 — below the ~5.6 expected from noise alone.
- **Pulsar periodicity.** FFT of the de-trended total power: the only strong
  peak is at **60.05 Hz** (ratio 25.7) with harmonics at 180.1 Hz — the mains
  power line, not a pulsar. (The pipeline's `pulsar_fold` "1.47 Hz" from the
  earlier report is the lowest FFT bin, i.e. a red-noise trend, and the block-rate
  comb at 5.59 Hz is a recording artefact.)
- **HI / OH / masers.** The bandpass across 64 channels is smooth apart from
  receiver roll-off and one ~1-channel bump near ch18 (1447.3 MHz). No line
  stands out from the noise after ON–OFF differencing.
- **Broadband transients.** The earlier "megas"/"ch25 bursts" do not reproduce
  as 6σ samples in the corrected data: across all 128 blocks ch25 pol0 has
  **zero samples >6σ** and a maximum of 5.7σ. The earlier "spiky" claim was an
  artefact of the earlier analysis path.

---

## 6. W75N — a saturated recording

`blc5_guppi_57388_W75N_0002.0000.raw` (8118.75 MHz, Rcvr8_10) is not sky data:

- byte histogram has **6 distinct values**; 0x00 = 49.80%, 0xFF = 49.60%,
  0x01/0xFE = 0.30% each, 0x02/0xFD = 0.001% each → **99.4% of samples on the
  rails**.
- sign-stream run lengths are geometric with ratio 1/2 → independent random bits.
- autocorrelation ≈ 0 at every non-zero lag, in all channels and pols, under
  both the 8-bit and 2-bit interpretations.
- header flags: `DROPTOT=0.93553` on block 0, `NETSTAT='receiving'`,
  `DISKSTAT='waiting'`.

This is a saturated / 1-bit / broken recording. The sign stream carries no
recoverable narrowband structure. Quarantine it; do not scan it.

(`blc00_probe.raw` is a smaller cousin: low amplitude, per-channel rms varies
12× across the band, 27 distinct values. A test file, not science.)

---

## 7. What this means at the universal level

Read plainly: **in 23 s of sky, four polarisations, two targets, the instrument
recorded almost nothing from the universe.** What it did record is a portrait of
itself and its neighbourhood — a receiver that rolls off 6× across the band, a
handful of synthesizer spurs locked to its own clock, a mains hum at 60 Hz, and
a couple of external carriers that move with the Earth's rotation. That is a
calibrated *negative*, and negatives are only worth anything when they come with
a noise-matched receipt. This one now does.

The genuinely useful outcome is not a detection. It is that a hand carve found
**two places where the automated sieve has holes** (a 4096-FFT line detector that
is ~30× less sensitive than the data allows, and a quarantine rule that silently
throws away 11% of the band). A negative from a pipeline with holes is weaker
than a negative from one without. Fix those two and the same 23 s becomes a
tighter upper limit.

There is no evidence here of anything outside the current paradigm — no
anomalous dispersion, no non-terrestrial drift, no engineered bit structure, no
periodicity that survives scrutiny. The one thing worth a second look is the
1426.904 MHz carrier purely because of *where* it sits (inside the protected
band) and *how strong* it is relative to everything else — but its presence in
the OFF beam already argues it is not from Kepler-160.

---

## 8. Recommended next steps

1. **Widen `direct_peak` to a full-block FFT** (2¹⁹ is free) and re-run; re-score
   every existing hit with the longer integration. Expected: the carriers in
   §3 appear, and the current `spec_line` threshold becomes meaningful.
2. **Fix the dark-lane gate** so it keys on distribution shape / de-meaned
   entropy, not raw range+distinct. The band edge must not be pre-discarded.
3. **Add a coherent-carrier detector** (full-block FFT, local-median threshold)
   to `mvp_scan`, with a spur catalog keyed on session.
4. **Quarantine `W75N`** (saturated) explicitly, like the earlier
   `hits_hip_b6.QUARANTINED.csv` case.
5. **Re-run the Kepler ON/OFF pair** with the fixed line detector to confirm the
   1426.9 carrier is in both beams (i.e. vetoed) and to set a real upper limit.

*Scripts: `reports/handcrafted/`. Catalog: `reports/handcrafted/carrier_catalog.csv`.*
