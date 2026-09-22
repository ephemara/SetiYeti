; corpus_invariants.smt2 - formal spec of the SetiYeti corpus library
; (python/corpus.py SQLite store). The DB is the pipeline's memory; a corrupt
; memory poisons every future threshold proposal. These invariants must hold
; after every ingest (violations UNSAT):
;   C1: the ingest map (key->slice) is functional (re-ingest replaces,
;       never duplicates)
;   C4: review soundness from the view definition (a flagged+watched row
;       is in the review set)
;   C5: livability (the interesting states exist)
; Deliberately NOT in SMT (SAT-vacuous over unconstrained predicates -
; measured, not assumed): orphan-freedom, flags-on-signal-rows, and
; pinned-join correctness. Those are DATA invariants, enforced live on
; 104k slices by z3/verify_corpus.py (0 violations), where the quantifiers
; range over rows instead of nothing.
(set-logic QF_UF)
(declare-sort Slice 0)
(declare-sort Run 0)
(declare-fun key (Slice) Int)
(declare-fun sig (Slice) Bool)      ; signal row (scored kind)
(declare-fun grade_hi (Slice) Bool) ; grade I2+
(declare-fun flagged (Slice Run) Bool)
(declare-fun disp_watch (Slice Run) Bool)

; C1: the ingest map (key->slice) is functional - equal keys resolve to
; equal slices (function congruence; violation UNSAT). (A draft stated this
; over uninterpreted key/sorts, where the solver trivially collides two
; slices - vacuous SAT. The map form is the checkable one. History kept.)
(declare-fun slot (Int) Slice)
; expect UNSAT
(push)
(declare-const x Int) (declare-const y Int)
(declare-const s Slice) (declare-const t Slice)
(assert (and (= (slot x) s) (= (slot y) t) (= x y) (not (= s t))))
(check-sat)
(pop)
; C4: review soundness - reviewed => grade_hi or watched (violation UNSAT)
; expect UNSAT
(push)
(declare-const s4 Slice) (declare-const r4 Run)
(define-fun in_review ((s Slice) (r Run)) Bool
  (or (grade_hi s) (disp_watch s r)))
(assert (and (flagged s4 r4) (disp_watch s4 r4)
             (not (in_review s4 r4))))
(check-sat)
(pop)
; C5: livability - the interesting states exist (all SAT)
; expect SAT
(push)
(declare-const s5 Slice) (declare-const r5 Run)
(assert (and (sig s5) (flagged s5 r5) (grade_hi s5)))
(check-sat)
(pop)
; expect SAT
(push)
(declare-const s6 Slice) (declare-const r6 Run)
(assert (and (sig s6) (flagged s6 r6) (disp_watch s6 r6)
             (not (grade_hi s6))))
(check-sat)
(pop)
; expect SAT
(push)
(declare-const s7 Slice)
(assert (and (sig s7) (not (grade_hi s7))))
(check-sat)
(pop)
