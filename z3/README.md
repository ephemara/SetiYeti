# z3/ — formal verification for SetiYeti BEAST (z3-solver 5.1.0)

Proves replace hand-waving where the cost of being wrong is a missed signal
or a false veto. Two layers, both must pass:

## Layer 1 — SMT2 libs (`smt2/*.smt2`, checked by `run_smt2.py`)
Machine-checked specs with `; expect` verdicts. No z3 binary needed
(`z3.parse_smt2_string` replay with push/pop scoping).

| lib | theorems |
|---|---|
| `comb_rule.smt2` | single peak can never reach 3 members (UNSAT); Kepler family {(4,30),(16,25),(32,20)} fires at b0=4 (SAT) |
| `veto_disposition.smt2` | P1 hard-block⇒BLOCK, P2 CANDIDATE⇒persist&(eng\|multi), P3 engineered+recurring never hard-blocks, P4 BLOCK/CANDIDATE exclusive (all UNSAT-of-violation); all three dispositions reachable (SAT) |
| `pack_bits.smt2` | pack injectivity over 8-bit vectors (UNSAT-of-collision) |

## Layer 2 — code ties (`verify_*.py`: the proofs are vacuous if the spec ≠ code)
| verifier | what it ties | receipt |
|---|---|---|
| `verify_c_comb.py` | SMT2 rule semantics vs shipped `structure_pass.comb_rule_on_bins`, 2000 random peak sets + Z3 canonical cases | 2000/2000 + PASS |
| `verify_c_median.py` | **FULL PROOF**: unrolled Lomuto quickselect N=5 == sorted median over ALL 1024 inputs (0..3), UNSAT-of-counterexample; plus compiled C header (`harness_median.c`) vs `statistics.median` | UNSAT + 6/6 agree |
| `verify_veto.py` | disposition-tail transcription vs real `rfi_veto.score_slice`, 3000 fuzz rows; P1/P2/P3 re-checked on real verdicts | 3000/3000, 0 violations |
| `verify_pack.py` | shipped `bitslice.pack_bits` roundtrip, exhaustive 256 + 500 streams | ALL PASS |

## Run
```
C:/scoop/apps/python/current/python.exe -m pip install z3-solver   # one dep
python z3/run_smt2.py          # 10 formal checks
python z3/verify_c_median.py   # full median proof + C tie
python z3/verify_c_comb.py     # rule tie
python z3/verify_veto.py       # veto tie (backs every SMT2 safety property)
python z3/verify_pack.py       # packing tie
```

## Honest scope
Proven: comb counting, median selection, veto disposition boundaries, bit
packing. Tested (not proven): FFT core (8.4e-12 vs DFT + tone-in-one-bin),
Viterbi DP, SCD plane, all Python proves. TheNext formal targets, in order:
`sy_fft` butterfly permutation (N=8 exhaustive), `build_evidence` persist
predicate, `cadence_pair` promotion gate.
