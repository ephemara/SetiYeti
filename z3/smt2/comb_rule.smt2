; comb_rule.smt2 — formal spec of THE COMB RULE
; (c/comb_scan.c sy_comb_rule + python/structure_pass.py comb_rule_on_bins —
;  the two MUST agree; differential fuzz in ../verify_c_comb.py ties them).
;
; Rule: f0 candidate b0 in 2..128 fires iff >=3 distinct peaks lie within
; ±1 bin of m*b0 (m=1..8) AND mean member ratio >= 6.0.

(set-logic QF_LIA)
(declare-const b0 Int)
(assert (and (>= b0 2) (<= b0 128)))

; ---- Theorem A: a SINGLE peak (bin 56) can never reach 3 members ----
; expect UNSAT
(push)
(define-fun hit ((m Int)) Int
  (ite (or (= (* m b0) 55) (= (* m b0) 56) (= (* m b0) 57)) 1 0))
(assert (>= (+ (hit 1) (hit 2) (hit 3) (hit 4) (hit 5) (hit 6) (hit 7) (hit 8)) 3))
(check-sat)
(pop)

; ---- Theorem B: the Kepler family {(4,30),(16,25),(32,20)} fires ----
; A peak (pb,pr) is a member of slot s=m*b0 iff |s-pb|<=1, contributing pr.
; expect SAT (witness: b0=4, members m=1,4,8, mean 25>=6)
(push)
(define-fun mem ((m Int) (pb Int) (pr Int)) Int (ite (or (= (* m b0) (- pb 1)) (= (* m b0) pb) (= (* m b0) (+ pb 1))) 1 0))
(define-fun crate ((m Int) (pb Int) (pr Int)) Int (ite (or (= (* m b0) (- pb 1)) (= (* m b0) pb) (= (* m b0) (+ pb 1))) pr 0))
; peak (4,30): member count and ratio contribution over m=1..8
(define-fun n1 () Int (+ (mem 1 4 30) (mem 2 4 30) (mem 3 4 30) (mem 4 4 30) (mem 5 4 30) (mem 6 4 30) (mem 7 4 30) (mem 8 4 30)))
(define-fun n2 () Int (+ (mem 1 16 25) (mem 2 16 25) (mem 3 16 25) (mem 4 16 25) (mem 5 16 25) (mem 6 16 25) (mem 7 16 25) (mem 8 16 25)))
(define-fun n3 () Int (+ (mem 1 32 20) (mem 2 32 20) (mem 3 32 20) (mem 4 32 20) (mem 5 32 20) (mem 6 32 20) (mem 7 32 20) (mem 8 32 20)))
(define-fun r1 () Int (+ (crate 1 4 30) (crate 2 4 30) (crate 3 4 30) (crate 4 4 30) (crate 5 4 30) (crate 6 4 30) (crate 7 4 30) (crate 8 4 30)))
(define-fun r2 () Int (+ (crate 1 16 25) (crate 2 16 25) (crate 3 16 25) (crate 4 16 25) (crate 5 16 25) (crate 6 16 25) (crate 7 16 25) (crate 8 16 25)))
(define-fun r3 () Int (+ (crate 1 32 20) (crate 2 32 20) (crate 3 32 20) (crate 4 32 20) (crate 5 32 20) (crate 6 32 20) (crate 7 32 20) (crate 8 32 20)))
; distinct-peak guard: one peak contributes at most one member per b0 here
; (slots 4k apart for b0>=2... for b0=1 slots collide, but b0>=2 always)
(assert (>= (+ n1 n2 n3) 3))
(assert (>= (div (+ r1 r2 r3) (+ n1 n2 n3)) 6))
(check-sat)
(pop)
