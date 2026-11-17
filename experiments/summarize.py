import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def summarize_retained(frame,label,out):
    summaries=[]
    prefixes=[]
    for dataset,case in frame.groupby('dataset'):
        if case.duplicated(['backend','rep','ordinal']).any():raise ValueError('Duplicate trial positions')
        if case.groupby('ordinal').results.nunique().max()!=1:raise ValueError('Disagreeing exact answers')
        traces={}
        for method,group in case.groupby('backend'):
            by_rep=[]
            for _,trial in group.groupby('rep',sort=True):
                trial=trial.sort_values('ordinal')
                if trial.index_build_ns.nunique()!=1:raise ValueError('Inconsistent build charge')
                by_rep.append(trial.index_build_ns.iloc[0]+trial.request_ns.cumsum().to_numpy())
            traces[method]=np.stack(by_rep)
            values=np.median(traces[method],axis=0)
            prefixes.extend(dict(suite=label,dataset=dataset,method=method,request=i+1,paid_ms=float(v)/1e6) for i,v in enumerate(values))
        for method,values in traces.items():
            references=['sql_opt_memo','bitmap_direct_memo'] if method.endswith('_memo') else ['sql_opt','bitmap_direct']
            times=case[case.backend==method].request_ns.to_numpy()/1e6
            for reference in references:
                if reference==method or reference not in traces:continue
                other=traces[reference]
                delta=np.median(values-other,axis=0)
                good=delta<=0
                lost=np.flatnonzero(~good)
                sustained=None if not good[-1] else int(lost[-1]+2 if len(lost) else 1)
                summaries.append(dict(suite=label,dataset=dataset,method=method,reference=reference,replicates=len(values),requests=values.shape[1],paid_ms=float(np.median(values[:,-1]))/1e6,reference_paid_ms=float(np.median(other[:,-1]))/1e6,paired_delta_ms=float(delta[-1])/1e6,sustained_crossing=sustained,p50_ms=float(np.quantile(times,.5)),p95_ms=float(np.quantile(times,.95)),p99_ms=float(np.quantile(times,.99))))
    pd.DataFrame(prefixes).to_csv(out/(label+'-prefixes.tsv'),sep='\t',index=False)
    return summaries


def frozen(out):
    source=ROOT/'research/artifact/livegroups/results'
    answers=pd.read_csv(source/'oracles.csv.gz')
    manifest={x['dataset']:x for x in json.loads((source/'source_manifest.json').read_text())}
    for (dataset,dim),group in answers.groupby(['dataset','dim'],sort=False):
        content='"key","n","missing"\n'+group[['key','n','missing']].to_csv(index=False,header=False,lineterminator='\n')
        if hashlib.sha256(content.encode()).hexdigest()!=manifest[dataset]['oracle'][dim]:raise ValueError('Archived source oracle mismatch: '+dataset+'-'+dim)
    if len(answers)!=9020:raise ValueError('Incomplete grouped source oracle')
    base=ROOT/'research/artifact/pageaudit/results'
    rows=[]
    for f in sorted(base.glob('*/trials.tsv')):
        frame=pd.read_csv(f,sep='\t')
        if not {'dataset','method','rep','ns'}.issubset(frame):continue
        frame=frame[frame.dataset!='fcc']
        if not len(frame):continue
        stats=frame.groupby(['dataset','method']).ns.agg(median_ns='median',p95_ns=lambda x:x.quantile(.95),trials='size').reset_index()
        stats['campaign']=f.parent.name
        rows.append(stats)
    pd.concat(rows,ignore_index=True).to_csv(out/'published-file-medians.tsv',sep='\t',index=False)
    data=pd.read_csv(base/'confirm/trials.tsv',sep='\t')
    data=data[data.dataset!='fcc']
    med=data.groupby(['dataset','method']).ns.median().unstack()
    totals=med.sum()/1e9
    fastest=med[['sql','dense','roaring','packed']].min(axis=1)
    summary=dict(audits=len(med),jurisdictions=len({x.rsplit('-',1)[0] for x in med.index}),oracle_tuples=len(answers),oracle_hashes_verified=25,rounds=int(data.rep.nunique()),sum_of_query_medians_s=totals.to_dict(),fastest_reference_s=float(fastest.sum()/1e9),prefix_wins_vs_sql=int((med.endpoint<med.sql).sum()),prefix_wins_vs_dense=int((med.endpoint<med.dense).sum()))
    expected={'endpoint':3.32,'packed':4.59,'dense':4.92,'roaring':7.29,'sql':8.23}
    if any(round(totals[k],2)!=v for k,v in expected.items()):raise ValueError('Published confirmation totals do not match frozen trial records')
    if round(summary['fastest_reference_s'],2)!=4.09:raise ValueError('Fastest-reference accounting differs')
    (out/'published-confirmation.json').write_text(json.dumps(summary,indent=2)+'\n')
    order=['sql','dense','roaring','packed','endpoint']
    fig,ax=plt.subplots(figsize=(6.4,2.8))
    ax.bar(['SQL','Dense rank','CRoaring','Packed scores','ScopeCount'],totals[order],color=['#888888']*4+['#2476A7'])
    ax.set_ylabel('Sum of query medians (s)')
    ax.set_title('Published confirmation: 25 audits, 10 rounds')
    ax.spines[['top','right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(out/'published-confirmation.pdf')
    fig.savefig(out/'published-confirmation.png',dpi=180)
    plt.close(fig)
    return summary


def resident_files(root,out):
    rows=[]
    paid=[]
    for file in sorted(root.rglob('*.csv')):
        if out in file.parents:continue
        frame=pd.read_csv(file)
        if not {'dataset','dim','method','round','ns'}.issubset(frame):continue
        for (dataset,dim,method),group in frame.groupby(['dataset','dim','method']):
            values=group.ns/1e6
            rows.append(dict(suite='resident',dataset=dataset+'-'+dim,method=method,replicates=len(group),median_ms=float(values.median()),p95_ms=float(values.quantile(.95)),p99_ms=float(values.quantile(.99))))
        dataset=str(frame.dataset.iloc[0])
        setup=file.parent/(dataset+'-setup.json')
        if setup.exists():
            info=json.loads(setup.read_text())
            build=float(np.median(info['row_degree_build_ns']))/1e6
            paid.append(dict(dataset=dataset,common_load_ms=info['load_ns']/1e6,row_degree_build_ms=build))
    pd.DataFrame(paid).drop_duplicates().to_csv(out/'resident-setup.tsv',sep='\t',index=False)
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--frozen',action='store_true')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.frozen:
        report=frozen(args.out)
        resident=resident_files(ROOT/'research/artifact/livegroups/evidence',args.out)
        pd.DataFrame(resident).to_csv(args.out/'published-resident-medians.tsv',sep='\t',index=False)
        report['resident_cases']=len(resident)
        print(json.dumps(report,indent=2))
        return
    summaries=resident_files(args.root,args.out)
    retained=[]
    degree=[]
    sources=[]
    for f in sorted(args.root.rglob('*.tsv')):
        if args.out in f.parents or f.name in ('selection.tsv','profiles.tsv'):continue
        frame=pd.read_csv(f,sep='\t')
        label=f.parent.relative_to(args.root).as_posix()
        if {'table','rep','method','build_ns','query_ns'}.issubset(frame):
            totals=frame.groupby(['table','method','rep']).agg(build_ns=('build_ns','sum'),query_ns=('query_ns','sum'),requests=('dataset','size')).reset_index()
            totals['paid_ns']=totals.build_ns+totals.query_ns
            for (table,method),group in totals.groupby(['table','method']):
                degree.append(dict(table=table,method=method,replicates=len(group),observed_requests=int(group.requests.iloc[0]),build_median_ms=float(group.build_ns.median()/1e6),query_median_ms=float(group.query_ns.median()/1e6),paid_median_ms=float(group.paid_ns.median()/1e6),paid_p95_ms=float(group.paid_ns.quantile(.95)/1e6)))
            sources.append(str(f.relative_to(args.root)))
            continue
        if {'backend','index_build_ns','request_ns','ordinal','results'}.issubset(frame):
            retained+=summarize_retained(frame,label.replace('/','-'),args.out)
            sources.append(str(f.relative_to(args.root)))
            continue
        timing=next((x for x in ['ns','request_ns','time_ns'] if x in frame),None)
        method=next((x for x in ['method','op'] if x in frame),None)
        if not timing or not method:continue
        dimension=next((x for x in ['dataset','layout'] if x in frame),None)
        if dimension is None:
            frame['dataset']=f.stem
            dimension='dataset'
        if 'query' in frame:
            frame=frame.groupby([dimension,method,'rep'],as_index=False)[timing].sum()
        for (dataset,name),group in frame.groupby([dimension,method]):
            values=group[timing]/1e6
            summaries.append(dict(suite=label,dataset=dataset,method=name,replicates=len(values),median_ms=float(values.median()),p95_ms=float(values.quantile(.95)),p99_ms=float(values.quantile(.99))))
        sources.append(str(f.relative_to(args.root)))
    pd.DataFrame(summaries).to_csv(args.out/'query-summary.tsv',sep='\t',index=False)
    pd.DataFrame(retained).to_csv(args.out/'amortization.tsv',sep='\t',index=False)
    pd.DataFrame(degree).to_csv(args.out/'row-degree-paid.tsv',sep='\t',index=False)
    if summaries:
        frame=pd.DataFrame(summaries)
        for label,group in frame.groupby('suite'):
            totals=group.groupby('method').median_ms.sum().sort_values()
            fig,ax=plt.subplots(figsize=(6.4,3.3))
            totals.plot.barh(ax=ax,color='#2476A7')
            ax.set_xlabel('Sum of case medians (ms)')
            ax.set_title(label)
            ax.spines[['top','right']].set_visible(False)
            fig.tight_layout()
            fig.savefig(args.out/(label.replace('/','-')+'.pdf'))
            fig.savefig(args.out/(label.replace('/','-')+'.png'),dpi=160)
            plt.close(fig)
    summary=dict(inputs=sources,query_summary_rows=len(summaries),amortization_rows=len(retained),row_degree_paid_rows=len(degree),memoization='Compared only with references using the same result-cache policy',build_accounting='One index build plus cumulative dispatched request time; common import reported separately')
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
