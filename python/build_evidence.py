"""build_evidence.py - M1 evidence producer: persistence + multichan flags.

WHY THIS EXISTS: rfi_veto.py scores persistence (signal present across the
span, not a one-block flicker) and multichan coincidence (common-mode across
channels/pols) - but longhaul never passed --evidence, so every flag ate
+0.30 "transient" +0.15 "single-channel" by default and the veto graded
blind. This tool derives both from the scan CSVs themselves:

  persist    chan flagged (FAM-HIT/SPECTRAL-LINE) in >= --persist-min blocks
             spanning >= half the file  -> the mark of continuous traffic
             (Objective 1, jackpot item 3)
  multichan  1 iff ANY of:
             (a) >= --multichan-min flagged chans in the same block (any alpha)
             (b) same alpha (+-180 Hz, one FAM bin pair) in >= 2 chans, same block
             (c) same (block, chan) flagged in >= 2 polarizations
             (cross-pol files must all be passed via repeated --scan)

Output: evidence.csv with a TARGET column (veto keys evidence by
(target, block, chan); legacy two-column keys still accepted as fallback).

Usage:
  python build_evidence.py --scan runs/longhaul_kepler/scan_on_p0.csv
      --scan runs/longhaul_kepler/scan_on_p1.csv --target KEPLER160
      --out runs/longhaul_kepler/evidence.csv
  python build_evidence.py --selftest
"""
import argparse
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seti_common as SC  # noqa: E402  (manifest writer)

FLAG_VERDICTS = ('FAM-HIT', 'SPECTRAL-LINE')
ALPHA_TOL = 180.0           # Hz: two FAM bins (SEG=32768 grid is 89.4 Hz)


def is_flag(r):
    v = str(r.get('verdict', ''))
    return v.startswith(FLAG_VERDICTS)


def build(rows_by_file, target, persist_min=4, multichan_min=3):
    """rows_by_file: list of (pol, rows). Returns {(target,block,chan): row}."""
    # index flags per file
    flags = []              # (pol, block:int, chan:int, alpha:float)
    blocks_seen = set()
    for pol, rows in rows_by_file:
        for r in rows:
            try:
                b = int(r['block'])
            except (KeyError, ValueError):
                continue
            blocks_seen.add(b)
            if not is_flag(r):
                continue
            try:
                flags.append((str(pol), b, int(r['chan']),
                              float(r.get('fam_hz') or 0)))
            except (KeyError, ValueError):
                continue
    nblocks = (max(blocks_seen) - min(blocks_seen) + 1) if blocks_seen else 0

    # persist: flagged blocks per chan (any file/pol)
    chan_blocks = {}
    for _, b, ch, _ in flags:
        chan_blocks.setdefault(ch, set()).add(b)
    persist_ch = set()
    for ch, bs in chan_blocks.items():
        if len(bs) >= persist_min and (max(bs) - min(bs) + 1) >= max(nblocks // 2, 1):
            persist_ch.add(ch)

    ev = {}
    # per (block, chan): multichan (a) count, (b) alpha coincidence, (c) pol coincidence
    by_block = {}
    by_blockchan = {}
    for pol, b, ch, a in flags:
        by_block.setdefault(b, []).append((ch, a))
        by_blockchan.setdefault((b, ch), set()).add(pol)
    for (b, ch), pols in by_blockchan.items():
        multi = False
        mates = by_block.get(b, [])
        if len(mates) >= multichan_min:
            multi = True
        if not multi:
            for ch2, a2 in mates:
                if ch2 == ch:
                    continue
                for _, _, chx, ax in [f for f in flags if f[1] == b and f[2] == ch]:
                    if abs(a2 - ax) <= ALPHA_TOL:
                        multi = True
                        break
                if multi:
                    break
        if len(pols) >= 2:
            multi = True
        ev[(target, str(b), str(ch))] = {
            'target': target, 'block': str(b), 'chan': str(ch),
            'persist': '1' if ch in persist_ch else '0',
            'multichan': '1' if multi else '0',
        }
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', action='append', default=[],
                    help='scan CSV (repeatable; may be a glob)')
    ap.add_argument('--target', default='')
    ap.add_argument('--out', default='evidence.csv')
    ap.add_argument('--persist-min', type=int, default=4)
    ap.add_argument('--multichan-min', type=int, default=3)
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)

    files = []
    for pat in a.scan:
        files.extend(sorted(glob.glob(os.path.join(a.root, pat))
                            if not os.path.isabs(pat) else glob.glob(pat)))
    if not files:
        sys.exit('no scan files matched')
    rows_by_file = []
    for f in files:
        with open(f, newline='') as fh:
            rows = list(csv.DictReader(fh))
        pol = rows[0].get('pol', '0') if rows else '0'
        rows_by_file.append((pol, rows))
    ev = build(rows_by_file, a.target, a.persist_min, a.multichan_min)
    with open(os.path.join(a.root, a.out), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['target', 'block', 'chan',
                                           'persist', 'multichan'])
        w.writeheader()
        for k in sorted(ev):
            w.writerow(ev[k])
    SC.write_manifest(os.path.join(a.root, a.out), {
        'tool': 'build_evidence.py', 'scans': files, 'target': a.target,
        'persist_min': a.persist_min, 'multichan_min': a.multichan_min,
        'evidence_rows': len(ev)})
    print(f'[evidence] {len(ev)} rows -> {a.out}')


def selftest():
    """Synthetic scans: persistent chan, multi-chan block, cross-pol pair."""
    def row(b, ch, pol='0', v='FAM-HIT', a='358'):
        return {'block': str(b), 'chan': str(ch), 'pol': pol,
                'spec_ratio': '2.0', 'spec_bin': '1', 'fam_best': '5.0',
                'fam_hz': a, 'fam_tag': 'Y4', 'vm_sign': '0.00/noise-like',
                'vm_diff': '0.00/noise-like', 'spikes': '0', 'rms': '10.0',
                'verdict': v}
    rows0, rows1 = [], []
    for b in range(10):                       # chan 52 persistent, alpha 358
        rows0.append(row(b, 52, '0', 'FAM-HIT', '358'))
    rows0.append(row(3, 10, '0', 'FAM-HIT', '99999'))   # loners
    rows0.append(row(3, 11, '0', 'FAM-HIT', '99999'))
    rows0.append(row(3, 12, '0', 'FAM-HIT', '99999'))   # block 3: 3 chans -> multi
    rows0.append(row(5, 27, '0', 'FAM-HIT', '27627'))   # single transient
    rows1.append(row(5, 27, '1', 'FAM-HIT', '27627'))   # same slice, other pol
    rows0.append(row(0, 60, '0', 'clean', '0'))
    ev = build([('0', rows0), ('1', rows1)], 'TEST')
    checks = [
        ('persist chan52', ev[('TEST', '3', '52')]['persist'] == '1'),
        ('transient chan27 not persist',
         ev[('TEST', '5', '27')]['persist'] == '0'),
        ('multichan block3', ev[('TEST', '3', '10')]['multichan'] == '1'),
        ('cross-pol b5/ch27 multi',
         ev[('TEST', '5', '27')]['multichan'] == '1'),
        ('loner b3/ch52 single-chan... (block3 is multi, so 1)',
         ev[('TEST', '3', '52')]['multichan'] == '1'),
    ]
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print('[selftest] ' + ('ALL PASS' if ok else 'FAILURES PRESENT'))
    return ok


if __name__ == '__main__':
    main()
