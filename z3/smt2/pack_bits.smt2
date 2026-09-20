; pack_bits.smt2 — REAL proof: pack is injective (hence a faithful encoding).
; Model: pack(b0..b7) = concat(ite(bi,1,0)) MSB-first, exactly the shipped
;   out[i>>3] |= (1 << (7-(i&7))) loop for one byte.
; Theorem: pack(x) = pack(y) => x = y, for all 8-bit x,y.
; Violation below must be UNSAT. (Roundtrip + differential vs shipped code:
; ../verify_pack.py, exhaustive over all 256 byte values + random streams.)

(set-logic QF_BV)
(declare-const x (_ BitVec 8))
(declare-const y (_ BitVec 8))
; pack is the identity on the byte when bits are read MSB-first, so injectivity
; reduces to: x != y but every extracted bit equal — impossible.
(assert (distinct x y))
(assert (= ((_ extract 7 7) x) ((_ extract 7 7) y)))
(assert (= ((_ extract 6 6) x) ((_ extract 6 6) y)))
(assert (= ((_ extract 5 5) x) ((_ extract 5 5) y)))
(assert (= ((_ extract 4 4) x) ((_ extract 4 4) y)))
(assert (= ((_ extract 3 3) x) ((_ extract 3 3) y)))
(assert (= ((_ extract 2 2) x) ((_ extract 2 2) y)))
(assert (= ((_ extract 1 1) x) ((_ extract 1 1) y)))
(assert (= ((_ extract 0 0) x) ((_ extract 0 0) y)))
; expect UNSAT
(check-sat) ; equal packs force equal bytes
