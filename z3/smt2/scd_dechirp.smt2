; scd_dechirp.smt2 — formal spec of the SCD plane + dechirp verdict logic
; (c/scd_dechirp.c + python/scd_frf.py — the two MUST agree;
;  differential tie in ../verify_c_scd.py).
;
; scd_hit  = scd_top >= 8.0      (peak vs Rayleigh floor median, S[1:] only;
;                                 zero-pads excluded — the floor is Rayleigh)
; baud_hit = baudstack > 2 * noise_stack  (Gardner comb needs a real family,
;                                 not one bin; measured BPSK 8.3x over noise)
; dechirp_hit = dechirp > 1.5 * noise_bank AND dechirp > 3 * direct
;                                 (bank must concentrate smeared energy AND
;                                  beat the bank's own noise floor)
; verdict  = scored always (this stage characterises; the veto attributes).

(set-logic QF_LRA)
(declare-const scd_top Real)
(declare-const scd_floor Real)
(declare-const baud Real)
(declare-const baud_noise Real)
(declare-const dechirp Real)
(declare-const dechirp_noise Real)
(declare-const direct Real)
(define-fun scd_hit () Bool (>= scd_top 8.0))
(define-fun baud_hit () Bool (> baud (* 2.0 baud_noise)))
(define-fun dechirp_hit () Bool (and (> dechirp (* 1.5 dechirp_noise))
                                     (> dechirp (* 3.0 direct))))

; ---- S1: floor quiescence: top 4.5 with floor 8 => no hit ----
; expect UNSAT
(push)
(assert (and (= scd_top 4.5) scd_hit))
(check-sat)
(pop)

; ---- S2: BPSK fires both: top 124.8, baud 8.3x over noise ----
; expect SAT
(push)
(assert (and (= scd_top 124.8) (= baud 134700.0) (= baud_noise 16120.0)
             scd_hit baud_hit))
(check-sat)
(pop)

; ---- S3: single-bin RFI is not a baud family: baud == noise => no hit ----
; expect UNSAT
(push)
(assert (and (= baud 16120.0) (= baud_noise 16120.0) baud_hit))
(check-sat)
(pop)

; ---- S4: chirp bank: 1379 vs direct 49 (28x) and noise 18 (76x) fires ----
; expect SAT
(push)
(assert (and (= dechirp 1379.7) (= direct 49.3) (= dechirp_noise 18.4)
             dechirp_hit))
(check-sat)
(pop)

; ---- S5: bank without concentration is not a hit (dechirp == direct) ----
; expect UNSAT
(push)
(assert (and (= dechirp 49.3) (= direct 49.3) (= dechirp_noise 18.4)
             dechirp_hit))
(check-sat)
(pop)

; ---- S6: SCD index guard: valid cells need k-h>=0 and k+h<Np ----
; (k=0,h=1,Np=1024 is invalid => cell is zero-pad, never a peak)
; encoded as: invalid => ratio contribution 0 < 8, so no hit from it alone.
; expect UNSAT for invalid-cell-hit
(push)
(declare-const cell Real)
(assert (and (= cell 0.0) (>= cell 8.0)))
(check-sat)
(pop)
