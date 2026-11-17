
import argparse, pathlib, json
import numpy as np
BASE=pathlib.Path(__file__).resolve().parents[2]/'data'
def project(file, slices=24):
    d=np.load(file,allow_pickle=False); a=np.ascontiguousarray(d['masks'],dtype='<u8'); n=len(a); names=list(map(str,d['names']))
    if not n or len(names)>63: raise ValueError(file)
    a.tofile(file.with_suffix('.rows'))
    mix=np.bitwise_or.reduce(a)^np.bitwise_and.reduce(a)
    active=[i for i in range(len(names)) if int(mix)>>i&1] or [0]
    rows=[]; meta=[]
    for seed in [1103,2207,3301]:
        rng=np.random.default_rng(seed)
        for family in ['complete','anchored','mixed','single']:
            for bundle in range(2):
                if family=='single' and bundle:continue
                intervals=[]
                for j in range(slices):
                    width=max(1,min(n,round(n*[.0001,.001,.01,.1,.5,1.][j%6])))
                    l=int(rng.integers(n-width+1)); intervals.append((l,l+width))
                anchor=int(a[int(rng.integers(n))])
                for slot in range(8):
                    arity=1 if family=='single' else min(len(active),[2,3,4,6][slot%4])
                    bits=list(map(int,rng.choice(active,arity,replace=False)))
                    fields=sum(1<<b for b in bits)
                    if family=='complete': req=0
                    elif family=='anchored': req=anchor&fields
                    elif family=='single':req=fields if slot%2 else 0
                    else:req=int(a[int(rng.integers(n))])&fields if slot%2 else sum(1<<b for b in bits if rng.integers(2))
                    present=fields^req
                    key=f'{seed}-{family}-{bundle}-{slot}'
                    for l,r in intervals: rows.append(f'{key} {req} {present} {l} {r}\n')
                    meta.append(dict(id=key,seed=seed,family=family,bundle=bundle,slot=slot,required_null=str(req),required_present=str(present),arity=arity))
    file.with_suffix('.queries').write_text(''.join(rows))
    file.with_suffix('.meta.json').write_text(json.dumps(dict(n=n,fields=names,active=active,shapes=len(np.unique(a)),queries=meta)))
if __name__=='__main__':
    pp=argparse.ArgumentParser();pp.add_argument('files',nargs='*',type=pathlib.Path);args=pp.parse_args()
    for f in args.files or sorted(BASE.glob('*.npz')):project(f)
