"""satpass.py - SetiYeti satellite conjunction check (RFI attribution aid).

WHY THIS EXISTS: half of everything the battery flags is metal in orbit.
A flag at 1575 MHz during a GPS pass, at 137 MHz under NOAA, or beneath a
Starlink train is answered in one lookup - no staring required. This tool
propagates TLEs (SGP4, open-source `sgp4` pip package) over an observation
window for a real observatory and reports what was overhead, when, and how
high. It is attribution EVIDENCE, not a veto rule: satellite-overhead does
not prove a flag is RFI (sidelobes, beacons, and the bystander case all
complicate it), but satellite-absent removes one mundane hypothesis.

Offline-first: propagation + GMST + topocentric math are hand-rolled numpy
(arcminute accuracy, no IERS downloads). `--update-tle` fetches Celestrak
groups when network exists; every prove and every analysis runs offline
with embedded sample TLEs (checksums repaired in-code).

  python satpass.py --prove
  python satpass.py --at 2020-09-13T04:00:00 --dur 30 --site GBT
  python satpass.py --update-tle --group stations
  python satpass.py --tle tle.txt --at ... --dur 60 --min-el 30 --json

Observatory presets: GBT, Parkes, MeerKAT, VLA, FAST.
"""
import argparse
import datetime
import json
import math
import os
import sys

import numpy as np

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from sgp4.api import Satrec, jday
    HAVE_SGP4 = True
except ImportError:
    HAVE_SGP4 = False

SITES = {
    'GBT': (38.4331, -79.8398, 0.880),
    'Parkes': (-32.9984, 148.2637, 0.400),
    'MeerKAT': (-30.7210, 21.4110, 1.000),
    'VLA': (34.0784, -107.6184, 2.100),
    'FAST': (25.6529, 106.8565, 0.500),
}

CELESTRAK = 'https://celestrak.org/NORAD/elements/gp.php?GROUP={}&FORMAT=tle'


# ------------------------------------------------------------- TLE utils --
def fix_ck(line):
    """Repair TLE checksum (col 69): mod-10 of digits + minus signs."""
    s = 0
    for ch in line[:68]:
        if ch.isdigit():
            s += int(ch)
        elif ch == '-':
            s += 1
    return line[:68] + str(s % 10) + line[69:]


SAMPLE_TLE = {
    # inclination/mean-motion-faithful samples (epochs arbitrary; SGP4
    # propagates any epoch - accuracy degrades, self-consistency holds)
    'ISS': ['1 25544U 98067A   26263.50000000  .00016717  00000-0  10270-3 0  9000',
            '2 25544  51.6416 208.9163 0006703  69.9862  25.2906 15.49560532    10'],
    'GOES-E': ['1 41866U 16071A   26263.50000000  .00000000  00000-0  00000-0 0  9000',
               '2 41866   0.0192  45.0000 0000456  90.0000 135.0000  1.00270000    10'],
    'GPS': ['1 24876U 97035A   26263.50000000  .00000000  00000-0  00000-0 0  9000',
            '2 24876  55.0000 120.0000 0050000  40.0000  60.0000  2.00560000    10'],
}
for _k in SAMPLE_TLE:
    SAMPLE_TLE[_k] = [fix_ck(SAMPLE_TLE[_k][0]), fix_ck(SAMPLE_TLE[_k][1])]


def parse_tle_text(txt):
    sats = []
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        if lines[i].startswith('1 ') and i + 1 < len(lines) and lines[i + 1].startswith('2 '):
            sats.append(('', lines[i], lines[i + 1]))
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith('1 ') and lines[i + 2].startswith('2 '):
            sats.append((lines[i], lines[i + 1], lines[i + 2]))
            i += 3
        else:
            i += 1
    return sats


def guppi_block_iso(path, block=0):
    """GUPPI header clock -> ISO UTC of a block. STT_IMJD/SMJD/OFFS give
    the file start; block duration comes from BLOCSIZE/geometry x TBIN."""
    sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
    import seti_common as SC
    h = SC.read_header(path)
    try:
        mjd = float(h['STT_IMJD']) + float(h.get('STT_SMJD', 0)) / 86400.0
    except (KeyError, ValueError, TypeError):
        raise SystemExit('GUPPI header lacks STT_IMJD/SMJD clock')
    try:
        bs = float(h['BLOCSIZE'])
        nchan = float(h.get('OBSNCHAN', h.get('NCHAN', 0)))
        npol = float(h.get('NPOL', 0))
        nbits = float(h.get('NBITS', 0))
        tbin = float(h.get('TBIN', 0))
        blk_s = bs / (nchan * npol * nbits / 8.0) * tbin
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        raise SystemExit('GUPPI header lacks geometry for block duration')
    unix = (mjd - 40587.0) * 86400.0 + block * blk_s
    return datetime.datetime.fromtimestamp(
        unix, tz=datetime.timezone.utc).isoformat()


def tle_epoch_jd(l1):
    """TLE line-1 epoch (YYDDD.DDDD, cols 19-32) -> Julian date."""
    yy = int(l1[18:20])
    day = float(l1[20:32])
    year = 2000 + yy if yy < 57 else 1900 + yy
    return sum(jday(year, 1, 1, 0, 0, 0.0)) + day - 1.0


# ------------------------------------------------------------- astro math --
def gmst_rad(jd):
    """Greenwich Mean Sidereal Time (Vallado, arcminute-grade offline)."""
    T = (jd - 2451545.0) / 36525.0
    g = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
         + 0.000387933 * T * T - T ** 3 / 38710000.0)
    return math.radians(g % 360.0)


def eci_to_sez(r_eci, lat, lon, jd):
    """Satellite ECI (km) -> observer SEZ unit look vector + range."""
    th = gmst_rad(jd) + lon
    R = 6378.137
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    sl, cl = math.sin(lat), math.cos(lat)
    N = R / math.sqrt(1 - e2 * sl * sl)
    r_obs = np.array([N * cl * math.cos(th), N * cl * math.sin(th),
                      N * (1 - e2) * sl])
    rho = r_eci - r_obs
    rng = float(np.linalg.norm(rho))
    st, ct = math.sin(th), math.cos(th)
    S = np.array([-sl * ct, -sl * st, cl])
    E = np.array([-st, ct, 0.0])
    Z = np.array([cl * ct, cl * st, sl])
    u = rho / rng
    s, e, z = float(u @ S), float(u @ E), float(u @ Z)
    el = math.degrees(math.asin(max(-1.0, min(1.0, z))))
    az = math.degrees(math.atan2(e, -s)) % 360.0
    return el, az, rng


def iso_to_jd(iso):
    dt = datetime.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    if HAVE_SGP4:
        return sum(jday(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                        dt.second + dt.microsecond / 1e6))
    # fallback (Meeus): JD at 0h + fraction
    a = (14 - dt.month) // 12
    y, m = dt.year + 4800 - a, dt.month + 12 * a - 3
    jdn = (dt.day + (153 * m + 2) // 5 + 365 * y + y // 4
           - y // 100 + y // 400 - 32045)
    return jdn - 0.5 + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24


def propagate(sat, jd):
    e, r, v = sat.sgp4(jd, 0.0)
    if e != 0:
        return None
    return np.array(r)


def passes_for(satrec, name, lat, lon, jd0, dur_s, min_el=0.0, step=20.0):
    """Sample the window; return pass segments above min_el."""
    ts = np.arange(0, dur_s + step, step)
    els, azs, rngs = [], [], []
    for t in ts:
        jd = jd0 + t / 86400.0
        r = propagate(satrec, jd)
        if r is None:
            els.append(-90.0)
            azs.append(0.0)
            rngs.append(0.0)
            continue
        el, az, rng = eci_to_sez(r, math.radians(lat), math.radians(lon), jd)
        els.append(el)
        azs.append(az)
        rngs.append(rng)
    els = np.array(els)
    out, i, n = [], 0, len(ts)
    while i < n:
        if els[i] >= min_el:
            j = i
            while j + 1 < n and els[j + 1] >= min_el:
                j += 1
            k = i + int(np.argmax(els[i:j + 1]))
            out.append({'sat': name, 'rise_s': float(ts[i]),
                        'set_s': float(ts[min(j + 1, n - 1)]),
                        'tca_s': float(ts[k]), 'max_el': round(float(els[k]), 1),
                        'tca_az': round(float(azs[k]), 1),
                        'tca_range_km': round(float(rngs[k]), 0)})
            i = j + 1
        else:
            i += 1
    return out


# ------------------------------------------------------------------ main --
def load_sats(args):
    sats = []
    if args.tle and os.path.exists(args.tle):
        sats += parse_tle_text(open(args.tle).read())
    if args.sample:
        for nm, (l1, l2) in SAMPLE_TLE.items():
            sats.append((nm, l1, l2))
    return sats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tle', default='')
    ap.add_argument('--sample', action='store_true',
                    help='include embedded sample TLEs (ISS/GOES/GPS)')
    ap.add_argument('--group', default='',
                    help='with --update-tle: celestrak group (stations,noaa,goes,gps-ops,iridium)')
    ap.add_argument('--update-tle', action='store_true')
    ap.add_argument('--tle-out', default='tle.txt')
    ap.add_argument('--site', default='GBT')
    ap.add_argument('--lat', type=float, default=None)
    ap.add_argument('--lon', type=float, default=None)
    ap.add_argument('--alt', type=float, default=0.0)
    ap.add_argument('--at', default='')
    ap.add_argument('--guppi-at', default='',
                    help='GUPPI .raw file: read STT_IMJD/SMJD clock (no guessing)')
    ap.add_argument('--block', type=int, default=0,
                    help='with --guppi-at: block index -> exact UTC of that block')
    ap.add_argument('--dur', type=float, default=60.0)
    ap.add_argument('--min-el', type=float, default=0.0)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--prove', action='store_true')
    a = ap.parse_args()

    if not HAVE_SGP4:
        sys.exit('sgp4 not installed: pip install sgp4')
    if a.prove:
        sys.exit(0 if prove() else 1)
    if a.update_tle:
        if not a.group:
            sys.exit('need --group with --update-tle')
        import urllib.request
        url = CELESTRAK.format(a.group)
        try:
            txt = urllib.request.urlopen(url, timeout=30).read().decode()
        except Exception as e:
            sys.exit(f'fetch failed (offline?): {e}')
        open(a.tle_out, 'w').write(txt)
        print(f'[tle] {len(parse_tle_text(txt))} sats -> {a.tle_out}')
        return
    if a.guppi_at:
        a.at = guppi_block_iso(a.guppi_at, a.block)
        print(f'[satpass] {os.path.basename(a.guppi_at)} block {a.block} -> {a.at}')
    if not a.at:
        sys.exit('need --at ISO (or --guppi-at FILE / --prove / --update-tle)')

    if a.lat is not None and a.lon is not None:
        lat, lon, alt = a.lat, a.lon, a.alt
        site = 'custom'
    else:
        if a.site not in SITES:
            sys.exit(f'unknown site {a.site} (or pass --lat/--lon)')
        lat, lon, alt = SITES[a.site]
        site = a.site
    _ = alt
    sats = load_sats(a)
    if not sats:
        sys.exit('no TLEs: pass --tle and/or --sample')
    jd0 = iso_to_jd(a.at)
    # Staleness guard: TLEs age in days (drag uncertainty); propagating a
    # 2026 element set at a 2020 timestamp returns confidently wrong
    # positions (measured: lunar-distance LEO ranges). Warn, never silence.
    # (Placed AFTER jd0 exists - an early draft read it before assignment
    # and the bare except swallowed the NameError. Order matters.)
    try:
        ep = max(tle_epoch_jd(l1) for _, l1, _ in sats)
        stale = abs(jd0 - ep)
        if stale > 30:
            print(f'[warn] TLE set is {stale:.0f} days from query time: '
                  f'positions unreliable, attribution-grade use only within '
                  f'~30 days (fetch archive elements for old observations)',
                  file=sys.stderr)
    except Exception as _e:
        print(f'[warn] staleness check failed ({_e})', file=sys.stderr)
    allp = []
    for name, l1, l2 in sats:
        try:
            rec = Satrec.twoline2rv(l1, l2)
        except Exception as e:
            print(f'[warn] bad TLE {name!r}: {e}', file=sys.stderr)
            continue
        allp += passes_for(rec, name or f'NORAD{l1[2:7]}',
                           lat, lon, jd0, a.dur, a.min_el)
    allp.sort(key=lambda p: -p['max_el'])
    if a.json:
        print(json.dumps({'site': site, 'at': a.at, 'dur_s': a.dur,
                          'passes': allp}, indent=1))
        return
    print(f'[satpass] {site} ({lat},{lon}) @ {a.at} +{a.dur:.0f}s: '
          f'{len(allp)} passes above {a.min_el:.0f} deg')
    for p in allp[:20]:
        print(f"  {p['sat']:12s} max_el={p['max_el']:5.1f} tca=+{p['tca_s']:5.0f}s "
              f"az={p['tca_az']:.0f} rng={p['tca_range_km']:.0f}km")
    if not allp:
        print('  (nothing above the elevation mask - one mundane hypothesis down)')


def prove():
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    iss = Satrec.twoline2rv(*SAMPLE_TLE['ISS'])
    jd0 = iso_to_jd('2026-01-01T00:00:00')
    r0 = propagate(iss, jd0)
    rad = float(np.linalg.norm(r0))
    check('ISS radius sane (LEO)', 6600 < rad < 7000, f'{rad:.0f} km')
    # half an orbit later (period 1440/15.4956 = 92.9 min): opposite side.
    # (An early draft used +90 min - nearly a FULL orbit, displacement ~0.
    # Orbital mechanics 1, test author 0.)
    r1 = propagate(iss, jd0 + 2786 / 86400)
    moved = float(np.linalg.norm(r1 - r0))
    check('ISS moves (~orbital rate)', 10000 < moved < 18000, f'{moved:.0f} km/half-orbit')

    geo = Satrec.twoline2rv(*SAMPLE_TLE['GOES-E'])
    lons = []
    for h in range(0, 25, 4):
        r = propagate(geo, jd0 + h / 24)
        th = gmst_rad(jd0 + h / 24)
        lon = (math.degrees(math.atan2(r[1], r[0])) - math.degrees(th)) % 360
        lons.append(lon if lon < 180 else lon - 360)
    drift = max(lons) - min(lons)
    check('GEO subpoint fixed (geostationary)', abs(drift) < 2.0,
          f'drift={drift:.2f} deg/24h')
    # visibility from beneath its own subpoint (the sample is parked over
    # the wrong ocean for GBT - an early draft asserted GBT and measured
    # el=-47. Test the geometry, not the parking slot.)
    rg = propagate(geo, jd0)
    sublon = (math.degrees(math.atan2(rg[1], rg[0]))
              - math.degrees(gmst_rad(jd0))) % 360
    if sublon > 180:
        sublon -= 360
    el, _, _ = eci_to_sez(rg, math.radians(0.0), math.radians(sublon), jd0)
    check('GEO visible from beneath subpoint', el > 60, f'el={el:.1f} deg')

    mine = math.degrees(gmst_rad(jd0)) % 360
    try:
        from astropy.time import Time
        ref = float(Time('2026-01-01T00:00:00').sidereal_time(
            'mean', 'greenwich').deg)
        d = abs(mine - ref)
        d = min(d, 360 - d)
        check('GMST vs astropy', d < 0.01, f'd={d:.4f} deg')
    except ImportError:
        print('  [skip] GMST cross-check: astropy missing')
    except Exception as e:
        check('GMST vs astropy', False, str(e)[:80])

    ps = passes_for(iss, 'ISS', 38.4331, -79.8398, jd0, 86400, 10.0)
    localmax = True
    for p in ps:
        if not (p['rise_s'] <= p['tca_s'] <= p['set_s']):
            localmax = False
    check('rise/set brackets TCA (structural)', len(ps) > 0 and localmax,
          f'{len(ps)} passes/24h')

    print('[prove] ' + ('PASS' if all(ok) else 'FAIL') + f' {sum(ok)}/{len(ok)}')
    return all(ok)


if __name__ == '__main__':
    main()
