"""sy_prove_all.py — BEAST full testing framework entry point.

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

Runs every detector prove + selftest in dependency order and reports a single
receipt table. This is the enterprise gate: no threshold ships without
calibration, no module ships without firing on target AND staying quiet on
matched noise (AGENTS.md rule 1).

  python sy_prove_all.py --root .        # full suite (slow: jerk/latent)
  python sy_prove_all.py --quick         # fast subset (<2 min)
"""
import argparse, os, subprocess, sys, time

PY = sys.executable
C_PROVES = [
    (['c/comb_scan', '--selftest'], 'comb_scan comb+nongauss'),
    (['c/xeno_scan', '--selftest'], 'xeno_scan micro+exotic'),
    (['c/xvm_sandbox', '--selftest'], 'xvm_sandbox 6-machine'),
    (['c/jerk_track', '--selftest'], 'jerk_track Viterbi drift+jerk'),
    (['c/fold_dm', '--selftest'], 'fold_dm pulsar+DM shots'),
    (['c/scd_dechirp', '--selftest'], 'scd_dechirp plane+dechirp'),
]
PY_PROVES = [
    (['python/structure_pass.py', '--selftest'], 'structure_pass comb rule'),
    (['python/build_evidence.py', '--selftest'], 'build_evidence persist/multi'),
    (['python/veto_prove.py'], 'veto M1 bystander legs'),
    (['python/frame_hunt.py', '--prove'], 'frame_hunt M2 rhythm'),
    (['python/pulsar_fold.py', '--prove'], 'pulsar_fold periodicity'),
    (['python/transient_dm.py', '--prove'], 'transient_dm shots'),
    (['python/drift_hunt.py', '--prove'], 'drift_hunt de-Doppler'),
    (['python/raster_hunt.py', '--prove'], 'raster_hunt payload framing'),
    (['python/scint_pol.py', '--prove'], 'scint_pol ISM+pol'),
    (['python/exotic_pass.py', '--prove'], 'exotic_pass bizarre-physics'),
    (['python/xeno_pass.py', '--selftest'], 'xeno_pass grade ladder'),
    (['z3/verify_xeno.py'], 'verify_xeno grade tie'),
    (['z3/verify_c_jerk.py'], 'verify_c_jerk Viterbi tie'),
    (['z3/verify_c_fold.py'], 'verify_c_fold pulsar/DM tie'),
    (['z3/verify_c_scd.py'], 'verify_c_scd plane tie'),
    (['z3/run_smt2.py'], 'smt2 spec libs'),
    (['z3/run_cbmc.py'], 'cbmc proof gate'),
    (['python/corpus.py', '--selftest'], 'corpus invariants'),
    (['z3/verify_corpus.py'], 'verify_corpus live-DB tie'),
    (['python/univ_ingest.py', '--prove'], 'univ_ingest round-trips'),
    (['python/satpass.py', '--prove'], 'satpass conjunction'),
    (['z3/verify_ingest.py'], 'verify_ingest dispatch tie'),
    (['python/burst_zoom.py', '--prove'], 'burst_zoom morphology'),
    (['python/dsss_prove.py'], 'dsss spread spectrum'),
    (['python/earth_mirror.py'], 'earth_mirror Earth-at-40ly ground truth'),
    (['python/scd_frf.py', '--prove'], 'scd full plane + dechirp'),
    (['python/jerk_scan.py', '--prove'], 'jerk Viterbi drift+jerk'),
    (['python/latent_pca.py', '--prove'], 'latent PCA triage'),
]
QUICK_SKIP = {'jerk_scan.py', 'latent_pca.py', 'scd_frf.py', 'dsss_prove.py', 'frame_hunt.py'}


def run(cmd, root, timeout=900):
    ext = '.exe' if os.name == 'nt' else ''
    if cmd[0].startswith('c/'):
        cmd = [os.path.join(root, cmd[0] + ext)] + cmd[1:]
    else:
        cmd = [PY, os.path.join(root, cmd[0])] + cmd[1:]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=root)
        tail = (r.stdout.strip().splitlines() or ['(no output)'])[-3:]
        ok = r.returncode == 0
        return ok, time.time() - t0, ' | '.join(tail)[-220:]
    except subprocess.TimeoutExpired:
        return False, timeout, 'TIMEOUT'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()
    rows = []
    suite = list(C_PROVES) + [p for p in PY_PROVES
                              if not (a.quick and any(s in p[0][0] for s in QUICK_SKIP))]
    print(f'=== BEAST prove suite ({len(suite)} stages, quick={a.quick}) ===')
    for cmd, name in suite:
        ok, dt, tail = run(cmd, a.root)
        rows.append((name, ok, dt))
        print(f"[{'PASS' if ok else 'FAIL'}] {name:38s} {dt:6.1f}s  {tail}", flush=True)
    n_ok = sum(1 for _, ok, _ in rows if ok)
    print(f'\n=== {n_ok}/{len(rows)} proves passed ===')
    print('ALL PROVES PASSED' if n_ok == len(rows) else 'FAILURES PRESENT — do not trust thresholds')
    return 0 if n_ok == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
