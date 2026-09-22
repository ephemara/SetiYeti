"""verify_corpus.py - the smt2/corpus_invariants.smt2 theorems state the
INVARIANTS; this checks the LIVE database satisfies them (a spec the data
violates is decoration).

C1 duplicate-free: no (obs,block,chan,pol,kind) key repeats.
C2/C3 flag soundness: every flag joins a slice AND sits on a signal row
    (veto only scores FAM-HIT/SPECTRAL - a flag on clean/quarantine is a
    join bug, measured twice during construction).
C4 review soundness: every v_review row is grade>=I2 or WATCH/CANDIDATE.
C5 pinned joins: every flag's slice file is a scored hits file (struct/
    scan kind - flags must never resolve to xeno-only or wrong-file rows).
Plus idempotency: re-ingesting a veto log yields identical flag counts.
Usage: python z3/verify_corpus.py [--root .] [--db corpus/setiyeti.db]
"""
import argparse
import os
import sqlite3
import sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.getcwd(), 'python'))
import corpus as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    ap.add_argument('--db', default='corpus/setiyeti.db')
    a = ap.parse_args()
    db = os.path.join(a.root, a.db)
    if not os.path.exists(db):
        print(f'[skip] no corpus at {a.db} (build one: corpus.py --auto)')
        return 0
    cx = sqlite3.connect(db)
    ok = []

    def check(name, cond, detail=''):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")

    n = cx.execute('SELECT COUNT(*) FROM (SELECT obs_id, block, chan, pol,'
                   ' src_kind FROM slices GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1)'
                   ).fetchone()[0]
    check('C1 slice keys unique', n == 0, f'{n} duplicate keys')
    n = cx.execute('SELECT COUNT(*) FROM flags f LEFT JOIN slices s'
                   ' ON f.slice_id=s.slice_id WHERE s.slice_id IS NULL').fetchone()[0]
    check('C2 no orphan flags', n == 0, f'{n} orphans')
    rows = cx.execute("SELECT COUNT(*) FROM flags f JOIN slices s"
                      " ON f.slice_id=s.slice_id WHERE s.verdict NOT LIKE 'FAM-HIT%'"
                      " AND s.verdict NOT LIKE 'SPECTRAL%'").fetchone()[0]
    check('C3 flags sit on signal rows only', rows == 0, f'{rows} violations')
    rows = cx.execute("SELECT COUNT(*) FROM flags WHERE run_id LIKE '%.log'"
                      " AND (reasons IS NULL OR reasons='')").fetchone()[0]
    check('C7 veto-log flags carry reasons (the WHY)', rows == 0,
          f'{rows} reason-less')
    rows = cx.execute("""SELECT COUNT(*) FROM (
      SELECT s.grade, f.disposition FROM flags f
      JOIN slices s ON f.slice_id=s.slice_id) WHERE NOT
      (grade IN ('I2','I3','I4','I5') OR disposition IN ('WATCH','CANDIDATE'))"""
                      ).fetchone()[0]
    check('C4 review soundness (flagged rows reviewable)', rows == 0,
          f'{rows} violations')
    rows = cx.execute("""SELECT COUNT(*) FROM flags f JOIN slices s
      ON f.slice_id=s.slice_id JOIN observations o ON s.obs_id=o.obs_id
      WHERE s.src_kind NOT IN ('scan','struct')""").fetchone()[0]
    check('C5 flags resolve to scored files (scan/struct)', rows == 0,
          f'{rows} violations')
    # idempotency machinery: the (slice,run) UNIQUE contract is what makes
    # re-ingest replace instead of duplicate. Attempt a duplicate insert;
    # it MUST be rejected (true re-ingest stability is covered in-corpus by
    # corpus.py --selftest and the run-scoped wipe in ingest_veto_log).
    row = cx.execute('SELECT slice_id, disposition, run_id FROM flags'
                     ' LIMIT 1').fetchone()
    if row:
        try:
            cx.execute('INSERT INTO flags(slice_id,disposition,run_id,scored_at)'
                       ' VALUES(?,?,?,?)', (row[0], row[1], row[2], 'dup-test'))
            check('C6 duplicate flag insert rejected', False, 'no error raised!')
        except sqlite3.IntegrityError:
            cx.rollback()
            check('C6 duplicate flag insert rejected', True, 'UNIQUE enforced')
    else:
        print('  [skip] C6: no flags in corpus')
    ns = cx.execute('SELECT COUNT(*) FROM slices').fetchone()[0]
    nf = cx.execute('SELECT COUNT(*) FROM flags').fetchone()[0]
    print(f'[corpus] {ns} slices, {nf} flags under verification')
    print('VERIFY_CORPUS: ' + ('ALL PASS' if all(ok) else 'FAILURES PRESENT'))
    return 0 if all(ok) else 1


if __name__ == '__main__':
    sys.exit(main())
