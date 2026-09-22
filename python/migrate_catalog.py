#!/usr/bin/env python
"""migrate_catalog.py - v1 -> v2 catalog rewrite (the ratchet repair).

v1 pathologies fixed here (see FULL_REPORT/FIX doc for the full audit):
  * %.3g buckets smashed 6.7 kHz-apart lines into one key (1.44e+06 trio)
  * target+band-prior key prefixes fragmented one oscillator into many
    'classes' (TRAPPIST:.. vs TRAPPIST1:..) and blinded cross-target matching
  * 5,492 null/zero-alpha rows (missing fam_hz filed as alpha 0)
  * n_seen counted slices AND reprocessings (burst filed n=8 across re-runs)

v2: keys SIG:int-MHz:int-Hz (target-agnostic, exact) + documented tolerance
matcher; recurrence counts independent runs (grandfathered one step below the
bar: n_runs=2 if old n_seen>=3 else 1/0 - learned knowledge is kept but must
re-prove once under the fixed counting); structured entries seed the analyst
review queue and can never auto-block.

Default is REHEARSAL (prints the rewrite plan, touches nothing).
  python migrate_catalog.py --catalog rfi_catalog.json
  python migrate_catalog.py --catalog rfi_catalog.json --apply
"""
import argparse, copy, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rfi_veto as V

BARE = re.compile(r"^([A-Z0-9-]+):([-\d.eE+]+)(Hz)?$")
TARG = re.compile(r'^([^:]+):([^:]+):(terr|ra|sat|radar|ism|unk)$')
SIGP = re.compile(r'^([^:]+):([-\d.eE+]+)Hz$')


def parse_old(key, val):
    """-> (tag, alpha_exact, freq, targets[]) or (None, reason)."""
    sig = val.get('sig', '')
    m = SIGP.match(str(sig))
    tag = m.group(1) if m else None
    try:
        alpha = float(val.get('alpha'))
    except (TypeError, ValueError):
        alpha = None
    freq = val.get('freq_mhz')
    targets = []
    mt = TARG.match(key)
    mb = BARE.match(key)
    if mt:
        targets = [mt.group(1)]
        if tag is None:
            return None, 'unparseable sig'
    elif mb:
        if tag is None:
            tag = mb.group(1)
        targets = []
    else:
        return None, 'unparseable key'
    if tag is None:
        return None, 'unparseable sig'
    if alpha is None or alpha <= 0:
        return None, 'null-alpha'
    return (tag, alpha, freq, targets), ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catalog', default='rfi_catalog.json')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    cat = json.load(open(a.catalog))
    feats = cat.get('features', {})
    new, health, dropped = {}, [], []
    merges, splits_from = {}, {}
    for key, val in feats.items():
        parsed, why = parse_old(key, val if isinstance(val, dict) else {})
        if parsed is None:
            if why == 'null-alpha':
                health.append(key)
            else:
                dropped.append((key, why))
            continue
        tag, alpha, freq, targets = parsed
        nkey = V.catalog_key(tag, freq, alpha)
        d = new.setdefault(nkey, {
            'sig': f"{tag}:{alpha:.0f}Hz", 'alpha': alpha, 'freq_mhz': freq,
            'freq_span': [freq, freq], 'n_seen': 0, 'n_runs': 0,
            'seen_in': [], 'targets': [], 'structured': False,
            'disp': 'WATCH', 'old_keys': []})
        try:
            n = int(val.get('n_seen', 0))
        except (TypeError, ValueError):
            n = 0
        d['n_seen'] += n
        for t in targets:
            if t not in d['targets']:
                d['targets'].append(t)
        if len(d['old_keys']) < 10:
            d['old_keys'].append(key)
        merges.setdefault(nkey, []).append(key)
        try:
            fq = float(freq)
            lo, hi = d['freq_span']
            d['freq_span'] = [min(lo, fq) if lo is not None else fq,
                              max(hi, fq) if hi is not None else fq]
        except (TypeError, ValueError):
            pass
        d['structured'] = bool(d['structured']) or bool(val.get('structured', False))
        if val.get('disp', '').startswith('BLOCK'):
            d['disp'] = 'BLOCK:earth-likely'
    for nkey, d in new.items():
        d['n_runs'] = 2 if d['n_seen'] >= 3 else (1 if d['n_seen'] >= 1 else 0)
    for nkey, olds in merges.items():
        if len(olds) > 1:
            splits_from[nkey] = olds
    review = [k for k, d in new.items() if d['structured']]

    print(f'[migrate] features {len(feats)} -> {len(new)} keys '
          f'({len(health)} null-alpha quarantined, {len(dropped)} unparseable dropped)')
    print(f'[migrate] merges (fragmentation healed): {len(splits_from)}')
    for nkey, olds in sorted(splits_from.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f'    {nkey} <- {olds}')
    trio = [k for k in new if '144' in k.split(':')[1] or '1437' in str(new[k]['alpha'])[:4]]
    print(f'[migrate] 1.44 MHz trio now: {[k for k in new if abs(new[k]['alpha'] - 1437128) < 20000]}')
    print(f'[migrate] review seeds (structured, never auto-block): {len(review)}')
    for k in sorted(review)[:20]:
        print(f'    {k} n_seen={new[k]["n_seen"]} n_runs={new[k]["n_runs"]}')
    near = [k for k, d in new.items() if d['n_runs'] == 2 and not d['structured']]
    print(f'[migrate] grandfathered one step below hard-block (n_runs=2): {len(near)}')
    for k in sorted(near, key=lambda k: -new[k]['n_seen'])[:15]:
        print(f'    {k} n_seen={new[k]["n_seen"]} targets={new[k]["targets"]}')
    if dropped:
        print(f'[migrate] dropped sample: {dropped[:10]}')

    if not a.apply:
        print('[migrate] REHEARSAL - catalog untouched. Re-run with --apply.')
        return 0
    bak = a.catalog + f'.pre_v2.{time.strftime("%Y%m%d-%H%M%S")}.bak'
    with open(bak, 'w') as fh:
        json.dump(cat, fh, indent=1)
    out = {'version': V.CAT_VERSION,
           'migrated': {'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'in': len(feats), 'out': len(new),
                        'null_quarantined': len(health),
                        'dropped': len(dropped)},
           'features': new,
           'review': [{'key': k, 'sig': new[k]['sig'], 'alpha': new[k]['alpha'],
                       'freq_mhz': new[k]['freq_mhz'], 'target': '',
                       'run': 'migration-seed', 'S': 0.25, 'E': 0.0,
                       'why': 'grandfathered structured (pre-v2 auto-block review)'}
                      for k in sorted(review)],
           'runs': cat.get('runs', {}),
           'health': {'null_alpha_keys': len(health)}}
    V.save_catalog(out, a.catalog)
    print(f'[migrate] APPLIED. backup -> {bak}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
