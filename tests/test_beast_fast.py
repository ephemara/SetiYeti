"""test_beast_fast.py — pytest: fast deterministic unit tests (<2 min, no data)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
import numpy as np


def test_comb_rule_fires_on_harmonics():
    import structure_pass as SP
    n, s, b0 = SP.comb_rule_on_bins({4: 30.0, 16: 25.0, 32: 20.0, 900: 40.0}, 16384)
    assert n >= 3 and b0 == 4


def test_comb_rule_quiet_on_single_tone():
    import structure_pass as SP
    n, _, _ = SP.comb_rule_on_bins({56: 120.0, 900: 40.0}, 16384)
    assert n == 0


def test_evidence_persist_and_multichan():
    import build_evidence as BE

    def row(b, ch, pol='0', v='FAM-HIT', a='358'):
        return {'block': str(b), 'chan': str(ch), 'pol': pol, 'verdict': v,
                'fam_hz': a, 'fam_best': '5.0', 'spec_ratio': '2.0'}
    rows0 = [row(b, 52) for b in range(10)]
    rows0 += [row(3, 10, a='99999'), row(3, 11, a='99999'), row(3, 12, a='99999')]
    ev = BE.build([('0', rows0)], 'TEST')
    assert ev[('TEST', '3', '52')]['persist'] == '1'
    assert ev[('TEST', '3', '10')]['multichan'] == '1'


def test_veto_separates_hum_from_link():
    import veto_prove  # noqa — proves run in sy_prove_all; import checks wiring
    import rfi_veto as V
    cf = V.make_chan_freq(1407.71484375, -187.5, 64)
    ctx = {'chan_freq': cf, 'evidence': {('0', '32'): {'persist': '1', 'multichan': '1'}},
           'catalog': {'features': {}}, 'target': 'T',
           'on_idx': [(32, 179.0)], 'off_idx': [(32, 179.0)]}
    row = {'block': '0', 'chan': '32', 'pol': '0', 'spec_ratio': '1.5',
           'spec_bin': '1', 'fam_best': '5.0', 'fam_hz': '179.0',
           'fam_tag': 'Y2', 'vm_sign': '0.00/noise-like',
           'vm_diff': '0.00/noise-like', 'verdict': 'FAM-HIT'}
    E, S, net, disp, _, _ = V.score_slice(row, ctx)
    assert disp.startswith('BLOCK')


def test_fold_finds_pulsar_and_quiet_on_noise():
    import pulsar_fold as PF
    rng = np.random.default_rng(5)
    N = 2 * 524288
    fs = 2929687.5
    noise = rng.normal(0, 14, N).astype(np.float32)
    assert not PF.detect(noise, fs)['detected']
    t = np.arange(N) / fs
    phase = (t * 29.7) % 1.0
    pulse = np.exp(-0.5 * ((phase - 0.5) / 0.03) ** 2)
    y = (noise + 6.0 * pulse * 14).astype(np.float32)
    r = PF.detect(y, fs)
    assert r['detected'] and abs(r['best']['freq_hz'] - 29.7) / 29.7 < 0.03


def test_dm_finds_shot_and_quiet_on_noise():
    import transient_dm as TD
    rng = np.random.default_rng(6)
    N = 2 * 524288
    fs = 2929687.5
    noise = rng.normal(0, 14, N)
    assert not TD.detect(noise, fs)['detected']
    y = noise.copy()
    y[300000:300008] += 12 * 14
    assert TD.detect(y, fs)['detected']


def test_raster_arecibo_vs_noise():
    import raster_hunt as RH
    rng = np.random.default_rng(7)
    assert not RH.analyze(rng.integers(0, 2, 1679).astype(np.uint8))['detected']
    msg, p, q = RH._arecibo_bits()
    r = RH.analyze(msg)
    assert r['detected'] and r['best_fold']['p'] == p


def test_burst_morphology():
    import burst_zoom as BZ
    rng = np.random.default_rng(8)
    N = 524288
    assert BZ.classify(BZ.features(rng.normal(0, 14, N))) == 'CLEAN'
    y = rng.normal(0, 14, N)
    y[99999:100005] += 25 * 14
    assert BZ.classify(BZ.features(y)) in ('GLINT', 'CARRIER-BURST')


def test_config_defaults_resolve():
    import seti_config as C
    cfg = C.resolve(None, None, {})
    assert cfg['fam_trig'] == 3.0 and cfg['fs'] > 2e6 and cfg['pol_list'] == [0, 1, 2, 3]
