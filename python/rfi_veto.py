"""rfi_veto.py - SetiYeti disposition engine (M1: bystander-model rewrite)

WHAT CHANGED AND WHY
--------------------
The previous version was a *beacon-era* filter. It assumed:

    signal in ON and OFF  ->  human  ->  BLOCK

Under Objective 1 (see `_objective/objective_1.md`) that assumption is wrong.
Our target class is **third-party traffic and monuments** - signals that do not
care which way we point:

    a radio link between two distant stars is present in the ON pointing
    AND the OFF pointing, because it is not coming from our target at all.

The old veto would kill the jackpot and log it as `earth-likely`. That was the
blindfold.

This version replaces one flat "earth score" with TWO axes:

    EARTH      - evidence the signal is local (hum, wander, radar, backend)
    STRUCTURE  - evidence the signal is *engineered* (baud comb, frame period,
                 non-Gaussian tail, coded block, VM structure)

    net = EARTH - STRUCTURE

and common-mode stops being a death sentence. It becomes a *category*:

    common-mode + UNSTRUCTURED  ->  local (the building humming)   -> BLOCK
    common-mode + ENGINEERED    ->  not from our target             -> ESCALATE

Other fixes in this file:
  * band/frequency comes from the raw file header, NOT a hardcoded X-band table
  * cadence awareness (present-ON-only vs present-in-both) is scored
  * recurrence no longer auto-blocks a *structured* signature - a monument is
    DEFINED by recurring, so an unconditional recurrence rule would silently
    delete exactly the thing we are looking for
  * catalog dedupes at class level (alpha bucket x band), not per (block,chan)

v2 catalog doctrine (the self-blinding ratchet repair, 2026-09): keys are
target-agnostic and exact (SIG:int-MHz:int-Hz) with a documented tolerance
matcher; recurrence counts independent (raw, pointing) runs; engineered
slices never auto-block on either path (WATCH + analyst review queue);
null/zero alpha never files (5,492 bogus alpha-0 rows quarantined to health
telemetry). See migrate_catalog.py for the v1->v2 rewrite with receipts.

Inputs
  --hits      hits CSV (required)
  --evidence  optional evidence.csv (persist, multichan)
  --raw       optional .raw file -> read band/frequency from its header
  --freq-mhz / --bw-mhz / --nchan   optional explicit geometry overrides
  --on --off  optional ON / OFF hits CSVs -> builds the cadence map
  --target    dataset tag (evidence + catalog keying)
  --catalog   catalog path (default rfi_catalog.json)

Optional per-slice STRUCTURE columns in the hits CSV (absent = 0):
  comb        baud comb detected in the SCD plane
  frame       frame period / repetition detected
  nongauss    non-Gaussian tail excess vs matched noise
  pol         polarisation coherence across pols
  skflag/cohflag/ladderq/dm_sign
              XENO microscopic markers (c/xeno_scan), also accepted under
              their xeno_pass output aliases x_skflag/x_cohflag/x_ladderq/
              x_dm_sign.
  scint_class COMMON/SCINT/QUIET
              ISM scintillation verdict (python/scint_pol via xeno_pass):
              COMMON adds EARTH (gain wander), SCINT subtracts it (sky).
              Chain: scan -> structure_pass -> xeno_pass -> veto,
              so one CSV carries every detector. impuls is DELIBERATELY
              excluded: impulsivity alone (shots, pops, discharges) is not
              engineering - it needs persistence to matter (criteria doc).
  (vm_sign / vm_diff already carry the VM sandbox verdict)

Usage:
  python rfi_veto.py --hits runs/hits_trap_on.csv \
      --raw data/<file>.raw --on runs/hits_trap_on.csv --off runs/hits_trap_off.csv
"""
import argparse, csv, hashlib, json, os, re, shutil, sys, time

CAT_DEFAULT = 'rfi_catalog.json'
CAT_VERSION = 2
ALPHA_MATCH_TOL = 180.0      # Hz: ~2 FAM bins (SEG=32768 grid is 89.4 Hz).
# --- v2 catalog doctrine (2026-09: the self-blinding ratchet repair) ---------
# Keys are target-agnostic and exact: SIG:integer-channel-MHz:integer-alpha-Hz
# (e.g. Y4:1371:626). Matching uses catalog_tol() below, documented in Hz.
# Recurrence counts INDEPENDENT (raw-file, pointing) runs, never slices and
# never reprocessings of the same data. Engineered slices never auto-block:
# they go to WATCH + the analyst review queue on either the score or the
# recurrence path. Null/zero alpha never files (missing-data guard).
ALPHA_TOL_LO = 45.0             # Hz floor: splits 179/268 (89 Hz apart)
ALPHA_TOL_REL = 0.003           # 0.3% of alpha
ALPHA_TOL_HI = 500.0            # Hz cap: splits the 1.44 MHz trio (6.7 kHz apart)
FREQ_MATCH_TOL = 2.0            # MHz: same-channel spill only (2.93 MHz spacing)
HARD_N_RUNS = 3                 # independent runs required to hard-block
REVIEW_CAP = 500

# ---------------------------------------------------------------- band table --
# (f_lo MHz, f_hi MHz, label, kind)
# kind: 'ra'  = radio-astronomy protected (quietest spectrum on Earth)
#       'radar'/'ism' = terrestrial transmitters, strong earth prior
#       'sat' = satellite allocations, mild earth prior
#       'terr' = terrestrial fixed/mobile, mild earth prior
BANDS = [
    (1314.0, 1400.0, 'fixed/mobile/radiolocation (L lower)',            'terr'),
    (1400.0, 1427.0, 'RADIO ASTRONOMY (protected - quietest band)',     'ra'),
    (1427.0, 1429.0, 'space operation (downlink)',                      'sat'),
    (1429.0, 1452.0, 'fixed/mobile',                                    'terr'),
    (1452.0, 1492.0, 'fixed/mobile/broadcasting',                       'terr'),
    (1492.0, 1518.0, 'mobile',                                          'terr'),
    (1518.0, 1525.0, 'mobile-satellite',                                'sat'),
    (1525.0, 1559.0, 'mobile-satellite downlink (Inmarsat)',            'sat'),
    (1559.0, 1610.0, 'RADIONAVIGATION-SATELLITE (GPS/GLONASS)',         'sat'),
    (1610.0, 1611.0, 'mobile-satellite uplink',                         'sat'),
    (1610.6, 1613.8, 'RADIO ASTRONOMY (protected)',                     'ra'),
    (1613.8, 1626.5, 'mobile-satellite uplink / radiodetermination',    'sat'),
    (1660.0, 1670.0, 'RADIO ASTRONOMY (OH lines)',                      'ra'),
    (1670.0, 1690.0, 'meteorological aids / fixed',                     'terr'),
    (2400.0, 2483.5, 'ISM (WiFi/Bluetooth)',                            'ism'),
    (2690.0, 2700.0, 'RADIO ASTRONOMY (protected)',                     'ra'),
    (3700.0, 4200.0, 'fixed-satellite downlink (C-band)',               'sat'),
    (4200.0, 4400.0, 'aeronautical radionavigation (radar altimeters)', 'radar'),
    (5091.0, 5150.0, 'aeronautical radionavigation',                    'radar'),
    (5150.0, 5350.0, 'satellite / radiolocation',                       'sat'),
    (8400.0, 8500.0, 'space research / fixed',                          'sat'),
    (9200.0, 9300.0, 'maritime radionav + radiolocation RADAR',         'radar'),
    (9300.0, 9500.0, 'aeronautical/maritime radionav + radiolocation',  'radar'),
    (10700.0, 11700.0, 'fixed-satellite downlink (Ku)',                 'sat'),
    (12250.0, 12750.0, 'satellite (Ku)',                                'sat'),
    (13750.0, 14500.0, 'satellite uplink (Ku)',                         'sat'),
]

EARTH_PRIOR = {'radar': 0.20, 'ism': 0.20, 'terr': 0.10, 'sat': 0.10,
               'ra': -0.10, 'unk': 0.00}


def alloc(f):
    """Return (label, kind) for a frequency in MHz."""
    if f is None:
        return ('unknown band (no geometry)', 'unk')
    for a, b, label, kind in BANDS:
        if a <= f < b:
            return (label, kind)
    return ('unallocated', 'unk')


# ------------------------------------------------------------ raw file header --
def parse_guppi_header(path):
    """Read GUPPI cards (fixed 80-byte records) from the first block."""
    out = {}
    try:
        with open(path, 'rb') as fh:
            blob = fh.read(80 * 512)
    except OSError:
        return out
    for i in range(0, len(blob) - 80, 80):
        card = blob[i:i + 80].decode('ascii', 'replace')
        if card.startswith('END'):
            break
        if '=' not in card:
            continue
        k, v = card.split('=', 1)
        out[k.strip()] = v.split('/')[0].strip()
    return out


def geometry(args):
    """Resolve (freq_mhz, bw_mhz, nchan, source). Header first, args win."""
    freq = bw = None
    nchan = None
    src = 'unknown'
    if args.raw:
        h = parse_guppi_header(args.raw)
        try:
            freq = float(h.get('OBSFREQ', 'nan'))
        except ValueError:
            freq = None
        try:
            bw = float(h.get('OBSBW', 'nan'))
        except ValueError:
            bw = None
        try:
            nchan = int(float(h.get('OBSNCHAN') or h.get('NCHAN') or 0))
        except ValueError:
            nchan = None
        if freq is not None and bw is not None:
            src = os.path.basename(args.raw)
    if args.freq_mhz is not None:
        freq = args.freq_mhz; src = 'cli'
    if args.bw_mhz is not None:
        bw = args.bw_mhz; src = 'cli'
    if args.nchan is not None:
        nchan = args.nchan
    return freq, bw, (nchan or 64), src


def make_chan_freq(freq, bw, nchan):
    """Channel index -> MHz. Returns None if geometry unknown."""
    if freq is None or bw is None:
        return lambda ch: None
    step = bw / nchan                       # signed: negative for descending bands
    return lambda ch: freq + (ch - (nchan - 1) / 2.0) * step


# -------------------------------------------------------------------- catalog --
def load_catalog(path):
    if not os.path.exists(path):
        return {'features': {}}
    try:
        c = json.load(open(path))
    except (OSError, ValueError):
        return {'features': {}}
    feats = c.get('features', {})
    if isinstance(feats, list):             # migrate old flat list -> class dict
        merged = {}
        for e in feats:
            sig = e.get('sig', '')
            m = re.match(r'^([^:]+):([-\d.]+)Hz$', sig)
            if not m:
                continue
            tag, a = m.group(1), float(m.group(2))
            key = catalog_key(tag, e.get('freq_mhz'), a)
            d = merged.setdefault(key, {'sig': f'{tag}:{a:.0f}Hz', 'alpha': a,
                                        'n_seen': 0, 'n_runs': 0, 'seen_in': [],
                                        'targets': [], 'structured': False,
                                        'freq_mhz': e.get('freq_mhz'), 'disp': e.get('disp')})
            d['n_seen'] += 1
        c['features'] = merged
    return c


def save_catalog(c, path):
    tmp = path + '.tmp'          # atomic: concurrent readers never see half a catalog
    json.dump(c, open(tmp, 'w'), indent=1)
    os.replace(tmp, path)


def is_signal_row(row):
    v = str(row.get('verdict', 'clean'))
    return v.startswith('FAM-HIT') or v.startswith('SPECTRAL-LINE')


def alpha_bucket(a):
    """LEGACY v1 bucket (%.3g). Kept for reading old records only - v2 uses
    catalog_key() + catalog_tol(). Do not use for new matching."""
    return f'{a:.3g}'


def catalog_tol(alpha):
    """Match tolerance in Hz, documented: min(max(45 Hz, 0.3% of alpha),
    500 Hz). At 626 Hz -> 45 Hz (splits nothing real, merges grid halves);
    at 1.44 MHz -> 500 Hz (the 1.44e+06 trio sits 6.7 kHz apart: split)."""
    try:
        a = float(alpha)
    except (TypeError, ValueError):
        return ALPHA_TOL_LO
    if a <= 0:
        return ALPHA_TOL_LO
    return min(max(ALPHA_TOL_LO, ALPHA_TOL_REL * a), ALPHA_TOL_HI)


def catalog_key(tag, freq_mhz, alpha):
    """v2 key: SIG:integer-channel-MHz:integer-alpha-Hz. No target name, no
    band-prior suffix - RFI is local to the telescope, and per-target /
    per-band suffixes fragmented one oscillator into a dozen 'classes'.
    Unknown geometry files as -1 (matches only -1)."""
    try:
        f = int(round(float(freq_mhz)))
    except (TypeError, ValueError):
        f = -1
    try:
        al = int(round(float(alpha)))
    except (TypeError, ValueError):
        al = -1
    return f"{tag}:{f}:{al}"


def catalog_lookup(features, tag, freq_mhz, alpha):
    """Tolerance match on (tag, channel-freq, alpha). Returns (key, entry)
    or (exact_new_key, None). Null/zero alpha never matches and never
    files (missing-data guard: empty fam_hz used to file as alpha 0)."""
    try:
        fq = float(freq_mhz)
        al = float(alpha)
    except (TypeError, ValueError):
        return catalog_key(tag, freq_mhz, alpha), None
    if al <= 0:
        return catalog_key(tag, freq_mhz, alpha), None
    tol = catalog_tol(al)
    best_key, best_d = None, None
    for key, _e in features.items():
        try:
            parts = key.split(':')
            if len(parts) != 3:
                continue                    # v1 key: migration owns it, not matching
            ktag, kfq, kal = parts[0], float(parts[1]), float(parts[2])
        except ValueError:
            continue
        if ktag != tag:
            continue
        if abs(kfq - fq) <= FREQ_MATCH_TOL and abs(kal - al) <= tol:
            if best_d is None or abs(kal - al) < best_d:
                best_key, best_d = key, abs(kal - al)
    if best_key is None:
        return catalog_key(tag, round(fq), round(al)), None
    return best_key, features[best_key]


def file_review(ctx, key, row, tag, freq_mhz, alpha, S, E, why):
    """Analyst queue: engineered slices any rule wanted dead. Dedupe by
    (key, run); capped. This is the escalation-track substrate (promotion
    machinery stays future work; nothing engineered vanishes silently)."""
    try:
        q = ctx['catalog'].setdefault('review', [])
        if len(q) >= REVIEW_CAP:
            return
        run = ctx.get('run_id', '')
        if any(d.get('key') == key and d.get('run') == run for d in q):
            return
        q.append({'key': key, 'sig': f"{tag}:{float(alpha):.0f}Hz",
                  'alpha': float(alpha), 'freq_mhz': freq_mhz,
                  'target': ctx.get('target', ''), 'run': run,
                  'S': round(S, 2), 'E': round(E, 2), 'why': why})
    except (TypeError, ValueError, AttributeError):
        pass


def catalog_file(cat, tag, freq_mhz, alpha, S, disp, target, run_id):
    """File one slice. Returns (key, n_runs, filed). Null/zero alpha is
    refused (returns filed=False): unmodulated-DC and empty-field rows used
    to file 5,492 bogus alpha-0 'detections'."""
    try:
        al = float(alpha)
    except (TypeError, ValueError):
        return catalog_key(tag, freq_mhz, alpha), 0, False
    if al <= 0:
        return catalog_key(tag, freq_mhz, alpha), 0, False
    key, _prev = catalog_lookup(cat['features'], tag, freq_mhz, al)
    fe = cat['features'].setdefault(key, {
        'sig': f"{tag}:{al:.0f}Hz", 'alpha': al, 'freq_mhz': freq_mhz,
        'n_seen': 0, 'n_runs': 0, 'seen_in': [], 'targets': [],
        'structured': False, 'disp': disp})
    fe.setdefault('seen_in', [])       # migrate-on-read for v1 entries
    fe.setdefault('targets', [])
    fe['n_seen'] = int(fe.get('n_seen', 0)) + 1
    if run_id and run_id not in fe['seen_in']:
        fe['seen_in'] = (fe['seen_in'] + [run_id])[-64:]
    fe['n_runs'] = len(set(fe['seen_in']))
    if target and target not in fe['targets']:
        fe['targets'].append(target)
    fe['structured'] = bool(fe.get('structured', False)) or (S >= 0.25)
    fe['disp'] = disp
    return key, fe['n_runs'], True


def make_run_id(hits_path, raw_path, target):
    """Data-fingerprinted idempotency. The old key hashed the hits-CSV
    path, so reprocessing the SAME raw data from a new outdir counted as an
    independent sighting (the burst filed n=8 across reprocessings). Same
    raw + same target now counts ONCE, forever."""
    if raw_path and os.path.exists(raw_path):
        try:
            st = os.stat(raw_path)
            base = f'{os.path.abspath(raw_path)}|{st.st_mtime_ns}|{target}'
            return hashlib.sha1(base.encode()).hexdigest()[:12]
        except OSError:
            pass
    try:
        st = os.stat(hits_path)
        base = f'{os.path.abspath(hits_path)}|{st.st_mtime_ns}|{target}'
    except OSError:
        base = f'manual-{int(time.time())}'
    return hashlib.sha1(base.encode()).hexdigest()[:12]


# ------------------------------------------------------------------- cadence --
def signature_index(csv_path, tol=ALPHA_MATCH_TOL):
    """(chan, alpha) pairs present in a hits file."""
    idx = []
    if not csv_path or not os.path.exists(csv_path):
        return idx
    for r in csv.DictReader(open(csv_path)):
        if not is_signal_row(r):
            continue
        try:
            idx.append((int(r['chan']), float(r['fam_hz'] or 0)))
        except (KeyError, ValueError):
            continue
    return idx


def in_index(idx, chan, alpha, tol=ALPHA_MATCH_TOL):
    for c, a in idx:
        if c == chan and abs(a - alpha) <= max(tol, 0.02 * max(a, alpha)):
            return True
    return False


# ------------------------------------------------------------------- scoring --
def flag(row, name):
    v = str(row.get(name, '') or '').strip().lower()
    return v in ('1', '1.0', 'true', 'yes', 'y')


def structure_score(row):
    """Evidence that the signal is engineered. Capped at 1.0."""
    s, why = 0.0, []
    # Thickey discount FIRST: a comb found inside an intermod thicket is
    # comb-by-density (proven in-prove: synthetic thicket scores 1940 with
    # 7 members), not evidence of modulation. Counting it would let the
    # artifact promote itself. lines10==-1/unknown counts normally.
    try:
        _nl = int(row.get('lines10') if row.get('lines10') not in (None, '') else -1)
    except (ValueError, TypeError):
        _nl = -1
    in_thicket = _nl >= 25
    vm = str(row.get('vm_sign', '')) + str(row.get('vm_diff', ''))
    if 'CANDIDATE' in vm:
        s += 0.25; why.append('+0.25 VM sandbox structure flag')
    if flag(row, 'comb') and not in_thicket:
        s += 0.20; why.append('+0.20 baud comb in SCD plane')
    elif flag(row, 'comb') and in_thicket:
        why.append('+0.00 comb DISCOUNTED (inside intermod thicket: comb-by-density)')
    if flag(row, 'frame'):
        s += 0.25; why.append('+0.25 frame period / repetition detected')
    if flag(row, 'nongauss'):
        s += 0.15; why.append('+0.15 non-Gaussian tail vs matched noise')
    if flag(row, 'pol'):
        s += 0.15; why.append('+0.15 polarisation coherence')
    # XENO microscopic battery (c/xeno_scan via xeno_pass; x_ aliases are
    # the xeno_pass output column names - absent columns read as 0).
    # These are the markers the overhaul made GRADE-GIVING; the veto now
    # scores them instead of ignoring them (b76/ch44's skflag is why).
    if flag(row, 'skflag') or flag(row, 'x_skflag'):
        s += 0.15; why.append('+0.15 spectral-kurtosis packet structure')
    if flag(row, 'cohflag') or flag(row, 'x_cohflag'):
        s += 0.10; why.append('+0.10 clock-grade coherence')
    if flag(row, 'ladderq') or flag(row, 'x_ladderq'):
        s += 0.15; why.append('+0.15 cepstral comb (engineering until proven otherwise)')
    dm = str(row.get('dm_sign', '') or row.get('x_dm_sign', '') or '0')
    if dm.strip() in ('-1', '+1', '1'):
        s += 0.15; why.append('+0.15 dispersion-order sign (normal or EXOTIC)')
    # Scores are 0.05-granular by construction; round so verdict boundaries
    # (0.50/0.15) never flip on float dust (caught live: net=0.1499... at the
    # WATCH/CANDIDATE seam promoted a held slice - prove SC1).
    return round(min(s, 1.0), 2), why


def score_slice(row, ctx):
    """Return (earth, structure, net, disp, reasons). Pure function - testable."""
    ch = int(row['chan'])
    alpha = float(row.get('fam_hz') or 0)
    f = ctx['chan_freq'](ch)
    evkey = (str(ctx.get('target', '')), str(row.get('block')), str(ch))
    evrow = ctx['evidence'].get(evkey)
    if evrow is None:
        evrow = ctx['evidence'].get((str(row.get('block')), str(ch)), {})
    # NOTE: str('0') is truthy - bool('0')==True silently armed every stale
    # row. Compare flag values explicitly.
    persist = str(evrow.get('persist', '0')).strip().lower() in (
        '1', '1.0', 'true', 'yes')
    multi = str(evrow.get('multichan', '0')).strip().lower() in (
        '1', '1.0', 'true', 'yes')

    S, s_why = structure_score(row)
    engineered = S >= 0.25

    # --- cadence ---------------------------------------------------------
    cad = 'unknown'
    if ctx['on_idx'] is not None and ctx['off_idx'] is not None:
        on = in_index(ctx['on_idx'], ch, alpha)
        off = in_index(ctx['off_idx'], ch, alpha)
        cad = 'both' if (on and off) else ('on_only' if on else ('off_only' if off else 'neither'))

    # --- EARTH axis ------------------------------------------------------
    E, e_why = 0.0, []
    label, kind = alloc(f)
    if f is not None:
        prior = EARTH_PRIOR.get(kind, 0.0)
        E += prior
        e_why.append(f'{prior:+.2f} band {f:.1f}MHz [{label}]')

    if multi:
        # common-MODE across channels. Under the bystander model this is NOT
        # automatically local - it means "not from our pointing".
        if engineered:
            E -= 0.30
            e_why.append('-0.30 common-mode BUT ENGINEERED -> not from target (the target class)')
        else:
            E += 0.60
            e_why.append('+0.60 common-mode, unstructured -> backend/local')
    else:
        E += 0.15
        e_why.append('+0.15 single-channel')
        if 1e5 <= alpha <= 5e6:
            E += 0.20; e_why.append(f'+0.20 alpha {alpha:.0f}Hz in electronics zone')
        elif 1 <= alpha <= 2000:
            E -= 0.25; e_why.append(f'-0.25 alpha {alpha:.0f}Hz in rotation-astro band')

    if cad == 'both':
        if engineered:
            E -= 0.15
            e_why.append('-0.15 present in ON and OFF + structured -> not from target')
        else:
            E += 0.25
            e_why.append('+0.25 present in ON and OFF, unstructured -> local')
    elif cad == 'on_only':
        e_why.append('+0.00 ON-only (classic celestial geometry)')
    elif cad == 'off_only':
        E += 0.20; e_why.append('+0.20 OFF-only (not in target pointing)')
    elif cad == 'neither':
        E += 0.15; e_why.append('+0.15 not found in either cadence half')

    if not persist:
        E += 0.30; e_why.append('+0.30 transient (absent over full span)')
    else:
        E -= 0.20; e_why.append('-0.20 persistent across span')

    # Scintillation medium-test (python/scint_pol via xeno_pass scint_class).
    # This wires the analyst hold INTO the machine: COMMON (gain wander moves
    # every band together) is the backend fingerprint; SCINT (decorrelated
    # ISM breathing) is the sky fingerprint. Absent column reads as 0.
    sc = str(row.get('scint_class', '') or '').strip().upper()
    if sc == 'COMMON':
        E += 0.30; e_why.append('+0.30 common gain-wander scintillation (backend, all bands together)')
    elif sc == 'SCINT':
        E -= 0.20; e_why.append('-0.20 ISM-signed decorrelated scintillation (sky marker)')

    # THICKET (XENO overhaul): a dense intermod line forest games the comb
    # rule - with a line in every bin, accidental harmonic alignments are
    # certain and the mean member ratio stays high (proven in-prove:
    # synthetic thicket scores comb 1940 with 7 members vs 859 for a real
    # AM baud comb; the fence is the line count, 9 vs 25+). A real baud
    # comb lights a few bins; a thicket lights dozens. lines10==-1 means
    # the numpy fallback ran (unknown) and is ignored, never penalised.
    try:
        nl10 = int(row.get('lines10') if row.get('lines10') not in (None, '') else -1)
    except (ValueError, TypeError):
        nl10 = -1
    if nl10 >= 25:
        E += 0.35
        e_why.append(f'+0.35 intermod thicket ({nl10} lines>10x: comb-by-density, not modulation)')

    vm = str(row.get('vm_sign', '')) + str(row.get('vm_diff', ''))
    if 'noise-like' in vm and not engineered:
        E += 0.10; e_why.append('+0.10 VM noise-like')

    E = max(E, 0.0)

    # --- recurrence (v2: independent runs, never slices; structured exempt) -
    tag = str(row.get('fam_tag') or '-').strip() or '-'
    class_key, prev = catalog_lookup(ctx['catalog']['features'], tag, f, alpha)
    prev = prev or {}
    n_runs = len(set(prev.get('seen_in', [])))
    n_seen = int(prev.get('n_seen', 0))
    hard_block = False
    if n_runs >= HARD_N_RUNS:
        if engineered:
            E = max(E - 0.10, 0.0)
            e_why.append(f'-0.10 recurring x{n_runs} runs AND structured -> monument-like, NOT auto-blocked')
            file_review(ctx, class_key, row, tag, f, alpha, S, E,
                        'recurring structured (monument watch)')
        else:
            hard_block = True
            e_why.append(f'HARD-BLOCK recurring known-local signature ({n_runs} independent runs, {n_seen} slices)')

    E = round(E, 2)              # boundary-exact dispositions (see structure_score)
    net = round(E - S, 2)
    reasons = list(s_why) + e_why

    if hard_block:
        disp = 'BLOCK:earth-likely'
    elif net >= 0.50:
        if engineered:
            # Score-BLOCK is where structured signals actually died (e.g.
            # KEPLER160:626:terr, structured:true + BLOCK). Engineered
            # slices never score-BLOCK: WATCH + analyst queue instead.
            # (First-sight UNSTRUCTURED junk still score-BLOCKs - the veto
            # must delete obvious RFI immediately or every run floods WATCH.)
            disp = 'WATCH'
            reasons.append('score-block suppressed: engineered -> analyst review (never auto-block structure)')
            file_review(ctx, class_key, row, tag, f, alpha, S, E,
                        'engineered, score would block')
        else:
            disp = 'BLOCK:earth-likely'
    elif net >= 0.15:
        disp = 'WATCH'
    else:
        disp = 'CANDIDATE'
        # candidacy still needs more than a low score: persistence + structure
        # (or common-mode structure). Never promote a one-off nothing.
        if not (persist and (engineered or multi)):
            disp = 'WATCH'
            reasons.append('capped: candidacy requires persistence + structure/coincidence')

    return E, S, net, disp, reasons, class_key


# ---------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hits', required=True)
    ap.add_argument('--evidence')
    ap.add_argument('--raw')
    ap.add_argument('--freq-mhz', type=float)
    ap.add_argument('--bw-mhz', type=float)
    ap.add_argument('--nchan', type=int)
    ap.add_argument('--on')
    ap.add_argument('--off')
    ap.add_argument('--target', default='')
    ap.add_argument('--catalog', default=CAT_DEFAULT)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--dry-run', action='store_true',
                    help='score and print, but do not mutate the catalog')
    ap.add_argument('--run-id', default='',
                    help='idempotency key (default: hash of hits path+mtime+target)')
    a = ap.parse_args()

    freq, bw, nchan, src = geometry(a)
    chan_freq = make_chan_freq(freq, bw, nchan)
    if freq is None:
        print(f'[veto] WARNING: no band geometry ({src}); band priors disabled. '
              f'Pass --raw <file.raw> or --freq-mhz/--bw-mhz.', file=sys.stderr)
    else:
        print(f'[veto] band geometry from {src}: {freq:.3f} MHz centre, '
              f'{bw:.3f} MHz, {nchan} chan')

    ev = {}
    if a.evidence and os.path.exists(a.evidence):
        for r in csv.DictReader(open(a.evidence)):
            ev[(r['block'], r['chan'])] = r

    on_idx = signature_index(a.on) if a.on else None
    off_idx = signature_index(a.off) if a.off else None
    if on_idx is not None:
        print(f'[veto] cadence: ON={len(on_idx)} signatures, '
              f'OFF={"n/a" if off_idx is None else len(off_idx)}')

    cat = load_catalog(a.catalog)
    cat.setdefault('runs', {})
    if not a.run_id:
        rawpath = a.raw if (a.raw and os.path.exists(a.raw)) else None
        a.run_id = make_run_id(a.hits, rawpath, a.target)
    recount = a.run_id not in cat['runs']
    n_block = n_watch = n_cand = n_skip = n_null = 0
    n_rev0 = len(cat.get('review', []))
    ctx = {'chan_freq': chan_freq, 'evidence': ev, 'catalog': cat,
           'target': a.target, 'on_idx': on_idx, 'off_idx': off_idx,
           'run_id': a.run_id}

    for row in csv.DictReader(open(a.hits)):
        if not is_signal_row(row):
            n_skip += 1
            continue
        E, S, net, disp, reasons, class_key = score_slice(row, ctx)
        sig = f"{row.get('fam_tag','?')}:{float(row.get('fam_hz') or 0):.0f}Hz"
        print(f"[veto] b{row['block']}/ch{row['chan']} {sig} "
              f"E={E:.2f} S={S:.2f} net={net:+.2f} -> {disp}")
        if not a.quiet:
            for r in reasons:
                print(f'         - {r}')
        if disp.startswith('BLOCK'):
            n_block += 1
        elif disp == 'WATCH':
            n_watch += 1
        else:
            n_cand += 1
        if recount:
            # v2 filing: null/zero alpha refused (missing-data guard); the
            # health line below reports how many rows were telemetry, not signal.
            tag = str(row.get('fam_tag') or '-').strip() or '-'
            _key, _nruns, filed = catalog_file(
                cat, tag, chan_freq(int(row['chan'])), row.get('fam_hz'),
                S, disp, a.target, a.run_id)
            if not filed:
                n_null += 1
    if a.dry_run:
        print(f'[veto] DRY-RUN run_id={a.run_id}: catalog untouched')
    else:
        if os.path.exists(a.catalog) and recount:
            try:  # rolling backup before every mutation of the record
                shutil.copy2(a.catalog, a.catalog + '.bak')
            except OSError as e:
                print(f'[veto] WARNING: backup failed ({e}); aborting save',
                      file=sys.stderr)
                recount = 'aborted'
        if recount != 'aborted':
            cat['runs'][a.run_id] = {
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'hits': a.hits, 'target': a.target}
            save_catalog(cat, a.catalog)
    n_rev1 = len(cat.get('review', []))
    print(f'[veto] BLOCK={n_block} WATCH={n_watch} CANDIDATE={n_cand} '
          f'skipped_nonflag={n_skip} | catalog={len(cat["features"])} classes '
          f'| run_id={a.run_id}'
          + ('' if recount else ' (recount skipped: id seen)'))
    if n_null:
        print(f'[veto] health: {n_null} signal rows with null/zero alpha '
              f'(telemetry, not signal - not filed)')
    if n_rev1 > n_rev0:
        print(f'[veto] review: +{n_rev1 - n_rev0} analyst-queue items '
              f'({n_rev1} total - engineered slices no rule may auto-block)')


if __name__ == '__main__':
    main()
