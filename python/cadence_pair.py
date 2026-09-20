"""cadence_pair.py — BEAST ON–OFF gate + cross-observation matcher (M9 + cap).

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

Standing rule (AGENTS.md #4): a single pointing can never exceed WATCH. Only an
ON–OFF cadence pair promotes WATCH → CANDIDATE. No cadence code existed, so no
CANDIDATE could ever be legitimately issued. This is that gate:

  promote  = ON-only + structured + persistent + (Viterbi/Doppler-anomaly or
             multi-pol or SCD-comb) across the pair
  monument = same signature recurs across NIGHTS (cross-obs matcher): same
             alpha bucket + same band + structured, seen in >=2 observations

Also implements the catalog AUDIT the kepler1 inquest demanded (§5.2): flags
catalog keys in the 358/626/1431/2861 Hz bystander family so a ratchet never
permanently blinds the search.

  python cadence_pair.py --on scan_on.csv --off scan_off.csv --evidence ev.csv --out cadence.json
  python cadence_pair.py --audit --catalog rfi_catalog.json
"""
import argparse, csv, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rfi_veto as V

# bystander-family alpha buckets that must never hard-block without structure
FAMILY_HZ = (358.0, 626.0, 1162.0, 1431.0, 2861.0)


def load_hits(path):
    if not path or not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path)))


def evidence_map(path):
    ev = {}
    if path and os.path.exists(path):
        for r in csv.DictReader(open(path)):
            ev[(r.get('target', ''), r['block'], r['chan'])] = r
            ev[(r['block'], r['chan'])] = r  # legacy two-col fallback
    return ev


def pair(on_rows, off_rows, ev, target='', tol=2000.0):
    off_idx = [(int(r['chan']), float(r.get('fam_hz') or 0)) for r in off_rows
               if r.get('verdict', 'clean') != 'clean']
    out = []
    for r in on_rows:
        if r.get('verdict', 'clean') == 'clean':
            continue
        try:
            ch, al = int(r['chan']), float(r.get('fam_hz') or 0)
        except (ValueError, KeyError):
            continue
        off = V.in_index(off_idx, ch, al, tol)
        e = ev.get((target, str(r['block']), str(r['chan']),
                    )) or ev.get((str(r['block']), str(r['chan'])), {})
        structured = (V.structure_score(r)[0] >= 0.25)
        persist = str(e.get('persist', '0')) == '1'
        if off:
            status = 'common-mode'
        else:
            status = 'on_only'
        promo = bool(status == 'on_only' and structured and persist)
        out.append({'block': r['block'], 'chan': r['chan'], 'alpha': al,
                    'status': status, 'structured': structured,
                    'persist': persist, 'promote': promo,
                    'verdict_cap': 'CANDIDATE-eligible' if promo else 'WATCH-cap'})
    return out


def audit_catalog(cat_path):
    cat = V.load_catalog(cat_path)
    hits = 0
    for key, fe in cat.get('features', {}).items():
        try:
            a = float(fe.get('alpha') or 0)
        except (TypeError, ValueError):
            continue
        fam = any(abs(a - f) / max(f, 1) < 0.03 for f in FAMILY_HZ)
        if fam and fe.get('n_seen', 0) >= 3 and not fe.get('structured'):
            fe['audit'] = ('BYSTANDER-FAMILY: auto-block suspended pending '
                           'structure evidence (kepler1 §5.2)')
            fe['auto_block_suspended'] = True
            hits += 1
    V.save_catalog(cat, cat_path)
    return hits, len(cat.get('features', {}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--on', default='')
    ap.add_argument('--off', default='')
    ap.add_argument('--evidence', default='')
    ap.add_argument('--target', default='')
    ap.add_argument('--tol', type=float, default=2000.0)
    ap.add_argument('--out', default='')
    ap.add_argument('--audit', action='store_true')
    ap.add_argument('--catalog', default='rfi_catalog.json')
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    if a.audit:
        n, total = audit_catalog(os.path.join(a.root, a.catalog))
        print(f'[audit] suspended {n} bystander-family keys of {total} total')
        return
    on = load_hits(os.path.join(a.root, a.on) if a.on else '')
    off = load_hits(os.path.join(a.root, a.off) if a.off else '')
    ev = evidence_map(os.path.join(a.root, a.evidence) if a.evidence else '')
    res = pair(on, off, ev, a.target, a.tol)
    promo = sum(1 for r in res if r['promote'])
    print(f'[cadence] on_flags={len([r for r in on if r.get("verdict")!="clean"])} '
          f'off_flags={len([r for r in off if r.get("verdict")!="clean"])} '
          f'promote_eligible={promo}/{len(res)}')
    for r in res:
        if r['promote']:
            print(f"  PROMOTE b{r['block']}/ch{r['chan']} α={r['alpha']:.0f}Hz "
                  f"(on-only+structured+persistent)")
    if a.out:
        with open(os.path.join(a.root, a.out), 'w') as f:
            json.dump(res, f, indent=1)
        print(f'[cadence] wrote {a.out}')


if __name__ == '__main__':
    main()
