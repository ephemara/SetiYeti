; veto_disposition.smt2 — formal spec of the M1 two-axis disposition
; (python/rfi_veto.py score_slice tail logic).
;
; net = E - S. hard_block (recurring unstructured local) forces BLOCK.
;   disp = BLOCK     iff hard_block OR net >= 0.50
;   disp = WATCH     iff not BLOCK and (net >= 0.15 or candidacy-cap applies)
;   disp = CANDIDATE iff not BLOCK and net < 0.15 AND persist AND (engineered OR multi)
;
; Safety properties (must all be SAT-consistent, violations UNSAT):
;   P1: hard_block => BLOCK.  P2: CANDIDATE => persist & (engineered | multi).
;   P3: engineered common-mode is NEVER hard-blocked (monument protection).
;   P4: BLOCK and CANDIDATE are mutually exclusive.

(set-logic QF_LRA)
(declare-const E Real) (declare-const S Real)
(declare-const persist Bool) (declare-const engineered Bool) (declare-const multi Bool)
(declare-const n_seen Int) (declare-const hard_block Bool)
(assert (>= E 0.0)) (assert (>= S 0.0)) (assert (<= S 1.0)) (assert (>= n_seen 0))
; catalog rule transcription: hard_block <=> (n_seen>=3 AND NOT engineered)
(assert (= hard_block (and (>= n_seen 3) (not engineered))))
(define-fun net () Real (- E S))
(define-fun is_block () Bool (or hard_block (>= net 0.5)))
(define-fun may_cand () Bool (and (not is_block) (< net 0.15) persist (or engineered multi)))

; P1: hard_block => is_block (violation must be UNSAT)
; expect UNSAT
(push)
(assert (and hard_block (not is_block)))
(check-sat)
(pop)
; P2: may_cand => persist & (engineered | multi) (violation UNSAT)
; expect UNSAT
(push)
(assert (and may_cand (not (and persist (or engineered multi)))))
(check-sat)
(pop)
; P3: engineered & recurring => NOT hard_block (violation UNSAT)
; expect UNSAT
(push)
(assert (and engineered (>= n_seen 3) hard_block))
(check-sat)
(pop)
; P4: is_block & may_cand mutually exclusive (violation UNSAT)
; expect UNSAT
(push)
(assert (and is_block may_cand))
(check-sat)
(pop)
; P5: spec is livable — each disposition reachable (all SAT)
; expect SAT
(push)
(assert is_block)
(check-sat)
(pop)
; expect SAT
(push)
(assert may_cand)
(check-sat)
(pop)
; expect SAT
(push)
(assert (and (not is_block) (not may_cand)))
(check-sat)
(pop)