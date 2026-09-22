; jerk_track.smt2 — formal spec of the JERK track-before-detect verdict logic
; (c/jerk_track.c + python/jerk_scan.py sidereal screen — the two MUST agree;
;  differential tie in ../verify_c_jerk.py).
;
; flagged   = score >= thresh  (a track exists at this floor)
; bound     = 0.35 * freq_mhz / 1407.7  (Earth-rotation Doppler screen, M5)
; anom      = |v| > bound  (off-Earth Doppler — screening only, veto attributes)
; continuous= |step| <= k  (Viterbi agility contract: the path can move at
;             most k bins per row; anything larger is not a Viterbi path)
; verdict   = CANDIDATE-track iff flagged (thresh>0); else clean/scored.

(set-logic QF_LRA)
(declare-const score Real)
(declare-const thresh Real)
(declare-const v Real)
(declare-const freq Real)
(declare-const step Real)
(declare-const k Real)
(define-fun bound () Real (/ (* 0.35 freq) 1407.7))
(define-fun flagged () Bool (>= score thresh))
(define-fun anom () Bool (> (abs v) bound))
(define-fun continuous () Bool (<= (abs step) k))

; ---- J1: CANDIDATE needs a flag: not-flagged => not-CANDIDATE ----
; expect UNSAT
(push)
(assert (and (< score thresh) flagged))
(check-sat)
(pop)

; ---- J2: v=0.2 at L-band is inside the bound, never anomalous ----
; expect UNSAT
(push)
(assert (and (= freq 1407.7) (= v 0.2) anom))
(check-sat)
(pop)

; ---- J3: bound scales with frequency: 2x freq => 2x bound ----
; b2815 = 0.70, b1407 = 0.35; assert they differ from 2x => UNSAT
(push)
(assert (and (= freq 2815.4) (not (= bound 0.70))))
(check-sat)
(pop)

; ---- J4: a 3-bin step with k=2 violates the Viterbi contract ----
; expect UNSAT (i.e. no model where step=3,k=2 is continuous)
(push)
(assert (and (= step 3.0) (= k 2.0) continuous))
(check-sat)
(pop)

; ---- J5: a flagged, continuous, anomalous track is the jackpot class ----
; (flagged & continuous & anom) is SAT — the logic can express it
; expect SAT
(push)
(assert (and (= score 6.0) (= thresh 4.0) (= v 1631.0) (= freq 1407.7)
             (= step 1.0) (= k 2.0) flagged continuous anom))
(check-sat)
(pop)

; ---- J6: stationary tone v=0 is never anomalous for any positive freq ----
; expect UNSAT
(push)
(assert (and (= v 0.0) (> freq 0.0) anom))
(check-sat)
(pop)
