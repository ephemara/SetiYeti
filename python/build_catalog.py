#!/usr/bin/env python3
"""Build catalog.tsv — the master ledger of every sky file in storage.

Scans E:/data + D:/data, joins live mvp_scan manifests (runs/**/*.manifest.json)
for coverage/flag counts, and stamps per-target result summaries curated from
the campaign reports (runs/*/REPORT.md, runs/vm_hunt/FULL_REPORT.md).

Re-run after every new scan/download:
    python python/build_catalog.py
and commit the regenerated catalog.tsv.

Scan-status vocabulary:
  SCANNED_FULL     full census (all/most blocks x chans x pols 0-1)
  SCANNED_PARTIAL  subset of blocks/chans/pols, or small-window scan
  SMOKE            1 GB excerpt / tiny engineering test only
  LEGACY           scanned long ago, manifest missing (coverage approximate)
  NOT_SCANNED      on disk, never scanned
  PARTIAL_FILE     incomplete download, unscannable until finished
  QUARANTINED      probe failed (dark digitizer) — do NOT scan, lane is bad
"""
import csv, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E_DATA = os.path.join(ROOT, "data")
D_DATA = "D:/data"

# ---------------------------------------------------------------- manifests
# raw basename -> list of {csv, flagged, blocks, chans, pol, ts}
BY_RAW = {}
for mf in glob.glob(os.path.join(ROOT, "runs", "**", "*.manifest.json"), recursive=True):
    try:
        d = json.load(open(mf))
    except Exception:
        continue
    raw = (d.get("raw") or "").replace("\\", "/").split("/")[-1]
    if not raw or "." not in raw:
        continue
    BY_RAW.setdefault(raw, []).append({
        "csv": os.path.relpath(mf, ROOT)[:-len(".manifest.json")],
        "flagged": d.get("flagged"),
        "blocks": d.get("blocks"), "chans": d.get("chans"),
        "pol": d.get("pol"), "ts": d.get("timestamp", "?"),
    })

def coverage(entries):
    parts = []
    for e in entries:
        b = e["blocks"]; c = e["chans"]; p = e["pol"]
        bs = f"blocks {b[0]}-{b[1]}" if isinstance(b, list) and len(b) == 2 else f"blocks {b}"
        parts.append(f"{e['csv'].split('/')[-1]}: {bs}, ch {c}, p{p} ({e['flagged']} flagged, {e['ts']})")
    return " | ".join(parts)

def verdict_tally(csv_rel):
    """verdict distribution for a runs csv (None if unreadable)."""
    try:
        p = os.path.join(ROOT, csv_rel)
        with open(p) as f:
            r = csv.DictReader(f)
            if "verdict" not in (r.fieldnames or []):
                return None
            tot, flag = 0, {}
            for row in r:
                tot += 1
                v = (row.get("verdict") or "").strip()
                if v != "clean":
                    flag[v] = flag.get(v, 0) + 1
        return tot, flag
    except Exception:
        return None

# ------------------------------------------------------- curated knowledge
# Per raw file: (status_override, result_summary, notes). Status defaults:
#   in BY_RAW -> SCANNED_PARTIAL (refined below), else NOT_SCANNED.
KNOW = {
 # ---- E:/data TRAPPIST-1 ----
 "blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.PART1GB.raw": (
    "SMOKE",
    "BEAST e2e/trap-smoke: BLOCK-only dispositions, 0 WATCH, 0 CANDIDATE; backend-line thicket both legs.",
    "1 GB excerpt of the 17 GB ON file; full file below is the real record."),
 "blc04_guppi_57807_75725_DIAG_TRAPPIST1_0015.0000.raw": (
    "SCANNED_FULL",
    "Full census p0 (670 flags) + p1 (637); xeno grades to I2 max; 6-machine xvm: bits noise-like, 0 CANDIDATE-structure; legacy vm false-alarmed on a quiet control (held by upgrade).",
    "Primary TRAPPIST-1 ON leg. Legacy baseline_0015_*.csv also cover it (manifest missing)."),
 "blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.PART1GB.raw": (
    "SMOKE",
    "BEAST e2e/trap-smoke OFF leg: BLOCK-only, 0 WATCH, 0 CANDIDATE.",
    "1 GB excerpt of the 17 GB OFF file."),
 "blc04_guppi_57807_75805_DIAG_TRAPPIST1_OFF_0016.0000.raw": (
    "SCANNED_FULL",
    "Full census p0 (787 flags) + p1 (736); OFF mirrors ON line-for-line (common-mode backend); xeno/xvm quiet.",
    "Primary TRAPPIST-1 OFF leg. Legacy baseline_0016_*.csv also cover it (manifest missing)."),
 "blc04_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw": (
    "SCANNED_FULL",
    "ON FIRE: full census p0/p1/p2 = 2030/1996/2387 flagged (dense RFI inferno vs 1-2 FAM-HITs in 0015); strongest coherent line b2/ch56 31.5x@268Hz + Y2 6.4x@358Hz; bits noise-like, 0 xvm CANDIDATE. Needs ON-OFF cadence_pair vs 0016 before any claim.",
    "Third TRAPPIST file, first deep look 2026-09-21. Small scan runs/vm_hunt/blc00_t17_p0.csv is the blc00 node of same pointing."),
 # ---- E:/data Kepler-160 ----
 "blc44_guppi_59103_01984_DIAG_KEPLER-160_0010.0000.raw": (
    "SCANNED_FULL",
    "BEAST_kepler ON: p1 gave 2 CANDIDATE + 27 WATCH (only CANDIDATEs in corpus; need ON-OFF pair review via cadence_pair); longhaul SCD megas to 40x are backend comb (discounted); xvm noise-like.",
    "Control target. Hottest veto output in the corpus — follow-up priority #1."),
 "blc44_guppi_59103_02170_DIAG_KEPLER-160_OFF_0011.0000.raw": (
    "SCANNED_FULL",
    "OFF leg FAM-HIT heavy on p2/p3 (87/83 slices) — backend wander fingerprint, not sky.",
    "Pairs with 0010 ON for cadence gating."),
 # ---- E:/data odds ----
 "blc5_guppi_57388_W75N_0002.0000.raw": (
    "QUARANTINED",
    "Probe showed dark digitizer (few distinct codes, low RMS); scan output quarantined to runs/hits_w75n.QUARANTINED.csv. Phantom SPECTRAL-LINE+VM-WATCH flags are digitizer artifacts.",
    "DO NOT SCAN. Quarantine before analysis per AGENTS.md."),
 "blc00_probe.raw": (
    "SMOKE",
    "262 MB layout probe snippet (interleaved, 8-bit). Engineering only.",
    "Not a sky observation; do not count as coverage."),
 # ---- D:/data M31 (all 12 scanned 2026-09-21) ----
 "blc2_2bit_guppi_57396_MESSIER031_0008.0000.raw": (
    "SCANNED_FULL", "Stride p0 clean (0 flags); full census 11 flags; struct+xeno+xpol grades ≤I2; quiet.",
    "M31 campaign 2026-09-21: all 12 bank files stride-scanned, mostly clean."),
 "blc2_2bit_guppi_57396_MESSIER031_0008.0001.raw": (
    "SCANNED_PARTIAL", "Stride scan 0 flags; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0008.0002.raw": (
    "SCANNED_PARTIAL", "Stride 1 flag; full census 3 flags + xeno grades ≤I2; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0009.0000.raw": (
    "SCANNED_PARTIAL", "Stride scan 1 flag; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0009.0001.raw": (
    "SCANNED_PARTIAL", "Stride scan 2 flags; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0009.0002.raw": (
    "SCANNED_PARTIAL", "Stride scan 0 flags; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0010.0000.raw": (
    "SCANNED_PARTIAL", "Stride scan 0 flags; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0010.0001.raw": (
    "SCANNED_PARTIAL", "Stride scan 1 flag; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0010.0002.raw": (
    "SCANNED_PARTIAL", "Stride scan 0 flags; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0011.0000.raw": (
    "SCANNED_FULL", "Full census 7 flags; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0011.0001.raw": (
    "SCANNED_PARTIAL", "Stride scan 1 flag; quiet.", ""),
 "blc2_2bit_guppi_57396_MESSIER031_0011.0002.raw": (
    "SCANNED_PARTIAL", "Stride scan 0 flags; quiet.", ""),
 # ---- D:/data HIP fleet spot checks ----
 "blc2_2bit_guppi_57423_33368_HIP54810_0021.0000.raw": (
    "SCANNED_PARTIAL", "blocks 0-31 p0: 4 flags (FAM 3.0-3.5x, spectra silent); cadence vs OFF 0022: 0/4 persistent, 0 coincidences — gated CLEAN 2026-09-21.",
    "ON leg of a fully-gated pair. No struct follow-up (flags too weak to warrant it)."),
 "blc2_2bit_guppi_57423_33694_HIP54810_OFF_0022.0000.raw": (
    "SCANNED_PARTIAL", "blocks 0-31 p0: 7 flags (FAM 3.0-3.3x); cadence vs ON: zero (block,chan) coincidences — gated CLEAN 2026-09-21.",
    "runs/hip54810_off_p0.csv. OFF leg of a fully-gated pair."),
 "blc2_2bit_guppi_57424_86073_HIP14286_0021.0000.raw": (
    "SCANNED_PARTIAL", "blocks 0-31 p0: 3 flags (FAM 3.0-3.1x); cadence vs OFF 0022: 0/3 persistent, 0 coincidences — gated CLEAN 2026-09-21.",
    "ON leg of a fully-gated pair."),
 "blc2_2bit_guppi_57425_00000_HIP14286_OFF_0022.0000.raw": (
    "SCANNED_PARTIAL", "blocks 0-31 p0: 3 flags (FAM 3.0-3.1x); cadence vs ON: zero coincidences — gated CLEAN 2026-09-21.",
    "runs/hip14286_off_p0.csv. OFF leg of a fully-gated pair."),
 "blc2_2bit_guppi_57432_31271_HIP57866_0021.0000.raw": (
    "SCANNED_PARTIAL", "blocks 0-31 p0: 7 flags; struct pass 2026-09-21: comb=0 nongauss=0 frame=0 on all flags — unstructured threshold flickers, ch40 repeats b28+b31 (weak persistence, no structure).",
    "ON leg only and NO OFF pair exists on disk — cannot be cadence-gated. Host slice (ch20) for python/earth_mirror.py (MIRROR PASS)."),
 # ---- D:/data TRAPPIST nodes ----
 "blc00_guppi_57807_75885_DIAG_TRAPPIST1_0017.0000.raw": (
    "SCANNED_PARTIAL", "Small scan 47 flags (runs/vm_hunt/blc00_t17_p0.csv); same pointing as blc04 0017 inferno.",
    "blc00 node of the 0017 pointing; blc01 node NOT scanned."),
 # ---- D:/data Voyager ----
 "blc2_2bit_guppi_57396_VOYAGER1_0002.0000.raw": (
    "SCANNED_PARTIAL", "Full census runs/voy_0002_full.csv blocks 0-31 ch 0-63 p0 (6 flags, 2026-09-21): Y2-only marginal 3.0-3.1, noise-like VM, veto BLOCK. OFF-CARRIER node (9281 MHz; downlink 8415 MHz out of band) = negative control, behaved exactly as predicted.",
    "Negative control PASSED: pipeline does not hallucinate carriers. Per-file manifest missing so exact split across the 3 bank files is unlogged."),
 "blc2_2bit_guppi_57396_VOYAGER1_0002.0001.raw": (
    "SCANNED_PARTIAL", "Covered by runs/voy_0002_full.csv (see 0002.0000 note); off-carrier node, no carrier physically present.",
    "Negative-control leg."),
 "blc2_2bit_guppi_57396_VOYAGER1_0002.0002.raw": (
    "SCANNED_PARTIAL", "Covered by runs/voy_0002_full.csv (see 0002.0000 note); off-carrier node, no carrier physically present.",
    "Negative-control leg."),
 "blc3_guppi_57386_VOYAGER1_0004.0000.raw": (
    "SCANNED_FULL", "Carrier-node campaign 2026-09-21 (16.9 GB, X-band 8493.75 MHz, contains 8415 MHz downlink): full census 10 flags (veto BLOCK, I1 max); direct 64-channel sweep max peak/median 1.35x (carrier would be 100x+); all 4 pols checked at predicted Doppler-corrected channel (~8414.2 MHz). NO CARRIER DETECTED. Pols 2/3 are dark digitizers (97/256 codes, RMS 10 vs 34) — QUARANTINE lanes 2-3 in this file. Lead hypothesis: pointing miss (1.4 arcmin X-band beam vs up to ~25 arcmin geocentric-parallax frame error) or transmitter off.",
    "Positive control INCONCLUSIVE (missing signal, not pipeline blindness): band math, tracking header, digitizer health all verified; signal simply absent. Downloaded 2026-09-21 from BL archive (sole 8493.75 MHz Voyager file of 337)."),
 # ---- D:/data pulsars (first looks 2026-09-21; two sessions converged) ----
 "blc2_2bit_guppi_57397_PSR_J2321+6024_0002.0000.raw": (
    "SCANNED_FULL", "Full census 810/2048 flags, ALL at alpha=179 Hz, all blocks+channels (fam med 3.32, max 5.09). TWO independent terrestrial verdicts: (1) envelope-dispersion test across 155 MHz gives ZERO lag, phase -0.09 vs -0.15 rad; (2) manual spectral-phase DM = +11.7+/-21.5 (t=0.54, consistent with zero). Hum structure: identical ~5.67 Hz harmonic comb in all lanes at 100-360 sigma (19th harmonic = 107.75 Hz envelope peak), amplitude CV=0.15 steady; header pointing verified RA 23:21:55 Dec +60:24:30, S-band 2681 MHz. Veto 810/810 BLOCK (common-mode backend); xeno I1 x810, I2+ zero. NO pulsar in this node.",
    "runs/psr2321_full.csv + manifest. Sibling .0001 stride-scanned 2026-09-21: 107/256 at 179 Hz (hum fills session). Catalog 179 Hz as backend/mains mode (also faint in M31 + Voyager X-band). A faint steep-spectrum pulsar could hide below the hum -- needs 300 s full-band dedispersed fold at catalog P/DM."),
 "blc2_2bit_guppi_57397_PSR_J2321+6024_0002.0001.raw": (
    "SCANNED_PARTIAL", "Stride 107/256 flags, all 179 Hz; same hum as .0000.", ""),
 "blc2_2bit_guppi_57403_PSR_J2326+6113_0002.0000.raw": (
    "SCANNED_PARTIAL", "Stride 1 flag (b10/ch16 3.01); quiet companion.", ""),
 "blc2_2bit_guppi_57403_PSR_J2326+6113_0003.0000.raw": (
    "SCANNED_FULL", "Full census 5/2048 flags (max 3.16, scattered alpha, veto BLOCK); data PRISTINE (no 179 Hz storm). Blind pulsar_fold reports PERIODIC per-channel but periods differ per channel (5.68/90.7/113.4 Hz) and the SAME tool reports PERIODIC at +38-52-sigma on known-clean M31 control -- gate miscalibrated for full-length 2-bit channels, verdicts unusable without recalibration (prove-harness gap logged). transient_dm no shot. No pulsar detected; honest upper limit only.",
    "C-band 4281 MHz. Cleanest pulsar-band data in hand; worth a targeted fold once J2326+6113 ephemeris is in hand."),
 # ---- D:/data galactic center ----
 "gc_C07_sample.fil": ("NOT_SCANNED", "Never scanned.", "1.8 GB filterbank sample, Galactic-Center field."),
 "spliced_blc0001020304050607_guppi_58331_12314_DIAG_SGR_B2_0013.gpuspec.0000.h5": (
    "NOT_SCANNED", "Never scanned.", "SGR B2 (Sgr B2 molecular cloud, Galactic Center) ON, 2.8 GB coarse spectra."),
 "spliced_blc0001020304050607_guppi_58331_12314_DIAG_SGR_B2_0013.gpuspec.0002.h5": (
    "NOT_SCANNED", "Never scanned.", "SGR B2 fine-spectra companion (46 MB)."),
 "spliced_blc0001020304050607_guppi_58331_12314_DIAG_SGR_B2_0013.gpuspec.8.0001.h5": (
    "NOT_SCANNED", "Never scanned.", "SGR B2 mid-resolution companion (207 MB)."),
 "spliced_blc0001020304050607_guppi_58331_12383_DIAG_SGR_B2_0014.gpuspec.0002.h5": (
    "NOT_SCANNED", "Never scanned.", "Second SGR B2 epoch fine-spectra (462 MB)."),
 "spliced_blc0001020304050607_guppi_58331_12383_DIAG_SGR_B2_0014.gpuspec.8.0001.h5": (
    "NOT_SCANNED", "Never scanned.", "Second SGR B2 epoch mid-resolution (2.4 GB)."),
 "gt.bin": ("PARTIAL_FILE", "Unscannable: 7.9 GB of ~16 GB (header: HIP113357, 1968 MHz, blc1 node); aria2 fetch died on unreachable storage.googleapis.com.",
    "Resume with bl_download.py get --target HIP113357; real name blc1_guppi_57388_HIP113357_0010.0000.raw."),
}

TARGET_RE = re.compile(r"(HIP\d+|TRAPPIST1|MESSIER031|VOYAGER1|KEPLER-160|W75N|PSR_J\d+\+\d+|SGR_B2|HIP113357|HIP57866|ProxCen)(?:_OFF)?")
# filename carries no target — read from the file header instead
TARGET_OVERRIDE = {"gt.bin": ("HIP113357", "ON"), "blc00_probe.raw": ("TRAPPIST1", "UNKNOWN")}

def target_of(fn):
    m = TARGET_RE.search(fn)
    return m.group(1) if m else "UNKNOWN"

def pointing_of(fn):
    if "_OFF_" in fn or fn.endswith("_OFF"):
        return "OFF"
    if "ProxCen" in fn or "gt.bin" == fn or "probe" in fn:
        return "UNKNOWN"
    return "ON"

def fmt_of(fn):
    if fn.endswith(".raw"):
        return "guppi_raw"
    if fn.endswith(".fil"):
        return "filterbank_fil"
    if fn.endswith(".h5"):
        return "filterbank_h5"
    if fn == "gt.bin":
        return "guppi_raw(partial)"
    return "?"

def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f}{u}"
        n /= 1024.0

rows = []
def add(location, path, kind):
    fn = os.path.basename(path)
    try:
        sz = os.path.getsize(path)
    except OSError:
        sz = -1
    entries = BY_RAW.get(fn, [])
    status, summary, notes = KNOW.get(fn, (None, "", ""))
    if status is None:
        status = "SCANNED_PARTIAL" if entries else "NOT_SCANNED"
        if not entries:
            summary = "Never scanned."
    ev = coverage(entries) if entries else ""
    if fn in ("blc2_2bit_guppi_57396_VOYAGER1_0002.0000.raw",):
        ev = "runs/voy_0002_full.csv (1536 slices; legacy archive/root_20260921/hits_voyager.csv); NO per-file manifest"
    elif "VOYAGER1_0002.000" in fn:
        ev = "runs/voy_0002_full.csv (shared across 0002 bank files; NO per-file manifest)"
    tgt, ptg = TARGET_OVERRIDE.get(fn, (target_of(fn), pointing_of(fn)))
    rows.append([fn, tgt, ptg, location, str(sz),
                 human(sz) if sz >= 0 else "?", fmt_of(fn), status,
                 coverage(entries) if entries and "VOYAGER1_0002" not in fn else
                 (ev if ev else ("blocks 0-31, ch 0-63, p0" if entries else "")),
                 ev, summary, notes, kind])

for fn in sorted(os.listdir(E_DATA)):
    p = os.path.join(E_DATA, fn)
    if os.path.isfile(p) and (fn.endswith(".raw")):
        add("E:/data", p, "raw_storage")

for fn in sorted(os.listdir(os.path.join(D_DATA, "raw"))):
    add("D:/data/raw", os.path.join(D_DATA, "raw", fn), "raw_storage")

for fn in sorted(os.listdir(os.path.join(D_DATA, "gc"))):
    if fn == "sgr_input.txt":
        continue
    add("D:/data/gc", os.path.join(D_DATA, "gc", fn), "raw_storage")

add("D:/data", os.path.join(D_DATA, "gt.bin"), "partial_download")

# remote ProxCen sources (scanned via univ_scan, file not retained on disk)
for blc, mhz in (("blc02", "896"), ("blc06", "1408"), ("blc07", "1536"), ("blc10", "1664")):
    fn = f"{blc}_ProxCen_S_2019-04-29T12-56-23.000.fil"
    rows.append([fn, "ProxCen", "UNKNOWN", "remote(BL archive, not retained)", "134218034",
                 "128.0MB", "filterbank_fil(power)", "SCANNED_PARTIAL",
                 f"runs/prox_{blc}: spectral-only battery",
                 f"runs/prox_{blc}/REPORT.md",
                 f"I0 CLEAN at {mhz} MHz window (phase discarded at record time; spectral subset only).",
                 "Re-download to rescan with voltage battery.", "remote_source"])

# synthetic demo vectors (not sky; prove the ingest path only)
for fn, desc in (("weird.fil", "I1 notable-but-unstructured (injected tone in test vector)"),
                 ("weird.h5", "HDF5 ingest prove leg"), ("weird.npy", "npy ingest prove leg"),
                 ("weird.wav", "wav ingest prove leg; thicket-flagged by design")):
    p = os.path.join(E_DATA, "univ_demo", fn)
    sz = os.path.getsize(p) if os.path.exists(p) else -1
    rows.append([fn, "SYNTHETIC", "N/A", "E:/data/univ_demo", str(sz),
                 human(sz) if sz >= 0 else "?", "synthetic_demo", "SCANNED_PARTIAL",
                 "runs/univ_*", "runs/univ_*/REPORT.md", desc,
                 "Test vectors, NOT sky observations. Never cite as coverage.", "synthetic_demo"])

# partner-aware nudge: an unscanned OFF whose ON leg is scanned (or vice versa)
# is the cheapest path to a cadence gate — flag it in notes.
scanned_targets = {(r[1], r[2]) for r in rows if r[7].startswith("SCANNED")}
for r in rows:
    if r[7] == "NOT_SCANNED" and r[2] in ("ON", "OFF"):
        other = "OFF" if r[2] == "ON" else "ON"
        if (r[1], other) in scanned_targets:
            extra = f"Pairs with the already-scanned {other} leg — scanning this unlocks ON-OFF cadence gating (cadence_pair.py)."
            r[11] = (r[11] + " " + extra).strip()

out = os.path.join(ROOT, "catalog.tsv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["filename", "target", "pointing", "location", "size_bytes",
                "size_human", "format", "scan_status", "coverage",
                "runs_evidence", "result_summary", "notes", "kind"])
    w.writerows(rows)

n_scan = sum(1 for r in rows if r[7].startswith("SCANNED") or r[7] in ("SMOKE", "LEGACY", "QUARANTINED"))
n_not = sum(1 for r in rows if r[7] == "NOT_SCANNED")
print(f"catalog.tsv: {len(rows)} rows ({n_scan} scanned/quarantined/smoke, "
      f"{n_not} NOT_SCANNED, rest partial-file/remote/synthetic)")
