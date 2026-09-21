; ingest_dispatch.smt2 - formal spec of the universal ingest router
; (python/univ_ingest.py detect_format + kind assignment).
;
; The router MUST be total (every input maps to exactly one reader or a
; clean refusal) and must never silently misread (container magic wins for
; self-describing formats; headerless raw-IQ without --fs refuses instead
; of guessing; detected power is never labelled voltage).
;
; Properties (violations must be UNSAT):
;   D1: facts determine exactly one reader (exhaustive + exclusive)
;   D2: HDF5 magic forces the H5 reader regardless of extension
;   D3: headerless raw-IQ with unknown sample rate REFUSES (no guessing)
;   D4: kind soundness - filterbank/HDF5-power readers imply kind=power;
;       GUPPI/WAV imply voltage; unknown implies refusal, never voltage
(set-logic QF_UF)
(declare-datatypes () ((Reader R_GUPPI R_FIL R_H5 R_GENH5 R_FITS R_WAV
                               R_IQ R_NPY R_CSV R_F32 R_UNKNOWN)))
(declare-datatypes () ((Kind K_VOLTAGE K_COMPLEX K_POWER K_OTHER)))
; input facts
(declare-const m_hdf5 Bool) (declare-const m_fits Bool)
(declare-const m_wav Bool) (declare-const m_npy Bool)
(declare-const e_raw Bool) (declare-const guppi_cards Bool)
(declare-const e_fil Bool) (declare-const fil_parses Bool)
(declare-const e_h5 Bool) (declare-const e_fits Bool) (declare-const e_wav Bool)
(declare-const e_npy Bool) (declare-const e_f32 Bool)
(declare-const e_csv Bool) (declare-const e_iq Bool)
(declare-const fs_known Bool)
; router transcription (order mirrors detect_format)
(define-fun reader () Reader
  (ite m_hdf5 R_H5
  (ite m_fits R_FITS
  (ite m_wav R_WAV
  (ite (or m_npy e_npy) R_NPY
  (ite e_f32 R_F32
  (ite (and e_raw guppi_cards) R_GUPPI
  (ite (or e_fil fil_parses) R_FIL
  (ite e_csv R_CSV
  (ite e_iq R_IQ
  (ite e_wav R_WAV
  (ite e_fits R_FITS
  (ite e_h5 R_GENH5 R_UNKNOWN)))))))))))))
(define-fun kind () Kind
  (ite (or (= reader R_FIL) (= reader R_H5) (= reader R_GENH5)) K_POWER
  (ite (= reader R_IQ) K_COMPLEX
  (ite (or (= reader R_GUPPI) (= reader R_WAV) (= reader R_F32)
           (= reader R_NPY) (= reader R_FITS) (= reader R_CSV)) K_VOLTAGE
       K_OTHER))))
(define-fun refuses () Bool (or (= reader R_UNKNOWN)
                                (and (= reader R_IQ) (not fs_known))))

; D1a: exhaustive - some reader always results (negation UNSAT).
; NOTE: ite-chains are exhaustive by construction; this check pins that.
; expect UNSAT
(push)
(assert (not (or (= reader R_GUPPI) (= reader R_FIL) (= reader R_H5)
                 (= reader R_GENH5) (= reader R_FITS) (= reader R_WAV)
                 (= reader R_IQ) (= reader R_NPY) (= reader R_CSV)
                 (= reader R_F32) (= reader R_UNKNOWN))))
(check-sat)
(pop)
; D1b: no facts at all => UNKNOWN (violation UNSAT)
; expect UNSAT
(push)
(assert (and (not m_hdf5) (not m_fits) (not m_wav) (not m_npy)
             (not e_f32) (not (and e_raw guppi_cards))
             (not (or e_fil fil_parses)) (not e_csv) (not e_iq)
             (not e_wav) (not e_fits) (not e_h5) (not e_npy)
             (not (= reader R_UNKNOWN))))
(check-sat)
(pop)
; D2: HDF5 magic forces H5 regardless of extension (violation UNSAT)
; expect UNSAT
(push)
(assert (and m_hdf5 (not (= reader R_H5))))
(check-sat)
(pop)
; D3: raw-IQ without sample rate refuses (violation UNSAT)
; expect UNSAT
(push)
(assert (and (= reader R_IQ) (not fs_known) (not refuses)))
(check-sat)
(pop)
; D4a: filterbank readers imply power (violation UNSAT)
; expect UNSAT
(push)
(assert (and (or (= reader R_FIL) (= reader R_H5)) (not (= kind K_POWER))))
(check-sat)
(pop)
; D4b: GUPPI/WAV imply voltage (violation UNSAT)
; expect UNSAT
(push)
(assert (and (or (= reader R_GUPPI) (= reader R_WAV)) (not (= kind K_VOLTAGE))))
(check-sat)
(pop)
; D4c: refusal never carries voltage (violation UNSAT)
; expect UNSAT
(push)
(assert (and refuses (= kind K_VOLTAGE) (not (= reader R_IQ))))
(check-sat)
(pop)
; D5: every reader reachable (all SAT)
; expect SAT
(push)
(assert (= reader R_GUPPI))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_FIL))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_H5))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_FITS))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_WAV))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_IQ))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_CSV))
(check-sat)
(pop)
; expect SAT
(push)
(assert (= reader R_UNKNOWN))
(check-sat)
(pop)
