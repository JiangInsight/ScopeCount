
from pathlib import Path
import duckdb,pyarrow as pa,numpy as np,pandas as pd,time,sys
P=Path(__file__).resolve().parents[2];res=[]
for name in ['diabetes','nhanes','scania','storm','crash','survey','taxi','maude']:
 d=duckdb.connect();d.execute('set threads=1');a=np.load(P/'data'/f'{name}.npz')['masks'];n=len(a)
 tab=pd.read_csv(P/'data'/f'{name}.queries',sep=' ',names=['id','one','zero','l','r'],dtype={'one':str,'zero':str}); names=tab.id.unique()[:8];assert names[0]=='1103-complete-0-0'
 rules=[(int(v.one),int(v.zero)) for v in tab.drop_duplicates('id')[:8].itertuples()]
 bits=sorted({j for p,z in rules for j in range(63) if ((p|z)>>j)&1})
 tbl=pa.table({'rid':pa.array(np.arange(n,dtype=np.uint32)),**{f'c{j}':pa.array(np.ones(n,dtype=bool),mask=(a&(1<<j))!=0) for j in bits}})
 d.register('src',tbl);d.execute('create table audit as select * from src');slices=tab[tab.id==names[0]][['l','r']].reset_index(drop=True).rename_axis('wid').reset_index()
 d.register('wins',slices);d.execute('create table widths as select * from wins')
 expr=['count(rid) filter (where '+' and '.join(f'c{j} is '+('null' if p>>j&1 else 'not null') for j in bits if (p|z)>>j&1)+')' for p,z in rules]
 sql='select wid,'+','.join(expr)+' from widths left join audit on rid>=l and rid<r group by wid order by wid'
 start=time.perf_counter_ns();d.execute('prepare bundle as '+sql);prep=time.perf_counter_ns()-start
 truth=[(v.wid,*[int(np.count_nonzero(((a[v.l:v.r]&p)==p)&((a[v.l:v.r]&z)==0))) for p,z in rules]) for v in slices.itertuples()]
 for rep in range(3):
    start=time.perf_counter_ns();rows=d.execute('execute bundle').fetchall();ex=time.perf_counter_ns()-start
    assert rows==truth;res.append([name,n,names[0],len(rows),rep,prep,ex])
 d.close();print(name,flush=True)
pd.DataFrame(res,columns=['dataset','rows','bundle','slices','rep','prepare_ns','exec_ns']).to_csv(P/'runs'/'batched_sql.tsv',sep='\t',index=False)
