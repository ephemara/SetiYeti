"""hython_triage.py - build /obj/SETIYETI_TRIAGE in a live Houdini session.
Run from Houdini python shell / shelf (needs hou). NOT system python.

  exec(open(r'T:/Projects/SetiYeti/houdini/hython_triage.py').read())

Builds, idempotently (deletes old node first):
  /obj/SETIYETI_TRIAGE
    terrain_b<BB>c<CC>  (File SOP -> terrain_*.npy via Python SOP heightfield)
    FLAG_POINTS         (File SOP -> hits_points.csv, color by score)
    macro_b<BB>         (COP2 or SOP grid textured with macro_*.png)

OUT_DIR must point at houdini/out from export_triage.py.
"""
OUT_DIR = r'T:/Projects/SetiYeti/houdini/out'

import os, glob

try:
    import hou
except ImportError:
    raise SystemExit("run this inside Houdini (python shell / shelf), not system python.")

obj = hou.node('/obj')
old = obj.node('SETIYETI_TRIAGE')
if old is not None:
    old.destroy()
root = obj.createNode('geo', 'SETIYETI_TRIAGE')

# 1. flag points from CSV (File SOP reads .csv as points natively)
csv_path = os.path.join(OUT_DIR, 'hits_points.csv').replace('\\', '/')
if os.path.exists(os.path.join(OUT_DIR, 'hits_points.csv')):
    fpts = root.createNode('file', 'FLAG_POINTS')
    fpts.parm('file').set(csv_path)
    # color by score: wrangle maps score 2.0..4.0 -> blue..red
    wr = root.createNode('attribwrangle', 'color_by_score')
    wr.setInput(0, fpts)
    wr.parm('class').set(0)  # point wrangle
    wr.parm('snippet').set(
        "f s = ch('score_fallback');\n"
        "if (haspointattrib(0, 'score')) s = f@score;\n"
        "f t = clamp((s - 2.0) / 2.0, 0, 1);\n"
        "v@Cd = mix(set(0.2,0.4,1.0), set(1.0,0.15,0.1), t);\n"
        "v@scale = set(1 + t*3);\n")
    out_pts = root.createNode('null', 'OUT_POINTS')
    out_pts.setInput(0, wr)
    out_pts.setDisplayFlag(True)
else:
    print("[triage] no hits_points.csv yet — run export_triage.py first.")

# 2. one terrain subnet per exported heightfield PNG (heightfield_file)
for png in sorted(glob.glob(os.path.join(OUT_DIR, 'terrain_*.png'))):
    name = os.path.splitext(os.path.basename(png))[0]  # terrain_b30c56
    sub = root.createNode('geo', name.upper())
    hf = sub.createNode('heightfield_file', 'load')
    hf.parm('file').set(png.replace('\\', '/'))
    hf.parm('mode').set(0)  # image as height
    sc = sub.createNode('null', 'OUT')
    sc.setInput(0, hf)
    print(f"[triage] terrain wired: {name}")

# 3. macro strips as textured grids (one per macro_b<BB>.png)
for png in sorted(glob.glob(os.path.join(OUT_DIR, 'macro_*.png'))):
    name = os.path.splitext(os.path.basename(png))[0]
    sub = root.createNode('geo', ('VIEW_' + name).upper())
    grid = sub.createNode('grid', 'strip')
    grid.parm('sizex').set(64)
    grid.parm('sizey').set(8)
    uv = sub.createNode('uvtexture', 'uv')
    uv.setInput(0, grid)
    mat = sub.createNode('principledshader::2.0', 'tex')
    mat.parm('basecolor_useTexture').set(1)
    mat.parm('basecolor_texture').set(png.replace('\\', '/'))
    print(f"[triage] macro view wired: {name}")

root.layoutChildren()
print("[triage] /obj/SETIYETI_TRIAGE built. Fly through terrains, check ridges.")
