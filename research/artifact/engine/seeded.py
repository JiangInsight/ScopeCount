
import argparse,time
from collections import defaultdict
from pathlib import Path
from replay import connect,run,save
ROOT=Path(__file__).resolve().parents[3]
SOURCES=('nhanes','diabetes','scania','storm','crash','survey','taxi','maude')
def requests_for(prefix):
    q=defaultdict(list)
    with prefix.with_suffix('.queries').open() as f:
        for line in f:
            name,a,b,l,r=line.split();q[name].append((int(a),int(b),int(l),int(r)))
    result=[]
    for seed in [1103,2207,3301]:
        for fam,width in [('complete',8),('anchored',4),('mixed',8),('single',1)]:
            keys=[f'{seed}-{fam}-0-{i}' for i in range(width)]
            for h in range(24):
                batch=[q[k][h] for k in keys];l,r=batch[0][2:]
                assert all(z[2:]==(l,r) for z in batch)
                result.append((f'{seed}-{fam}-{h}',l,r,[(a,b) for a,b,_,_ in batch]))
    return result
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('names',nargs='*');ap.add_argument('--repeats',type=int,default=5)
    ap.add_argument('--out',type=Path,default=ROOT/'runs'/'engine');ap.add_argument('--methods',nargs='+')
    args=ap.parse_args();args.out.mkdir(exist_ok=True,parents=True);db=connect()
    for name in args.names or SOURCES:
        prefix=ROOT/'data'/name;q=requests_for(prefix)
        start=time.perf_counter()
        rows=run(prefix.with_suffix('.rows'),q,args.repeats,args.methods,db,name)
        save(rows,args.out/(name+'.tsv'))
        print(name,len(q),len(rows),round(time.perf_counter()-start,2),'seconds',flush=True)
    db.close()
