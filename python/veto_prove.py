"""veto_prove.py - prove for M1 (bystander-model veto).

Per Objective 1 and AGENTS.md rule 1: a detector ships with a test that shows it
fires on the target class AND stays quiet on matched junk. For the veto, the
three legs are:

  NEGATIVE   real backend hum (common-mode, unstructured)      -> BLOCK
  NEGATIVE   M31-style transient radar blip                   -> BLOCK
  POSITIVE   ENGINEERED common-mode, present ON and OFF        -> WATCH/CANDIDATE
  POSITIVE   ON-only structured celestial candidate            -> CANDIDATE
  MONUMENT   recurring AND structured                          -> NOT auto-blocked
  GUARD      recurring AND unstructured                        -> hard BLOCK
  CATALOG v2 ratchet repair: integer-Hz target-agnostic keys + tolerance
  matcher; null-alpha never files; recurrence counts independent runs;
  engineered slices never auto-block (score or recurrence) -> WATCH+review.

If NEGATIVE legs pass and POSITIVE legs pass, the veto can tell
"the building humming" from "someone else's modem" - which the old
beacon-era veto could not do.

Usage: python veto_prove.py [--root .]
"""
import argparse, csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rfi_veto as V

FREQ, BW, NCHAN = 1407.71484375, -187.5, 64     # TRAPPIST blc04 L-band geometry


def make_row(block=0, chan=32, fam_hz=179.0, tag='Y2', vm='0.00/noise-like',
             spec_ratio='1.5', extra=None):
    r = {'block': str(block), 'chan': str(chan), 'pol': '0', 'spec_ratio': spec_ratio,
         'spec_bin': '1', 'fam_best': '5.0', 'fam_hz': str(fam_hz), 'fam_tag': tag,
         'vm_sign': vm, 'vm_diff': '0.00/noise-like', 'verdict': 'FAM-HIT'}
    if extra:
        r.update(extra)
    return r


def make_ctx(target='TEST', evidence=None, catalog=None, on=None, off=None):
    return {'chan_freq': V.make_chan_freq(FREQ, BW, NCHAN),
            'evidence': evidence or {},
            'catalog': catalog or {'features': {}},
            'target': target,
            'on_idx': on, 'off_idx': off}


def verdict_of(row, ctx):
    E, S, net, disp, reasons, key = V.score_slice(row, ctx)
    return E, S, net, disp, reasons


def plant(features, tag, freq, alpha, n_runs, structured, prefix='r'):
    """Seed a v2 catalog entry with n_runs independent sightings."""
    key = V.catalog_key(tag, freq, alpha)
    features[key] = {'sig': f'{tag}:{alpha:.0f}Hz', 'alpha': alpha,
                     'freq_mhz': freq, 'n_seen': n_runs, 'n_runs': n_runs,
                     'seen_in': [f'{prefix}{i}' for i in range(n_runs)],
                     'targets': ['T'], 'structured': structured,
                     'disp': 'BLOCK:earth-likely'}
    return key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    a = ap.parse_args()

    results = []

    def check(name, got, want, detail=''):
        ok = got in want if isinstance(want, (tuple, list, set)) else got == want
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         got={got}  want={want}  {detail}")

    print("=== synthetic legs (L-band 1407.7 MHz geometry) ===\n")

    # ---- NEGATIVE 1: real backend hum -------------------------------------
    # common-mode across channels, persistent, unstructured, 179 Hz
    ev = {('0', '32'): {'persist': '1', 'multichan': '1'}}
    ctx = make_ctx(evidence=ev, on=[(32, 179.0)], off=[(32, 179.0)])
    E, S, net, disp, _ = verdict_of(make_row(fam_hz=179.0), ctx)
    check('NEG-1 backend hum (common-mode, unstructured)', disp, 'BLOCK:earth-likely',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')

    # ---- NEGATIVE 2: M31-style transient radar blip -----------------------
    ev = {('30', '56'): {'persist': '0', 'multichan': '0'}}
    ctx = make_ctx(target='M31', evidence=ev,
                   on=[(56, 1434624.0)], off=[])
    E, S, net, disp, _ = verdict_of(make_row(block=30, chan=56, fam_hz=1434624.0), ctx)
    check('NEG-2 transient radar blip', disp, 'BLOCK:earth-likely',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')

    # ---- NEGATIVE 3: unstructured common-mode tone (not the hum) ----------
    # guards against "any common-mode at all now passes"
    ev = {('0', '10'): {'persist': '1', 'multichan': '1'}}
    ctx = make_ctx(target='TEST2', evidence=ev, on=[(10, 48213.0)], off=[(10, 48213.0)])
    E, S, net, disp, _ = verdict_of(make_row(chan=10, fam_hz=48213.0), ctx)
    check('NEG-3 unstructured common-mode (guard)', disp, 'BLOCK:earth-likely',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')

    # ---- POSITIVE 1: ENGINEERED common-mode, present ON and OFF ----------
    # the target class: a third-party link crossing our line of sight
    ev = {('0', '40'): {'persist': '1', 'multichan': '1'}}
    ctx = make_ctx(target='LINK', evidence=ev, on=[(40, 900000.0)], off=[(40, 900000.0)])
    r = make_row(chan=40, fam_hz=900000.0, extra={'comb': '1', 'frame': '1'})
    E, S, net, disp, reasons = verdict_of(r, ctx)
    check('POS-1 engineered common-mode (bystander target class)', disp,
          ('WATCH', 'CANDIDATE'), f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    assert any('not from target' in x for x in reasons), 'missing bystander reason'

    # ---- POSITIVE 2: ON-only structured celestial candidate --------------
    ev = {('0', '17'): {'persist': '1', 'multichan': '0'}}
    ctx = make_ctx(target='CEL', evidence=ev, on=[(17, 1782.4)], off=[])
    r = make_row(chan=17, fam_hz=1782.4, extra={'comb': '1', 'nongauss': '1'})
    E, S, net, disp, _ = verdict_of(r, ctx)
    check('POS-2 ON-only structured celestial', disp, 'CANDIDATE',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')

    # ---- MONUMENT: recurring AND structured must NOT be auto-blocked -----
    _cf = V.make_chan_freq(FREQ, BW, NCHAN)
    cat = {'features': {}}
    plant(cat['features'], 'Y2', _cf(40), 900.0, n_runs=12, structured=True)
    ev = {('0', '40'): {'persist': '1', 'multichan': '1'}}
    ctx = make_ctx(target='MON', evidence=ev, catalog=cat,
                   on=[(40, 900.0)], off=[(40, 900.0)])
    r = make_row(chan=40, fam_hz=900.0, extra={'comb': '1', 'frame': '1'})
    E, S, net, disp, reasons = verdict_of(r, ctx)
    check('MON recurring + structured (monument protection)', disp,
          ('WATCH', 'CANDIDATE'), f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    check('MON recurrence reason present',
          any('monument' in x for x in reasons), True)

    # ---- THICKET: dense forest + comb + common-mode -> BLOCK -------------
    # the fence for comb-by-density (TRAPPIST OFF b1/ch57 archetype): a real
    # baud comb (lines10 ~ 9) with engineering still passes; a thicket
    # (lines10 60+) with a spurious comb does not, even when structured.
    ev = {('0', '57'): {'persist': '0', 'multichan': '1'}}
    ctx = make_ctx(target='THICK', evidence=ev, on=[(57, 626.0)], off=[(57, 626.0)])
    r = make_row(chan=57, fam_hz=626.0,
                 extra={'comb': '1', 'nongauss': '1', 'lines10': '60'})
    E, S, net, disp, reasons = verdict_of(r, ctx)
    check('THICKET intermod forest + spurious comb blocks', disp,
          'BLOCK:earth-likely', f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    assert any('thicket' in x for x in reasons), 'missing thicket reason'

    # ---- THICKET GUARD: real comb (few lines) + eng still passes --------
    ev = {('0', '40'): {'persist': '1', 'multichan': '0'}}
    ctx = make_ctx(target='REALCOMB', evidence=ev, on=[(40, 900000.0)], off=[])
    r = make_row(chan=40, fam_hz=900000.0,
                 extra={'comb': '1', 'frame': '1', 'lines10': '9'})
    E, S, net, disp, _ = verdict_of(r, ctx)
    check('THICKET-GUARD real comb (9 lines) + eng still candidate', disp,
          ('WATCH', 'CANDIDATE'), f'E={E:.2f} S={S:.2f} net={net:+.2f}')

    # ---- GUARD: recurring AND unstructured still hard-blocks -------------
    cat = {'features': {}}
    plant(cat['features'], 'Y2', _cf(32), 179.0, n_runs=400, structured=False)
    ev = {('0', '32'): {'persist': '1', 'multichan': '1'}}
    ctx = make_ctx(target='HUM', evidence=ev, catalog=cat,
                   on=[(32, 179.0)], off=[(32, 179.0)])
    E, S, net, disp, _ = verdict_of(make_row(fam_hz=179.0), ctx)
    check('GUARD recurring + unstructured (hum) still blocks', disp,
          'BLOCK:earth-likely', f'E={E:.2f} S={S:.2f} net={net:+.2f}')

    # ---- CATALOG v2 legs (the ratchet repair) ---------------------------
    # C1: %.3g bucket collisions split three ways under integer-Hz keys
    keys = {V.catalog_key('Y4', 1500.0, a) for a in (1437128.0, 1439631.0, 1443923.0)}
    check('C1 bucket-collision trio splits under v2 keys', len(keys), 3)
    # C2: null/zero alpha never files (missing-data guard)
    cat2 = {'features': {}}
    for bad in ('', '0', '0.0', None):
        _k, _nr, filed = V.catalog_file(cat2, 'Y4', 1407.7, bad, 0.0, 'WATCH', 'T', 'run1')
        check(f'C2 null-alpha {bad!r} refused', filed, False)
    check('C2 catalog untouched by null rows', len(cat2['features']), 0)
    # C3: tolerance matcher reunites grid halves (625.85 <-> 626.0)
    cat3 = {'features': {}}
    kplant = plant(cat3['features'], 'Y4', _cf(52), 626.0, n_runs=1, structured=False)
    kfound, _prev = V.catalog_lookup(cat3['features'], 'Y4', _cf(52), 625.85)
    check('C3 tolerance match 625.85Hz <-> planted 626.0Hz', kfound, kplant)
    # C4: engineered + score-block-range verdict -> WATCH + review, never BLOCK
    cat4 = {'features': {}}
    ev = {('0', '40'): {'persist': '0', 'multichan': '0'}}
    ctx = make_ctx(target='C4', evidence=ev, catalog=cat4,
                   on=[(40, 900000.0)], off=[])
    r = make_row(chan=40, fam_hz=900000.0,
                 extra={'frame': '1', 'nongauss': '1', 'lines10': '60'})
    E, S, net, disp, reasons = verdict_of(r, ctx)
    check('C4 engineered high-net slice escapes score-BLOCK', disp, 'WATCH',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    check('C4 review reason present', any('review' in x for x in reasons), True)
    check('C4 analyst queue filed', len(cat4.get('review', [])), 1)
    # C5: structured flag is sticky across runs
    cat5 = {'features': {}}
    V.catalog_file(cat5, 'Y4', 1347.0, 626.0, 0.40, 'WATCH', 'T', 'run1')
    V.catalog_file(cat5, 'Y4', 1347.0, 626.0, 0.00, 'BLOCK:earth-likely', 'T', 'run2')
    only = next(iter(cat5['features'].values()))
    check('C5 structured flag sticky once set', only['structured'], True)
    check('C5 two runs counted once each', only['n_runs'], 2)
    # C6: two independent runs never hard-block (boundary below HARD_N_RUNS)
    cat6 = {'features': {}}
    plant(cat6['features'], 'Y2', _cf(25), 1782.0, n_runs=2, structured=False)
    ev = {('0', '25'): {'persist': '1', 'multichan': '0'}}
    ctx = make_ctx(target='C6', evidence=ev, catalog=cat6,
                   on=[(25, 1782.0)], off=[])
    E, S, net, disp, _ = verdict_of(make_row(chan=25, fam_hz=1782.0), ctx)
    check('C6 n_runs=2 never hard-blocks', disp.startswith('BLOCK'), False,
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    # C7: same raw data reprocessed counts once (run-id fingerprint)
    raw_probe = os.path.join(a.root, 'python', 'rfi_veto.py')
    id1 = V.make_run_id('out/a.csv', raw_probe, 'T')
    id2 = V.make_run_id('out/b.csv', raw_probe, 'T')
    check('C7 same raw -> same run-id across outdirs', id1, id2)
    cat7 = {'features': {}}
    V.catalog_file(cat7, 'Y4', 1347.0, 626.0, 0.0, 'BLOCK:earth-likely', 'T', id1)
    V.catalog_file(cat7, 'Y4', 1347.0, 626.0, 0.0, 'BLOCK:earth-likely', 'T', id2)
    check('C7 reprocessing does not inflate n_runs',
          next(iter(cat7['features'].values()))['n_runs'], 1)

    # ---- XENO-microstructure legs (the b76/ch44 completion) --------------
    # SK1: skflag + nongauss, high-net -> engineered -> escapes score-BLOCK
    cat8 = {'features': {}}
    ev = {('0', '40'): {'persist': '0', 'multichan': '0'}}
    ctx = make_ctx(target='SK1', evidence=ev, catalog=cat8,
                   on=[(40, 555555.0)], off=[])
    r = make_row(chan=40, fam_hz=555555.0,
                 extra={'x_skflag': '1', 'nongauss': '1', 'lines10': '60'})
    E, S, net, disp, reasons = verdict_of(r, ctx)
    check('SK1 xeno-skflag slice engineered, escapes score-BLOCK', disp, 'WATCH',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    check('SK1 review filed', len(cat8.get('review', [])), 1)
    # IM1: impulsivity alone (x_impuls, no sk/ladder/coh) changes NOTHING -
    # shots and discharges are not engineering (criteria doc). High-E row
    # carrying x_impuls=1 must still BLOCK with an empty review queue.
    cat9 = {'features': {}}
    ev = {('0', '57'): {'persist': '0', 'multichan': '0'}}
    ctx = make_ctx(target='IM1', evidence=ev, catalog=cat9,
                   on=[], off=[(57, 626.0)])
    r = make_row(chan=57, fam_hz=626.0,
                 extra={'x_impuls': '1', 'lines10': '90'})
    E, S, net, disp, _ = verdict_of(r, ctx)
    check('IM1 impuls-only high-E row still BLOCKs', disp, 'BLOCK:earth-likely',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    check('IM1 no review filed for impuls alone', len(cat9.get('review', [])), 0)

    # ---- Scintillation-medium legs (the analyst hold, wired in) ----------
    # SC1: the b76/ch44 construction (skflag+nongauss, COMMON, thicket,
    # persistent, ON-only) must WATCH, never CANDIDATE - the COMMON verdict
    # is what holds the I3 at WATCH inside the machine.
    catA = {'features': {}}
    ev = {('76', '44'): {'persist': '1', 'multichan': '0'}}
    ctx = make_ctx(target='SC1', evidence=ev, catalog=catA,
                   on=[(44, 625.85)], off=[])
    r = make_row(block=76, chan=44, fam_hz=625.85,
                 extra={'comb': '1', 'lines10': '103', 'nongauss': '1',
                        'x_skflag': '1', 'x_impuls': '1',
                        'scint_class': 'COMMON'})
    E, S, net, disp, _ = verdict_of(r, ctx)
    check('SC1 COMMON holds engineered slice at WATCH', disp, 'WATCH',
          f'E={E:.2f} S={S:.2f} net={net:+.2f}')
    # SC2: SCINT subtracts EARTH vs a COMMON twin (sky marker, documented).
    # Transient twins (persist 0) keep both sides off the E=0 floor so the
    # 0.30+0.20=0.50 documented gap reads exactly.
    ev2 = {('76', '44'): {'persist': '0', 'multichan': '0'}}
    catB = {'features': {}}
    ctxB = make_ctx(target='SC2', evidence=ev2, catalog=catB,
                    on=[(44, 625.85)], off=[])
    rC = make_row(block=76, chan=44, fam_hz=625.85,
                  extra={'comb': '1', 'lines10': '103', 'nongauss': '1',
                         'x_skflag': '1', 'scint_class': 'COMMON'})
    rD = make_row(block=76, chan=44, fam_hz=625.85,
                  extra={'comb': '1', 'lines10': '103', 'nongauss': '1',
                         'x_skflag': '1', 'scint_class': 'SCINT'})
    EC, _, _, _, _ = verdict_of(rC, ctxB)
    ED, _, _, _, _ = verdict_of(rD, ctxB)
    check('SC2 SCINT/COMMON gap is the documented 0.50', round(EC - ED, 2), 0.50,
          f'E_common={EC:.2f} E_scint={ED:.2f}')

    # ---- REAL DATA: the actual TRAPPIST 179 Hz hum ------------------------
    hits = os.path.join(a.root, 'runs', 'hits_trap_on.csv')
    offp = os.path.join(a.root, 'runs', 'hits_trap_off.csv')
    if os.path.exists(hits):
        rows = [r for r in csv.DictReader(open(hits))]
        on_idx = V.signature_index(hits)
        off_idx = V.signature_index(offp) if os.path.exists(offp) else None
        # derive multichan / persist from the corpus itself
        from collections import Counter
        perblock = Counter((r['block'], r['fam_hz']) for r in rows)
        perchan = Counter((r['chan'], r['fam_hz']) for r in rows)
        ev = {}
        for r in rows:
            ev[(r['block'], r['chan'])] = {
                'persist': '1' if perchan[(r['chan'], r['fam_hz'])] >= 3 else '0',
                'multichan': '1' if perblock[(r['block'], r['fam_hz'])] >= 8 else '0'}
        ctx = make_ctx(target='TRAPPIST', evidence=ev, on=on_idx, off=off_idx)
        disp_counts = Counter()
        for r in rows:
            _E, _S, _net, disp, _reasons, _key = V.score_slice(r, ctx)
            disp_counts[disp.split(':')[0]] += 1
        blocked = disp_counts.get('BLOCK', 0)
        total = sum(disp_counts.values())
        frac = blocked / total if total else 0
        check(f'REAL TRAPPIST hum: >=90% BLOCK ({blocked}/{total})', frac >= 0.90, True,
              dict(disp_counts))
    else:
        print('  [skip] real-data leg: runs/hits_trap_on.csv not present')

    print()
    n_ok = sum(1 for x in results if x)
    print(f"=== {n_ok}/{len(results)} checks passed ===")
    if n_ok != len(results):
        print('PROVE FAILED')
        return 1
    print('PROVE PASS: veto separates local hum from engineered common-mode')
    return 0


if __name__ == '__main__':
    sys.exit(main())
