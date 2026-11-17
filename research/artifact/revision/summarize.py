
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parents[3]
def summarize(src,out,expected_repeats=None,expected_requests=None):
    comparisons=[];totals=[];sizes=[];frames=list(sorted(src.glob('*.tsv')))
    if not frames:raise ValueError(src)
    for path in frames:
        d=pd.read_csv(path,sep='\t')
        assert not d.duplicated(['dataset','backend','rep','ordinal']).any()
        if expected_repeats is not None:
            assert (d.groupby('backend').rep.nunique()==expected_repeats).all()
        if expected_requests is not None:
            assert d.ordinal.between(1,expected_requests).all()
            assert (d.groupby(['backend','rep']).size()==expected_requests).all()
        ds=d.dataset.iloc[0]
        ref='bitmap_direct_memo' if set(d.backend)=={'tree_direct_memo','sql_opt_memo','bitmap_direct_memo'} else 'bitmap_direct'
        costs={};builds={}
        for method,m in d.groupby('backend'):
            m=m.sort_values(['rep','ordinal'])
            n=m.ordinal.max()
            q=m.request_ns.to_numpy().reshape(-1,n)
            build=m.groupby('rep').index_build_ns.first().to_numpy()
            assert (m.groupby('rep').index_build_ns.nunique()==1).all()
            cum=build[:,None]+np.cumsum(q,axis=1)
            costs[method]=cum;builds[method]=build
            totals.append(dict(dataset=ds,method=method,n=n,paid_ns=np.median(cum[:,-1]),build_ns=np.median(build),
                req_ns=np.median(q.sum(axis=1)),p95_request_ns=np.quantile(q,.95),bytes=m.base_bytes.max(),cache_bytes=m.cache_bytes.max(),
                load_ns=m.load_ns.iloc[0],rows=m.rows.iloc[0]))
        for method,c in costs.items():
            control=ref if not method.endswith('_memo') or 'bitmap_direct_memo' not in costs else 'bitmap_direct_memo'
            if control not in costs or method==control:continue
            delta=c-costs[control];c0=builds[method]-builds[control]
            diff=np.median(delta,axis=0)
            sustained=np.flatnonzero(np.maximum.accumulate(diff[::-1])[::-1]<=0)
            first=np.flatnonzero(diff<=0);n=len(diff)
            comparisons.append(dict(dataset=ds,method=method,control=control,n=n,build_delta_ns=np.median(c0),end_delta_ns=diff[-1],
                first=int(first[0]+1) if len(first) else 0,sustained=int(sustained[0]+1) if len(sustained) else 0,
                allfive=int(np.all(delta[:,-1]<0)),allfive_loss=int(np.all(delta[:,-1]>0)),h1=diff[0]))
    out.mkdir(exist_ok=True,parents=True)
    pd.DataFrame(comparisons).to_csv(out/(src.name+'-cross.csv'),index=False)
    pd.DataFrame(totals).to_csv(out/(src.name+'-totals.csv'),index=False)
    t=pd.DataFrame(totals)
    print(src.name,len(frames));print((t.groupby('method').paid_ns.sum()/1e9).round(3).to_string())
    x=pd.DataFrame(comparisons)
    if x.empty:return
    for method in x.method.unique():
        y=x[x.method==method]
        if method not in ('tree_direct','tree_direct_memo','online_direct'):continue
        pos=y[y.build_delta_ns>0];h=pos.sustained
        print(method,'all/positive premium',len(y),len(pos),'sustained among premium',[(h==1).sum(),h.between(2,10).sum(),h.between(11,40).sum(),(h>40).sum(),(h==0).sum()],'all endpoint wins/unanimous win,loss', (y.end_delta_ns<0).sum(),y.allfive.sum(),y.allfive_loss.sum(),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('src',type=Path,nargs='+');p.add_argument('--out',type=Path,default=R/'revision'/'summaries');a=p.parse_args()
    for src in a.src:summarize(src,a.out)
