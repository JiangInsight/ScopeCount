import argparse
import json
import os
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
os.environ['SCOPECNT_EXTENSION']=str(ROOT/'compiled/duckdb155_roaring/scopecount.duckdb_extension')
sys.path.insert(0,str(ROOT/'research/artifact/engine'))
import replay


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--corpus',choices=['transport','ci'],required=True)
    parser.add_argument('--limit',type=int,default=8)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    source=ROOT/'traces'/args.corpus
    frame=pd.read_csv(source/'manifest.tsv',sep='\t',keep_default_na=False)
    frame=frame[frame.status=='ok'].copy()
    frame['rows']=pd.to_numeric(frame.rows)
    frame=frame.sort_values(['table','rows','prefix']).reset_index(drop=True)
    if args.limit>0 and args.limit<len(frame):
        chosen=[]
        for _,group in frame.groupby('table'):
            positions=[0,len(group)//2,len(group)-1]
            positive=group[group.observed.map(lambda x:any(json.loads(x)))]
            chosen+=list(group.iloc[positions].index)
            if len(positive):chosen.append(int(positive.index[0]))
        chosen=list(dict.fromkeys(chosen))
        chosen+=list(i for i in frame.index if i not in chosen)
        frame=frame.loc[chosen[:args.limit]]
    methods=['sql_opt','tree_direct','bitmap_direct','roaring_direct','online_direct','sql_opt_memo','tree_direct_memo','bitmap_direct_memo','roaring_direct_memo']
    args.out.mkdir(parents=True,exist_ok=True)
    frame.to_csv(args.out/'selection.tsv',sep='\t',index=False)
    results=[]
    db=replay.connect()
    try:
        for row in frame.itertuples():
            path=Path(row.prefix)
            key=str(getattr(row,'feed',getattr(row,'resource','source')))+'-'+row.table
            records=replay.run(path.with_suffix('.rows'),path.with_suffix('.tsv'),args.repeats,methods,db,dataset=key)
            expected=tuple(json.loads(row.observed))
            if any(tuple(map(int,r['results'].split(',')))!=expected for r in records):
                raise AssertionError('Published output mismatch: '+key)
            results+=records
            print(key,int(row.rows),len(records),'exact answers',flush=True)
    finally:db.close()
    pd.DataFrame(results).to_csv(args.out/'trials.tsv',sep='\t',index=False)
    print(json.dumps(dict(corpus=args.corpus,snapshots=len(frame),input_rows=int(frame.rows.sum()),checked_dispatches=len(results),methods=methods)))


if __name__=='__main__':main()
