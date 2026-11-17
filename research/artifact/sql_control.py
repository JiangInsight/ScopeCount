
from pathlib import Path
import time,sys
import numpy as np, pyarrow as pa, duckdb, pandas as pd
root=Path(__file__).resolve().parents[2]; files=[Path(x) for x in sys.argv[1:]] or sorted((root/'data').glob('*.npz'))
for f in files:
    ar=np.load(f); a=ar['masks']; n=len(a)
    d=duckdb.connect();d.execute('set threads=1')
    groups=pd.read_csv(f.with_suffix('.queries'),sep=' ',names=['name','one','zero','l','r'],dtype={'one':str,'zero':str})
    active=sorted({i for mask in set(groups.one)|set(groups.zero) for i in range(len(ar['names'])) if int(mask)>>i&1})
    st=time.perf_counter_ns()
    cols={'rid':pa.array(np.arange(n,dtype=np.uint32))}
    trivial=np.ones(n,dtype=bool)
    for i in active:cols[f'c{i}']=pa.array(trivial,mask=(a&(1<<i))!=0)
    tbl=pa.table(cols);d.register('input_tab',tbl);d.execute('create table audit as select * from input_tab')
    build=time.perf_counter_ns()-st;res=[]
    for z in range(0,groups.name.nunique(),8):
        names=groups.name.unique()[z:z+8];g=groups[groups.name==names[0]]
        expr=[]; rules=[]
        for nm in names:
            t=groups[groups.name==nm].iloc[0];p,q=int(t.one),int(t.zero);rules.append((p,q))
            expr.append('count(*) filter(where '+' and '.join(f'c{i} is '+('null' if p>>i&1 else 'not null') for i in active if (p|q)>>i&1)+')')
        sql='select '+','.join(expr)+' from audit where rid >= ? and rid < ?'

        st=time.perf_counter_ns();d.execute('prepare auditq as '+sql);prepare=time.perf_counter_ns()-st
        for rep in range(3):
            dur=0
            for row in g.itertuples():
                stmt=f'execute auditq({row.l},{row.r})';st=time.perf_counter_ns();ans=d.execute(stmt).fetchone();dur+=time.perf_counter_ns()-st
                if not rep:
                    part=a[row.l:row.r]
                    if ans!=tuple(int(np.count_nonzero(((part&p)==p)&((part&q)==0))) for p,q in rules):raise AssertionError((f,names[0]))
            res.append([names[0],rep,len(g),dur,prepare,build])
        d.execute('deallocate auditq')
    pd.DataFrame(res,columns=['bundle','rep','ranges','exec_ns','prepare_ns','load_ns']).to_csv(root/'runs'/f'{f.stem}.sql.tsv',sep='\t',index=False)
    print(f.stem,flush=True)
