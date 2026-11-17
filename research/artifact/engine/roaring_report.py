
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from summarize import crossings

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ORDER=['tree_direct','bitmap_direct','roaring_direct']


def report(base,output,tex):
    details=[]
    pairs=[]
    for group,expected_size in [('domains',8),('ci',128),('bts',1)]:
        files=sorted((base/group).glob('*.tsv'))
        if len(files)!=expected_size:raise ValueError(f'incomplete {group}: {len(files)}')
        comparison=crossings(files)
        comparison.insert(0,'group',group)
        pairs.append(comparison)
        for file in files:
            records=pd.read_csv(file,sep='\t')
            if set(records.rep)!=set(range(5)) or set(records.backend)!=set(ORDER):
                raise ValueError('incomplete method or repetition coverage: '+str(file))
            for method,g in records.groupby('backend'):
                trials=g.groupby('rep',sort=True)
                last=g.sort_values('ordinal').groupby('rep',sort=True).tail(1)
                build=trials.index_build_ns.first()
                execute=trials.request_ns.sum()
                paid=build+execute
                details.append(dict(group=group,dataset=g.dataset.iloc[0],method=method,rows=int(g.rows.iloc[0]),
                    requests=int(g.ordinal.max()),scalar_outputs=int(g[g.rep==0].rules.sum()),
                    paid_ms=np.median(paid)/1e6,build_ms=np.median(build)/1e6,execute_ms=np.median(execute)/1e6,
                    final_payload_bytes=np.median(last.base_bytes+last.cache_bytes),
                    query_p95_us=np.quantile(g.request_ns,.95)/1e3))
    details=pd.DataFrame(details)
    pairs=pd.concat(pairs,ignore_index=True)
    output.mkdir(parents=True,exist_ok=True)
    details.to_csv(output/'roaring-snapshot.tsv',sep='\t',index=False)
    pairs.to_csv(output/'roaring-crossings.tsv',sep='\t',index=False)
    pooled=details.groupby(['group','method']).agg(
        datasets=('dataset','count'),rows=('rows','sum'),requests=('requests','sum'),scalar_outputs=('scalar_outputs','sum'),
        summed_paid_ms=('paid_ms','sum'),summed_final_payload_bytes=('final_payload_bytes','sum')).reset_index()
    pooled.to_csv(output/'roaring-pooled.tsv',sep='\t',index=False)
    if not tex:return
    def values(group,column='summed_paid_ms',scale=1000):
        lookup=pooled[pooled.group==group].set_index('method')
        return [float(lookup.at[x,column])/scale for x in ORDER]
    def triplet(xs,precision=2):
        return ', '.join(f'{x:,.{precision}f}' for x in xs[:-1])+' and '+f'{xs[-1]:,.{precision}f}'
    def against(group,method):
        return pairs[(pairs.group==group)&(pairs.method==method)&(pairs.reference=='roaring_direct')]
    domain=against('domains','tree_direct')
    ci=against('ci','tree_direct')
    premium=ci[ci.median_paired_build_delta_ms>0]
    repaid=premium[premium.sustained_crossing.notna()]
    crossing=(f' The median sustained crossing among those {len(repaid)} tables was at '
              f'request {repaid.sustained_crossing.median():g}.' if len(repaid) else '')
    paid=values('bts');payload=values('bts','summed_final_payload_bytes',2**20)
    n_ci=int(pooled[pooled.group=='ci'].requests.iloc[0])
    text=(
        r'\paragraph{Compressed bitmaps.} '
        r'We built CRoaring 5.5.5~\cite{roaringimpl} directly from the same DuckDB validity vectors. It chooses array, bitmap or run '
        'containers, intersects the most selective literal first and retains conjunctions across requests. '
        'We reran the tree, dense rank bitmap and CRoaring through the same extension, in shuffled order across '
        'five repetitions, with exact-result memoization disabled for all three. '
        f'On the eight controlled streams the sum of per-source median paid times was {triplet(values("domains"))} seconds, '
        f'respectively. The tree finished ahead of CRoaring on {int((domain.median_paired_delta_ms<0).sum())} of eight '
        'sources by paired median. '
        f'The 128 stratified CI tables contributed {n_ci:,} observed requests. Their corresponding totals were '
        f'{triplet(values("ci"))} seconds. The tree led CRoaring on {int((ci.median_paired_delta_ms<0).sum())} tables '
        f'by paired median and on {int((ci.strict_reps_winning==5).sum())} in all five repetitions. '
        f'Of {len(premium)} CI snapshots with a positive tree build premium, {len(repaid)} recovered it '
        f'and stayed ahead through the last observed request.{crossing} '
        f'On the 36 controlled BTS monthly windows the paid times were {triplet(paid)} seconds and final retained '
        f'index payloads were {triplet(payload,1)} MiB.\n'
    )
    tex.write_text(text,encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=ROOT/'revision'/'roaring')
    parser.add_argument('--output',type=Path,default=ROOT/'revision'/'summaries')
    parser.add_argument('--tex',type=Path,default=None)
    args=parser.parse_args();report(args.base,args.output,args.tex)
