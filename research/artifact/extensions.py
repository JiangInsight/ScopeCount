
from pathlib import Path
import numpy as np, pandas as pd, os,json
from cases import D,P,rules
from prepare import collect_inputs
where=P/'scales';where.mkdir(exist_ok=True)
def pack(name,ds,arr,ranges,pre):
    arr.tofile(pre.with_suffix('.rows'))
    names=list(np.load(D/(ds+'.npz'))['names']);mask=lambda spec: sum(1<<names.index(c) for c in spec.split())
    with pre.with_suffix('.queries').open('w') as f:
        for i,(pos,neg) in enumerate(rules[ds]):
            for l,r in ranges:f.write(f'{name}-named-0-{i} {mask(neg)} {mask(pos)} {l} {r}\n')
if __name__=='__main__':
    d=np.load(D/'maude.npz')['masks']
    for n in [50000,200000,800000,len(d)]:
        rng=np.random.default_rng(904);rr=[]
        for j in range(24):
            w=max(1,int(n*[.001,.01,.1,.5][j%4]));l=int(rng.integers(n-w+1));rr.append((l,l+w))
        pack(str(n),'maude',d[:n],rr,where/('scale'+str(n)))
    archive=P/'runs'/'years.tsv'
    if archive.exists():
        yr=pd.read_csv(archive,sep='\\t');years=yr.year.tolist();ends=[0]+yr.r.tolist()
        assert yr.l.tolist()==ends[:-1] and years==list(range(2020,2025))
    else:
        sources=collect_inputs('storm',Path(os.getenv('LOCALAPPDATA',Path.home()/'.cache'))/'scopecount-raw',None)
        ends=[0];years=[]
        for url,f in sources:
            ds=pd.read_csv(f,usecols=['YEAR']);assert ds.YEAR.nunique()==1;years.append(int(ds.YEAR.iloc[0]));ends.append(ends[-1]+len(ds))
        pd.DataFrame({'year':years,'l':ends[:-1],'r':ends[1:]}).to_csv(archive,sep='\\t',index=False)
    d=np.load(D/'storm.npz')['masks'];assert ends[-1]==len(d)
    pack('annual','storm',d,list(zip(ends[:-1],ends[1:])),where/'years')
