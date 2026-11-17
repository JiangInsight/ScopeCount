
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[3]

def crossings(files):
    rows=[]
    for fn in files:
        f=pd.read_csv(fn,sep='\t',dtype={'results':str})
        identifiers=['backend','rep','ordinal']
        if f.duplicated(identifiers).any():raise ValueError('duplicate backend/repetition/ordinal: '+str(fn))
        if (f.groupby('ordinal').request_id.nunique()!=1).any():raise ValueError('inconsistent request identity')
        if f.groupby('ordinal').results.nunique().max()!=1:raise ValueError('returned counts differ: '+str(fn))
        methods=sorted(f.backend.unique())
        rep_ids=sorted(f.rep.unique())
        expected=np.arange(1,f.ordinal.max()+1)
        counters=['index_build_ns','request_ns','base_bytes','cache_bytes','compile_ns','kernel_ns','result_cache_hits']
        if f[counters].isna().any().any() or (f[counters]<0).any().any():raise ValueError('negative or missing counter')
        if (f.result_cache_hits>f.rules).any():raise ValueError('more reported cache hits than outputs')
        traces={}
        for method in methods:
            subset=f[f.backend==method]
            if sorted(subset.rep.unique())!=rep_ids:raise ValueError('backend is missing a repetition')
            reps=[]
            for rep,g in subset.groupby('rep',sort=True):
                g=g.sort_values('ordinal')
                if not np.array_equal(g.ordinal,expected):raise ValueError('partial trace')
                if g.index_build_ns.nunique()!=1:raise ValueError('multiple index charges in one trial')
                if not g.result_cache_entries.is_monotonic_increasing:raise ValueError('result cache lost entries')
                reps.append(g.index_build_ns.iloc[0]+g.request_ns.cumsum().to_numpy())
            traces[method]=np.stack(reps)
        for method in methods:
            for ref in ('bitmap_direct','bitmap_direct_memo','sql_opt','synopsis','tree_direct','tree_direct_memo','sql_opt_memo','roaring_direct','roaring_direct_memo'):
                if ref==method or ref not in methods:continue
                A=traces[method];B=traces[ref]

                a=np.median(A,axis=0);b=np.median(B,axis=0)
                delta=np.median(A-B,axis=0);lead=delta<=0
                first=int(np.flatnonzero(lead)[0]+1) if lead.any() else None
                lost=np.flatnonzero(~lead)
                stable=None if not lead[-1] else int(lost[-1]+2 if len(lost) else 1)
                measurements=f[f.backend==method]
                trials=measurements.groupby('rep')
                base=trials.index_build_ns.first().to_numpy()
                ref_base=f[f.backend==ref].groupby('rep').index_build_ns.first().to_numpy()
                request_p50,request_p95,request_p99=np.quantile(measurements.request_ns,[.5,.95,.99])/1e3
                end_q25,end_q75=np.quantile(A[:,-1],[.25,.75])/1e6
                rows.append(dict(dataset=f.dataset.iloc[0],requests=len(a),replicates=len(A),method=method,
                      reference=ref,first_crossing=first,sustained_crossing=stable,method_total_ms=a[-1]/1e6,
                      ref_total_ms=b[-1]/1e6,ref_to_method=np.median(B[:,-1]/A[:,-1]),
                      marginal_ref_to_method=b[-1]/a[-1],median_paired_delta_ms=delta[-1]/1e6,
                      method_build_ms=np.median(base)/1e6,ref_build_ms=np.median(ref_base)/1e6,
                      median_paired_build_delta_ms=np.median(base-ref_base)/1e6,
                      med_compile_total_ms=trials.compile_ns.sum().median()/1e6,
                      med_kernel_total_ms=trials.kernel_ns.sum().median()/1e6,
                      med_new_predicates=trials.new_predicates.sum().median(),
                      strict_reps_winning=int((A[:,-1]<B[:,-1]).sum()),
                      end_q25_ms=end_q25,end_q75_ms=end_q75,reps_winning=int((A[:,-1]<=B[:,-1]).sum()),
                      p50_request_us=request_p50,p95_request_us=request_p95,p99_request_us=request_p99))
    return pd.DataFrame(rows)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,default=ROOT/'runs'/'engine');p.add_argument('--out',type=Path,default=ROOT/'runs'/'engine_summary.tsv')
    a=p.parse_args();d=crossings(sorted(a.directory.glob('*.tsv')));d.to_csv(a.out,sep='\t',index=False)
