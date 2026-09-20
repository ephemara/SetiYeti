# BEAST report — KEPLER160

preset: configs/kepler_L.toml  fs=2929687.500000003 (header TBIN)
elapsed: 2.2 min

- on p0: 8192 slices; clean=6901, QUARANTINE=896, hump-note=374, FAM-HIT=21
- on p1: 8192 slices; clean=6778, QUARANTINE=898, hump-note=369, SPECTRAL-LINE=128, FAM-HIT=19
- on p2: 8192 slices; clean=6992, QUARANTINE=617, hump-note=434, SPECTRAL-LINE=129, FAM-HIT=20
- on p3: 8192 slices; clean=6933, QUARANTINE=620, hump-note=618, FAM-HIT=20, SPECTRAL-LINE=1
- off p0: 8320 slices; clean=6991, QUARANTINE=908, hump-note=366, FAM-HIT=55
- off p1: 8384 slices; clean=6897, QUARANTINE=916, hump-note=382, SPECTRAL-LINE=131, FAM-HIT=58
- off p2: 8640 slices; clean=7352, QUARANTINE=656, hump-note=410, SPECTRAL-LINE=135, FAM-HIT=87
- off p3: 8640 slices; clean=7259, QUARANTINE=652, hump-note=646, FAM-HIT=83

## veto (with evidence, all pols)

- p0: [veto] BLOCK=21 WATCH=0 CANDIDATE=0 skipped_nonflag=8171 | catalog=1387 classes | run_id=a49bd9dd34a7
- p1: [veto] BLOCK=118 WATCH=27 CANDIDATE=2 skipped_nonflag=8045 | catalog=1387 classes | run_id=176f59c62a82
- p2: [veto] BLOCK=149 WATCH=0 CANDIDATE=0 skipped_nonflag=8043 | catalog=1452 classes | run_id=94ec90da17f4
- p3: [veto] BLOCK=20 WATCH=1 CANDIDATE=0 skipped_nonflag=8171 | catalog=1460 classes | run_id=d15f674e6b0f
