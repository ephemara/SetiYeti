# BEAST report — E2E

preset: configs/beast_e2e.toml  fs=2929687.500000003 (header TBIN)
elapsed: 0.9 min

- on p0: 128 slices; clean=102, QUARANTINE=14, hump-note=10, SPECTRAL-LINE=2
- on p1: 128 slices; clean=106, QUARANTINE=14, hump-note=8
- on p2: 128 slices; clean=102, QUARANTINE=12, hump-note=10, SPECTRAL-LINE=2, FAM-HIT=2
- on p3: 128 slices; clean=100, QUARANTINE=14, hump-note=12, SPECTRAL-LINE=2
- off p0: 128 slices; clean=101, QUARANTINE=13, hump-note=11, SPECTRAL-LINE=2, FAM-HIT=1
- off p1: 128 slices; clean=100, QUARANTINE=13, hump-note=10, FAM-HIT=3, SPECTRAL-LINE=2
- off p2: 128 slices; clean=95, QUARANTINE=15, FAM-HIT=8, hump-note=8, SPECTRAL-LINE=2
- off p3: 128 slices; clean=92, QUARANTINE=16, hump-note=11, FAM-HIT=7, SPECTRAL-LINE=2

## veto (with evidence, all pols)

- p0: [veto] BLOCK=2 WATCH=0 CANDIDATE=0 skipped_nonflag=126 | catalog=1462 classes | run_id=b3a32741bfe6
- p1: [veto] BLOCK=0 WATCH=0 CANDIDATE=0 skipped_nonflag=128 | catalog=1462 classes | run_id=2970cd8f4914
- p2: [veto] BLOCK=4 WATCH=0 CANDIDATE=0 skipped_nonflag=124 | catalog=1466 classes | run_id=6ee02c21bbf5
- p3: [veto] BLOCK=2 WATCH=0 CANDIDATE=0 skipped_nonflag=126 | catalog=1468 classes | run_id=c591d2071199
