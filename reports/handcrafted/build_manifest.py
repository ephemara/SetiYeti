"""build_manifest.py — curate a download list of high-value SETI targets."""
import json, re, os
from collections import defaultdict
d=json.load(open('reports/handcrafted/tmp/all_baseband.json'))
rows=d['data']
# dedupe by filename, prefer GCS url
best={}
for r in rows:
    fn=r['url'].split('/')[-1]
    if fn not in best or ('storage.googleapis' in r['url']):
        best[fn]=r
rows=list(best.values())
bytarget=defaultdict(list)
for r in rows: bytarget[r['target']].append(r)

def pick(target, n, prefer_small=False):
    rs=bytarget.get(target,[])
    # sort by (band prefix, scan number, part)
    def key(r):
        fn=r['url'].split('/')[-1]
        m=re.match(r'(blc\d+).*?_(\d{5})_(\d+)\.(\d+)\.raw', fn)
        return (fn.split('_')[0], m.group(2) if m else '99999', fn)
    rs=sorted(rs,key=key)
    if prefer_small: rs=sorted(rs,key=lambda r:r['size'])
    return rs[:n]

sel=[]
# nearby stars: ON + OFF first file each
stars=sorted(t for t in bytarget if re.fullmatch(r'HIP\d+', t))
for s in stars:
    off=s+'_OFF'
    if off in bytarget:
        for t in (s,off):
            r=pick(t,1)
            if r: sel += r
    else:
        r=pick(s,1)
        if r: sel += r
# deep single-star sets
sel += pick('HIP113357',6)
sel += pick('MESSIER031',12)
sel += pick('VOYAGER1',3)
sel += pick('PSR_J2326+6113',2)
sel += pick('PSR_J2321+6024',2)
sel += pick('W3',2)

seen=set(); out=[]
for r in sel:
    fn=r['url'].split('/')[-1]
    if fn in seen: continue
    seen.add(fn); out.append(r)
tot=sum(r['size'] for r in out)
print(f'{len(out)} files, {tot/1e12:.3f} TB ({tot/1e9:.1f} GB)')
with open('reports/handcrafted/tmp/manifest.csv','w') as f:
    f.write('target,size_bytes,url,filename\n')
    for r in out:
        f.write('%s,%d,%s,%s\n'%(r['target'],r['size'],r['url'],r['url'].split('/')[-1]))
from collections import Counter
c=Counter(r['target'] for r in out)
for t,n in sorted(c.items()): print(f'  {t:22s} {n}')
