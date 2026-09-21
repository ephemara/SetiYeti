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
    _ck = f"MON:{V.alpha_bucket(900.0)}:{V.alloc(_cf(40))[1]}"
    cat = {'features': {_ck: {'sig': 'Y2:900Hz', 'alpha': 900.0,
                              'n_seen': 12, 'structured': True}}}
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
    _ck = f"HUM:{V.alpha_bucket(179.0)}:{V.alloc(_cf(32))[1]}"
    cat = {'features': {_ck: {'sig': 'Y2:179Hz', 'alpha': 179.0,
                              'n_seen': 400, 'structured': False}}}
    ev = {('0', '32'): {'persist': '1', 'multichan': '1'}}
    ctx = make_ctx(target='HUM', evidence=ev, catalog=cat,
                   on=[(32, 179.0)], off=[(32, 179.0)])
    E, S, net, disp, _ = verdict_of(make_row(fam_hz=179.0), ctx)
    check('GUARD recurring + unstructured (hum) still blocks', disp,
          'BLOCK:earth-likely', f'E={E:.2f} S={S:.2f} net={net:+.2f}')

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
