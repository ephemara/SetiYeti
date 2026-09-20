"""run_smt2.py — check every z3/smt2/*.smt2 lib via z3-solver (no binary needed).

Replays each file like a real SMT-LIB script: declarations accumulate,
(push)/(pop) scope the solver, and every (check-sat) must match the `; expect`
verdict on the preceding line. Any mismatch FAILS the suite.
Usage: python z3/run_smt2.py [--root .]
"""
import argparse, os, re, sys

import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import z3


def flush(solver, buf, decls, path):
    new = [l for l in buf if l.strip()]
    if not new:
        return True
    # Each parse_smt2_string call is a FRESH context: the chunk must re-carry
    # every declaration seen so far (re-declaring in one string would error,
    # so decls are stored once and prepended; only new asserts are added).
    src = '\n'.join(decls + new)
    if not src.strip():
        return True
    try:
        vec = z3.parse_smt2_string(src)
    except Exception as e:
        print(f'    [ERROR] parse in {os.path.basename(path)}: {str(e)[:160]}')
        return False
    try:
        solver.add(vec)
    except Exception as e:
        print(f'    [ERROR] add in {os.path.basename(path)}: {str(e)[:160]}')
        return False
    return True


def iter_forms(path):
    """Yield (kind, text) with multi-line s-exprs joined by paren depth.
    kind: 'cmd' (push/pop/check-sat/set-logic), 'comment', 'decl', 'assert'."""
    buf, depth = [], 0
    def flush_form():
        txt = ' '.join(buf).strip()
        if not txt:
            return None
        if re.match(r'\(push\)|\(pop\)|\(check-sat\)|\(set-logic', txt):
            return ('cmd', txt)
        if re.match(r'\((declare-|define-)', txt):
            return ('decl', txt)
        return ('assert', txt)
    for raw in open(path, encoding='utf-8').read().splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith(';'):
            m = re.match(r';\s*expect\s+(SAT|UNSAT)\b', s)
            if m:
                f = flush_form()
                buf, depth = [], 0
                if f is not None and f[0] != 'comment':
                    yield f
                yield ('expect', m.group(1))
            continue
        buf.append(s)
        depth += s.count('(') - s.count(')')
        if depth <= 0:
            depth = 0
            f = flush_form()
            buf = []
            if f is not None:
                yield f
    if buf:
        f = flush_form()
        if f is not None:
            yield f
def check_file(path):
    solver = z3.Solver()
    decls, buf, ok, n, want = [], [], True, 0, None
    for kind, txt in iter_forms(path):
        if kind == 'expect':
            want = txt
        elif kind == 'decl':
            decls.append(txt)  # carried into every later parse
        elif kind == 'assert':
            buf.append(txt)
        elif kind == 'cmd':
            if txt.startswith('(push)'):
                if not flush(solver, buf, decls, path):
                    ok = False
                buf = []
                solver.push()
            elif txt.startswith('(pop)'):
                if not flush(solver, buf, decls, path):
                    ok = False
                buf = []
                solver.pop()
            elif txt.startswith('(check-sat)'):
                if not flush(solver, buf, decls, path):
                    ok = False
                buf = []
                got = solver.check()
                n += 1
                mark = 'PASS' if (want is not None and got == (
                    z3.sat if want == 'SAT' else z3.unsat)) else 'FAIL'
                if mark == 'FAIL':
                    ok = False
                print(f'    [{mark}] check #{n}: expect {want}, got {got}')
            # (set-logic ignored: solver logic fixed by API; kept for binary compat)
    if buf:
        flush(solver, buf, decls, path)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.getcwd())
    a = ap.parse_args()
    d = os.path.join(a.root, 'z3', 'smt2')
    files = sorted(f for f in os.listdir(d) if f.endswith('.smt2'))
    allok = True
    for f in files:
        print(f'== {f} ==')
        check_file._exp = None
        if not check_file(os.path.join(d, f)):
            allok = False
    print('SMT2 LIBS: ' + ('ALL PASS' if allok else 'FAILURES PRESENT'))
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
