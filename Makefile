# ============================================================================
#  SetiYeti — build the C tools
# ============================================================================
#  Why this exists: build success must never be asserted by reading an echo
#  statement. Every rule here fails loudly on error.
#
#    make            build the three tools
#    make check      build, then verify each binary actually runs
#    make prove      run the full detector prove suite (slow, needs python)
#    make clean      remove binaries
#    make help       this list
#
#  Notes
#   * -Wall -Wextra are MANDATORY. The one real latent bug found so far
#     (a non-NUL-terminated MAGIC[16]) was only visible because of -Wextra.
#   * On Windows/MinGW gcc appends .exe automatically; the python detectors
#     look for that suffix, so we build both names consistently.
# ============================================================================

ifeq ($(OS),Windows_NT)
  EXE := .exe
  RM  := rm -f
else
  EXE :=
  RM  := rm -f
endif

# `?=` does NOT work for CC: make predefines CC=cc, so the default always wins.
# Assign unconditionally instead - a command-line `make CC=clang` still overrides.
CC      := gcc
CFLAGS  ?= -O3 -march=native -Wall -Wextra -std=c99 -I c
LDLIBS  ?= -lm
# BEAST: vendored single-headers live in c/vendor (sy_fft/sy_stats/sy_io:
# cached-twiddle FFT, quickselect median, 64-bit I/O). -march=native lets the
# auto-vectorizer use AVX2 on the FFT and filter loops. Override with e.g.
# `make CFLAGS="-O2 -Wall -Wextra -std=c99 -I c"` for portable binaries.

BIN     := c
TOOLS   := seti_slice fam_scan vm_sandbox comb_scan xeno_scan xvm_sandbox
BINS    := $(addprefix $(BIN)/,$(addsuffix $(EXE),$(TOOLS)))

PY      ?= python
ROOT    := .

.PHONY: all check prove prove-quick pytest clean help

all: $(BINS)

# one pattern rule for every tool: c/<name>.c -> c/<name>[.exe]
$(BIN)/%$(EXE): $(BIN)/%.c
	@echo "  CC    $<"
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

# ---- smoke: prove the binaries are alive, not just present -----------------
check: all
	@echo "== binaries =="
	@for t in $(TOOLS); do \
	  printf "  %-12s %8s bytes  " "$$t" "$$(wc -c < $(BIN)/$$t$(EXE))"; \
	  $(BIN)/$$t$(EXE) >/dev/null 2>&1; \
	  rc=$$?; \
	  if [ $$rc -eq 2 ] || [ $$rc -eq 1 ] || [ $$rc -eq 0 ]; then \
	    echo "runs (rc=$$rc)"; \
	  else \
	    echo "BROKEN (rc=$$rc)"; exit 1; \
	  fi; \
	done
	@echo "== layout detection on real data (if present) =="
	@for f in data/*.raw; do \
	  [ -e "$$f" ] || continue; \
	  printf "  %-58s " "$$(basename $$f)"; \
	  $(BIN)/seti_slice$(EXE) "$$f" 32 /tmp/_mk.f32 1 --pol 0 2>&1 \
	    | sed -n 's/^(layout: \(.*\))/\1/p' | head -1; \
	done
	@rm -f /tmp/_mk.f32
	@echo "OK"

# ---- full detector prove suite --------------------------------------------
prove: all
	$(PY) python/sy_prove_all.py     --root $(ROOT)

# ---- fast subset (<2 min): C selftests + pure-rule + new-detector proves --
prove-quick: all
	$(PY) python/sy_prove_all.py     --root $(ROOT) --quick

# ---- pytest unit gate (no data, deterministic) ----------------------------
pytest: all
	$(PY) -m pytest tests/test_beast_fast.py -q

# ---- legacy per-detector proves (kept for forensics; `prove` runs them all)
prove-legacy: all
	$(PY) python/dsss_prove.py     --root $(ROOT)
	$(PY) python/jerk_scan.py      --prove --root $(ROOT)
	$(PY) python/scd_frf.py        --prove
	$(PY) python/latent_pca.py     --prove
	$(PY) python/veto_prove.py     --root $(ROOT)
	$(PY) python/frame_hunt.py     --prove
	$(PY) python/structure_pass.py --selftest
	$(PY) python/build_evidence.py --selftest
	$(BIN)/comb_scan$(EXE) --selftest
	@echo "ALL PROVES PASSED"

clean:
	$(RM) $(BINS)
	@echo "cleaned $(BINS)"

help:
	@echo "SetiYeti C tools"
	@echo "  make            build $(TOOLS)"
	@echo "  make check      build + verify binaries run + detect file layout"
	@echo "  make prove      run full detector prove suite (slow)"
	@echo "  make clean      remove binaries"
	@echo ""
	@echo "  CC=$(CC)  CFLAGS=$(CFLAGS)"
