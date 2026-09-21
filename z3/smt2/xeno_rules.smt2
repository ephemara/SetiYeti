; xeno_rules.smt2 — formal spec of the XENO interstellar grade ladder
; (python/xeno_pass.py grade_slice).
;
; eng    = veto-eng (S>=0.25) OR >=2 xeno markers
; sky    = scint-SCINT OR pol-SKY-LIKE OR (persist AND on_only)
; exo    = negDM OR prime-train OR precursor
; strong = exo OR doppler-anomaly OR xvm-candidate
;
; grade = I0 iff not flagged
;       = I1 iff flagged and not eng            (exotic alone never engineers)
;       = I2 iff eng and not sky
;       = I3 iff eng and sky and not strong
;       = I4 iff eng and sky and strong and not (xvm and persist)
;       = I5 iff eng and sky and strong and xvm and persist (full house)
;
; Safety properties (violations must be UNSAT):
;   X1: I5 => persist & xvm & eng & sky (the full house is really full)
;   X2: eng & sky & exo => grade >= I4 (exotic+sky+structure always escalates)
;   X3: not flagged => I0 (silence is silence)
;   X4: grade is bounded (never below I0, never above I5)
;   X5: not eng => I0|I1 (a chirp with no coding is NOTABLE, not ENGINEERED)

(set-logic QF_UF)
(declare-const flagged Bool)
(declare-const eng_v Bool) (declare-const x2 Bool)
(declare-const scint Bool) (declare-const pol_sky Bool)
(declare-const persist Bool) (declare-const on_only Bool)
(declare-const negdm Bool) (declare-const primes Bool) (declare-const precursor Bool)
(declare-const doppler Bool) (declare-const xvm_cand Bool)
(define-fun eng () Bool (or eng_v x2))
(define-fun sky () Bool (or scint pol_sky (and persist on_only)))
(define-fun exo () Bool (or negdm primes precursor))
(define-fun strong () Bool (or exo doppler xvm_cand))
(define-fun g0 () Bool (not flagged))
(define-fun g1 () Bool (and flagged (not eng)))
(define-fun g2 () Bool (and flagged eng (not sky)))
(define-fun g3 () Bool (and flagged eng sky (not strong)))
(define-fun g4 () Bool (and flagged eng sky strong (not (and xvm_cand persist))))
(define-fun g5 () Bool (and flagged eng sky strong xvm_cand persist))

; X1: I5 => persist & xvm & eng & sky (violation UNSAT)
; expect UNSAT
(push)
(assert (and g5 (not (and persist xvm_cand eng sky))))
(check-sat)
(pop)
; X2: flagged & eng & sky & exo => grade >= I4, i.e. NOT g0/g1/g2/g3.
; (flagged is load-bearing: markers are only ever computed FOR a flagged
; slice - unflagged rows never reach the battery, so the ladder gates on
; flagged first. An early draft omitted it and Z3 correctly found g0.)
; expect UNSAT
(push)
(assert (and flagged eng sky exo (or g0 g1 g2 g3)))
(check-sat)
(pop)
; X3: not flagged => I0 (violation UNSAT)
; expect UNSAT
(push)
(assert (and (not flagged) (not g0)))
(check-sat)
(pop)
; X4a: grades exhaustive - one of g0..g5 always holds (negation UNSAT)
; expect UNSAT
(push)
(assert (not (or g0 g1 g2 g3 g4 g5)))
(check-sat)
(pop)
; X4b: g4 & g5 exclusive (violation UNSAT)
; expect UNSAT
(push)
(assert (and g4 g5))
(check-sat)
(pop)
; X4c: g3 & (g4|g5) exclusive (violation UNSAT)
; expect UNSAT
(push)
(assert (and g3 (or g4 g5)))
(check-sat)
(pop)
; X5: not eng => I0|I1 (violation UNSAT)
; expect UNSAT
(push)
(assert (and (not eng) (not (or g0 g1))))
(check-sat)
(pop)
; X6: spec is livable - every grade reachable (all SAT)
; expect SAT
(push)
(assert g0)
(check-sat)
(pop)
; expect SAT
(push)
(assert g1)
(check-sat)
(pop)
; expect SAT
(push)
(assert g2)
(check-sat)
(pop)
; expect SAT
(push)
(assert g3)
(check-sat)
(pop)
; expect SAT
(push)
(assert g4)
(check-sat)
(pop)
; expect SAT
(push)
(assert g5)
(check-sat)
(pop)
