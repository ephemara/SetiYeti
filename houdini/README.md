# SetiYeti × Houdini — `houdini/` folder

## Take: triage now, graveyard second, raw-topology never (until it earns it)

Your note is correct on all three mechanisms — but each one moves the
threshold, it doesn't remove it. So this folder is built in two tiers:

**Tier 1 — Flag triage (this weekend, cheap, solves the real bottleneck).**
Only slices already in `hits.csv` with `verdict != clean` get terrain.
You render what the math caught to answer one question fast:
*isolated narrowband ridge, or the peak of a broadband sweep / radar sidelobe?*
3 flags → 3 terrains + 3 macro strips. Seconds of compute, minutes of eyes.

**Tier 2 — Sub-threshold graveyard (next, bounded).**
Downsampled full-band heightfields for *flag-adjacent blocks only*
(b0, b24, b30 + neighbors), not all 581 rejects at full res. That's where
a 2.8x coherent ridge or a non-repeating burst lives without drowning you
in 581 EXRs. Full-raw topology at native res is Phase 3 — it needs a
downsample + VDB strategy first, or one M31 file becomes terabytes of images.

Why tiered: a VEX curvature filter *will* catch continuity the 3.0x boolean
gate deletes — but every radar sidelobe also becomes a beautiful ridge.
Eye-in-the-loop without bounds = 10x the false positives, just prettier.
Tiers keep Houdini as the appeal court, not the primary sieve.

## What's in here

```
houdini/
  README.md                this file
  export_triage.py         system-python exporter: hits.csv + .raw -> out/
  hython_triage.py         hython shelf script: builds /obj/SETIYETI_TRIAGE
  vex/faint_ridge_wrangles.txt  VEX snippets: curvature + density filters
  out/                     generated: PNG + NPY + EXR + OBJ/MTL + points CSV
```

Per flag two terrains ship: `terrain_*` (total power) and `terrain_*_y2`
(square-law — the domain the FAM flag was actually raised in; appeal the
flag on the `_y2` mesh, use the power mesh for context).

## UE5 import (terrains as 3D meshes)

Meshes are ~126x410 (~52k verts, ~102k tris), 10m x 10m plane, up to 2m
relief, Y-up with UVs + gradient normals + MTL pointing at the terrain PNG.
Content Browser → Import `houdini/out/terrain_b24c27_y2.obj` (keep the
`.mtl` + `.png` beside it so albedo links): Convert Scene ON (default,
Y-up → UE5 Z-up), scale 1.0 (already cm), Import Normals. Material
builds itself from the MTL; swap in an emissive/height-tinted MI to taste.
Axes in-engine: X = frequency (2.93 MHz of that coarse channel), Y = time
(~0.18 s per block), Z = log-power relief. Carrier = straight wall along
Y; drifter = diagonal blade; radar speckle = popcorn. b24's `_y2` mesh
should read as popcorn — the kill verdict in 3D.

## Run it (Windows, system python — NOT hython for export)

```
python houdini/export_triage.py --root .
```

Reads `hits.csv`, re-slices each flagged `(block,chan)` from the `.raw`
via `c/seti_slice`, writes per-flag waterfall terrain + per-flag-block
64-channel macro strip into `houdini/out/`. Re-run safe (overwrites).

Then inside Houdini (FX 22):

1. Open Houdini FX, new scene.
2. Python shell / shelf → Run `houdini/hython_triage.py`
   (it builds `/obj/SETIYETI_TRIAGE`: terrain + flag points + macro strips).
3. Or hand-wire: File SOP → `out/terrain_b<BB>c<CC>.png` as heightfield,
   File SOP → `out/hits_points.csv` as points, color by `score`.

## What to look at (the actual adjudication)

* **Single-block single-chan spike, no ridge into neighbors, macro strip
  shows one hot pixel in one channel** → terrestrial burst / radar key-up.
  This is what killed all 3 M31 flags from C alone; terrain should confirm.
* **Faint ridge continuous across time rows at fixed freq (even at 2.5–2.9x,
  under our 3.0 gate)** → appeal granted, promote to full SCD + despread.
* **Diagonal ridge across time, or energy smeared across 10+ channels in the
  macro strip** → drift/jerk or broadband chirp; route to `jerk_scan.py`,
  not the VM sandbox.
* **Blob in Takens/cloud view with no FAM line** → non-repeating burst
  candidate; needs envelope + DM sweep, not cyclo.

## VPS / fleet notes

Export runs on system python + `seti_slice.exe` only (numpy + PIL, EXR
best-effort). No Houdini license needed for export — Houdini is only the
viewer. `hython_triage.py` needs FX/Engine + `hou`. Don't install Houdini
on the 4-core workers; export there, view here.

## What this folder deliberately does NOT do

* No re-detection in Houdini. C owns thresholds; VEX owns appeal review.
* No full-581-slice terrain dump (storage + time trap).
* No `.hip` binary in git — the network is code (`hython_triage.py`),
  reproducible, diffable. Save your own `.hip` locally, don't commit it.
