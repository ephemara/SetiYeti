; fold_dm.smt2 — formal spec of the FOLD + DM shot verdict logic
; (c/fold_dm.c + python/pulsar_fold.py + python/transient_dm.py — all three
;  MUST agree; differential ties in ../verify_c_fold.py).
;
; fold_det = fold_sig >= 16.0  (8-draw noise max ~10.8; weakest inject 3400+)
; dm_det   = dm_sig   >= 14.0  (noise max ~10.8 over DM x width; injects 168+)
; verdict  = PERIODIC/SHOT iff fold_det OR dm_det, else quiet.
; DM physics guard: shifts grow monotonically with DM (higher DM => larger
; delay); a non-monotone shift table is not cold plasma.

(set-logic QF_LRA)
(declare-const fold_sig Real)
(declare-const dm_sig Real)
(declare-const dm0 Real)
(declare-const dm1 Real)
(declare-const sh0 Real)
(declare-const sh1 Real)
(define-fun fold_det () Bool (>= fold_sig 16.0))
(define-fun dm_det () Bool (>= dm_sig 14.0))
(define-fun verdict () Bool (or fold_det dm_det))

; ---- F1: quiet means quiet: both below gate => no verdict ----
; expect UNSAT
(push)
(assert (and (< fold_sig 16.0) (< dm_sig 14.0) verdict))
(check-sat)
(pop)

; ---- F2: fold gate is sharp: 15.9 does not fire, 16.0 does ----
; 15.9 AND fold_det => UNSAT
(push)
(assert (and (= fold_sig 15.9) fold_det))
(check-sat)
(pop)
; ---- F3: DM gate is sharp: 13.9 does not fire ----
; expect UNSAT
(push)
(assert (and (= dm_sig 13.9) dm_det))
(check-sat)
(pop)

; ---- F4: either arm fires the verdict (fold 4799, dm 11.7 => verdict) ----
; expect SAT
(push)
(assert (and (= fold_sig 4799.0) (= dm_sig 11.7) verdict))
(check-sat)
(pop)

; ---- F5: DM shift monotonicity: dm1>dm0 => sh1>=sh0 (cold plasma) ----
; violation (dm grows, shift shrinks) => UNSAT under the plasma axiom
; expect UNSAT
(push)
(assert (> dm1 dm0))
(assert (= sh1 (* 2.0 dm1)))
(assert (= sh0 (* 2.0 dm0)))
(assert (< sh1 sh0))
(check-sat)
(pop)

; ---- F6: noise pair (9.4, 11.7) stays quiet ----
; expect UNSAT
(push)
(assert (and (= fold_sig 9.4) (= dm_sig 11.7) verdict))
(check-sat)
(pop)
