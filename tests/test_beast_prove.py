"""test_beast_prove.py — pytest wrapper around the full prove suite (slow).

Run: pytest tests/test_beast_prove.py -x -q   (or: python python/sy_prove_all.py)
Each prove is a separate test so failures localise to one detector.
"""
import os, subprocess, sys

ROOT = os.path.join(os.path.dirname(__file__), '..')
PY = sys.executable
EXT = '.exe' if os.name == 'nt' else ''

CASES = [
    (['c/comb_scan', '--selftest'], 'comb_scan'),
    (['python/structure_pass.py', '--selftest'], 'structure_pass'),
    (['python/build_evidence.py', '--selftest'], 'build_evidence'),
    (['python/veto_prove.py'], 'veto'),
    (['python/pulsar_fold.py', '--prove'], 'fold'),
    (['python/transient_dm.py', '--prove'], 'dm'),
    (['python/raster_hunt.py', '--prove'], 'raster'),
    (['python/burst_zoom.py', '--prove'], 'burst'),
]


def _run(cmd):
    if cmd[0].startswith('c/'):
        cmd = [os.path.join(ROOT, cmd[0] + EXT)] + cmd[1:]
    else:
        cmd = [PY, os.path.join(ROOT, cmd[0])] + cmd[1:]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=ROOT)
    return r.returncode, (r.stdout + r.stderr)[-1500:]


def test_comb_scan():
    rc, tail = _run(['c/comb_scan', '--selftest'])
    assert rc == 0, tail


def test_structure_pass():
    rc, tail = _run(['python/structure_pass.py', '--selftest'])
    assert rc == 0, tail


def test_build_evidence():
    rc, tail = _run(['python/build_evidence.py', '--selftest'])
    assert rc == 0, tail


def test_veto():
    rc, tail = _run(['python/veto_prove.py'])
    assert rc == 0, tail


def test_fold():
    rc, tail = _run(['python/pulsar_fold.py', '--prove'])
    assert rc == 0, tail


def test_dm():
    rc, tail = _run(['python/transient_dm.py', '--prove'])
    assert rc == 0, tail


def test_raster():
    rc, tail = _run(['python/raster_hunt.py', '--prove'])
    assert rc == 0, tail


def test_burst():
    rc, tail = _run(['python/burst_zoom.py', '--prove'])
    assert rc == 0, tail
